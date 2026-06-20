#!/usr/bin/perl -w

use lib '.';
use FontRender;
use Weather;
use Data::Dumper;
use strict;


my $weather       = new Weather;
my $fontrender    = new FontRender;

my $k_min_forecast_length = 40;

$weather->updateData();
my $out24hTempChange = $weather->get24hTempChange();
print ">>> 24h Temp Change: $out24hTempChange\n";

my $ar_forecast_text = $weather->getARForecastText();
my $ar_precip_amounts = $weather->getARPrecipAmounts();

# check for warning text
# not setting a limit; this may fill the buffer
my $ar_warning_text = $weather->getWarningText();
if ( $ar_warning_text ) {
    for my $warning_text ( @$ar_warning_text ) {
      print "$warning_text\n";
    }
}

# only the next two forecasts; make sure it's long enough
for my $i ( 0 .. 1 ) {
    if ( $ar_forecast_text->[$i]
        && length( $ar_forecast_text->[$i] ) > $k_min_forecast_length )
    {
      print "$ar_forecast_text->[$i], $ar_precip_amounts->[$i]\n";
    }
}

# current weather conditions
my $current_weather_bitmap = renderWeatherBitmap( 1 );

sub renderWeatherBitmap {
    my ( $center ) = @_;

    # allow to not center to exercise other pixels
    $center ||= 1;

    # using global $weather and $fontrender
    my $ar_forecast_temps = $weather->getARForecastTempsPrecip();
    my $first_line =
        $weather->getOutsideTemp()
      . chr(130) . ' '
      . $weather->getLastHourOutTempDiff()
      . chr(130) . '     '
      . $weather->getInsideTemp
      . chr(130);
    my $second_line = undef;

    if ( defined($ar_forecast_temps) ) {
        $second_line = join( chr(129), @{$ar_forecast_temps}[ 0 .. 3 ] );

        # chr(129) is pretty much this: ->

        my $rain                    = $weather->getRain();
        my $rain_rate               = $weather->getRainRate();
        my $seconds_since_last_rain = $weather->getSecondsSinceLastRain();

        my $wind_gust = $weather->getWindGust();

        # rain wins, but wind is cool, too
        if ( $wind_gust > 10 ) {
            $second_line = join( chr(129), @{$ar_forecast_temps}[ 0, 1 ] )
              . "    Gust $wind_gust";
        }

        # rain info is cooler, so show that
        # but only if it's rained in the last 8h
        if ( $rain && ( $seconds_since_last_rain < ( 60 * 60 * 8 ) ) ) {
            $second_line = "R: $rain\"";

            if ($rain_rate) {
                $second_line .= ' @ ' . $rain_rate . '"/h';
            }
            else {
                $second_line = join( chr(129), @{$ar_forecast_temps}[ 0, 1 ] )
                  . "   $second_line";
            }
        }
    }

    else {
        $second_line = 'NETWORK TIMEOUT';
    }

    # render the two line current condition strings
    return $fontrender->renderTwoStrings( $first_line, $second_line, $center );
}

__END__
