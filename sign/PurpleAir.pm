#!/usr/bin/perl -w

package PurpleAir;

use DBI;
use Data::Dumper;
use strict;

my %aqi_defs = ( 0   =>  { desc  => 'Good',
                           color => 'Green' },
                 51  =>  { desc  => 'Moderate',
                           color => 'Yellow' },
                 101 =>  { desc  => 'Unhealthy for Sensitive Groups',
                           color => 'Orange' },
                 151 =>  { desc  => 'Unhealthy',
                           color => 'Red' },
                 201 =>  { desc  => 'Very Unhealty',
                           color => 'Purple' },
                 301 =>  { desc  => 'Hazardous',
                           color => 'Maroon'});

my $driver   = 'SQLite';
my $database = '/home/pi/sensors/sensors.db';
my $userid   = '';
my $password = '';
my $dbs      = "DBI:$driver:dbname=$database";
my $dbh      = DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } )
  or die $DBI::errstr;

sub new {
    my $class = shift;
    my $self  = {};
    bless $self, $class;

    $self->{'min_alert_aqi'} = 101;
    $self->getAQI();

    return $self;
}

sub getAQI {
    my ($self) = @_;

    my $statement = qq!select
                     aqi
                     from purple_air
                     where id = 'v1'
                     order by datetime desc
                     limit 1!;
    my $sth = $dbh->prepare($statement);
    my $rv = $sth->execute() or die $DBI::errstr;
    print $DBI::errstr if ( $rv < 0 );

    $self->{'aqi'} = ($sth->fetchrow_array())[0];

    $sth->finish();

    return $self->{'aqi'};
}

sub getLastHourAQI {
    my ($self) = @_;

    my $statement = qq!select
                     aqi
                     from purple_air
                     where id = 'v1'
                     and strftime('%s', 'now', 'localtime')
                       - strftime('%s', datetime) > ( 60*60 )
                     order by datetime desc
                     limit 1!;
    my $sth = $dbh->prepare($statement);
    my $rv = $sth->execute() or die $DBI::errstr;
    print $DBI::errstr if ( $rv < 0 );

    $self->{'last_hour_aqi'} = $self->{'aqi'} - ($sth->fetchrow_array())[0];

    $sth->finish();

    return $self->{'last_hour_aqi'};
}

sub getAQIDesc {
    my ($self) = @_;

    my @aqi_mins = sort keys %aqi_defs;
    my $curr_min = shift @aqi_mins;

    for my $aqi_min ( @aqi_mins ) {
        last if ( $self->{'aqi'} < $aqi_min );

        $curr_min = $aqi_min;
    }

    $self->{'aqi_desc'} = $aqi_defs{$curr_min};

    return $self->{'aqi_desc'};
}

sub getWarningText {
    my ($self) = @_;

    my $warning_text = '';

    if ( $self->{'aqi'} >= $self->{'min_alert_aqi'} ) {
        my $aqi_desc = $self->getAQIDesc()->{'desc'};
        $warning_text = ">> AIR QUALITY ALERT << AQI is $self->{aqi}: $aqi_desc";
    }

    return $warning_text;
}

1;
__END__
