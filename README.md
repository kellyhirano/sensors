# IoT Sensors
Set of scripts to read data from IoT devices for use on other devices (see [flp](https://github.com/kellyhirano/flp) and [inky](https://github.com/kellyhirano/inky) as examples.

These scripts require `sensors.conf` to have a few basic entries for mqtt server information as well as a sqlite3 file desination. Required values are:

    [ALL]
    base_dir: <directory containing db file>
    db_file: <db file, can be %(base_dir)/sensors.db>
    mqtt_host: <ip address of mqtt server>

## Awair
Script: `get_awair.py`. An [Awair Developer account (free)](https://developer.getawair.com/onboard/welcome) is required for an access token which is stored in `sensors.conf`. The following entry is required:

    [AWAIR]
    auth_token_api: <auth token, do nott include "Bearer ">

Optionally, you can add a `location` entry in the `[AWAIR]` section of `sensors.conf` if you have multiple locations under your account and want to filter down all units at a single location. This location name is `locationName` from the [Devices endpoint](https://docs.developer.getawair.com/#26ca616d-b6e6-4647-a07d-5c90a23b7afe). Otherwise, devices from all locations will be used.

An `awair` sqlite3 table needs to be created in the `db_file` using the `awair.sql` schema.

Fragility in the code includes some cold start problems where the last hour delta calculations will likely break when there are no previous entries in the database. Also, there aren't any sanity checks for the existance of required configuration varibles nor testing. Sounds bad when I write it down...

## Purple Air
Script: `get_aqi.py`. Usage `get_aqi.py <station_id>`. You can get your station ID by looking at a station on the Purple Air map and extracting it from the URL. In this example `https://www.purpleair.com/map?opt=1/i/mAQI/a10/cC0&select=20501#12.99/37.79276/-122.40393` the station ID is set to the URL arg `select`: `20501`.

A `purple_air` sqlite3 table needs to be created in the `db_file` using the `purple_air.sql` schema. 
