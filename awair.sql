CREATE TABLE awair(
  datetime	TEXT	NOT NULL,
  location	TEXT	NOT NULL,
  temp	REAL,
  humid	INTEGER,
  co2	INTEGER,
  voc	INTEGER,
  dust  REAL,
  PRIMARY KEY (datetime, location)
);
