#!/usr/bin/env python3

import xml.etree.ElementTree as ET
import configparser
import http.client
import fcntl, sys
import json
import re
import time
import base64
import sqlite3
import paho.mqtt.publish as publish
import logging

# Only one proess allowed to be running
lock_file = '/tmp/rainforest.exists'
fp = open(lock_file, 'w')
try:
  fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
  print ('Only one instance may run. Delete lockfile ' + lock_file)
  sys.exit(0)


def save_data_to_db(db_file, load):
  """
  Connect to the specified sqlite3 db_file and save the load value to the rainforest table.
  """

  # Connect to the db, get a cursor
  connection = sqlite3.connect(db_file, timeout=30)
  cursor = connection.cursor()

  # Collect the data of tuples into an array
  data_to_db = ( load, )

  # Execute these statements en masse against the list
  cursor.execute('replace into rainforest (load) values (?)', data_to_db)

  # Don't forget to commit!
  connection.commit()
  connection.close()


def publish_to_mqtt(mqtt_host, payload, channel):
  """
  Publish the payload to the specified mqtt server and channel.
  """
  try:
    publish.single( 'rainforest/' + channel, payload, hostname=mqtt_host, retain=True )

  except Exception as ex:
    logging.warning('Publishing to mqtt error')
    logging.warning('Type: ' + str(type(ex)))

def format_load_string(raw_load):
  """
  Clean up the raw load number to be of the format 0.3f
  """

  try:
    #formatted_load = re.sub(r'[^0-9.]', r'', raw_load)
    formatted_load = '{:0.3f}'.format(float(raw_load.strip()))

    return formatted_load

  except Exception as ex:
    logging.warning('Load string formatting error')
    logging.warning('Type: ' + str(type(ex)))
    logging.warning('raw_load: ' + str(raw_load))


def get_hourly_average(db_file):
  """Calculate average load over the last 60 minutes."""
  try:
    connection = sqlite3.connect(db_file, timeout=30)
    cursor = connection.cursor()
    cursor.execute("""
      SELECT AVG(load), COUNT(*)
      FROM rainforest
      WHERE datetime >= datetime('now', '-60 minutes', 'localtime')
    """)
    row = cursor.fetchone()
    connection.close()

    if row and row[0] is not None:
      return {
        'avg_kw': round(row[0], 3),
        'sample_count': row[1]
      }
  except Exception as ex:
    logging.warning('Error getting hourly average: ' + str(ex))
  return None


def get_24h_comparison(db_file):
  """Compare current hour average to same hour 24h ago."""
  try:
    connection = sqlite3.connect(db_file, timeout=30)
    cursor = connection.cursor()

    # Current hour average (last 60 min)
    cursor.execute("""
      SELECT AVG(load)
      FROM rainforest
      WHERE datetime >= datetime('now', '-60 minutes', 'localtime')
    """)
    current_avg = cursor.fetchone()[0]

    # 24h ago average (2-hour window centered on 24h ago)
    cursor.execute("""
      SELECT AVG(load)
      FROM rainforest
      WHERE datetime >= datetime('now', '-25 hours', 'localtime')
        AND datetime < datetime('now', '-23 hours', 'localtime')
    """)
    past_avg = cursor.fetchone()[0]
    connection.close()

    if current_avg is not None and past_avg is not None and past_avg > 0:
      diff = current_avg - past_avg
      return {
        'current_hour_avg': round(current_avg, 3),
        'hour_24h_ago_avg': round(past_avg, 3),
        'diff_kw': round(diff, 3)
      }
  except Exception as ex:
    logging.warning('Error getting 24h comparison: ' + str(ex))
  return None


def get_daily_total(db_file):
  """Calculate total kWh consumed today (since midnight)."""
  try:
    connection = sqlite3.connect(db_file, timeout=30)
    cursor = connection.cursor()
    # Each sample represents ~1 minute of usage
    # kWh = kW * hours, so each minute sample = kW * (1/60) hours
    cursor.execute("""
      SELECT SUM(load) / 60.0
      FROM rainforest
      WHERE date(datetime, 'localtime') = date('now', 'localtime')
    """)
    row = cursor.fetchone()
    connection.close()

    if row and row[0] is not None:
      return {'total_kwh': round(row[0], 2)}
  except Exception as ex:
    logging.warning('Error getting daily total: ' + str(ex))
  return None


def get_peak_today(db_file):
  """Get highest instantaneous demand today."""
  try:
    connection = sqlite3.connect(db_file, timeout=30)
    cursor = connection.cursor()
    cursor.execute("""
      SELECT MAX(load), datetime
      FROM rainforest
      WHERE date(datetime, 'localtime') = date('now', 'localtime')
    """)
    row = cursor.fetchone()
    connection.close()

    if row and row[0] is not None:
      peak_time = "??:??"
      if row[1]:
        try:
          peak_time = row[1][11:16]  # "YYYY-MM-DD HH:MM:SS" -> "HH:MM"
        except:
          pass
      return {
        'peak_kw': round(row[0], 3),
        'peak_time': peak_time
      }
  except Exception as ex:
    logging.warning('Error getting peak today: ' + str(ex))
  return None


def publish_aggregate_metrics(db_file, mqtt_host):
  """Calculate and publish all aggregate metrics."""
  try:
    hourly = get_hourly_average(db_file)
    if hourly:
      publish_to_mqtt(mqtt_host, json.dumps(hourly), 'hourly')

    compare = get_24h_comparison(db_file)
    if compare:
      publish_to_mqtt(mqtt_host, json.dumps(compare), '24h_compare')

    daily = get_daily_total(db_file)
    if daily:
      publish_to_mqtt(mqtt_host, json.dumps(daily), 'daily')

    peak = get_peak_today(db_file)
    if peak:
      publish_to_mqtt(mqtt_host, json.dumps(peak), 'peak')

  except Exception as ex:
    logging.warning('Error publishing aggregate metrics: ' + str(ex))


def create_request_body(config, logging):
  """
  Merely return the XML command (given a hardware_address) to be POSTed to the Rainforest
  """

  request_body = '''<Command>
 <Name>device_query</Name>
 <DeviceDetails>
 <HardwareAddress>{hardware}</HardwareAddress>
 </DeviceDetails>
 <Components>
 <Component>
 <Name>Main</Name>
 <Variables>
 <Variable>
 <Name>zigbee:InstantaneousDemand</Name>
 </Variable>
 </Variables>
 </Component>
 </Components>
</Command>'''.format(hardware = config.get('RAINFOREST', 'hardware_address'))

  logging.info('Request Body: ' + request_body)

  return request_body


def create_request_headers(config, logging):
  """
  Create the request header, including the authorization header
  """

  username = config.get('RAINFOREST', 'username')
  password = config.get('RAINFOREST', 'password')
  user_pass = username + ':' + password
  user_pass_ascii = base64.b64encode(user_pass.encode('ascii'))
  basic_cred = "Basic " + user_pass_ascii.decode('UTF-8')

  request_headers = {"Content-type": "application/x-www-form-urlencoded", "Authorization": basic_cred}

  logging.info('Request Headers: ' + str(request_headers))

  return request_headers


def extract_load_from_xml(raw_xml):
  """
  Take in raw XML, parse it, extract the InstantaneousDemand load from the XML
  """

  logging.info("In extract_load_from_xml")

  try:
    xml_root = ET.fromstring(raw_xml)
    for variable in xml_root.findall("./Components/Component/Variables/Variable"):
      if ( variable[0].text == 'zigbee:InstantaneousDemand' ):
        raw_load = variable[1].text 
        logging.info('raw_load: ' + str(raw_load))

        if ( raw_load is not None ):
          formatted_load = format_load_string(raw_load)
          logging.info('formatted_load: ' + str(formatted_load))
          return formatted_load

  except (ET.ParseError):
    logging.warning('Failed to parse XML from Rainforest')
    logging.warning(xml_response)

  ## Will return 'None" on error/no match


# Gather our code in a main() function
def main():
    """
    Read in config file, set up logging, run main loop
    """

    config = configparser.ConfigParser()
    config.read('sensor.conf')

    logging.basicConfig(filename=config.get('ALL', 'base_dir') + '/rainforest.log',
                        format="%(asctime)s %(levelname)-8s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S",
                        level=logging.WARN)

    request_body = create_request_body(config, logging)
    request_headers = create_request_headers(config, logging)

    last_save_minute = -1
    last_aggregate_minute = -1
    while_loop_sleep = 3
    mqtt_host = config.get('ALL', 'mqtt_host')
    db_file = config.get('ALL', 'db_file')

    while True:

      ## Make the connection and get the XML response
      response = None
      xml_response = None
      connection = None

      try:
        logging.info("Start while loop")

        connection = http.client.HTTPConnection(config.get('RAINFOREST', 'eagle_ip'), timeout=10)
        connection.set_debuglevel(0)
        connection.request("POST", "/cgi-bin/post_manager", request_body, request_headers);

        response = connection.getresponse()
        xml_response = response.read()

        logging.info('Status: ' + str(response.status))
        logging.info('Reason: ' + response.reason)
        logging.info('Headers: ' + str(response.getheaders()))
        logging.info('Response: ' + xml_response.decode('UTF-8'))

      except Exception as ex:
        logging.warning('Connection error: ' + str(type(ex).__name__) + ' - ' + str(ex))
        if response is not None:
          logging.warning('Status: ' + str(response.status))
          logging.warning('Reason: ' + response.reason)
        if xml_response is not None:
          logging.warning('Response: ' + xml_response.decode('UTF-8'))

        if connection is not None:
          try:
            connection.close()
          except:
            pass
        time.sleep(while_loop_sleep * 2)
        continue

      ## Parse the XML
      formatted_load = extract_load_from_xml(xml_response)

      if ( formatted_load is not None  ):
        publish_to_mqtt(mqtt_host, '{"instantaneous": ' + formatted_load + '}', 'load')

        ## Don't save to the db more than once a minute
        curr_time = time.localtime()
        if ( curr_time[4] != last_save_minute ):
          last_save_minute = curr_time[4]
          save_data_to_db(db_file, formatted_load)

        ## Publish aggregate metrics every 5 minutes
        if curr_time[4] % 5 == 0 and curr_time[4] != last_aggregate_minute:
          last_aggregate_minute = curr_time[4]
          publish_aggregate_metrics(db_file, mqtt_host)

      connection.close()
      time.sleep(while_loop_sleep)

# Standard boilerplate to call the main() function to begin
# the program.
if __name__ == '__main__':
    main()

'''
<Device>
  <DeviceDetails>
    <Name>Power Meter</Name>
    <HardwareAddress>redacted</HardwareAddress>
    <NetworkInterface>redacted</NetworkInterface>
    <Protocol>Zigbee</Protocol>
    <NetworkAddress>redacted</NetworkAddress>
    <Manufacturer>Generic</Manufacturer>
    <ModelId>electric_meter</ModelId>
    <LastContact>redacted</LastContact>
    <ConnectionStatus>Connected</ConnectionStatus>
  </DeviceDetails>
  <Components>
    <Component>
      <HardwareId></HardwareId>
      <FixedId>0</FixedId>
      <Name>Main</Name>
      <Variables>
        <Variable>
          <Name>zigbee:InstantaneousDemand</Name>
          <Value>2.151000 kW</Value>
          <Units>kW</Units>
        </Variable>
      </Variables>
    </Component>
  </Components>
</Device>

<Command>
 <Name>device_query</Name>
 <DeviceDetails>
 <HardwareAddress>redacted</HardwareAddress>
 </DeviceDetails>
 <Components>
 <Component>
 <Name>Main</Name>
 <Variables>
 <Variable>
 <Name>zigbee:InstantaneousDemand</Name>
 </Variable>
 </Variables>
 </Component>
 </Components>
</Command>
'''
