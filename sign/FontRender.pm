package FontRender;

use Data::Dumper;
use strict;

sub new {
    my $class = shift;
    my $self  = {
        _characters => {},
        _max_width  => 96
    };
    bless $self, $class;

    $self->readFonts();

    return $self;
}

sub readFont {
    my ( $self, $ar_lines ) = @_;

    my $this_ascii = 0;
    my $h_offset   = 0;
    my $v_offset   = 0;

    for my $line (@$ar_lines) {

        chomp $line;

        # we found a header
        if ( $line =~ /^(\d+) (\d+) (\d+)/ ) {
            ( $this_ascii, $h_offset, $v_offset ) = ( $1, $2, $3 );
            $self->{_characters}->{$this_ascii} =
              { h_offset => $h_offset, v_offset => $v_offset, bitmap => [] };
        }

        # bitmap
        elsif ( $this_ascii && $line =~ /^[01]+$/ ) {
            push( @{ $self->{_characters}->{$this_ascii}->{bitmap} }, $line );
        }

        # hopefully this only matches a blank line
        else {
            $this_ascii = 0;
        }
    }
}

sub padCharacters {
    my ($self) = @_;

    for my $ascii ( keys %{ $self->{_characters} } ) {
        my $width    = length( $self->{_characters}->{$ascii}->{bitmap}->[0] );
        my $pad_row  = 0 x $width;
        my $num_rows = scalar( @{ $self->{_characters}->{$ascii}->{bitmap} } );

        # if v_offset < 7, pad the top
        # if v_offset = 7 and but the bitmap size is < 7, pad the bottom
        if ( $self->{_characters}->{$ascii}->{v_offset} < 7 ) {
            my $rows_to_pad = 7 - $self->{_characters}->{$ascii}->{v_offset};
            $rows_to_pad =
                ( ( $rows_to_pad + $num_rows ) > 7 )
              ? ( 7 - $num_rows )
              : $rows_to_pad;    # make sure we don't pad too much
            for my $i ( 1 .. ($rows_to_pad) ) {
                unshift(
                    @{ $self->{_characters}->{$ascii}->{bitmap} },
                    $pad_row
                );
            }
        }

        if ( $self->{_characters}->{$ascii}->{v_offset} == 7 && $num_rows < 7 )
        {
            for my $i ( 1 .. ( 7 - $num_rows ) ) {
                push( @{ $self->{_characters}->{$ascii}->{bitmap} }, $pad_row );
            }
        }
    }
}

sub readFonts {
    my ($self) = @_;

    my $font_basedir = '/home/pi/sign/font';
    my @font_files =
      ( '7x7.simpleglyphs', 'amends.simpleglyphs', 'specific.simpleglyphs' );

    for my $file (@font_files) {
        open( FH, "$font_basedir/$file" ) || die "Can't open $file: $!";
        my @lines = <FH>;
        close FH;

        $self->readFont( \@lines );
    }
    $self->padCharacters;
}

sub renderString {
    my ( $self, $string, $blank_at_top, $center ) = @_;

    # stick the blank line at the top? each row is 8 pixels, fonts are 7.
    $blank_at_top ||= 0;

    # center?
    $center ||= 0;

    # bitmap and initialization
    my @bitmap_rows = ();
    for my $i ( 0 .. 7 ) {
        $bitmap_rows[$i] = 0 x $self->{_max_width};
    }

    my $h_cursor = 0;

    for my $this_ascii ( map { ord($_) } split( //, $string ) ) {
        my $width =
          length( $self->{_characters}->{$this_ascii}->{bitmap}->[0] );
        last if ( $h_cursor + $width > $self->{_max_width} );
        $self->fillBitmapArrayAtOffset( \@bitmap_rows, $h_cursor,
            $blank_at_top, $this_ascii );
        $h_cursor += $width + 1;
    }

    if ($center) {
        $h_cursor -= 1;    # remove the space since we're at the end
        my $blank_at_end    = $self->{_max_width} - $h_cursor;
        my $h_space_to_move = int( $blank_at_end / 2 );
        for my $i ( 0 .. $#bitmap_rows ) {

            # remove the padding from the end
            substr( $bitmap_rows[$i], $self->{_max_width} - $h_space_to_move,
                $h_space_to_move, '' );

            # add it back to the beginning
            $bitmap_rows[$i] = 0 x $h_space_to_move . $bitmap_rows[$i];
        }
    }

    # print debug bitmap
    my $debug_string = join( "\n", @bitmap_rows ) . "\n";
    $debug_string =~ s/0/./mg;
    $debug_string =~ s/1/X/mg;
    print $debug_string;

    join( '', @bitmap_rows );
}

sub renderTwoStrings {
    my ( $self, $string1, $string2, $center ) = @_;

    $self->renderString( $string1, 0, $center )
      . $self->renderString( $string2, 1, $center );
}

sub fillBitmapArrayAtOffset {
    my ( $self, $ar_bitmap, $h, $v, $this_ascii ) = @_;

    my $v_offset = 0;
    for my $row ( @{ $self->{_characters}->{$this_ascii}->{bitmap} } ) {
        my $width = length($row);
        substr( $ar_bitmap->[ $v + $v_offset ], $h, $width, $row );
        $v_offset++;
    }
}

1;
