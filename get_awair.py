#!/usr/bin/python3

import configparser
import fcntl
import sys
import http.client
import json
import pprint
import aqi
import sqlite3
import paho.mqtt.publish as publish

# Only one proess allowed to be running
lock_file = '/tmp/awair.exists'
fp = open(lock_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print('Only one instance may run. Delete lockfile ' + lock_file)
    sys.exit(0)


class AwairAPI():
    """Basic class to handle Awair API connections"""

    def __init__(self, auth_token, location=None):
        """Init auth_token"""

        self.__auth_token = auth_token
        self.__api_host = 'developer-apis.awair.is'
        self.__location = location
        self.__device_data = []

    def __uri_to_dict(self, uri):
        """URI sent to __api_host with results returned to a dict"""

        try:
            connection = http.client.HTTPSConnection(self.__api_host)
            headers = {'Authorization': 'Bearer ' + self.__auth_token}
            connection.request('GET', uri, headers=headers)
            response = connection.getresponse()
            output = response.read()
            output_dict = json.loads(output.decode('UTF-8'))

            return output_dict

        except IOError:
            print('problem reading url: ' + uri)

    def __get_devices(self):
        """Get list of devices, filtered by __location"""

        devices = self.__uri_to_dict('/v1/users/self/devices')
        if self.__location is not None:
            devices['devices'] = [loc for loc in devices['devices']
                                  if loc['locationName'] == self.__location]

        return devices

    def update_device_data(self):
        """Get devices, update them and store in __device_data"""
        self.devices = self.__get_devices()

        self.__device_data = []
        for device in self.devices['devices']:
            this_data = self.__get_device_data(device['deviceType'],
                                               device['deviceId'],
                                               device['name'])
            self.__device_data.append(this_data)

    @property
    def device_data(self):
        return self.__device_data

    def __create_air_data_uri(self, device_type, device_id):
        """Create URI to hit AirData API"""

        return('/v1/users/self/devices/' +
               '{}/{}/air-data/latest?fahrenheit=true'.format(device_type,
                                                              device_id))

    def __get_device_data(self, device_type, device_id, device_name):
        """Receive AirData API data, do conversions to standard format"""

        device_uri = self.__create_air_data_uri(device_type, device_id)
        device_data = self.__uri_to_dict(device_uri)

        sensor_data = {}
        sensor_data['location'] = device_name
        sensor_data['datetime'] = device_data['data'][0]['timestamp']

        # Convert list of dicts to dict indexed by comp
        raw_sensor_data = {}
        for sensor in device_data['data'][0]['sensors']:
            raw_sensor_data[sensor['comp']] = sensor['value']

        sensor_data['temp'] = '{:.1f}'.format(raw_sensor_data['temp'])
        sensor_data['humid'] = '{:.0f}'.format(raw_sensor_data['humid'])
        sensor_data['co2'] = '{:.0f}'.format(raw_sensor_data['co2'])
        sensor_data['voc'] = '{:.0f}'.format(raw_sensor_data['voc'])

        if 'pm25' in raw_sensor_data:
            sensor_data['dust'] = '{:.1f}'.format(raw_sensor_data['pm25'])
        else:
            sensor_data['dust'] = ''

        return sensor_data


def save_data_to_db(db_file, storage_data):
    """Save Awair data to local sensor sqlite3 file"""

    # Connect to the db, get a cursor
    con = sqlite3.connect(db_file)
    cur = con.cursor()

    # Collect the data of tuples into an array
    data_to_db = []
    for sensor in storage_data:
        data_to_db.append((sensor['datetime'], sensor['location'],
                           sensor['temp'], sensor['co2'], sensor['humid'],
                           sensor['voc'], sensor['dust']))

    # Execute these statements en masse against the list
    statement = """replace
                   into awair
                   (datetime, location, temp, co2, humid, voc, dust)
                   values (?, ?, ?, ?, ?, ?, ?)"""
    cur.executemany(statement, data_to_db)

    # Don't forget to commit!
    con.commit()
    con.close()


def add_last_hour_data(db_file, storage_data):
    """Query sqlite3 to get delta sensor values from the last hour"""

    diff_data = []

    # Connect to the db
    con = sqlite3.connect(db_file)

    # Set this to allow for dictionary lookups for row returns
    # Must set this before even getting a cursor
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Note not localtime for strftime 'now' since Awair stores things in UTC
    statement = """select *
                   from awair
                   where location = ?
                   and strftime('%s', 'now')
                       - strftime('%s', datetime) > ( 60*60 )
                   order by datetime desc limit 1"""

    # Loop through the list of dictionaries for storage data
    for sensor in storage_data:

        # Second element must be a list!
        cur.execute(statement, (sensor['location'],))
        row = cur.fetchone()

        # Make sure there's a previous entry.
        # This should only come into play for new devices
        # TODO type(row) is returning a sql row type, not dict
        # if type(row) is not dict:
        #     continue

        # Slightly dangerous as the keys for the sensor
        # need to mirror that of the rows in the DB
        for key in row.keys():

            # Set last hour key
            last_hour_key = 'last_hour_' + key

            # Skip these
            if key == 'datetime' or key == 'location' or row[key] == '':
                continue

            # One-decimal floats
            elif key == 'temp' or key == 'dust':
                sensor[last_hour_key] = '{:.1f}'.format(float(sensor[key])
                                                        - row[key])

            # Ints
            else:
                sensor[last_hour_key] = int(sensor[key]) - row[key]

    con.close()


def add_last_hour_dust(db_file, storage_data):
    """Add last hour dust separately; diff func needed because of AQI calc"""

    avg_aqi = {}

    # Connect to the db
    con = sqlite3.connect(db_file)

    # Set this to allow for dictionary lookups for row returns
    # Must set this before even getting a cursor
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Note not localtime for strftime 'now' since Awair stores things in UTC
    statement = """select
                   location, avg(dust)
                   from awair
                   where strftime('%s', 'now') - strftime('%s', datetime)
                         < ( 60*60 )
                   and dust != ''
                   group by location"""

    # Second element must be a list!
    cur.execute(statement)
    rows = cur.fetchall()
    con.close()

    # Store the aqi
    for row in rows:
        avg_aqi[row['location']] = int(aqi.to_iaqi(aqi.POLLUTANT_PM25,
                                                   row['avg(dust)'],
                                                   algo=aqi.ALGO_EPA))

    # Add AQI to storage_data
    for sensor in storage_data:
        if sensor['location'] in avg_aqi:
            sensor['aqi'] = avg_aqi[sensor['location']]


def publish_to_mqtt(mqtt_host, data, channel):
    """Publish data to MQTT server"""

    for sensor in data:
        payload = json.dumps(sensor)

        print(">>>>> mqtt")
        print(payload)

        publish.single('awair/' + sensor['location'] + '/' + channel,
                       payload, hostname=mqtt_host, retain=True)


def main():

    config = configparser.ConfigParser()
    config.read('sensor.conf')

    mqtt_host = config.get('ALL', 'mqtt_host')
    db_file = config.get('ALL', 'db_file')
    auth_token = config.get('AWAIR', 'auth_token_api')
    location = config.get('AWAIR', 'location')

    awair_api = AwairAPI(auth_token, location)

    pp = pprint.PrettyPrinter()

    awair_api.update_device_data()
    storage_data = awair_api.device_data
    add_last_hour_dust(db_file, storage_data)
    add_last_hour_data(db_file, storage_data)
    save_data_to_db(db_file, storage_data)
    publish_to_mqtt(mqtt_host, storage_data, 'sensor')


# This is the standard boilerplate that calls the main() function.
if __name__ == '__main__':
    main()
