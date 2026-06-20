#!/usr/bin/python3
"""Fetch pollen data from Google Pollen API and publish to MQTT."""

import configparser
import argparse
import fcntl
import sys
import http.client
import json
import urllib.request
import urllib.parse

HTTP_TIMEOUT_SECONDS = 30

# Only one process allowed to be running
lock_file = '/tmp/pollen.exists'
fp = open(lock_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print('Only one instance may run. Delete lockfile ' + lock_file)
    sys.exit(0)

import paho.mqtt.publish as publish


def get_pollen_data(api_key, latitude, longitude):
    """Fetch today's pollen forecast from Google Pollen API."""
    host = 'pollen.googleapis.com'
    params = urllib.parse.urlencode({
        'key': api_key,
        'location.latitude': latitude,
        'location.longitude': longitude,
        'days': 1,
    })
    uri = '/v1/forecast:lookup?' + params

    try:
        connection = http.client.HTTPSConnection(host, timeout=HTTP_TIMEOUT_SECONDS)
        connection.request('GET', uri)
        response = connection.getresponse()
        output = response.read()
        return json.loads(output.decode('UTF-8'))
    except IOError:
        print('problem reading pollen forecast')
        return None


def build_payload(data):
    """Extract today's pollen type indices from API response."""
    daily = data.get('dailyInfo', [])
    if not daily:
        print('No dailyInfo in response')
        return None

    payload = {}
    for pollen_type in daily[0].get('pollenTypeInfo', []):
        code = pollen_type['code'].lower()
        index_info = pollen_type.get('indexInfo', {})
        payload[code + '_index'] = index_info.get('value')
        payload[code + '_desc'] = index_info.get('category', 'Unknown')
        payload[code + '_in_season'] = pollen_type.get('inSeason', False)

    return payload


def publish_to_mqtt(mqtt_host, payload):
    """Publish pollen payload to MQTT."""
    publish.single('pollen/sensor', json.dumps(payload),
                   hostname=mqtt_host, retain=True)


def ping_heartbeat(config):
    """Ping heartbeat URL on successful run. Configure via sensor.conf [POLLEN] or [ALL] heartbeat_url."""
    try:
        url = config.get('POLLEN', 'heartbeat_url')
    except configparser.NoOptionError:
        try:
            url = config.get('ALL', 'heartbeat_url')
        except configparser.NoOptionError:
            return
    try:
        urllib.request.urlopen(url, timeout=5).close()
        print('Heartbeat pinged')
    except Exception as e:
        print(f'Heartbeat ping failed: {e}')


def main():
    config = configparser.ConfigParser()
    config.read('sensor.conf')

    mqtt_host = config.get('ALL', 'mqtt_host')
    api_key = config.get('POLLEN', 'api_key')
    latitude = config.get('POLLEN', 'latitude')
    longitude = config.get('POLLEN', 'longitude')

    parser = argparse.ArgumentParser(
        description='Get pollen data from Google Pollen API')
    parser.add_argument('--nomqtt', action='store_const',
                        const=True, default=False)
    parser.add_argument('--verbose', action='store_const',
                        const=True, default=False)
    args = parser.parse_args()

    data = get_pollen_data(api_key, latitude, longitude)

    if data is None:
        print('Failed to fetch pollen data')
        sys.exit(1)

    if args.verbose:
        print(json.dumps(data, indent=2))

    payload = build_payload(data)
    if payload is None:
        print('Failed to parse pollen data from response')
        sys.exit(1)

    if args.verbose:
        print('Publishing:', json.dumps(payload, indent=2))

    if not args.nomqtt:
        publish_to_mqtt(mqtt_host, payload)
        ping_heartbeat(config)


# This is the standard boilerplate that calls the main() function.
if __name__ == '__main__':
    main()
