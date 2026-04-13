#!/usr/bin/env python3
"""Fetch pool status from Home Assistant and publish to MQTT."""

import argparse
import configparser
import json
import urllib.request

import paho.mqtt.publish as publish

ENTITIES = {
    'pool_temp':   'sensor.pool_temp',
    'pool_pump':   'switch.pool_pump',
    'pool_heater': 'switch.pool_heater',
    'spa_heater':  'switch.spa_heater',
    'pool_light':  'light.pool_light',
}


def get_state(ha_url, token, entity_id):
    url = '{}/api/states/{}'.format(ha_url, entity_id)
    req = urllib.request.Request(
        url, headers={'Authorization': 'Bearer ' + token})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())['state']


def main():
    parser = argparse.ArgumentParser(description='Fetch pool status from HA')
    parser.add_argument('--nomqtt', action='store_true',
                        help='Skip MQTT publish')
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('sensor.conf')

    mqtt_host = config.get('ALL', 'mqtt_host')
    ha_url = config.get('HA', 'url')
    ha_token = config.get('HA', 'token')

    data = {}
    for key, entity_id in ENTITIES.items():
        try:
            state = get_state(ha_url, ha_token, entity_id)
            if key == 'pool_temp':
                data[key] = (float(state)
                             if state not in ('unknown', 'unavailable')
                             else None)
            else:
                data[key] = state
        except Exception as e:
            print('Error fetching {}: {}'.format(entity_id, e))
            data[key] = None

    print(json.dumps(data))

    if not args.nomqtt:
        publish.single('pool/sensor', json.dumps(data),
                       hostname=mqtt_host, retain=True)


if __name__ == '__main__':
    main()
