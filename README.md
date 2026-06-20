# IoT Sensors
Set of scripts to read data from IoT devices for use on other devices (see [flp](https://github.com/kellyhirano/flp) and [inky](https://github.com/kellyhirano/inky) as examples.

These scripts require `sensor.conf` to have a few basic entries for mqtt server information as well as a sqlite3 file desination. Required values are:

    [ALL]
    base_dir: <directory containing db file>
    db_file: <db file, can be %(base_dir)/sensors.db>
    mqtt_host: <ip address of mqtt server>

## Awair
Script: `get_awair.py`. An [Awair Developer account (free)](https://developer.getawair.com/onboard/welcome) is required for an access token which is stored in `sensor.conf`. The following entry is required:

    [AWAIR]
    auth_token_api: <auth token, do not include "Bearer ">

Optionally, you can add a `location` entry in the `[AWAIR]` section of `sensor.conf` if you have multiple locations under your account and want to filter down all units at a single location. This location name is `locationName` from the [Devices endpoint](https://docs.developer.getawair.com/#26ca616d-b6e6-4647-a07d-5c90a23b7afe). Otherwise, devices from all locations will be used.

An `awair` sqlite3 table needs to be created in the `db_file` using the `awair.sql` schema.

Fragility in the code includes some cold start problems where the last hour delta calculations will likely break when there are no previous entries in the database. Also, there aren't any sanity checks for the existance of required configuration varibles nor testing. Sounds bad when I write it down...

## Purple Air
Script: `get_aqi.py`. Usage `get_aqi.py <station_id>`. You can get your station ID by looking at a station on the Purple Air map and extracting it from the URL. In this example `https://www.purpleair.com/map?opt=1/i/mAQI/a10/cC0&select=20501#12.99/37.79276/-122.40393` the station ID is set to the URL arg `select`: `20501`.

A `purple_air` sqlite3 table needs to be created in the `db_file` using the `purple_air.sql` schema. 

## Pollen
Script: `get_pollen.py`. Usage `python3 get_pollen.py`. It fetches the daily tree, grass, and weed forecast from the Google Pollen API and publishes it to `pollen/sensor`.

The following config entry is required:

    [POLLEN]
    api_key: <Google Pollen API key>
    latitude: <home latitude>
    longitude: <home longitude>
    heartbeat_url: <optional uptime kuma push url>

This collector is deployed on the `sensors` host through `ansible/playbooks/sensors-deploy.yml` as an hourly cron job. Do not add or edit the cron line manually on the Pi.

## SJ Water
Script: `get_water.py`. Usage `python3 get_water.py`. It logs in to SJWaterHUB, calls the VXEngage hourly usage graph endpoint, stores returned hourly intervals in SQLite, publishes retained MQTT summaries to `sjwater/daily` and `sjwater/hourly`, and publishes retained Home Assistant MQTT discovery configs for those sensors. Values are gallons rounded by the portal to whole gallons.

The following config entry is required. Use `RawConfigParser`, so `%` characters in the password are literal and should not be escaped.

    [SJWATER]
    username: <sjwaterhub.com email>
    password: <sjwaterhub.com password>
    account_number: <account number from sjwaterhub.com>
    heartbeat_url: <optional uptime kuma push url>

This collector is deployed on the `sensors` host through `ansible/playbooks/sensors-deploy.yml` every 4 hours to avoid hitting the customer portal unnecessarily. Do not add or edit the cron line manually on the Pi.

Home Assistant consumes this through retained MQTT discovery published by the collector. Expected entities are `sensor.sj_water_smart_meter_daily_usage`, `sensor.sj_water_smart_meter_hourly_usage`, and `sensor.sj_water_smart_meter_portal_last_updated`. If HA appears stale while MQTT is populated, check `Portal Last Updated`; SJWaterHUB may be returning an old `last_updated` timestamp and unchanged `0.0` gallon values.

## Rainforest
Script: `rainforest_loop.py`. Usage `rainforest_loop.py`. This connects to a
local [Rainforest EAGLE
3](https://rainforestautomation.com/us-retail-store/eagle-3-energy-gateway-and-smart-home-hub/)
leveraging the [local
API](https://rainforestautomation.com/wp-content/uploads/2017/02/EAGLE-200-Local-API-Manual-v1.0.pdf).
It publishes load data to a mqtt server and writes to a local sqlite db using
the `rainforest.sql` schema.

The following config entry is required:

    [RAINFOREST]
    username: <Eagle Cloud ID>
    password: <Eagle Install Code>
    hardware_address: <Hardware address from device_list command>
    eagle_ip: <local IP>
