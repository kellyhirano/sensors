#!/usr/bin/python3
"""Fetch water usage from SJ Water Hub and publish to MQTT."""

import argparse
import configparser
import datetime
import fcntl
import json
import sqlite3
import sys
import urllib.request

import paho.mqtt.publish as publish
import requests
from bs4 import BeautifulSoup

SQLITE_TIMEOUT_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 60
BASE_URL = 'https://www.sjwaterhub.com'

lock_file = '/tmp/water.exists'
fp = open(lock_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print('Only one instance may run. Delete lockfile ' + lock_file)
    sys.exit(0)


def connect_db(db_file):
    con = sqlite3.connect(db_file, timeout=SQLITE_TIMEOUT_SECONDS)
    con.execute('PRAGMA busy_timeout = {}'.format(SQLITE_TIMEOUT_SECONDS * 1000))
    return con


def init_db(db_file):
    con = connect_db(db_file)
    con.execute('''CREATE TABLE IF NOT EXISTS sjwater_hourly (
        read_date TEXT NOT NULL,
        hour TEXT NOT NULL,
        gallons REAL,
        leak_gallons REAL,
        unavailable_gallons REAL,
        last_updated TEXT,
        PRIMARY KEY (read_date, hour)
    )''')
    columns = {
        row[1]
        for row in con.execute('PRAGMA table_info(sjwater_hourly)').fetchall()
    }
    if 'unavailable_gallons' not in columns:
        con.execute('ALTER TABLE sjwater_hourly ADD COLUMN unavailable_gallons REAL')
    if 'last_updated' not in columns:
        con.execute('ALTER TABLE sjwater_hourly ADD COLUMN last_updated TEXT')
    con.commit()
    con.close()


def login(username, password):
    """Authenticate to sjwaterhub.com. Returns (session, page_token)."""
    session = requests.Session()
    session.headers['User-Agent'] = (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        'Chrome/120.0.0.0 Safari/537.36'
    )

    resp = session.get(BASE_URL + '/', timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    token_el = soup.find('input', id='Token')
    if not token_el:
        raise RuntimeError('Could not find Token on login page')

    login_req = {
        'Actions': 'VXengage_Login',
        'UserName': username,
        'Password': password,
        'ViewName': 'Login',
        'Language': '',
        'ExistingMFAToken': None,
        'RedirectUrl': '',
        'Token': token_el['value'],
        'SitePrefix': '',
        'AdditionalParameters': {'TargetElementId': 'Login_Password'},
    }
    resp2 = session.post(
        BASE_URL + '/api/WebApi/RequestBroker',
        data=json.dumps({'Request': json.dumps(login_req)}),
        headers={
            'Content-Type': 'application/json;charset=utf-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, */*',
            'Referer': BASE_URL + '/',
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    resp2.raise_for_status()
    ld = resp2.json()

    vx = ld.get('VXengage_Login', {})
    if not vx.get('Success'):
        raise RuntimeError(
            'Login failed: ' + str(vx.get('ErrorMessage') or vx.get('ErrorCode'))
        )

    resp3 = session.post(
        BASE_URL + '/AccountSummary',
        data={'token': ld['Token']},
        headers={'Referer': BASE_URL + '/', 'Accept': 'text/html,*/*'},
        timeout=HTTP_TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    resp3.raise_for_status()
    soup3 = BeautifulSoup(resp3.text, 'html.parser')
    page_token_el = soup3.find('input', id='Token')
    if not page_token_el:
        raise RuntimeError('Could not find Token on AccountSummary page')

    return session, page_token_el['value']


def fetch_water_data(session, page_token, account_number):
    """Call VXengage_GetHourlyGraph and return the response dict."""
    req = {
        'Actions': 'VXengage_GetHourlyGraph',
        'AccountNumber': account_number,
        'Template': 'RealTimeChart',
        'StartDate': '',
        'EndDate': '',
        'GroupData': True,
        'Token': page_token,
        'SitePrefix': '',
        'ViewName': 'UnderstandUsage',
    }
    resp = session.post(
        BASE_URL + '/api/WebApi/RequestBroker',
        data=json.dumps({'Request': json.dumps(req)}),
        headers={
            'Content-Type': 'application/json;charset=utf-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, */*',
            'Referer': BASE_URL + '/UnderstandUsage',
        },
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()

    hg = data.get('VXengage_GetHourlyGraph', {})
    if not hg.get('Success'):
        raise RuntimeError(
            'VXengage_GetHourlyGraph failed: ' + str(hg.get('ErrorMessage'))
        )

    return hg


def _to_float(value):
    if value is None or str(value) in ('', 'None'):
        return 0.0
    return float(value)


def _parse_last_updated(last_updated):
    """Parse the wall-clock portion of LastUpdated into a naive datetime.

    The server reports the TZ offset inconsistently between calls (e.g.
    -07:00 vs -06:00), so we ignore the offset and compare wall-clock to
    the (naive, local) hourly labels.
    """
    try:
        return datetime.datetime.strptime(last_updated[:19], '%Y-%m-%dT%H:%M:%S')
    except (TypeError, ValueError):
        return None


def get_readings(hg):
    """Return latest daily, latest hourly, and all hourly interval readings."""
    daily_labels = hg['Labels']
    daily_usage = hg['SlidingGraphDataSets'][0]['data']
    daily_leak = hg['SlidingGraphDataSets'][1]['data']
    daily_unavailable = hg['SlidingGraphDataSets'][2]['data']

    hourly_labels = hg['ComplexLabels']
    hourly_usage = hg['ComplexSlidingGraphDataSets'][0]['data']
    hourly_leak = hg['ComplexSlidingGraphDataSets'][1]['data']
    hourly_unavailable = hg['ComplexSlidingGraphDataSets'][2]['data']

    last_updated = hg['LastUpdated']

    latest_daily = None
    for i in range(len(daily_labels) - 1, -1, -1):
        val = daily_usage[i]
        if val is not None and str(val) not in ('', 'None'):
            latest_daily = {
                'date': daily_labels[i],
                'gallons': _to_float(val),
                'leak_gallons': _to_float(daily_leak[i]),
                'unavailable_gallons': _to_float(daily_unavailable[i]),
                'last_updated': last_updated,
            }
            break

    hourly_readings = []
    for i, label in enumerate(hourly_labels):
        hourly_readings.append({
            'date': label[0],
            'hour': label[1],
            'gallons': _to_float(hourly_usage[i]),
            'leak_gallons': _to_float(hourly_leak[i]),
            'unavailable_gallons': _to_float(hourly_unavailable[i]),
            'last_updated': last_updated,
        })

    # The hourly array extends to the end of the current day, so the trailing
    # entries are future hours stored as 0 (and not flagged unavailable). Pick
    # the latest reading at or before LastUpdated so we never publish a future
    # hour as the "latest" reading. Fall back to the last entry if LastUpdated
    # can't be parsed.
    cutoff = _parse_last_updated(last_updated)
    latest_hourly = None
    for reading in reversed(hourly_readings):
        if cutoff is not None:
            reading_dt = datetime.datetime.strptime(
                reading['date'] + ' ' + reading['hour'], '%Y-%m-%d %H:%M:%S'
            )
            if reading_dt > cutoff:
                continue
        latest_hourly = reading
        break

    return latest_daily, latest_hourly, hourly_readings


def save_to_db(db_file, hourly_readings):
    """Upsert hourly readings returned by SJ Water Hub."""
    if not hourly_readings:
        return
    con = connect_db(db_file)
    con.executemany(
        '''REPLACE INTO sjwater_hourly
           (read_date, hour, gallons, leak_gallons, unavailable_gallons, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)''',
        [
            (
                hourly['date'],
                hourly['hour'],
                hourly['gallons'],
                hourly['leak_gallons'],
                hourly['unavailable_gallons'],
                hourly['last_updated'],
            )
            for hourly in hourly_readings
        ],
    )
    con.commit()
    con.close()


def publish_to_mqtt(mqtt_host, subtopic, payload):
    publish.single(
        'sjwater/' + subtopic,
        json.dumps(payload),
        hostname=mqtt_host,
        retain=True,
    )


def publish_ha_discovery(mqtt_host):
    device = {
        'identifiers': ['sjwater_smart_meter'],
        'name': 'SJ Water Smart Meter',
        'manufacturer': 'San Jose Water',
        'model': 'SJWaterHUB MQTT',
    }
    sensors = {
        'daily_usage': {
            'name': 'Daily Usage',
            'unique_id': 'sjwater_daily_usage',
            'state_topic': 'sjwater/daily',
            'unit_of_measurement': 'gal',
            'device_class': 'water',
            'state_class': 'total_increasing',
            'value_template': '{{ value_json.gallons }}',
            'json_attributes_topic': 'sjwater/daily',
            'force_update': True,
            'device': device,
        },
        'hourly_usage': {
            'name': 'Hourly Usage',
            'unique_id': 'sjwater_hourly_usage',
            'state_topic': 'sjwater/hourly',
            'unit_of_measurement': 'gal',
            'device_class': 'water',
            'state_class': 'measurement',
            'value_template': '{{ value_json.gallons }}',
            'json_attributes_topic': 'sjwater/hourly',
            'force_update': True,
            'device': device,
        },
        'portal_last_updated': {
            'name': 'Portal Last Updated',
            'unique_id': 'sjwater_portal_last_updated',
            'state_topic': 'sjwater/hourly',
            'device_class': 'timestamp',
            'value_template': '{{ value_json.last_updated }}',
            'json_attributes_topic': 'sjwater/hourly',
            'device': device,
        },
    }
    for object_id, payload in sensors.items():
        publish.single(
            'homeassistant/sensor/sjwater_' + object_id + '/config',
            json.dumps(payload),
            hostname=mqtt_host,
            retain=True,
        )


def ping_heartbeat(config):
    try:
        url = config.get('SJWATER', 'heartbeat_url', raw=True)
    except configparser.NoOptionError:
        return
    try:
        urllib.request.urlopen(url, timeout=5).close()
        print('Heartbeat pinged')
    except Exception as e:
        print('Heartbeat ping failed: ' + str(e))


def main():
    # Default ConfigParser so db_file's %(base_dir)s interpolation works (matching
    # the other sensor scripts). The password can contain literal % characters, so
    # read it raw=True to bypass interpolation rather than requiring %% escaping.
    config = configparser.ConfigParser()
    config.read('sensor.conf')

    mqtt_host = config.get('ALL', 'mqtt_host')
    db_file = config.get('ALL', 'db_file')
    username = config.get('SJWATER', 'username')
    password = config.get('SJWATER', 'password', raw=True)
    account_number = config.get('SJWATER', 'account_number')

    parser = argparse.ArgumentParser(description='Fetch SJ Water Hub usage data')
    parser.add_argument('--nosave', action='store_const', const=True, default=False,
                        help='Skip writing to SQLite')
    parser.add_argument('--nomqtt', action='store_const', const=True, default=False,
                        help='Skip publishing to MQTT')
    parser.add_argument('--verbose', action='store_const', const=True, default=False)
    args = parser.parse_args()

    init_db(db_file)

    if args.verbose:
        print('Logging in...')
    session, page_token = login(username, password)

    if args.verbose:
        print('Fetching water data...')
    hg = fetch_water_data(session, page_token, account_number)

    latest_daily, latest_hourly, hourly_readings = get_readings(hg)

    if args.verbose:
        print('Latest daily:', latest_daily)
        print('Latest hourly:', latest_hourly)
        print('Hourly readings:', len(hourly_readings))

    if not args.nomqtt:
        publish_ha_discovery(mqtt_host)
        if latest_daily:
            publish_to_mqtt(mqtt_host, 'daily', latest_daily)
            if args.verbose:
                print('Published sjwater/daily:', latest_daily)
        if latest_hourly:
            publish_to_mqtt(mqtt_host, 'hourly', latest_hourly)
            if args.verbose:
                print('Published sjwater/hourly:', latest_hourly)
        ping_heartbeat(config)

    if not args.nosave and hourly_readings:
        save_to_db(db_file, hourly_readings)
        if args.verbose:
            print('Saved to DB')


if __name__ == '__main__':
    main()
