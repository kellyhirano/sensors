CREATE TABLE purple_air(
  datetime	TEXT	NOT NULL,
  id	TEXT	NOT NULL,
  aqi	INTEGER	NOT NULL,
  lrapa_aqi INTEGER NOT NULL,
  pm25 REAL NOT NULL,
  PRIMARY KEY (datetime, id)
);
