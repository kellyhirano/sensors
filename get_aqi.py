#!/usr/bin/python3

import configparser
import argparse
import fcntl
import sys
import http.client
import json
import aqi
import time
import sqlite3
import paho.mqtt.publish as publish

# Only one proess allowed to be running
lock_file = '/tmp/aqi.exists'
fp = open(lock_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print('Only one instance may run. Delete lockfile ' + lock_file)
    sys.exit(0)


def url_to_dict(host, uri):
    """Given a URI, fetch it, assume it's json an parse that into a dict"""
    try:
        connection = http.client.HTTPSConnection(host)
        connection.request('GET', uri)
        response = connection.getresponse()
        output = response.read()
        output_dict = json.loads(output.decode('UTF-8'))

        return output_dict

    except IOError:
        print('problem reading url: ' + uri)


def get_station_data(station_id):
    """Given a station id, return station data in a dict"""
    purpleair_host = 'www.purpleair.com'
    purpleair_uri = '/json?show=' + str(station_id)
    purple_air_data = url_to_dict(purpleair_host, purpleair_uri)

    # Init summary w/ empty list
    summary = {}
    summary['station_dicts'] = []
    summary['total'] = {}
    summary['average'] = {}
    summary['aqi'] = {}

    # The endpoint returns all station data; find what we're looking for
    for result in purple_air_data['results']:

        # Some results include child nodes for some reason; skip those
        if(int(result['ID']) != int(station_id)):
            continue

        stats_dict = json.loads(result['Stats'])
        stats_dict['station'] = result['ID']
        stats_dict['last_updated'] = result['LastSeen']
        summary['station_dicts'].append(stats_dict)

    # Loop through the keys we want to average,
    # first sum, average, then calculate AQI
    # v = Realtime
    # v1 = Short-Term
    # v2 = 30 min avg
    # v3 = 1 hr avg
    # v4 = 6 hr avg
    # v5 = 24 hr avg
    # v6 = 1 wk avg
    keys_to_avg = ['v', 'v1', 'v2', 'v3', 'v4', 'v5', 'v6']
    for station_dict in summary['station_dicts']:
        for key in keys_to_avg:
            if key not in summary['total']:
                summary['total'][key] = 0
            summary['total'][key] += station_dict[key]

    num_stations = len(summary['station_dicts'])
    for key in keys_to_avg:
        summary['average'][key] = summary['total'][key] / num_stations
        summary['aqi'][key] = int(aqi.to_iaqi(aqi.POLLUTANT_PM25,
                                              summary['average'][key],
                                              algo=aqi.ALGO_EPA))

    return summary


def get_aqi_description(aqi):
    """Take in an AQI, get a description"""

    # https://en.wikipedia.org/wiki/Air_quality_index
    aqi_defs = {0: {'desc': 'Good', 'color': 'Green'},
                51: {'desc': 'Moderate', 'color': 'Yellow'},
                101: {'desc': 'Unhealthy for SG', 'color': 'Orange'},
                151: {'desc': 'Unhealthy', 'color': 'Red'},
                201: {'desc': 'Very Unhealthy', 'color': 'Purple'},
                301: {'desc': 'Hazardous', 'color': 'Maroon'}}

    aqi_mins = sorted(aqi_defs.keys())
    curr_min = aqi_mins.pop(0)

    for aqi_min in aqi_mins:
        if aqi < aqi_min:
            break

        curr_min = aqi_min

    return aqi_defs[curr_min]['desc']


def save_data_to_db(db_host, station_data):
    """Save current readings into the purple_air table"""

    con = sqlite3.connect(db_host)
    cur = con.cursor()

    # Collect the data of tuples into an array
    data_to_db = []
    for key in station_data['aqi']:
        data_to_db.append((key, station_data['aqi'][key]))

    # Execute these statements en masse against the list
    statement = """insert into purple_air
                   (datetime, id, aqi)
                   values (datetime('now','localtime'), ?, ?)"""
    cur.executemany(statement, data_to_db)

    # Don't forget to commit!
    con.commit()
    con.close()


def get_last_hour_aqi_diff(db_host, station_data):
    """Get last hour AQI diff of v1 and return that value"""

    con = sqlite3.connect(db_host)
    cur = con.cursor()

    statement = """select aqi
                   from purple_air
                   where id = 'v1'
                   and strftime('%s', 'now', 'localtime')
                       - strftime('%s', datetime) > ( 60*60 )
                   order by datetime desc limit 1"""
    cur.execute(statement)

    rows = cur.fetchall()

    con.close()

    return station_data['aqi']['v1'] - rows[0][0]


def publish_to_mqtt(mqtt_host, payload, channel):
    """Publish single payload to channel on mqtt_host"""

    publish.single('purpleair/' + channel, payload, hostname=mqtt_host,
                   retain=True)


def main():
    config = configparser.ConfigParser()
    config.read('sensor.conf')

    mqtt_host = config.get('ALL', 'mqtt_host')
    db_host = config.get('ALL', 'db_file')

    parser = argparse.ArgumentParser(description='Get AQI data from PurpleAir')
    parser.add_argument('station_ids', nargs='+', type=int)
    parser.add_argument('--nosave', action='store_const',
                        const=True, default=False)
    parser.add_argument('--nomqtt', action='store_const',
                        const=True, default=False)
    parser.add_argument('--verbose', action='store_const',
                        const=True, default=False)
    args = parser.parse_args()

    time_now = int(time.time())
    stations = []
    station_data = {}

    for station_id in args.station_ids:
        station_data = get_station_data(station_id)

        # Store time delta as first elem in tuple for sorting
        time_since_update = time_now \
            - station_data['station_dicts'][0]['last_updated']
        stations.append((time_since_update, station_data))
        if args.verbose:
            print("Station ID: {}".format(station_id))
            print("Time since update: {}".format(time_since_update))

    # Bias to the first station unless it hasn't been upadted in the last 5m.
    # If the first station is stale, sort by time_since_update, then take
    # the first item. This prevents bouncing back and forth between stations.
    if stations[0][0] >= 300:
        stations.sort(key=lambda x: x[0])

    station_data = stations[0][1]

    if args.verbose:
        print("Selected data:")
        print(station_data)

    if not args.nosave:
        save_data_to_db(db_host, station_data)

    if not args.nomqtt:
        aqi_description = get_aqi_description(station_data['aqi']['v1'])
        publish_to_mqtt(mqtt_host,
                        '{"st_aqi": ' + str(station_data['aqi']['v1']) + ', '
                        + '"st_aqi_desc": "' + aqi_description + '"}',
                        'sensor')

        last_hour_aqi_diff = get_last_hour_aqi_diff(db_host, station_data)
        publish_to_mqtt(mqtt_host,
                        '{"st_aqi": ' + str(last_hour_aqi_diff) + '}',
                        'last_hour')


# This is the standard boilerplate that calls the main() function.
if __name__ == '__main__':
    main()
