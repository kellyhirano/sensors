#!/usr/bin/perl -w

package Weather;

use DBI;
use Time::ParseDate;
use Data::Dumper;
use strict;

# weather.gov url
my $k_forecast_url =
'https://forecast.weather.gov/MapClick.php?lat=37.3228&lon=-122.0566#.WaGn7BmGMxw';
my $k_min_display_wind = 10;

my $driver   = 'SQLite';
my $database = '/var/lib/weewx/weewx.sdb';
my $userid   = '';
my $password = '';
my $dbs      = "DBI:$driver:dbname=$database";
my $dbh      = DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } )
  or die $DBI::errstr;

my $awair_database = '/home/pi/sensors/sensors.db';
my $awair_userid   = '';
my $awair_password = '';
my $awair_dbs      = "DBI:$driver:dbname=$awair_database";
my $awair_dbh      = DBI->connect( $awair_dbs, $awair_userid, $awair_password, { RaiseError => 1 } )
  or die $DBI::errstr;

sub new {
    my ($class, $args) = @_;
    my $self  = { exclude_forecast => $args->{exclude_forecast} || 0 };
    bless $self, $class;
    $self->updateData();
    return $self;
}

sub updateCurrentConditions {
    my ($self) = @_;

    my $statement = qq(SELECT
                     outTemp, rainRate, outHumidity, barometer
                     from archive
                     order by datetime desc limit 1);
    if ( my @row = $self->executeQuery($statement, $dbh) ) {
        my ( $in_temp, $in_humid ) = $self->getCurrentInsideTempAndHumid();
        $self->{inTemp}        = $in_temp;
        $self->{outTemp}       = sprintf("%.1f", $row[0]);
        $self->{rainRate}      = sprintf("%.2f", $row[1]);
        $self->{inHumidity}    = $in_humid;
        $self->{outHumidity}   = sprintf("%.1f", $row[2]);
        $self->{barometer}     = sprintf("%.2f", $row[3]);
    }
}

sub getCurrentInsideTempAndHumid {
    my ($self) = @_;

    my $awair_phys_loc = 'Cupertino, CA';
    my $awair_loc = 'Kitchen';

    my $statement = qq(SELECT
                     temp, humid
                     from awair
                     where physical_location = '$awair_phys_loc'
                     and location = '$awair_loc'
                     order by datetime desc limit 1);
    if ( my @row = $self->executeQuery($statement, $awair_dbh) ) {
        return @row;
    } else {
        return '';
    }
}

sub update24hTempChange {
    my ($self) = @_;

    my $statement = qq!SELECT
                     outTemp
                     from archive
                     where datetime > strftime('%s','now') - 86400
                     order by datetime limit 1!;
    if ( my @row = $self->executeQuery($statement, $dbh) ) {
        $self->{out24hTemp} = $row[0];
        $self->{out24hTempChange} = sprintf('%.1f', $self->{outTemp} - $row[0]);
    }
}

sub update24hRain {
    my ($self) = @_;

    my $statement = qq!SELECT
                     sum(rain)
                     from archive
                     where datetime > strftime('%s','now') - 86400!;
    if ( my @row = $self->executeQuery($statement, $dbh) ) {
        $self->{rain} = sprintf( "%.2f", $row[0] );
    }
}

sub updateSecondsSinceLastRain {
    my ($self) = @_;

    my $statement = qq!select
                  strftime('%s','now') - datetime
                  from archive
                  where rain > 0
                  order by datetime desc limit 1!;
    if ( my @row = $self->executeQuery($statement, $dbh) ) {
        $self->{seconds_since_last_rain} = $row[0];
    }
}

sub updateWindGust {
    my ($self) = @_;

    my $statement = qq!select
                     max(windGust)
                     from archive
                     where datetime > strftime('%s', 'now') - 600!;
    if ( my @row = $self->executeQuery($statement, $dbh) ) {
        $self->{wind_gust} = sprintf("%d",$row[0]) || 0;
    }
}

sub updateHourTempDiff {
    my ( $self, $hours_back_to_compare, $column ) = @_;

    my $seconds_back = 60 * 60 * $hours_back_to_compare;
    my $key_name     = "last_${hours_back_to_compare}_hour_${column}_diff";

    # yes, SQL-injection, but this is interally called
    my $statement    = qq(SELECT
                     ${column}
                     from archive
                     where datetime < strftime('%s','now') - $seconds_back
                     order by datetime desc limit 1);
    if ( my @row = $self->executeQuery($statement, $dbh) ) {
        $self->{$key_name} = sprintf( "%.1f", $self->{$column} - $row[0] );

        # save clean version without special char
        $self->{ $key_name . '_clean' } = $self->{$key_name};

        $self->{$key_name} = '+' . $self->{$key_name}
          if ( $self->{$key_name} >= 0 );

        # make pretty arrows
        $self->{$key_name} =~ s/\+/chr(148)/e;
        $self->{$key_name} =~ s/\-/chr(149)/e;
    }
}

sub executeQuery {
    my ( $self, $statement, $this_dbh) = @_;

    my $sth = $this_dbh->prepare($statement);
    my $rv = $sth->execute() or die $DBI::errstr;
    print $DBI::errstr if ( $rv < 0 );
    my @row = $sth->fetchrow_array();
    $sth->finish();

    return @row;
}

sub parseAndFormatWarningText {
  my ( $self, $ar_warning_text ) = @_;

  my @formatted_strings = ();
  for my $string ( @$ar_warning_text ) {
    if ( $string =~ /^(.+?)\s?([a-z]+ \d+, [\d:apm]+)? until (.+)$/i ) {
      my @output = ();
      push ( @output, ">> " . uc ( $1 ) . " <<" );
      if ( defined ( $2 ) ) {
        push ( @output, $self->formatLocaltime( [ localtime( parsedate( $2 ) ) ] ) );
        push ( @output, '-' );
      } else {
        push ( @output, 'Now thru' );
      }
      push ( @output, $self->formatLocaltime( [ localtime( parsedate( $3 ) ) ] ) );
      push ( @formatted_strings, join ( ' ', @output ) );
    }
  }

  return @formatted_strings;
}

sub formatLocaltime {
  my ( $self, $ar_localtime ) = @_;

  my @output = ();
  my @today = localtime(time);
  my @days = ( 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat' );

  my $hr = $ar_localtime->[2];
  my $min = $ar_localtime->[1];
  my $dow = $ar_localtime->[6];

  # It's not today, so print the day
  if ( $today[6] != $dow ) {
    push ( @output, $days[$dow] );
  }
  my $time_str = sprintf( "%d:%02d%s", ( $hr > 12 ) ? $hr - 12 : $hr, $min, ( $hr >= 12 ) ? 'p' : 'a' );
  $time_str =~ s/:00//;
  push ( @output, $time_str );
  return join ( ' ' , @output );
}


sub calcPrecipChance {
  my ($self, $forecast_text, $precip_regex) = @_;

  my @precip_chances = ();
  my @forecast_pieces = ( $forecast_text );

  ## If it's something like "rain then chance rain" or something,
  ## replace the original array -- which was populated with the
  ## same string only -- with the pieces.
  if ( $forecast_text =~ /\sthen\s/ ) {
    @forecast_pieces = split(/\sthen\s/, $forecast_text);
  }

  for my $forecast_piece ( @forecast_pieces ) {
    my $precip_chance = 0;

    ## Must account for "chance rain then sunny"
    if ( $forecast_piece =~ /$precip_regex/io ) {
      if ( $forecast_piece =~ /likely/i ) {
	$precip_chance = 2;
      } elsif ( $forecast_piece =~ /chance|scattered|isolated/i ) {
	$precip_chance = 1;
      } else {
	$precip_chance = 3;
      }
    }
    push ( @precip_chances, $precip_chance );
  }

  ## Return the largest one
  return (sort ( @precip_chances ))[-1];
}


sub calcPrecipChanceSeverity {
  my ($self, $forecast_text) = @_;

  ## Differentiate between showers (.), rain (..) and heavy rain (...)
  my $precip_chance = 0;
  my $precip_regex = '((?:heavy )?rain|shower|storm|snow|drizzle)';
  my $precip_severity = 0;
  my %precip_severity = ( 'drizzle' => 1, 'shower' => 1, 'rain' => 2,
			  'heavy rain' => 3, 'storm' => 3, 'snow' => 3 );

  if ( $forecast_text =~ /$precip_regex/io ) {
    $precip_severity = $precip_severity{lc ( $1 )};
    $precip_chance = $self->calcPrecipChance($forecast_text, $precip_regex);
  }

  return ( $precip_chance, $precip_severity );
}


sub updateForecast {
    my ($self) = @_;

    my $response_body = undef;

    eval {
        local $SIG{ALRM} = sub { die "alarm\n" };    # NB: \n required
        alarm 75;
        $response_body = `curl -m 60 -s "$k_forecast_url"`;
        alarm 0;
    };

    # timed out
    if ($@) {
        die unless $@ eq "alarm\n";    # propagate unexpected errors
        return undef;
    }

    my @forecast_text = ();
    my @precip_amounts = ();
    while ( $response_body =~
        /<li class="forecast-tombstone">.+?alt="([^"]+)".+?<\/li>/sg )
    {
        my $forecast_text = $1;

        # debug
        print "ORIG (" . length($forecast_text) . ") $forecast_text\n";

        # abbreviations
        $forecast_text =~ s/ percent/%/g;
        $forecast_text =~ s/\bnorth/N/ig;
        $forecast_text =~ s/\bsouth/S/ig;
        $forecast_text =~ s/west\b/W/ig;
        $forecast_text =~ s/east\b/E/ig;
        $forecast_text =~ s/\b([A-Z]) ([A-Z]{2})\b/$1$2/g;    # N NW -> NNW
        $forecast_text =~ s/(precip)itation/$1/ig;
        $forecast_text =~ s/thunderstorm/t'storm/ig;
        $forecast_text =~ s/(temp)erature/$1/ig;
        $forecast_text =~ s/(decr)easing/$1/ig;
        $forecast_text =~ s/(incr)easing/$1/ig;
        $forecast_text =~ s/(?:then )becoming/->/ig;
        $forecast_text =~ s/, ->/ ->/ig;

        # approximiations
        $forecast_text =~ s/ near//ig;
        $forecast_text =~ s/ slight//ig;
        $forecast_text =~ s/ around//ig;
        $forecast_text =~ s/ possible//ig;
        $forecast_text =~ s/ possibly//ig;
        $forecast_text =~ s/ at times//ig;
        $forecast_text =~ s/ with(?: an?)?//ig;
        $forecast_text =~ s/as high as //ig;

        # other words to remove
        $forecast_text =~ s/ gradually//ig;
        $forecast_text =~ s/ of the//ig;
        $forecast_text =~ s/ mph//ig;

        # small numbers
        $forecast_text =~ s/(?: amounts|accumulation) of less than/ </ig;
        $forecast_text =~ s/(?: amounts|accumulation) of more than/ >/ig;
        $forecast_text =~ s/(?: a)? tenth(?:(?: of an)? inch)?/ .1"/ig;
        $forecast_text =~ s/ three quarters(?:(?: of an)? inch)?/ .75"/ig;
        $forecast_text =~ s/(?: a)? quarter(?:(?: of an)? inch)?/ .25"/ig;
        $forecast_text =~ s/(?: a)? half(?:(?: of an)? inch)?/ .5"/ig;
        $forecast_text =~ s/ one inch/ 1"/ig;
        $forecast_text =~ s/(?: amounts)? between (.*?) and (.*?)\./ $1-$2\./ig;
        $forecast_text =~ s/(\d+) to (\d+)/$1-$2/ig;
        $forecast_text =~ s/ inches?\b/"/ig;

        # spaces
        $forecast_text =~ s/\s+$//;
        $forecast_text =~ s/\s{2,}/ /g;
        $forecast_text =~ s/< /</g;

        # more cleaning
        $forecast_text =~ s/Winds could gust/Gusts to/;
        $forecast_text =~ s/Chance of precip is/Precip chance/;
        $forecast_text =~ s/except higher amounts/higher/;
        $forecast_text =~ s/in the/in/;
        $forecast_text =~ s/ and /\//;

        # uc day/time period
        $forecast_text =~ s/^([^:]+):\s+(\w+)/uc($1) . ': ' . ucfirst($2)/e;

        # only show interesting wind if there's a wind speed
        if ( $forecast_text =~ /\.\s.+?\bwinds?\b.+?(\d+)\smph[^.]*\./ ) {
            my $max_wind = $1;    # assume last number is the largest

            # make sure the wind is above the min display; light wind is boring
            if ( $max_wind < $k_min_display_wind ) {
                $forecast_text =~ s/\..+?\bwinds?\b.+?\././;
            }
        }

        # "light ... wind" is also boring
        $forecast_text =~ s/\..+?\blight\b.+?winds?.*?\././i;

        # fix two "'s from previous changes
        if ( $forecast_text =~ /".+"/ ) {
             $forecast_text =~ s/^(.*?)"/$1/;
        }

        # extract precip amounts
        my $precip_amount = 0;
        if ( $forecast_text =~ /(\S+").*?$/ ) {
            $precip_amount = $1;
        }
        push( @precip_amounts, $precip_amount );

        # debug
        print "(" . length($forecast_text)
              . ") $forecast_text, $precip_amount\n";

        push( @forecast_text, $forecast_text );

    }

    my @forecast_temps            = ();
    my @forecast_temps_with_label = ();
    while ( $response_body =~ /temp-(?:high|low)">(.+?)<\/p>/sg ) {
        my $temp = $1;
        $temp =~ s/<span[^>]+>[^<]+<\/span>//
          ;    # sometimes there's a &dArr; or &uArr; in there
        $temp =~ s/(\d)[^\d]+$/$1/;    # only keep the numbers
        $temp =~ s/High:/H/;
        $temp =~ s/Low:/L/;
        push( @forecast_temps_with_label, $temp . chr(130) );
        $temp =~ s/H //;
        $temp =~ s/L //;
        push( @forecast_temps, $temp . chr(130) );
    }

    # yes, this is stupid and should fit into the same while loop as above.
    # first shot had weird failures where the low temps weren't caputred,
    # but the highs were. this needs to be figured out to get rid of this
    # second loop.
    my @short_forecasts = ();
    my @precip_chances = ();
    my @precip_severities = ();
    my @forecast_temps_with_precip = @forecast_temps;
    my $count = 0;
    while ( $response_body =~
        /p class="period-name">(.+?)<\/p>.+?title="(.*?)".+?class="short-desc">(.+?)<\/p/sg )
    {
        my $time_period   = $1;
        my $time_title    = $2;
        my $forecast_text = ucfirst( lc($3) );

        print STDERR ("FORECAST: $time_period|$time_title|$forecast_text\n");

        next unless ( $time_title ); # If there's an active advisory, there's no title

        $time_period =~ s/<br>/ /g;
        $time_period =~ s/\s+$//;
        $forecast_text =~ s/<br>/ /g;
        $forecast_text =~ s/\./,/g;
        push( @short_forecasts, uc($time_period) . ": $forecast_text" );

        my ( $precip_chance, $precip_severity ) = $self->calcPrecipChanceSeverity($forecast_text);

        if ( $precip_chance ) {
          ## Math offset to get the right degree with precip char;
          ## all offsets from the base char, 130
          my $precip_degree_ascii = 130 + ( ( $precip_severity - 1 ) * 3 ) + $precip_chance;
          $forecast_temps_with_precip[$count] =~ s/\x82/chr($precip_degree_ascii)/e;
        }

        push ( @precip_chances, $precip_chance );
        push ( @precip_severities, $precip_severity );
        print STDERR "$forecast_text, $precip_severity, $precip_chance\n";
        $count++;
    }

    # grab any headline-details
    # Future: "Excessive Heat Warning September 1, 11:00am until September 4, 09:00pm"
    # Current: "Flash Flood Watch until September 1, 01:00pm"
    my @warning_text = ();
    if ( $response_body =~ /div id="headline-detail"><div>(.+?)<\/div><\/div>/s ) {
      my @headline_detail = split ( /<\/div><div>/, $1 );
      @warning_text = $self->parseAndFormatWarningText( \@headline_detail );
    }

    $self->{ar_forecast_text}              = \@forecast_text;
    $self->{ar_forecast_temps}             = \@forecast_temps;
    $self->{ar_forecast_temps_with_precip} = \@forecast_temps_with_precip;
    $self->{ar_forecast_temps_with_label}  = \@forecast_temps_with_label;
    $self->{ar_short_forecasts}            = \@short_forecasts;
    $self->{ar_precip_chances}             = \@precip_chances;
    $self->{ar_precip_severities}          = \@precip_severities;
    $self->{ar_warning_text}               = \@warning_text;
    $self->{ar_precip_amounts}             = \@precip_amounts;
}

sub getInsideTemp    { my ($self) = @_; return $self->{inTemp}; }
sub getOutsideTemp   { my ($self) = @_; return $self->{outTemp}; }
sub get24hTempChange { my ($self) = @_; return $self->{out24hTempChange}; }
sub getInsideHumid   { my ($self) = @_; return $self->{inHumidity}; }
sub getOutsideHumid  { my ($self) = @_; return $self->{outHumidity}; }
sub getBarometer     { my ($self) = @_; return $self->{barometer}; }
sub getRainRate      { my ($self) = @_; return $self->{rainRate}; }
sub getRain          { my ($self) = @_; return $self->{rain}; }
sub getWindGust      { my ($self) = @_; return $self->{wind_gust}; }
sub getWarningText   { my ($self) = @_; return $self->{ar_warning_text}; }

sub getLastHourInTempDiff {
    my ($self) = @_;
    return $self->{last_1_hour_inTemp_diff};
}

sub getLastHourInTempDiffClean {
    my ($self) = @_;
    return $self->{last_1_hour_inTemp_diff_clean};
}

sub getLastHourInHumidityDiff {
    my ($self) = @_;
    return $self->{last_1_hour_inHumidity};
}

sub getLastHourInHumidityDiffClean {
    my ($self) = @_;
    return $self->{last_1_hour_inHumidity_diff_clean};
}

sub getLastHourOutTempDiff {
    my ($self) = @_;
    return $self->{last_1_hour_outTemp_diff};
}

sub getLastHourOutTempDiffClean {
    my ($self) = @_;
    return $self->{last_1_hour_outTemp_diff_clean};
}

sub getLastHourOutHumidityDiff {
    my ($self) = @_;
    return $self->{last_1_hour_outHumidity_diff};
}

sub getLastHourOutHumidityDiffClean {
    my ($self) = @_;
    return $self->{last_1_hour_outHumidity_diff_clean};
}

sub getLastHourBarometerDiff {
    my ($self) = @_;
    return $self->{last_1_hour_barometer_diff};
}

sub getLastHourBarometerDiffClean {
    my ($self) = @_;
    return $self->{last_1_hour_barometer_diff_clean};
}

sub getLast24hOutTempDiff {
    my ($self) = @_;
    return $self->{last_24_hour_outTemp_diff};
}

sub getLast24hOutTempDiffClean {
    my ($self) = @_;
    return $self->{last_24_hour_outTemp_diff_clean};
}

sub getSecondsSinceLastRain {
    my ($self) = @_;
    return $self->{seconds_since_last_rain};
}
sub getForecastText    { my ($self) = @_; return $self->{forecast_text}; }
sub getARForecastTemps { my ($self) = @_; return $self->{ar_forecast_temps}; }
sub getARForecastTempsPrecip { my ($self) = @_; return $self->{ar_forecast_temps_with_precip}; }

sub getARForecastTempsWithLabel {
    my ($self) = @_;
    return $self->{ar_forecast_temps_with_label};
}

sub getARShortForecasts {
    my ($self) = @_;
    return $self->{ar_short_forecasts};
}
sub getARForecastText     { my ($self) = @_; return $self->{ar_forecast_text}; }
sub getARPrecipChances    { my ($self) = @_; return $self->{ar_precip_chances}; }
sub getARPrecipSeverities { my ($self) = @_; return $self->{ar_precip_severities}; }
sub getARPrecipAmounts    { my ($self) = @_; return $self->{ar_precip_amounts}; }

sub updateData {
    my ($self) = @_;

    $self->updateCurrentConditions();
    $self->updateSecondsSinceLastRain();
    $self->update24hTempChange();
    $self->update24hRain();
    $self->updateWindGust();
    $self->updateHourTempDiff(1, 'outTemp');
    #$self->updateHourTempDiff(1, 'inTemp');
    $self->updateHourTempDiff(1, 'outHumidity');
    #$self->updateHourTempDiff(1, 'inHumidity');
    $self->updateHourTempDiff(1, 'barometer');
    $self->updateHourTempDiff(24, 'outTemp');
    $self->updateForecast() unless ($self->{exclude_forecast});
}

1;
