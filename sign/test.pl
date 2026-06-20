#!/usr/bin/perl -w

use Rainforest;
use Time::ParseDate;
use strict;

my @test_strings = ( "Excessive Heat Warning September 1, 11:00am until September 4, 09:00pm",
                     "Flash Flood Watch until September 1, 01:00pm" );


for my $string ( @test_strings ) {
  if ( $string =~ /^(.+?)\s?([a-z]+ \d+, [\d:apm]+)? until (.+)$/i ) {
    my @output = ();
    push ( @output, ">> " . uc ( $1 ) . " <<" );
    print "$string\n";
    if ( defined ( $2 ) ) {
      push ( @output, format_localtime( [ localtime( parsedate( $2 ) ) ] ) );
    }
    push ( @output, 'until', format_localtime( [ localtime( parsedate( $3 ) ) ] ) );
    print join ( ' ', @output ) . "\n";
  }
}

sub format_localtime {
  my ( $ar_localtime ) = @_;

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
  push ( @output, sprintf( "%d:%02d%s", ( $hr > 12 ) ? $hr - 12 : $hr, $min, ( $hr >= 12 ) ? 'pm' : 'am' ) );
  return join ( ' ' , @output );
}

my $rainforest = new Rainforest;
print $rainforest->get5minPowerLoad() . "\n";
print $rainforest->isHighCostTime() . "\n";
__END__
