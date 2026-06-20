#!/usr/bin/perl -w

use DBI;
use Data::Dumper;
use Lingua::EN::Numbers::Ordinate;
use strict;

my @hr_birthdays = (
    {
        name  => 'Kyle',
        month => 3,
        day   => 31,
        year  => 2012
    },
    {
        name  => 'Cindy',
        month => 2,
        day   => 25,
        year  => 2010
    },
    {
        name  => 'Mommy',
        month => 9,
        day   => 23,
        year  => 1976
    },
    {
        name  => 'Daddy',
        month => 3,
        day   => 9,
        year  => 1975
    },
    {
        name  => 'Short Grandma',
        month => 6,
        day   => 5,
        year  => 1944
    },
    {
        name  => 'Tall Grandma',
        month => 12,
        day   => 22,
        year  => 1946
    },
    {
        name  => 'Tala',
        month => 4,
        day   => 13,
        year  => 2010
    },
    {
        name  => 'April',
        month => 12,
        day   => 30,
        year  => 1992
    },
    {
        name  => 'Auntie Megan',
        month => 2,
        day   => 17,
        year  => 1974
    },
    {
        name  => 'Michael',
        month => 10,
        day   => 25,
        year  => 1975
    },
);

my @hr_anniversaries = (
    {
        name  => 'Mommy and Daddy',
        month => 10,
        day   => 25,
        year  => 2008
    },
);

my @hr_single_events = (
    {
        name => 'Welcome Angelina',
        message =>
'Welcome to our house, Angelina! Have fun with Kyle!',
        start_datetime => '2018-05-13 14:00:00',
        end_datetime   => '2018-05-13 17:00:00',
    },
    {
        name => 'Welcome Wolves!',
        message =>
'Welcome to our house Mike, Steph, Mica, and Joaquin!',
        start_datetime => '2018-10-25 10:00:00',
        end_datetime   => '2017-10-26 12:00:00',
    },
);

my $driver   = 'SQLite';
my $database = '/home/pi/sign/sign.db';
my $userid   = '';
my $password = '';
my $dbs      = "DBI:$driver:dbname=$database";
my $dbh      = DBI->connect( $dbs, $userid, $password, { RaiseError => 1 } )
  or die $DBI::errstr;

sub parse_annual_celebration {
    my ( $ar_hr_birthdays, $celebration_text ) = @_;

    my $this_year = ( localtime(time) )[5] + 1900;

    for my $hr_birthday ( @{$ar_hr_birthdays} ) {
        my $name = $hr_birthday->{'name'} . " $celebration_text";
        my $message =
            'Happy '
          . ordinate( $this_year - $hr_birthday->{'year'} )
          . " $celebration_text, "
          . $hr_birthday->{'name'} . '!';
        my $start_datetime = sprintf(
            "%04d-%02d-%02d 00:00:00",
            $this_year, $hr_birthday->{'month'},
            $hr_birthday->{'day'}
        );
        my $end_datetime = sprintf(
            "%04d-%02d-%02d 23:59:59",
            $this_year, $hr_birthday->{'month'},
            $hr_birthday->{'day'}
        );

        insert_event( $name, $message, $start_datetime, $end_datetime );
    }
}

sub parse_single_events {
    my ($ar_hr_single_events) = @_;

    for my $hr_single_event ( @{$ar_hr_single_events} ) {
        insert_event(
            $hr_single_event->{'name'},
            $hr_single_event->{'message'},
            $hr_single_event->{'start_datetime'},
            $hr_single_event->{'end_datetime'}
        );
    }
}

sub insert_event {
    my ( $name, $message, $start_datetime, $end_datetime ) = @_;

    my $statement = qq!insert
                     into custom_message
                     ( name, message, start_datetime, end_datetime )
                     values ( ?, ?, ?, ? )!;
    my $sth = $dbh->prepare($statement);
    my $rv = $sth->execute( $name, $message, $start_datetime, $end_datetime )
      or die $DBI::errstr;
}

sub clear_database {
    my $statement = qq!delete from custom_message!;
    my $rv = $dbh->do($statement) or die $DBI::errstr;
}

clear_database();
parse_annual_celebration( \@hr_birthdays,     "Birthday" );
parse_annual_celebration( \@hr_anniversaries, "Anniversary" );
parse_single_events( \@hr_single_events );

__END__
