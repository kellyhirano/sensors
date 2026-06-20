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
my $dbh      = DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } )
  or die $DBI::errstr;

sub new {
    my $class = shift;
    my $self  = {};
    bless $self, $class;
    return $self;
}

sub getMessages {
    my ($self) = @_;

    my @messages = ();

    my $statement = qq!select
                     message
                     from custom_message
                     where datetime('now', 'localtime') > start_datetime
                     and datetime('now', 'localtime') < end_datetime!;
    my $sth = $dbh->prepare($statement);
    my $rv = $sth->execute() or die $DBI::errstr;
    print $DBI::errstr if ( $rv < 0 );

    while ( my @row = $sth->fetchrow_array() ) {
        push( @messages, $row[0] );
    }

    $sth->finish();

    return @messages;
}

1;
__END__
