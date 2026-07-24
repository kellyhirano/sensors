#!/usr/bin/perl -w

use lib '/home/pi/sign';
use Weather;
use JSON;
use Data::Dumper;
use Fcntl qw(:flock);
use Net::MQTT::Simple;
use Getopt::Long;
use DBI;
use POSIX qw(strftime mktime);
use Text::ParseWords qw(parse_line);
use strict;

# --- Constants ---
my $k_nws_forecast_url  = 'https://api.weather.gov/gridpoints/MTR/93,83/forecast';
my $k_nws_alerts_url    = 'https://api.weather.gov/alerts/active?point=37.3228%2C-122.0566';
my $k_nws_user_agent   = '(home sensors)';
my $k_ncei_normals_base = 'https://www.ncei.noaa.gov/access/services/data/v1'
    . '?dataset=normals-daily&stations=USW00023293'
    . '&dataTypes=DLY-TMAX-NORMAL,DLY-TMIN-NORMAL&format=json';
my $k_ncei_history_url  = 'https://www.ncei.noaa.gov/access/services/data/v1'
    . '?dataset=daily-summaries&stations=USW00023293'
    . '&startDate=1948-01-01&dataTypes=TMAX,TMIN&includeAttributes=true&format=csv';
# Long-history COOP station (San Jose, 1893-2007-09) so records reflect true
# ~130-year extremes rather than just the airport station's 1998-present data.
my $k_ncei_history_coop_url = 'https://www.ncei.noaa.gov/access/services/data/v1'
    . '?dataset=daily-summaries&stations=USC00047821'
    . '&startDate=1893-01-01&endDate=2007-12-31&dataTypes=TMAX,TMIN&includeAttributes=true&format=csv';
my $k_normals_cache     = '/home/pi/sensors/normals_cache.json';
my $k_history_cache     = '/home/pi/sensors/ksjc_history.csv';
my $k_history_coop_cache = '/home/pi/sensors/sjcoop_history.csv';
my $k_weewx_db          = '/var/lib/weewx/weewx.sdb';

# --- File lock ---
unless ( flock( DATA, LOCK_EX | LOCK_NB ) ) {
    print "$0 is already running. Exiting.\n";
    exit(1);
}

my ($exclude_forecast, $silent_output, $verify_forecast);
GetOptions(
    "exclude-forecast"  => \$exclude_forecast,
    "silent"            => \$silent_output,
    "verify-forecast"   => \$verify_forecast,
) or die("Error in command line arguments\n");

# --- MQTT setup ---
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

# --- Weather object ---
# verify-forecast: build the sign forecast path too and compare its output with weather.pl NWS mapping.
my $weather;
if ($verify_forecast) {
    print "Fetching sign forecast for comparison...\n";
    $weather = new Weather;
} else {
    $weather = new Weather({ exclude_forecast => 1 });
}

# --- Publish weewx/sensor ---
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
  . qq(, "outdoor_humidity_change": )
  . $weather->getLastHourOutHumidityDiffClean
  . qq(, "barometer": )
  . $weather->getBarometer
  . qq(, "barometer_change": )
  . $weather->getLastHourBarometerDiffClean
  . qq(, "rain_rate": )
  . $weather->getRainRate
  . qq(, "rain": )
  . $weather->getIntervalRain
  . qq(, "last_day_rain": )
  . $weather->getRain
  . qq(, "wind_gust": )
  . $weather->getWindGust
  . qq(});
print STDERR "$mqtt_json\n" unless $silent_output;
$mqtt->retain('weewx/sensor' => $mqtt_json);

# --- Heartbeat ---
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

if ($exclude_forecast) {
    $mqtt->disconnect();
    exit(0);
}

# --- Fetch NWS API forecast ---
my $nws_data = fetch_url_json($k_nws_forecast_url);
die "Failed to fetch NWS forecast\n" unless $nws_data && $nws_data->{properties}{periods};
my $nws_periods = $nws_data->{properties}{periods};

my @forecasts = build_forecast_from_nws($nws_periods);

# --- Verify mode: compare weather.pl NWS mapping with sign Weather.pm mapping, then exit ---
if ($verify_forecast) {
    compare_forecasts(\@forecasts, $weather);
    exit(0);
}

# --- Publish weathergov/forecast ---
$mqtt_json = to_json(\@forecasts);
print STDERR "FORECAST: $mqtt_json\n" unless $silent_output;
$mqtt->retain('weathergov/forecast' => $mqtt_json);

# --- NWS Alerts/Warnings ---
my $nws_alerts = eval { fetch_url_json($k_nws_alerts_url) };
my @warnings = ($nws_alerts && $nws_alerts->{features})
    ? build_warnings_from_nws($nws_alerts) : ();
$mqtt_json = to_json(\@warnings);
print STDERR "WARNINGS: $mqtt_json\n" unless $silent_output;
$mqtt->retain('weathergov/warnings' => $mqtt_json);

# --- Temptrend ---
my $temptrend = build_temptrend($nws_periods);
$mqtt_json = to_json($temptrend);
print STDERR "TEMPTREND: $mqtt_json\n" unless $silent_output;
$mqtt->retain('weathergov/temptrend' => $mqtt_json);
$mqtt->disconnect();

# ===================== Subroutines =====================

sub fetch_url_json {
    my ($url) = @_;
    my $json_str = `curl -m 45 -fsS -H 'User-Agent: $k_nws_user_agent' -H 'Accept: application/geo+json,application/json' "$url"`;
    if ( $? != 0 ) {
        warn "fetch failed for $url\n";
        return undef;
    }
    my $data = eval { decode_json($json_str) };
    warn "decode failed for $url: $@\n" if $@;
    return $data;
}

sub abbrev_forecast {
    my ($text) = @_;
    $text =~ s/ [Aa]nd /\//g;
    $text =~ s/[Tt]hen/>/g;
    $text =~ s/[Mm]ostly //g;
    $text =~ s/[Cc]hance/chc/ig;
    $text =~ s/[Ss]light //ig;
    $text =~ s/[Dd]ecreasing/Decr/ig;
    $text =~ s/[Tt]hunderstorms?/T'storms/ig;
    $text =~ s/[Tt]-([Ss]torms?)/$1/ig;
    $text =~ s/ [Pp]ossible//ig;
    $text =~ s/ [Pp]ossibly//ig;
    $text =~ s/ [Aa]t [Tt]imes//ig;
    return ucfirst($text);
}

sub extract_precip_amount {
    my ($detailed) = @_;
    return 0 unless $detailed;

    # Apply the same word-to-symbol conversions as the original Weather.pm HTML parser
    $detailed =~ s/(?: a)? tenth(?:(?: of an)? inch)?/ .1"/ig;
    $detailed =~ s/ three[ -]quarters(?:(?: of an)? inch)?/ .75"/ig;
    $detailed =~ s/(?: a)? quarter(?:(?: of an)? inch)?/ .25"/ig;
    $detailed =~ s/(?: a)? half(?:(?: of an)? inch)?/ .5"/ig;
    $detailed =~ s/ one inch/ 1"/ig;
    $detailed =~ s/(?: amounts?)? between ([\d.]+) and ([\d.]+)(?:\s*inch(?:es)?)/ $1-$2"/ig;
    $detailed =~ s/(\d+) to (\d+)(?:\s*inch(?:es)?)/$1-$2"/ig;
    $detailed =~ s/ inch(?:es)?\b/"/ig;
    $detailed =~ s/(?:amounts?|accumulation) of less than/<\//ig;
    $detailed =~ s/(?:amounts?|accumulation) of more than/>\//ig;

    if ($detailed =~ /(<?\S*")/) {
        return $1;
    }
    return 0;
}

sub build_forecast_from_nws {
    my ($periods) = @_;
    my @forecasts;
    for my $period (@$periods) {
        my $name  = $period->{name} // '';
        my $temp  = $period->{temperature} // '';
        my $short = abbrev_forecast($period->{shortForecast} // '');
        my $precip_obj    = $period->{probabilityOfPrecipitation};
        my $precip_chance = (ref($precip_obj) eq 'HASH' && defined($precip_obj->{value}))
            ? $precip_obj->{value} : 0;
        my $precip_amount = extract_precip_amount($period->{detailedForecast} // '');
        push @forecasts, {
            day           => uc($name),
            forecast      => $short,
            temp          => $temp,
            precip_chance => $precip_chance,
            precip_amount => $precip_amount,
        };
    }
    return @forecasts;
}

sub format_alert_time {
    my ($iso_time) = @_;
    return '' unless $iso_time && $iso_time =~ /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;
    my ($year, $mon, $mday, $hour, $min) = ($1, $2-1, $3, $4, $5);
    my $epoch = POSIX::mktime(0, $min, $hour, $mday, $mon, $year - 1900, 0, 0, -1);
    my @lt    = localtime($epoch);
    my @today = localtime(time);
    my @days  = ('Sun','Mon','Tue','Wed','Thu','Fri','Sat');
    my $hr12  = $lt[2] % 12 || 12;
    my $ampm  = $lt[2] >= 12 ? 'p' : 'a';
    my $time_str = sprintf("%d:%02d%s", $hr12, $lt[1], $ampm);
    $time_str =~ s/:00//;
    return ($today[6] == $lt[6]) ? $time_str : "$days[$lt[6]] $time_str";
}

sub build_warnings_from_nws {
    my ($nws_alerts) = @_;
    my @warnings;
    for my $feature (@{$nws_alerts->{features} // []}) {
        my $props = $feature->{properties} // {};
        my $event = uc($props->{event} // '');
        next unless $event;
        my $end_time = $props->{ends} || $props->{expires} || '';
        my $end_desc = format_alert_time($end_time);
        my $desc = $end_desc ? 'thru ' . $end_desc : '';
        push @warnings, { title => $event, desc => $desc };
    }
    return @warnings;
}

sub compare_forecasts {
    my ($nws_forecasts, $html_weather) = @_;
    my $html_shorts = $html_weather->getARShortForecasts();
    my $html_temps  = $html_weather->getARForecastTemps();

    printf("%-32s %4s  |  %-32s %4s  DIFF\n", "NWS Day", "Temp", "HTML Day", "Temp");
    printf("%s\n", '-' x 78);

    my $count = @$nws_forecasts < @$html_shorts ? @$nws_forecasts : @$html_shorts;
    $count = 8 if $count > 8;

    for my $i (0 .. $count - 1) {
        my $nws      = $nws_forecasts->[$i];
        my $nws_day  = $nws->{day}  // '';
        my $nws_temp = $nws->{temp} // '';

        my $html_short = $html_shorts->[$i] // '';
        my $html_temp  = $html_temps->[$i]  // '';
        $html_short =~ s/^[^:]+:\s*//;   # strip "DAY: " prefix for short display
        $html_temp  =~ s/[^\d]//g;

        my $diff = '';
        if ($nws_temp =~ /^\d+$/ && $html_temp =~ /^\d+$/) {
            my $d = $nws_temp - $html_temp;
            $diff = sprintf("%+d", $d);
            $diff .= " *** WARNING" if abs($d) > 5;
        }

        printf("%-32s %4s  |  %-32s %4s  %s\n",
               substr($nws_day,    0, 32), $nws_temp,
               substr($html_short, 0, 32), $html_temp,
               $diff);
    }
}

sub day_epoch {
    my ($offset) = @_;
    my @t = localtime(time);
    $t[0] = 0; $t[1] = 0; $t[2] = 0;   # midnight
    $t[3] += $offset;                    # adjust mday (mktime normalizes)
    return POSIX::mktime($t[0], $t[1], $t[2], $t[3], $t[4], $t[5]);
}

sub get_nws_day_temps {
    my ($periods, $date_str) = @_;
    my ($high, $low);
    for my $p (@$periods) {
        next unless ($p->{startTime} // '') =~ /^\Q$date_str\E/;
        if ($p->{isDaytime}) {
            $high = $p->{temperature};
        } else {
            $low = $p->{temperature};
        }
    }
    return ($high, $low);
}

sub fetch_normals {
    my ($mm_dd) = @_;

    # Load cache
    my $cache = {};
    if (-f $k_normals_cache && open(my $fh, '<', $k_normals_cache)) {
        local $/;
        my $content = <$fh>;
        close($fh);
        $cache = eval { decode_json($content) } // {};
    }

    # Return cached value if fresh (30 days)
    my $entry = $cache->{$mm_dd};
    if ($entry && (time - ($entry->{cached_at} // 0)) < 30 * 86400) {
        return ($entry->{normal_high}, $entry->{normal_low});
    }

    # Fetch from NCEI (normals-daily returns tenths of °F)
    my $url      = "${k_ncei_normals_base}&startDate=1991-${mm_dd}&endDate=1991-${mm_dd}";
    my $json_str = `curl -m 30 -s "$url"`;
    my $data     = eval { decode_json($json_str) };
    return (undef, undef) unless $data && ref($data) eq 'ARRAY' && @$data;

    my $row = $data->[0];
    my $hi  = defined($row->{'DLY-TMAX-NORMAL'}) ? $row->{'DLY-TMAX-NORMAL'} / 10 : undef;
    my $lo  = defined($row->{'DLY-TMIN-NORMAL'}) ? $row->{'DLY-TMIN-NORMAL'} / 10 : undef;

    # Cache
    $cache->{$mm_dd} = { normal_high => $hi, normal_low => $lo, cached_at => time };
    if (open(my $fh, '>', $k_normals_cache)) {
        print $fh to_json($cache);
        close($fh);
    }

    return ($hi, $lo);
}

sub load_ghcnd_cache {
    my ($file, $records) = @_;
    # Accumulate into a shared hashref so multiple station files can be merged
    # (min TMIN / max TMAX per mm-dd across all stations).
    $records //= {};
    open(my $fh, '<', $file) or return $records;

    my $header = <$fh>;
    chomp $header;
    my @cols = ghcnd_csv_fields($header);
    my %col_idx = map { $cols[$_] => $_ } 0 .. $#cols;

    return $records unless exists $col_idx{DATE};
    my ($di, $xi, $ni) = @col_idx{qw(DATE TMAX TMIN)};
    my ($xai, $nai) = @col_idx{qw(TMAX_ATTRIBUTES TMIN_ATTRIBUTES)};

    while (my $line = <$fh>) {
        chomp $line;
        my @f = ghcnd_csv_fields($line);
        my $date = (defined $di && defined $f[$di]) ? $f[$di] : '';
        next unless $date =~ /^(\d{4})-(\d{2}-\d{2})$/;
        my ($year, $mm_dd) = ($1, $2);

        # GHCND TMAX/TMIN are in tenths of °C; convert to °F
        if (defined $xi && defined $f[$xi] && $f[$xi] =~ /^-?\d+$/
            && !ghcnd_has_quality_flag(defined $xai ? $f[$xai] : undef)) {
            my $tmax_f = $f[$xi] / 10 * 9/5 + 32;
            if (!exists $records->{$mm_dd}{record_high} || $tmax_f > $records->{$mm_dd}{record_high}) {
                $records->{$mm_dd}{record_high}      = sprintf("%.1f", $tmax_f) + 0;
                $records->{$mm_dd}{record_high_year} = int($year);
            }
        }
        if (defined $ni && defined $f[$ni] && $f[$ni] =~ /^-?\d+$/
            && !ghcnd_has_quality_flag(defined $nai ? $f[$nai] : undef)) {
            my $tmin_f = $f[$ni] / 10 * 9/5 + 32;
            if (!exists $records->{$mm_dd}{record_low} || $tmin_f < $records->{$mm_dd}{record_low}) {
                $records->{$mm_dd}{record_low}      = sprintf("%.1f", $tmin_f) + 0;
                $records->{$mm_dd}{record_low_year} = int($year);
            }
        }
    }
    close($fh);
    return $records;
}

sub ghcnd_csv_fields {
    my ($line) = @_;
    my @fields = map { defined $_ ? $_ : '' } parse_line(',', 0, $line // '');
    s/^\s+|\s+$//g for @fields;
    return @fields;
}

sub ghcnd_cache_has_quality_attrs {
    my ($file) = @_;
    return 0 unless -f $file && open(my $fh, '<', $file);
    my $header = <$fh> // '';
    close($fh);
    my %cols = map { $_ => 1 } ghcnd_csv_fields($header);
    return $cols{TMAX_ATTRIBUTES} || $cols{TMIN_ATTRIBUTES};
}

sub ghcnd_has_quality_flag {
    my ($attrs) = @_;
    return 0 unless defined $attrs && length $attrs;
    my @parts = split(/,/, $attrs, -1);
    my $qflag = $parts[1] // '';
    $qflag =~ s/^\s+|\s+$//g;
    return $qflag ne '';
}

sub fetch_ghcnd_records {
    my $needs_refresh = 1;
    if (-f $k_history_cache) {
        my $mtime = (stat($k_history_cache))[9];
        $needs_refresh = 0 if (time - $mtime) < 30 * 86400;
        $needs_refresh = 1 unless ghcnd_cache_has_quality_attrs($k_history_cache);
    }

    if ($needs_refresh) {
        my $today = strftime('%Y-%m-%d', localtime(time));
        my $url   = "${k_ncei_history_url}&endDate=${today}";
        print STDERR "Downloading GHCND airport history cache (may take ~30s)...\n";
        my $result = system(qq(curl -m 120 -s -o '$k_history_cache' '$url'));
        unless ($result == 0 && -f $k_history_cache && -s $k_history_cache > 10000) {
            warn "Failed to download GHCND airport history\n";
            # Fall back to old cache if it exists
        }
    }

    # Long-history COOP station ended in 2007, so its data is static: fetch it
    # once and keep it forever (no periodic refresh needed).
    if (!-f $k_history_coop_cache || (-s $k_history_coop_cache // 0) < 10000
        || !ghcnd_cache_has_quality_attrs($k_history_coop_cache)) {
        print STDERR "Downloading GHCND COOP history cache (one-time, ~2MB)...\n";
        my $result = system(qq(curl -m 180 -s -o '$k_history_coop_cache' '$k_ncei_history_coop_url'));
        unless ($result == 0 && -f $k_history_coop_cache && -s $k_history_coop_cache > 10000) {
            warn "Failed to download GHCND COOP history\n";
        }
    }

    # Merge records across both stations (min TMIN / max TMAX per mm-dd). Load
    # the older COOP file first so ties keep the earlier year.
    my $records = {};
    load_ghcnd_cache($k_history_coop_cache, $records) if -f $k_history_coop_cache;
    load_ghcnd_cache($k_history_cache, $records)      if -f $k_history_cache;
    return $records;
}

sub build_temptrend {
    my ($periods) = @_;

    # Open weewx DB for past/today actual data
    my $dbh = eval {
        DBI->connect("DBI:SQLite:dbname=$k_weewx_db", '', '', { RaiseError => 1 })
    };
    warn "Cannot connect to weewx DB: $@\n" if $@;

    # Fetch records cache once (may download ~1MB on first run)
    my $records = eval { fetch_ghcnd_records() } // {};

    my @days;
    for my $offset (-3, -2, -1, 0, 1, 2, 3) {
        my $epoch      = day_epoch($offset);
        my $epoch_next = day_epoch($offset + 1);
        my $date_str   = strftime('%Y-%m-%d', localtime($epoch));
        my $mm_dd      = strftime('%m-%d',    localtime($epoch));
        my $label      = substr(strftime('%a', localtime($epoch)), 0, 2);

        my ($actual_high, $actual_low, $forecast_high, $forecast_low);

        # Past and today: query weewx for actual high/low
        if ($offset <= 0 && $dbh) {
            my $sth = eval {
                $dbh->prepare(
                    "SELECT max(outTemp), min(outTemp) FROM archive "
                  . "WHERE datetime >= ? AND datetime < ?"
                );
            };
            if ($sth) {
                eval { $sth->execute($epoch, $epoch_next) };
                unless ($@) {
                    my @row = $sth->fetchrow_array();
                    if (defined $row[0]) {
                        $actual_high = $row[0] + 0;
                        $actual_low  = $row[1] + 0;
                    }
                }
                $sth->finish();
            }
        }

        # Today and future: get NWS forecast
        if ($offset >= 0) {
            ($forecast_high, $forecast_low) = get_nws_day_temps($periods, $date_str);
        }

        # Normals
        my ($normal_high, $normal_low) = eval { fetch_normals($mm_dd) };

        # Records
        my $rec = $records->{$mm_dd} // {};

        push @days, {
            date             => $date_str,
            label            => $label,
            actual_high      => $actual_high,
            actual_low       => $actual_low,
            forecast_high    => defined($forecast_high) ? $forecast_high + 0 : undef,
            forecast_low     => defined($forecast_low)  ? $forecast_low  + 0 : undef,
            normal_high      => defined($normal_high)   ? $normal_high   + 0 : undef,
            normal_low       => defined($normal_low)    ? $normal_low    + 0 : undef,
            record_high      => $rec->{record_high},
            record_high_year => $rec->{record_high_year},
            record_low       => $rec->{record_low},
            record_low_year  => $rec->{record_low_year},
        };
    }

    $dbh->disconnect() if $dbh;
    return { days => \@days };
}

__END__
