# CLAUDE.md

## Overview

Python scripts that poll IoT sensors and publish JSON to MQTT (with `retain=True`). Data stored in SQLite for delta calculations.

## Scripts

| Script | Type | Schedule |
|--------|------|----------|
| `get_awair.py` | One-shot | cron */10m |
| `get_aqi.py` | One-shot | cron */10m |
| `get_pool.py` | One-shot | cron */5m |
| `get_pollen.py` | One-shot | cron 0 * * * * (hourly) |
| `get_water.py` | One-shot | cron 0 */4 * * * (every 4h) |
| `weather.pl` | One-shot | cron */10m |
| `rainforest_loop.py` | Continuous | systemd service |

## Configuration (`sensor.conf`, gitignored — note: NOT `sensors.conf`)

```ini
[ALL]
base_dir = <dir>
db_file = %(base_dir)s/sensors.db
mqtt_host = <ip>

[AWAIR]
auth_token_api = <token>
location = <optional filter>

[POLLEN]
api_key = <google pollen api key>
latitude = <lat>
longitude = <lon>
heartbeat_url = <uptime kuma push url>

[RAINFOREST]
username = <Eagle Cloud ID>
password = <Eagle Install Code>
hardware_address = <from device_list>
eagle_ip = <local IP>

[SJWATER]
username = <sjwaterhub.com email>
password = <password — literal % is fine, read with get(..., raw=True), no %% escaping>
account_number = <account number from sjwaterhub.com>
heartbeat_url = <uptime kuma push url>
```

## MQTT Topics Published

- `awair/{physical_location}/{location}/sensor` — temp, co2, humid, voc, dust, aqi, deltas
- `purpleair/sensor` — EPA + LRAPA AQI
- `purpleair/last_hour` — hour delta (legacy, kept for compat)
- `rainforest/load` — instantaneous kW (every 3s)
- `rainforest/hourly`, `rainforest/24h_compare`, `rainforest/daily`, `rainforest/peak` — every 5min
- `pool/sensor` — pool_temp, pool_pump, pool_heater, spa_heater, pool_light (from Home Assistant)
- `pollen/sensor` — tree_index, tree_desc, tree_in_season, grass_index, grass_desc, grass_in_season, weed_index, weed_desc, weed_in_season (from Google Pollen API, hourly)
- `sjwater/daily` — gallons, leak_gallons, unavailable_gallons, date, last_updated (most recent day with data)
- `sjwater/hourly` — gallons, leak_gallons, unavailable_gallons, date, hour, last_updated (latest interval, even when 0 gallons)
- `homeassistant/sensor/sjwater_*_usage/config` and `homeassistant/sensor/sjwater_portal_last_updated/config` — retained MQTT discovery configs published by `get_water.py`
- `weathergov/forecast` — NWS API 7-day forecast (replaces HTML scraping)
- `weathergov/warnings` — NWS active alerts for point 37.3228,-122.0566
- `weathergov/temptrend` — 7-day temp chart data (-3..+3 days): actual (weewx), forecast (NWS), normals (NCEI), records (GHCND KSJC)

## Verification

```bash
# Verify NWS API forecast vs old HTML scraping (prints side-by-side, no MQTT publish)
cd /home/pi/sensors && perl weather.pl --verify-forecast

# Check temptrend topic after deploy
mosquitto_sub -h 10.0.110.85 -t weathergov/temptrend --retained-only -C 1
```

## SJ Water HA Notes

`get_water.py` runs on the kitchen Pi, not Lenovo, and publishes retained MQTT discovery for HA. Expected HA entities are `sensor.sj_water_smart_meter_daily_usage`, `sensor.sj_water_smart_meter_hourly_usage`, and `sensor.sj_water_smart_meter_portal_last_updated`. If daily/hourly stay at `0.0`, first check the portal timestamp sensor or the `last_updated` attribute; on 2026-06-19 the end-to-end path was working but SJWaterHUB was still reporting `2026-06-19T07:00:00-07:00` with zero gallons. Verify with `cd /home/pi/sensors && ./get_water.py --nomqtt --nosave --verbose` on kitchen and retained MQTT topics `sjwater/daily`, `sjwater/hourly`, and `homeassistant/sensor/sjwater_*/config`.

## Key Patterns

- **File locking**: each script uses `/tmp/{name}.exists` to prevent duplicate instances
- **Test flags**: `--nosave` (skip DB) and `--nomqtt` (skip MQTT publishing)
- **MQTT changes**: coordinate with consumers (flp, inky, rainbow) before changing topic structure
- **Deployment**: sensor collectors on `kitchen` are not complete until `ansible/playbooks/sensors-deploy.yml` manages their cron/systemd entry and checks required `sensor.conf` keys

## Known Issues

- Cold start: last-hour delta calculations break on empty DB
- No config validation at startup
- `purpleair/last_hour` kept for backward compat but legacy
