#!/usr/bin/perl -w

package Weather;

use DBI;
use Data::Dumper;
use strict;

my $driver = 'SQLite';
my $database = '/var/lib/weewx/weewx.sdb';
my $userid = '';
my $password = '';
my $dbs = "DBI:$driver:dbname=$database";
my $dbh = DBI->connect($dbs, $userid, $password, { RaiseError => 1 })
                        or die $DBI::errstr;

my $select_statement = qq(SELECT datetime, datetime(datetime, 'unixepoch') from archive where rain > 0 order by datetime desc limit 1);
if ( my @row = executeQuery($select_statement) ) {
  my $update_statement = qq(UPDATE archive set rain = 0 where datetime = $row[0]);
  executeQuery($update_statement);
  if ( my @row = executeQuery($select_statement) ) {
    print "Next rain event is $row[1]\n";
  }
}

sub executeQuery {
  my ( $statement ) = @_;

  my $sth = $dbh->prepare( $statement );
  my $rv = $sth->execute() or die $DBI::errstr;
  print $DBI::errstr if($rv < 0);
  my @row = $sth->fetchrow_array();
  $sth->finish();

  return @row;
}
