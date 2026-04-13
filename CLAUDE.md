# CLAUDE.md

## Overview

Python scripts that poll IoT sensors and publish JSON to MQTT (with `retain=True`). Data stored in SQLite for delta calculations.

## Scripts

| Script | Type | Schedule |
|--------|------|----------|
| `get_awair.py` | One-shot | cron */10m |
| `get_aqi.py` | One-shot | cron */10m |
| `get_pool.py` | One-shot | cron */5m |
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

[RAINFOREST]
username = <Eagle Cloud ID>
password = <Eagle Install Code>
hardware_address = <from device_list>
eagle_ip = <local IP>
```

## MQTT Topics Published

- `awair/{physical_location}/{location}/sensor` — temp, co2, humid, voc, dust, aqi, deltas
- `purpleair/sensor` — EPA + LRAPA AQI
- `purpleair/last_hour` — hour delta (legacy, kept for compat)
- `rainforest/load` — instantaneous kW (every 3s)
- `rainforest/hourly`, `rainforest/24h_compare`, `rainforest/daily`, `rainforest/peak` — every 5min
- `pool/sensor` — pool_temp, pool_pump, pool_heater, spa_heater, pool_light (from Home Assistant)
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

## Key Patterns

- **File locking**: each script uses `/tmp/{name}.exists` to prevent duplicate instances
- **Test flags**: `--nosave` (skip DB) and `--nomqtt` (skip MQTT publishing)
- **MQTT changes**: coordinate with consumers (flp, inky, rainbow) before changing topic structure

## Known Issues

- Cold start: last-hour delta calculations break on empty DB
- No config validation at startup
- `purpleair/last_hour` kept for backward compat but legacy
