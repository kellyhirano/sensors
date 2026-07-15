#!/usr/bin/perl -w

package Rainforest;

use DBI;
use Data::Dumper;
use strict;

my $driver   = 'SQLite';
my $database = '/home/pi/sensors/sensors.db';
my $userid   = '';
my $password = '';
my $dbs      = "DBI:$driver:dbname=$database";
my $dbh = eval { DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } ) };
warn "Rainforest: DB connect failed: $@" if $@;

sub new {
    my $class = shift;
    my $self  = {};
    bless $self, $class;
    return $self;
}

sub get5minPowerLoad {
    my ($self) = @_;

    return undef unless defined $dbh;

    my $powerLoad;
    eval {
        my $statement = qq!select avg(load) from rainforest where datetime > datetime('now','-5 minutes')!;
        my $sth = $dbh->prepare($statement);
        $sth->execute();
        $powerLoad = ($sth->fetchrow_array())[0];
        $sth->finish();
    };
    warn "Rainforest: get5minPowerLoad failed: $@" if $@;

    return $powerLoad;
}

sub isHighCostTime {
  my ($self) = @_;

  my ($hour, $wday) = (localtime(time))[2,6];

  my $isHighCostTime = 0;

  # Expensive time is 4-9pm weekdays, excluding holidays
  if ( $wday != 0 && $wday != 6 && $hour >= 16 && $hour <= 21 ) {
    $isHighCostTime = 1;
  }

  return $isHighCostTime;
}

1;
__END__
