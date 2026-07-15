#!/usr/bin/python3
"""Fetch water usage from SJ Water Hub and publish to MQTT."""

import argparse
import base64
import configparser
import datetime
import fcntl
import json
import os
import socket
import sqlite3
import ssl
import struct
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import paho.mqtt.publish as publish
import requests
from bs4 import BeautifulSoup

SQLITE_TIMEOUT_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 60
NETWORK_ATTEMPTS = 3
BASE_URL = 'https://www.sjwaterhub.com'
WATER_GRAPH_DAYS = 7

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


def with_network_retries(label, func, *args):
    for attempt in range(1, NETWORK_ATTEMPTS + 1):
        try:
            return func(*args)
        except requests.RequestException as exc:
            if attempt == NETWORK_ATTEMPTS:
                raise
            delay = 10 * attempt
            print(
                '{} failed on attempt {}/{}: {}; retrying in {}s'.format(
                    label, attempt, NETWORK_ATTEMPTS, exc, delay
                ),
                file=sys.stderr,
            )
            time.sleep(delay)


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


def _water_graph_date_range(today=None):
    """Return the rolling date range to request from SJWaterHUB.

    The browser date picker sends YYYY-MM-DD values. Keep the request bounded so
    the 4-hour cron does not repeatedly ask the portal for the full account
    history.
    """
    today = today or datetime.date.today()
    start = today - datetime.timedelta(days=WATER_GRAPH_DAYS)
    return start.isoformat(), today.isoformat()


def fetch_water_data(session, page_token, account_number):
    """Call VXengage_GetHourlyGraph and return the response dict."""
    start_date, end_date = _water_graph_date_range()
    req = {
        'Actions': 'VXengage_GetHourlyGraph',
        'AccountNumber': account_number,
        'Template': 'RealTimeChart',
        'StartDate': start_date,
        'EndDate': end_date,
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
    # the latest reading STRICTLY BEFORE LastUpdated: the slot at the cutoff
    # time is the current open/incomplete hour (0 gallons), so skip it.
    # Fall back to the last entry if LastUpdated can't be parsed.
    cutoff = _parse_last_updated(last_updated)
    latest_hourly = None
    for reading in reversed(hourly_readings):
        if cutoff is not None:
            reading_dt = datetime.datetime.strptime(
                reading['date'] + ' ' + reading['hour'], '%Y-%m-%d %H:%M:%S'
            )
            if reading_dt >= cutoff:
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


def _recv_ws_frame(sock, buf):
    def need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError('websocket closed')
            buf += chunk

    need(2)
    b1, b2 = buf[0], buf[1]
    buf = buf[2:]
    fin = bool(b1 & 0x80)
    opcode = b1 & 0x0F
    length = b2 & 0x7F
    if length == 126:
        need(2)
        length = struct.unpack('!H', buf[:2])[0]
        buf = buf[2:]
    elif length == 127:
        need(8)
        length = struct.unpack('!Q', buf[:8])[0]
        buf = buf[8:]
    if b2 & 0x80:
        need(4)
        mask = buf[:4]
        buf = buf[4:]
    else:
        mask = None
    need(length)
    payload = buf[:length]
    buf = buf[length:]
    if mask:
        payload = bytes(ch ^ mask[i % 4] for i, ch in enumerate(payload))
    return fin, opcode, payload, buf


def _send_ws_json(sock, obj):
    data = json.dumps(obj).encode()
    header = bytearray([0x81])
    if len(data) < 126:
        header.append(0x80 | len(data))
    elif len(data) < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack('!H', len(data)))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack('!Q', len(data)))
    mask = os.urandom(4)
    header.extend(mask)
    masked = bytes(ch ^ mask[i % 4] for i, ch in enumerate(data))
    sock.sendall(bytes(header) + masked)


def _recv_ws_json(sock, buf):
    parts = []
    while True:
        fin, opcode, payload, buf = _recv_ws_frame(sock, buf)
        if opcode == 0x9:
            sock.sendall(b'\x8a\x00')
            continue
        if opcode == 0xA:
            continue
        if opcode == 0x8:
            raise RuntimeError('websocket closed')
        if opcode in (0x1, 0x0):
            parts.append(payload)
            if fin:
                return json.loads(b''.join(parts).decode()), buf


def ha_ws_call(ha_url, token, call_type, payload=None):
    parsed = urllib.parse.urlparse(ha_url.rstrip('/'))
    host = parsed.hostname or 'localhost'
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    raw_sock = socket.create_connection((host, port), timeout=HTTP_TIMEOUT_SECONDS)
    sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host) if parsed.scheme == 'https' else raw_sock
    buf = b''
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((
            'GET /api/websocket HTTP/1.1\r\n'
            'Host: {}:{}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Key: {}\r\n'
            'Sec-WebSocket-Version: 13\r\n\r\n'
        ).format(host, port, key).encode())
        while b'\r\n\r\n' not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError('websocket closed during handshake')
            buf += chunk
        head, buf = buf.split(b'\r\n\r\n', 1)
        if b'101' not in head.split(b'\r\n', 1)[0]:
            raise RuntimeError('websocket handshake failed')
        hello, buf = _recv_ws_json(sock, buf)
        if hello.get('type') != 'auth_required':
            raise RuntimeError('unexpected websocket hello: {}'.format(hello))
        _send_ws_json(sock, {'type': 'auth', 'access_token': token})
        auth, buf = _recv_ws_json(sock, buf)
        if auth.get('type') != 'auth_ok':
            raise RuntimeError('websocket auth failed: {}'.format(auth))
        req = {'id': 1, 'type': call_type}
        if payload:
            req.update(payload)
        _send_ws_json(sock, req)
        while True:
            msg, buf = _recv_ws_json(sock, buf)
            if msg.get('id') == 1:
                if not msg.get('success'):
                    raise RuntimeError('websocket call failed: {}'.format(msg.get('error')))
                return msg.get('result')
    finally:
        sock.close()


def import_ha_statistics(config, db_file):
    try:
        ha_url = config.get('HA', 'url')
        ha_token = config.get('HA', 'token', raw=True)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return

    stat_id = 'sjwater:water_hourly'
    tz = ZoneInfo('America/Los_Angeles')
    con = connect_db(db_file)
    rows = con.execute(
        'SELECT read_date, hour, gallons FROM sjwater_hourly ORDER BY read_date, hour'
    ).fetchall()
    con.close()
    if not rows:
        return

    stats = []
    cumulative = 0.0
    for date, hour, gallons in rows:
        cumulative += float(gallons or 0)
        dt = datetime.datetime.strptime(
            date + ' ' + hour, '%Y-%m-%d %H:%M:%S'
        ).replace(tzinfo=tz)
        stats.append({
            'start': dt.isoformat(),
            'state': round(cumulative, 2),
            'sum': round(cumulative, 2),
        })

    metadata = {
        'has_mean': False,
        'has_sum': True,
        'name': 'SJ Water Usage',
        'source': 'sjwater',
        'statistic_id': stat_id,
        'unit_of_measurement': 'gal',
    }
    ha_ws_call(
        ha_url,
        ha_token,
        'recorder/import_statistics',
        {'metadata': metadata, 'stats': stats},
    )
    print('Imported {} water statistic points to HA'.format(len(stats)))


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
            'state_class': 'total',
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
            'force_update': True,
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
    parser.add_argument('--noha-stats', action='store_const', const=True, default=False,
                        help='Skip importing DB-backed recorder statistics to HA')
    args = parser.parse_args()

    init_db(db_file)

    if args.verbose:
        print('Logging in...')
    session, page_token = with_network_retries('Login', login, username, password)

    if args.verbose:
        start_date, end_date = _water_graph_date_range()
        print('Fetching water data for {} through {}...'.format(start_date, end_date))
    hg = with_network_retries(
        'Fetch water data', fetch_water_data, session, page_token, account_number
    )

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
        if not args.noha_stats:
            import_ha_statistics(config, db_file)


if __name__ == '__main__':
    main()
