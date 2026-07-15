#!/usr/bin/perl -w

package Awair;

use DBI;
use Time::ParseDate;
use Data::Dumper;
use strict;

my $driver   = 'SQLite';
my $database = '/home/pi/sensors/sensors.db';
my $userid   = '';
my $password = '';
my $dbs      = "DBI:$driver:dbname=$database";
my $dbh = eval { DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } ) };
warn "Awair: DB connect failed: $@" if $@;

sub new {
    my $class = shift;
    my $self  = {};
    bless $self, $class;
    $self->populateRooms();
    $self->updateRoomData();
    return $self;
}

sub executeQuery {
    my ( $self, $statement, $param ) = @_;

    return () unless defined $dbh;

    my @row;
    eval {
        my $sth = $dbh->prepare($statement);
        if ( defined ($param) ) {
            $sth->execute($param);
        } else {
            $sth->execute();
        }
        @row = $sth->fetchrow_array();
        $sth->finish();
    };
    warn "Awair: query failed: $@" if $@;

    return @row;
}

sub executeMultipleRowQuery {
    my ( $self, $statement, $param ) = @_;

    return undef unless defined $dbh;

    my $ar_rows;
    eval {
        my $sth = $dbh->prepare($statement);
        if ( defined ($param) ) {
            $sth->execute($param);
        } else {
            $sth->execute();
        }
        $ar_rows = $sth->fetchall_arrayref();
        $sth->finish();
    };
    warn "Awair: query failed: $@" if $@;

    return $ar_rows;
}

sub updateData {
    my ($self) = @_;

}

sub populateRooms {
    my ($self) = @_;

    my $statement = qq(SELECT
                     distinct location
                     from awair);

    if ( my $ar_rows = $self->executeMultipleRowQuery($statement) ) {
        $self->{'ar_locations'} = [ map{ $_->[0] } @$ar_rows ];
        print join(',', @{$self->{'ar_locations'}}) . "\n";
    }
}

sub updateRoomData {
    my ($self) = @_;

    for my $room ( @{$self->{'ar_locations'}} ) {
      my $statement = qq(SELECT
                       location, temp
                       from awair
                       where location = ?
                       order by datetime desc
                       limit 1);

      if ( my @row = $self->executeQuery($statement, $room) ) {
        $self->{$room} = $row[1];
        print $room . ": " . $self->{$room} . "\n";
      }
    }

}




1;
__END__
