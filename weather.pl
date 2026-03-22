#!/usr/bin/perl -w

use lib '/home/pi/sign';
use Weather;
use JSON;;
use Data::Dumper;
use Fcntl qw(:flock);
use Net::MQTT::Simple;
use Getopt::Long;
use strict;

unless ( flock( DATA, LOCK_EX | LOCK_NB ) ) {
    print "$0 is already running. Exiting.\n";
    exit(1);
}

my $exclude_forecast;
my $silent_output;
GetOptions ("exclude-forecast"  => \$exclude_forecast,
            "silent"            => \$silent_output)
  or die("Error in command line arguments\n");

my $mqtt_host;
if (open(my $fh, '<', 'sensor.conf')) {
    my $in_section = 0;
    while (<$fh>) {
        if (/^\[ALL\]/)  { $in_section = 1; next; }
        if (/^\[/)       { $in_section = 0; }
        if ($in_section && /^mqtt_host\s*[=:]\s*(.+)/) {
            ($mqtt_host = $1) =~ s/\s+$//;
            last;
        }
    }
    close($fh);
}
die "mqtt_host not found in sensor.conf [ALL] section\n" unless $mqtt_host;
my $mqtt = Net::MQTT::Simple->new($mqtt_host);

my $weather;
if ( $exclude_forecast ) {
  $weather = new Weather({ exclude_forecast => 1 });
} else {
  $weather = new Weather;
}

# send current conditions to mqtt
my $mqtt_json =
    qq({"outdoor_temperature": )
  . $weather->getOutsideTemp
  . qq(, "outdoor_24h_temp_change": )
  . $weather->get24hTempChange
  . qq(, "indoor_temperature": )
  . $weather->getInsideTemp
  . qq(, "outdoor_humidity": )
  . $weather->getOutsideHumid
  . qq(, "indoor_humidity": )
  . $weather->getInsideHumid
  . qq(, "outdoor_temp_change": )
  . $weather->getLastHourOutTempDiffClean
#  . qq(, "indoor_humidity_change": )
#  . $weather->getLastHourInHumidityDiffClean
  . qq(, "outdoor_humidity_change": )
  . $weather->getLastHourOutHumidityDiffClean
  . qq(, "barometer": )
  . $weather->getBarometer
  . qq(, "barometer_change": )
  . $weather->getLastHourBarometerDiffClean
  . qq(, "rain_rate": )
  . $weather->getRainRate
  . qq(, "last_day_rain": )
  . $weather->getRain
  . qq(, "wind_gust": )
  . $weather->getWindGust
#  . qq(, "indoor_temp_change": )
#  . $weather->getLastHourInTempDiffClean
  . qq(});
print STDERR "$mqtt_json\n" unless $silent_output;
$mqtt->retain ('weewx/sensor' => $mqtt_json);
$mqtt->disconnect();

# Ping heartbeat URL from sensor.conf [WEATHER] section on successful publish
{
    my $heartbeat_url;
    if (open(my $fh, '<', 'sensor.conf')) {
        my $in_section = 0;
        while (<$fh>) {
            if (/^\[WEATHER\]/) { $in_section = 1; next; }
            if (/^\[/)          { $in_section = 0; }
            if ($in_section && /^heartbeat_url\s*[=:]\s*(.+)/) {
                ($heartbeat_url = $1) =~ s/\s+$//;
                last;
            }
        }
        close($fh);
    }
    system("wget -q -O /dev/null '$heartbeat_url' 2>/dev/null") if $heartbeat_url;
}

# send current conditions to mqtt
my $ar_short_forecasts = $weather->getARShortForecasts();
my $ar_forecast_temps = $weather->getARForecastTemps();
my $ar_precip_chances = $weather->getARPrecipChances();
my $ar_precip_severities = $weather->getARPrecipSeverities();
my $ar_precip_amounts = $weather->getARPrecipAmounts();

exit(0) if ( $exclude_forecast );

my @forecasts = ();
for my $i ( 0 .. scalar(@$ar_short_forecasts) - 1 ) {
  my ($day, $short_forecast) = split(/\s*:\s*/, $ar_short_forecasts->[$i]);
  $short_forecast =~ s/ and /\//g;
  $short_forecast =~ s/then/>/g;
  $short_forecast =~ s/(m)ostly/$1/ig;
  $short_forecast =~ s/(c)hance/$1hc/ig;
  $short_forecast =~ s/(s)light //ig;
  $short_forecast =~ s/(d)ecreasing/$1ecr/ig;
  $short_forecast =~ s/(t)-(storms?)/$1'$2/ig;
  $short_forecast = ucfirst($short_forecast);
  my $temp = $ar_forecast_temps->[$i];
  my $precip_chance = $ar_precip_chances->[$i];
  my $precip_severity = $ar_precip_severities->[$i];
  my $precip_amount = $ar_precip_amounts->[$i];
  $temp =~ s/[^\d]//g;

  push ( @forecasts, { 'day' => $day,
                       'forecast' => $short_forecast,
                       'temp' => $temp,
                       'precip_chance' => $precip_chance,
                       'precip_serverity' => $precip_severity,
                       'precip_amount' => $precip_amount } );
}

$mqtt_json = to_json( \@forecasts );
print STDERR "FORECAST: $mqtt_json\n" unless $silent_output;
$mqtt->retain ('weathergov/forecast' => $mqtt_json);
$mqtt->disconnect();


# send warning text
my $ar_warning_text = $weather->getWarningText();

# yes, reusing this var
@forecasts = ();

for my $warning_text ( @$ar_warning_text ) {
  $warning_text =~ /^>> (.+?) << (.+)$/;

  push ( @forecasts, { 'title' => $1,
                       'desc' => $2 } );
}

$mqtt_json = to_json( \@forecasts );
print STDERR "WARNINGS: $mqtt_json\n" unless $silent_output;
$mqtt->retain ('weathergov/warnings' => $mqtt_json);
$mqtt->disconnect();

__END__
