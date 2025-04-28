DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS billing;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL
);

CREATE TABLE billing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    company TEXT NOT NULL,
    year TEXT NOT NULL,
    month TEXT NOT NULL,
    service_name TEXT NOT NULL,
    usd REAL NOT NULL,
    bdt REAL NOT NULL,
    rate REAL NOT NULL,
    service_charge REAL NOT NULL,
    vat REAL NOT NULL,
    total REAL NOT NULL
);
