CREATE TABLE awair(
  datetime	TEXT	NOT NULL,
  location	TEXT	NOT NULL,
  physical_location	TEXT	NOT NULL,
  uuid	TEXT	NOT NULL,
  temp	REAL,
  humid	INTEGER,
  co2	INTEGER,
  voc	INTEGER,
  dust  REAL,
  PRIMARY KEY (datetime, location)
);

CREATE INDEX IF NOT EXISTS awair_uuid_datetime_idx
  ON awair(uuid, datetime DESC);

CREATE INDEX IF NOT EXISTS awair_datetime_uuid_idx
  ON awair(datetime, uuid);
