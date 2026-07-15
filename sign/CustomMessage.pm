#!/usr/bin/perl -w

package CustomMessage;

use DBI;
use Data::Dumper;
use strict;

my $driver   = 'SQLite';
my $database = '/home/pi/sign/sign.db';
my $userid   = '';
my $password = '';
my $dbs      = "DBI:$driver:dbname=$database";
my $dbh = eval { DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } ) };
warn "CustomMessage: DB connect failed: $@" if $@;

sub new {
    my $class = shift;
    my $self  = {};
    bless $self, $class;
    return $self;
}

sub getMessages {
    my ($self) = @_;

    return () unless defined $dbh;

    my @messages = ();
    eval {
        my $statement = qq!select
                         message
                         from custom_message
                         where datetime('now', 'localtime') > start_datetime
                         and datetime('now', 'localtime') < end_datetime!;
        my $sth = $dbh->prepare($statement);
        $sth->execute();

        while ( my @row = $sth->fetchrow_array() ) {
            push( @messages, $row[0] );
        }

        $sth->finish();
    };
    warn "CustomMessage: getMessages failed: $@" if $@;

    return @messages;
}

1;
__END__
