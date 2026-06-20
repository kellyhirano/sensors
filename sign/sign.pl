#!/usr/bin/perl -w

use lib '/home/pi/sign';
use FontRender;
use Weather;
use PurpleAir;
use CustomMessage;
use Device::MiniLED;
use Data::Dumper;
use Fcntl qw(:flock);
use strict;

unless ( flock( DATA, LOCK_EX | LOCK_NB ) ) {
    print "$0 is already running. Exiting.\n";
    exit(1);
}

my $purpleair     = new PurpleAir;
my $weather       = new Weather;
my $fontrender    = new FontRender;
my $custommessage = new CustomMessage;

my $prev_bitmap     = '';
my $screen_is_blank = 0;

my $k_min_forecast_length = 40;

while (1) {

    # need to move the constructor inside the loop since sending to the sign
    # does not flush its queue
    my $sign = Device::MiniLED->new( devicetype => "sign" );

    my $hour = ( localtime(time) )[2];

    # only run this from 6 to midnight
    if ( $hour >= 6 ) {

        $weather->updateData();

        my $ar_forecast_text = $weather->getARForecastText();

        my $max_messages  = 8;
        my $num_messages  = 0;
        my $center_bitmap = 1;

        # check for custom message
        my @custom_messages = $custommessage->getMessages();
        for my $custom_message (@custom_messages) {
            $sign->addMsg(
                data   => $custom_message,
                effect => 'scroll',
                speed  => 5
            );
            $num_messages++;
            print STDERR "CUSTOM: $custom_message\n";
        }

        # check for warning text
        # not setting a limit; this may fill the buffer
        my $ar_warning_text = $weather->getWarningText();
        my $aqi_warning_text = $purpleair->getWarningText();
        push ( @$ar_warning_text, $aqi_warning_text ) if ( $aqi_warning_text );
        if ( $ar_warning_text ) {
            for my $warning_text ( @$ar_warning_text ) {
              $sign->addMsg(
                  data   => $warning_text,
                  effect => 'scroll',
                  speed  => 5
              );
              $num_messages++;
              print STDERR "WARNING: $warning_text\n";
            }
        }

        # only the next two forecasts; make sure it's long enough
        for my $i ( 0 .. 1 ) {
            if ( $ar_forecast_text->[$i]
                && length( $ar_forecast_text->[$i] ) > $k_min_forecast_length )
            {
                $sign->addMsg(
                    data   => $ar_forecast_text->[$i],
                    effect => 'scroll',
                    speed  => 5
                );
                $num_messages++;
            }
        }

        if ( $num_messages == 0 ) {
          $center_bitmap = $hour % 2;
        }

        # current weather conditions
        my $current_weather_bitmap = renderWeatherBitmap( $center_bitmap );
        my $pic                    = $sign->addPix(
            height => 16,
            width  => 96,
            data   => $current_weather_bitmap
        );

        # buffer to get the bitmap to stay longer
        # max 8 messages
        # max range is "- 1" because of the 0-index count
        for my $i ( 0 .. ( $max_messages - $num_messages - 1 ) ) {
            $sign->addMsg(
                data   => $pic,
                effect => 'hold',
                speed  => 1
            );
        }

        # only send if there's a change in the bitmap
        if ( $current_weather_bitmap ne $prev_bitmap ) {
            $sign->send( device => "/dev/sign" );
            print STDERR scalar(localtime) . ": updated\n";
        }

        # set state vars
        $prev_bitmap     = $current_weather_bitmap;
        $screen_is_blank = 0;
    }

    # blank screen at night
    else {
        if ( !$screen_is_blank ) {
            $sign->addMsg( data => '' );
            $sign->send( device => "/dev/sign" );
            print STDERR scalar(localtime) . ": setting to black\n";
        }
        $screen_is_blank = 1;
    }

    sleep(300);
}


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

        my $aqi                     = $purpleair->getAQI();
        my $last_hour_aqi           = $purpleair->getLastHourAQI();
        my $rain                    = $weather->getRain();
        my $rain_rate               = $weather->getRainRate();
        my $seconds_since_last_rain = $weather->getSecondsSinceLastRain();

        my $wind_gust = $weather->getWindGust();

        # rain wins, but wind is cool, too
        if ( $wind_gust > 10 ) {
            $second_line = join( chr(129), @{$ar_forecast_temps}[ 0, 1 ] )
              . "    Gust $wind_gust";
        }

        # Air Quality is more intersting than wind
        if ( $aqi > 100 ) {
            my $aqi_percentage_change = $last_hour_aqi / $aqi;
            $second_line = join( chr(129), @{$ar_forecast_temps}[ 0, 1 ] );
            $second_line .= "   AQI $aqi";

            # Only add up/down arrow if it's a more significant change
            if ( $aqi_percentage_change > 0.05 ) {
              $second_line .= ( $last_hour_aqi > 0 ) ? chr(148) : chr(149);
            }
        }

        # rain info is cooler, so show that
        # but only if it's rained in the last 8h
        if ( $rain && ( $seconds_since_last_rain < ( 60 * 60 * 8 ) ) ) {
            $second_line = "R: $rain\"";

            if ( $rain_rate && ( $rain_rate ne '0.00' ) ) {
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
