# PoC 14

This repository runs a local proof-of-concept stack with mCSD, PDQm, and LDAP services for directory and addressing workflows.
It is part of the 'Generieke Functies, lokalisatie en addressering' project of the Ministry of Health, Welfare and Sport of the Dutch government.

This stack includes three app services plus a seeded LDAP directory:

- `mcsd` (port `8000`) - mCSD addressbook proxy
- `pdqm` (port `8001`) - PDQm FHIR API + hosted HTML test pages
- `ldap` (port `8002`) - HPD LDAP proxy
- `ldap-directory` (port `1389`) - local OpenLDAP with demo seed data

## Start

Prerequisite: Docker Desktop (or Docker Engine + Compose plugin).

```bash
docker compose up -d --build
```

## Quick checks

### 1) Health and metadata

```bash
curl http://localhost:8000/health
curl http://localhost:8001/fhir/metadata
curl http://localhost:8002/health
```

Expected: HTTP `200` responses.

### 2) LDAP search (seeded local data, deterministic)

```bash
# Person search
curl "http://localhost:8002/hpd/search?q=Jansen&scope=person&limit=10"
curl "http://localhost:8002/hpd/search?q=Mieke&scope=person&limit=10"

# Organization search
curl "http://localhost:8002/hpd/search?q=Ziekenhuis&scope=org&limit=10"
curl "http://localhost:8002/hpd/search?q=Zorgloket&scope=org&limit=10"
```

### 3) mCSD organization search

```bash
curl "http://localhost:8000/addressbook/organization?name:contains=Boston&limit=10"
```

Expected: at least one result (for example `Boston General Hospital`).

### 4) mCSD location search

```bash
curl "http://localhost:8000/addressbook/location?name:contains=Boston&limit=10"
```

Expected: at least one result (for example `Boston Family Health Clinic`).

## Browser routes

- `http://localhost:8001/ldap_zoek/`
- `http://localhost:8001/mcsd_zoek/`
- `http://localhost:8001/docs`

## Stop

```bash
docker compose down
```

## Notes

- Service defaults come from:
  - `LDAP/.env.Docker`
  - `mCSD/.env.Docker`
  - `PDQm/.env.Docker`
- mCSD currently points to `https://hapi.fhir.org/baseR4`, so mCSD search content can change over time.
