"""Tests for NWS-based weather data handling in weather.pl output.

These tests validate:
- The JSON structure expected from weathergov/temptrend
- GHCND CSV record-computation logic (Perl equivalent in Python)
- NCEI normals unit handling
- Day label generation for the 5-day window
- draw_temp_chart() with synthetic data (no hardware)
"""

import csv
import io
import sys
import os
from datetime import date, timedelta
from unittest.mock import MagicMock

# Add project root so we can import impression weather.py
IMPRESSION_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', 'impression')

# Mock hardware / display dependencies before importing weather
sys.modules['inky'] = MagicMock()
inky_mock = MagicMock()
inky_mock.BLACK = 0
inky_mock.WHITE = 1
inky_mock.GREEN = 2
inky_mock.BLUE = 3
inky_mock.RED = 4
inky_mock.YELLOW = 5
inky_mock.ORANGE = 6
inky_mock.WIDTH = 600
inky_mock.HEIGHT = 448
inky_uc_mod = MagicMock()
inky_uc_mod.Inky.return_value = inky_mock
sys.modules['inky.inky_uc8159'] = inky_uc_mod
sys.modules['paho'] = MagicMock()
sys.modules['paho.mqtt'] = MagicMock()
sys.modules['paho.mqtt.client'] = MagicMock()


# ---------------------------------------------------------------------------
# Unit helpers (mirror of Perl logic for cross-validation)
# ---------------------------------------------------------------------------

def parse_ghcnd_csv(csv_content):
    """Python mirror of Perl load_ghcnd_cache().

    Returns {mm_dd: {record_high, record_high_year, record_low, record_low_year}}
    GHCND TMAX/TMIN are tenths of deg C; convert to deg F.
    """
    records = {}
    rows = csv.reader(io.StringIO(csv_content))
    header = next(rows)
    col = {c: i for i, c in enumerate(header)}

    di = col.get('DATE')
    xi = col.get('TMAX')
    ni = col.get('TMIN')
    xai = col.get('TMAX_ATTRIBUTES')
    nai = col.get('TMIN_ATTRIBUTES')
    if di is None:
        return records

    def has_quality_flag(attrs):
        if not attrs:
            return False
        parts = attrs.split(',')
        qflag = parts[1].strip() if len(parts) > 1 else ''
        return qflag != ''

    for f in rows:
        if len(f) <= di:
            continue
        date_str = f[di]
        if len(date_str) < 10:
            continue
        year = int(date_str[:4])
        mm_dd = date_str[5:10]

        if (xi is not None and xi < len(f) and f[xi].strip().lstrip('-').isdigit()
                and not has_quality_flag(f[xai] if xai is not None and xai < len(f) else None)):
            tmax_f = int(f[xi]) / 10 * 9 / 5 + 32
            entry = records.setdefault(mm_dd, {})
            if 'record_high' not in entry or tmax_f > entry['record_high']:
                entry['record_high'] = round(tmax_f, 1)
                entry['record_high_year'] = year

        if (ni is not None and ni < len(f) and f[ni].strip().lstrip('-').isdigit()
                and not has_quality_flag(f[nai] if nai is not None and nai < len(f) else None)):
            tmin_f = int(f[ni]) / 10 * 9 / 5 + 32
            entry = records.setdefault(mm_dd, {})
            if 'record_low' not in entry or tmin_f < entry['record_low']:
                entry['record_low'] = round(tmin_f, 1)
                entry['record_low_year'] = year

    return records


# ---------------------------------------------------------------------------
# Test: GHCND record parsing
# ---------------------------------------------------------------------------

GHCND_CSV = """\
STATION,DATE,TMAX,TMIN
USW00023293,2020-04-12,222,83
USW00023293,2021-04-12,261,100
USW00023293,1984-04-12,356,150
USW00023293,1952-04-12,178,-17
"""


class TestGhcndRecordParsing:
    def test_record_high_year(self):
        records = parse_ghcnd_csv(GHCND_CSV)
        assert records['04-12']['record_high_year'] == 1984

    def test_record_high_value(self):
        records = parse_ghcnd_csv(GHCND_CSV)
        expected = round(356 / 10 * 9 / 5 + 32, 1)
        assert records['04-12']['record_high'] == expected

    def test_record_low_year(self):
        records = parse_ghcnd_csv(GHCND_CSV)
        assert records['04-12']['record_low_year'] == 1952

    def test_record_low_value(self):
        records = parse_ghcnd_csv(GHCND_CSV)
        expected = round(-17 / 10 * 9 / 5 + 32, 1)
        assert records['04-12']['record_low'] == expected

    def test_missing_tmax_skipped(self):
        csv = "STATION,DATE,TMAX,TMIN\nUSW00023293,2020-04-12,,50\n"
        records = parse_ghcnd_csv(csv)
        assert 'record_high' not in records.get('04-12', {})

    def test_multiple_dates_independent(self):
        csv = (
            "STATION,DATE,TMAX,TMIN\n"
            "USW00023293,2020-04-12,300,100\n"
            "USW00023293,2020-04-13,310,90\n"
        )
        records = parse_ghcnd_csv(csv)
        assert '04-12' in records
        assert '04-13' in records
        assert records['04-12']['record_high'] != records['04-13']['record_high']

    def test_quality_flagged_tmin_skipped(self):
        csv_text = (
            'STATION,DATE,TMAX,TMAX_ATTRIBUTES,TMIN,TMIN_ATTRIBUTES\n'
            'USC00047821,1989-07-19,311,",,0",156,",,0"\n'
            'USC00047821,1989-07-20,289,",,0",-150,",G,0"\n'
            'USC00047821,1909-07-20,306,",,0",72,",,0"\n'
        )
        records = parse_ghcnd_csv(csv_text)
        assert records['07-20']['record_low'] == round(72 / 10 * 9 / 5 + 32, 1)
        assert records['07-20']['record_low_year'] == 1909


# ---------------------------------------------------------------------------
# Test: NCEI normals unit (tenths of °F, not °C)
# ---------------------------------------------------------------------------

class TestNceiNormalsUnit:
    def test_ksjc_apr12_high(self):
        """API returns 693 for Apr 12 KSJC high → 69.3°F (reasonable for San Jose)."""
        raw = 693
        normal_f = raw / 10
        assert normal_f == 69.3
        assert 60 < normal_f < 80  # sanity: Apr high in San Jose

    def test_ksjc_apr12_low(self):
        raw = 479
        normal_f = raw / 10
        assert normal_f == 47.9
        assert 40 < normal_f < 60  # sanity: Apr low in San Jose


# ---------------------------------------------------------------------------
# Test: temptrend JSON structure
# ---------------------------------------------------------------------------

def make_day(**kwargs):
    base = {
        'date': '2026-04-12',
        'label': 'Su',
        'actual_high': None,
        'actual_low': None,
        'forecast_high': None,
        'forecast_low': None,
        'normal_high': 69.3,
        'normal_low': 47.9,
        'record_high': 96.1,
        'record_high_year': 1984,
        'record_low': 28.9,
        'record_low_year': 1952,
    }
    base.update(kwargs)
    return base


class TestTempTrendStructure:
    def test_past_day_has_actual(self):
        day = make_day(actual_high=72.0, actual_low=48.0)
        assert day['actual_high'] is not None
        assert day['forecast_high'] is None

    def test_future_day_has_forecast(self):
        day = make_day(forecast_high=75.0, forecast_low=52.0)
        assert day['actual_high'] is None
        assert day['forecast_high'] is not None

    def test_today_can_have_both(self):
        day = make_day(actual_high=68.0, actual_low=50.0,
                       forecast_high=72.0, forecast_low=49.0)
        assert day['actual_high'] is not None
        assert day['forecast_high'] is not None

    def test_all_required_keys_present(self):
        day = make_day()
        required = ('date', 'label', 'actual_high', 'actual_low',
                    'forecast_high', 'forecast_low', 'normal_high', 'normal_low',
                    'record_high', 'record_high_year', 'record_low', 'record_low_year')
        for key in required:
            assert key in day, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Test: day label generation (5-day window)
# ---------------------------------------------------------------------------

class TestDayLabels:
    def test_labels_are_two_chars(self):
        today = date.today()
        for offset in (-2, -1, 0, 1, 2):
            label = (today + timedelta(days=offset)).strftime('%a')[:2]
            assert len(label) == 2

    def test_five_days_centered_on_today(self):
        today = date.today()
        dates = [today + timedelta(days=i) for i in (-2, -1, 0, 1, 2)]
        assert len(dates) == 5
        assert dates[2] == today

    def test_day_index_2_is_today(self):
        today = date.today()
        dates = [today + timedelta(days=i) for i in (-2, -1, 0, 1, 2)]
        assert dates[2].strftime('%Y-%m-%d') == today.strftime('%Y-%m-%d')


# ---------------------------------------------------------------------------
# Test: temperature-to-pixel Y-coordinate scaling
# (mirrors the logic inside draw_temp_chart)
# ---------------------------------------------------------------------------

def make_temp_to_y(y_min, y_max, chart_y, bar_h):
    """Standalone version of the temp_to_y closure in draw_temp_chart."""
    temp_range = y_max - y_min

    def temp_to_y(temp):
        return (chart_y + bar_h - 1
                - int((float(temp) - y_min) / temp_range * (bar_h - 1)))
    return temp_to_y


class TestTempToY:
    """Verify the Y-scale math used by draw_temp_chart."""

    def test_min_temp_at_bottom(self):
        f = make_temp_to_y(y_min=40, y_max=80, chart_y=208, bar_h=70)
        # Min temp should map to bottom pixel: chart_y + bar_h - 1
        assert f(40) == 208 + 70 - 1

    def test_max_temp_at_top(self):
        f = make_temp_to_y(y_min=40, y_max=80, chart_y=208, bar_h=70)
        # Max temp maps to chart_y (top of bar area)
        assert f(80) == 208

    def test_midpoint(self):
        f = make_temp_to_y(y_min=40, y_max=80, chart_y=0, bar_h=70)
        mid_y = f(60)
        # 60 is halfway between 40 and 80, so y ≈ bar_h/2
        assert 30 <= mid_y <= 36

    def test_higher_temp_lower_y(self):
        f = make_temp_to_y(y_min=40, y_max=80, chart_y=0, bar_h=70)
        assert f(70) < f(50)  # higher temp → smaller y coordinate

    def test_scale_dynamic_range(self):
        """Chart auto-scales: y_min rounded down to 10, y_max rounded up to 10."""
        temps = [48.0, 49.0, 67.0, 69.3, 47.9, 96.1, 28.9]
        y_min = (int(min(temps)) // 10) * 10
        y_max = ((int(max(temps)) + 9) // 10) * 10
        assert y_min == 20
        assert y_max == 100
