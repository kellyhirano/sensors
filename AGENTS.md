# Repository Guidelines

## Project Structure & Module Organization
This repo contains Python 3 collectors that read IoT device data, persist to SQLite, and publish to MQTT.

- `get_awair.py`, `get_aqi.py`: one-shot collectors for Awair and PurpleAir.
- `rainforest_loop.py`: continuous collector for the Rainforest EAGLE-3.
- `awair.sql`, `purple_air.sql`, `rainforest.sql`: SQLite schemas.
- `sensor.conf`: runtime config (not tracked).

## Build, Test, and Development Commands
- Run collectors directly: `python3 get_awair.py` or `python3 get_aqi.py <station_id>`.
- Run continuous loop: `python3 rainforest_loop.py`.
- Use `--nosave` and/or `--nomqtt` to test without side effects (supported by sensor scripts).

## Coding Style & Naming Conventions
- Python 3, 4-space indentation, snake_case for functions and modules.
- MQTT payloads are JSON; keep topic names stable and documented.
- Each script uses file locks in `/tmp/*.exists` to prevent multi-instance runs.

## MQTT Topics
| Topic | Purpose |
| --- | --- |
| `awair/<location>/<room>/sensor` | Awair readings and hourly deltas. |
| `purpleair/sensor` | Current AQI values. |
| `purpleair/last_hour` | AQI delta (legacy). |
| `rainforest/load` | Instantaneous kW demand. |
| `rainforest/hourly` | 60-minute average kW. |
| `rainforest/24h_compare` | Current vs 24h-ago. |
| `rainforest/daily` | Daily kWh total. |
| `rainforest/peak` | Peak kW today. |

## Testing Guidelines
- No automated tests; validate with real devices and MQTT broker.
- Confirm SQLite tables exist by applying `*.sql` schemas before running collectors.

## Commit & Pull Request Guidelines
- Use short, imperative commit messages (“Fix config typo”, “Add Rainforest loop”).
- PRs should note new MQTT topics or schema changes and include sample payloads.

## Configuration & Ops Notes
- `sensor.conf` is required and uses INI format with `[ALL]`, `[AWAIR]`, and `[RAINFOREST]` sections.
- When adding a new sensor, add a schema file and document it in `README.md`.
