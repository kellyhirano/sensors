# CLAUDE.md - IoT Sensors Repository Guide

This document provides AI assistants with essential information about the codebase structure, development workflows, and key conventions for this IoT sensor data collection project.

## Repository Overview

**Purpose**: Collection of Python scripts to read data from various IoT devices (air quality sensors and energy monitors), store data in SQLite databases, and publish to MQTT servers for consumption by other applications.

**License**: MIT License (Copyright 2020 Kelly Hirano)

**Related Projects**:
- [flp](https://github.com/kellyhirano/flp) - Consumer of sensor data
- [inky](https://github.com/kellyhirano/inky) - Consumer of sensor data

## Codebase Structure

```
sensors/
├── README.md              # User-facing documentation
├── LICENSE                # MIT license
├── get_awair.py          # Awair air quality sensor data collection
├── get_aqi.py            # Purple Air AQI data collection
├── rainforest_loop.py    # Rainforest EAGLE-3 energy monitor (loop)
├── awair.sql             # Database schema for Awair data
├── purple_air.sql        # Database schema for Purple Air data
├── rainforest.sql        # Database schema for Rainforest data
└── sensor.conf           # Configuration file (not in repo, required for use)
```

### Core Scripts

1. **get_awair.py** (Lines: 303)
   - Collects data from Awair air quality sensors via API
   - Measures: temperature, humidity, CO2, VOC, PM2.5 dust
   - Calculates hourly deltas and AQI from dust particles
   - Entry point: `main()` at line 269
   - Key class: `AwairAPI` (lines 23-116)

2. **get_aqi.py** (Lines: 259)
   - Collects AQI data from Purple Air stations
   - Supports multiple station IDs with automatic selection based on freshness
   - Calculates both EPA and LRAPA AQI values
   - Entry point: `main()` at line 185
   - Station selection logic: lines 217-223 (bias to first unless >5min stale)

3. **rainforest_loop.py** (Lines: 399)
   - Continuously monitors Rainforest EAGLE-3 energy gateway
   - Runs in an infinite loop (line 300) with 3-second polling
   - Publishes instantaneous load every 3 seconds
   - Saves to DB once per minute (lines 335-338)
   - Publishes aggregate metrics every 5 minutes (lines 340-343)
   - Entry point: `main()` at line 278
   - Aggregate calculations: hourly avg, 24h comparison, daily total, peak

## Configuration System

All scripts require a `sensor.conf` file using Python's ConfigParser format.

### Required Configuration Entries

```ini
[ALL]
base_dir = <directory containing db file>
db_file = <path to sqlite3 file, can use %(base_dir)s/sensors.db>
mqtt_host = <IP address of MQTT server>

[AWAIR]
auth_token_api = <auth token from Awair Developer account>
location = <optional: locationName to filter devices>

[RAINFOREST]
username = <Eagle Cloud ID>
password = <Eagle Install Code>
hardware_address = <Hardware address from device_list command>
eagle_ip = <local IP address>
```

**Important**: The configuration file is named `sensor.conf` (not `sensors.conf` - typo was fixed in commit d6afbfd).

## Database Schema

### Awair Table (awair.sql)
- Primary key: `(datetime, location)`
- Columns: datetime, location, physical_location, uuid, temp, humid, co2, voc, dust
- Uses `REPLACE` for upserts (get_awair.py:135)

### Purple Air Table (purple_air.sql)
- Primary key: `(datetime, id)`
- Columns: datetime, id, aqi, lrapa_aqi, pm25
- Uses `INSERT` for new records (get_aqi.py:139)

### Rainforest Table (rainforest.sql)
- Primary key: `datetime`
- Columns: datetime (auto CURRENT_TIMESTAMP), load (REAL)
- Uses `REPLACE` for upserts (rainforest_loop.py:38)

## MQTT Publishing

All scripts publish JSON payloads to MQTT topics with `retain=True`.

### MQTT Topic Structure

**Awair**:
- `awair/{physical_location}/{location}/sensor` - Current sensor data with deltas
- Payload includes: datetime, location, temp, co2, humid, voc, dust, aqi, last_hour_* fields

**Purple Air**:
- `purpleair/sensor` - Current AQI data
- `purpleair/last_hour` - Hour-over-hour delta (legacy, kept for backwards compat)

**Rainforest**:
- `rainforest/load` - Instantaneous demand (every 3 seconds)
- `rainforest/hourly` - 60-minute average (every 5 minutes)
- `rainforest/24h_compare` - Comparison with same hour 24h ago (every 5 minutes)
- `rainforest/daily` - Total kWh consumed today (every 5 minutes)
- `rainforest/peak` - Peak instantaneous demand today (every 5 minutes)

## Key Dependencies

**External Libraries** (not explicitly versioned):
- `paho-mqtt` - MQTT client for publishing
- `aqi` - Air Quality Index calculations (EPA and LRAPA algorithms)

**Standard Library**:
- `configparser` - Configuration file parsing
- `sqlite3` - Database operations
- `http.client` - HTTP/HTTPS API calls
- `fcntl` - File locking for single-instance enforcement
- `json` - JSON serialization
- `argparse` - Command-line argument parsing
- `xml.etree.ElementTree` - XML parsing (rainforest only)
- `base64` - Basic auth encoding (rainforest only)
- `logging` - Logging (rainforest only)

## Development Conventions

### File Locking Pattern
All scripts use fcntl file locking to prevent multiple instances:
```python
lock_file = '/tmp/{script_name}.exists'
fp = open(lock_file, 'w')
try:
    fcntl.lockf(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
except IOError:
    print('Only one instance may run. Delete lockfile ' + lock_file)
    sys.exit(0)
```

**Lock files**:
- `/tmp/awair.exists`
- `/tmp/aqi.exists`
- `/tmp/rainforest.exists`

### Script Execution Pattern

**One-shot scripts** (get_awair.py, get_aqi.py):
- Designed to be run via cron or scheduler
- Execute once and exit
- Support `--nosave` and `--nomqtt` flags for testing

**Continuous script** (rainforest_loop.py):
- Runs in infinite loop with sleep intervals
- Publishes instantaneous data frequently
- Rate-limits database writes (once per minute)
- Rate-limits aggregate metrics (every 5 minutes)

### Testing Flags

All scripts support:
- `--nosave` - Skip database writes (useful for testing)
- `--nomqtt` - Skip MQTT publishing (useful for testing)
- `--verbose` - Extra output (get_aqi.py only)

### Error Handling Patterns

1. **API Errors**: Try/except with IOError, print warning, continue or exit
2. **Empty API Responses**: Check for empty data and skip device (get_awair.py:96)
3. **Missing Historical Data**: Check for None and skip calculations (get_awair.py:177)
4. **XML Parsing Errors**: Catch ET.ParseError (rainforest_loop.py:270)
5. **MQTT Errors**: Log warning and continue (rainforest_loop.py:52-54)

### Code Style Notes

- **Shebang**: All scripts use `#!/usr/bin/python3` (rainforest uses `#!/usr/bin/env python3`)
- **Indentation**: Mix of 2-space and 4-space (rainforest uses 2-space, others use 4-space)
- **String formatting**: Mix of `.format()` and f-strings
- **Comments**: Typo "proess" appears in all files (line 13-14)
- **Docstrings**: Triple-quoted strings for function documentation
- **Main pattern**: All use `if __name__ == '__main__': main()`

### Database Connection Pattern

```python
con = sqlite3.connect(db_file)
cur = con.cursor()
# ... execute statements ...
con.commit()
con.close()
```

**For row dictionary access**:
```python
con.row_factory = sqlite3.Row  # Must set before cursor
cur = con.cursor()
# Rows are now accessible as dictionaries
```

**Timeout handling** (rainforest only):
```python
connection = sqlite3.connect(db_file, timeout=30)
```

## Known Issues & Fragility

As documented in README.md (lines 21-22):

1. **Cold start problems**: Last hour delta calculations may break when database is empty
2. **No configuration validation**: Scripts don't check for required config values before using them
3. **No testing**: No automated tests exist
4. **Offline device handling**: Empty responses from offline devices are skipped (added in commit eb6dd96)
5. **LRAPA conversion**: Can go negative; fixed with check in commit 6f54859 (lines 91-92 in get_aqi.py)

## API Details

### Awair API
- **Host**: `developer-apis.awair.is`
- **Auth**: Bearer token in Authorization header
- **Endpoints**:
  - `/v1/users/self/devices` - Get list of devices
  - `/v1/users/self/devices/{type}/{id}/air-data/latest?fahrenheit=true` - Get latest air data
- **Response**: JSON with nested sensor data
- **Timestamp**: UTC (note in code at line 160)

### Purple Air API
- **Host**: `www.purpleair.com`
- **Endpoint**: `/json?show={station_id}`
- **Auth**: None (public API)
- **Response**: JSON with results array
- **Station Selection**: Prefers first station unless >5 minutes stale, then selects freshest

### Rainforest EAGLE-3 API
- **Connection**: HTTP POST to local device at `{eagle_ip}/cgi-bin/post_manager`
- **Auth**: Basic auth (Cloud ID:Install Code)
- **Request**: XML command `device_query` for `zigbee:InstantaneousDemand`
- **Response**: XML with device details and load value in kW
- **Timeout**: 10 seconds

## Development Workflow

### Making Changes

1. **Adding new sensor support**:
   - Create new Python script following existing patterns (file lock, config, DB, MQTT)
   - Create corresponding SQL schema file
   - Update README.md with configuration requirements
   - Add entry to `sensor.conf` template

2. **Modifying database schema**:
   - Update `.sql` file with new schema
   - Users must recreate table or migrate manually (no migration system)
   - Update corresponding script's DB insert/select statements

3. **Changing MQTT topics**:
   - Be aware of backwards compatibility (see commit e62d753)
   - Consumer applications may depend on existing topic structure
   - Consider keeping old topics for transition period

### Git Conventions

Based on recent commit history:
- **Commit message style**: Descriptive, lowercase, no period
  - "Add {feature}" for new features
  - "Fix {issue}" for bug fixes
  - "Added {feature}" also used (not consistent)
- **Branch**: Currently on `claude/add-claude-documentation-gpFGP`
- **No PR process visible**: Direct commits to main branch historically

## AQI Calculation Details

### EPA AQI Algorithm
Used for standard AQI calculations from PM2.5 values.
- Library: `aqi.to_iaqi(aqi.POLLUTANT_PM25, pm25_value, algo=aqi.ALGO_EPA)`
- Returns: Integer AQI value

### LRAPA Conversion (Purple Air)
Lane Regional Air Protection Agency correction formula:
```python
lrapa_average = 0.5 * raw_average - 0.66
if lrapa_average < 0:
    lrapa_average = 0
```
- Purpose: Corrects for Purple Air sensor bias
- Used in: get_aqi.py (lines 90-92)
- Fixed in commit 6f54859 to prevent negative values

### Awair AQI
Calculated from 1-hour average of PM2.5 dust readings:
```python
# Get average dust over last hour where dust != ''
avg_dust = SELECT avg(dust) FROM awair WHERE ... last hour ... GROUP BY uuid
aqi = aqi.to_iaqi(aqi.POLLUTANT_PM25, avg_dust, algo=aqi.ALGO_EPA)
```

## When Modifying This Codebase

### Do:
- ✅ Read existing code patterns before implementing new features
- ✅ Maintain backwards compatibility with MQTT topics
- ✅ Use file locking for any new scripts
- ✅ Support `--nosave` and `--nomqtt` flags for testing
- ✅ Handle empty/missing API responses gracefully
- ✅ Use `REPLACE` for idempotent DB operations where appropriate
- ✅ Set `retain=True` on MQTT publishes for sensor data
- ✅ Store timestamps in UTC for external APIs, localtime for local operations
- ✅ Include location/uuid identifiers for multi-device scenarios

### Don't:
- ❌ Remove existing MQTT topics without transition plan
- ❌ Change database primary keys (breaks existing data)
- ❌ Assume configuration values exist (though current code does this)
- ❌ Run multiple instances of same script (file lock prevents this)
- ❌ Forget to commit database transactions
- ❌ Use blocking operations in rainforest loop without considering 3-second cycle
- ❌ Change timestamp formats without considering time-based queries
- ❌ Forget that Awair uses UTC timestamps, Purple Air/Rainforest use localtime

### Questions to Ask:
- Does this change affect downstream consumers (flp, inky projects)?
- Will existing cron jobs continue to work?
- Is the database schema change backwards compatible?
- Does this change the MQTT payload structure?
- Have I tested with `--nosave` and `--nomqtt` flags?

## Future Improvement Suggestions

1. **Add requirements.txt**: Pin dependency versions for reproducibility
2. **Add configuration validation**: Check required config values at startup
3. **Add unit tests**: Test API parsing, DB operations, AQI calculations
4. **Standardize indentation**: Choose 2 or 4 spaces consistently
5. **Add migration system**: For database schema changes
6. **Add sensor.conf.example**: Template configuration file
7. **Improve error handling**: More specific exceptions, retry logic
8. **Add logging**: Extend rainforest logging pattern to other scripts
9. **Fix typo**: "proess" -> "process" in all three files
10. **Add health checks**: Detect stale data, API failures
11. **Document external dependencies**: Add requirements.txt with versions
12. **Add CI/CD**: Automated testing, linting

## Related Files & Resources

- **API Documentation**:
  - [Awair Developer API](https://docs.developer.getawair.com/)
  - [Purple Air Map](https://www.purpleair.com/map) - Find station IDs
  - [Rainforest EAGLE-200 API Manual](https://rainforestautomation.com/wp-content/uploads/2017/02/EAGLE-200-Local-API-Manual-v1.0.pdf)

- **External Libraries**:
  - [paho-mqtt](https://pypi.org/project/paho-mqtt/) - MQTT client
  - [python-aqi](https://pypi.org/project/python-aqi/) - AQI calculations

## Summary for AI Assistants

When working with this codebase:

1. **Understand the pattern**: Each sensor has a Python script, SQL schema, and configuration section
2. **Respect the ecosystem**: Changes may affect downstream consumers
3. **Test carefully**: Use flags to test without side effects (--nosave, --nomqtt)
4. **Be backwards compatible**: MQTT topics and DB schemas are API contracts
5. **Follow conventions**: File locking, config parsing, DB patterns are consistent
6. **Know the fragility**: No input validation, limited error handling, no tests
7. **Consider the use case**: These run unattended on IoT devices, reliability matters

This is a working, production codebase used for personal home automation. Prioritize stability and backwards compatibility over ideal code structure.
