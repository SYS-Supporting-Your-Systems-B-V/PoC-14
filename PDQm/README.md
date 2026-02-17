# PDQm (ITI-78) Minimal Server (Python/FastAPI)

A **working, minimal PDQm-supplier project** in **Python** using **FastAPI + SQLAlchemy + fhir.resources**.

It uses SQLAlchemy to build the WHERE.

It supports:

- **GET /fhir/Patient** — (search)  
- **POST /fhir/Patient/_search** — (form-body search)  
- **GET /fhir/Patient/{id}** — (read)  
- **GET /fhir/metadata** — (CapabilityStatement)

It includes bundles with **total**, **entry[]**, **link[self|next]**, and paging via **_count** and **_page**.

Additional features:

- **AND/OR semantics:** repeated parameters = **AND**, comma-separated values within a single parameter = **OR**  
- **identifier** as token **system|value** (multiple systems separated by commas), and also as plain **value**  
- String modifier **:exact** for **family** / **given**  
- Date prefixes for **birthdate** (**eq** /default, **ge**, **le**, **gt**, **lt**)  
- **Content negotiation:** JSON is supported; XML requests return **406** with **OperationOutcome** (placeholder; PDQm ultimately requires XML support)

# Examples

- **Metadata**  
  `GET http://localhost:8001/fhir/metadata`

- **Patient read**  
  `GET http://localhost:8001/fhir/Patient/p1`

- **Search (family contains 'smi' OR 'smy') + gender AND**  
  `GET http://localhost:8001/fhir/Patient?family=smi,smy&gender=male&_count=2&_page=1`

- **Search (family:exact & given:exact)**  
  `GET http://localhost:8001/fhir/Patient?family:exact=SMITH&given:exact=JOHN`

- **Identifier (system OR) & (value OR) – AND between repeated parameters**  
  `GET http://localhost:8001/fhir/Patient?identifier=urn:oid:1.2.3.4.5,http://hospital.example/national-id|ABC123,999-88-7777`

- **Telecom token**  
  `GET http://localhost:8001/fhir/Patient?telecom=phone|+31-20-123`

- **Birthdate with prefix**  
  `GET http://localhost:8001/fhir/Patient?birthdate=ge1975-01-01&birthdate=le1985-12-31`

- **POST search (form-encoded)**  
  `POST http://localhost:8001/fhir/Patient/_search`  
  Body: `family=SMI&_count=10`  
  → 307 redirect to GET (same parameters)

Testing is easy to do with curl.
 `curl -s -H "Accept: application/fhir+json" "http://localhost:8001/fhir/Patient?active=true&family=smit"`

> **TIP:**  
> This example uses SQLite with seed data so it can run immediately.  
> Replace the DB layer with your SQL Server views/tables (via **pyodbc/SQLAlchemy**) when moving to production.

## Installation
On OpenBSD install packages
```bash
pkg_add rust py3-setuptools freetds gcc gmake py3-cython
```

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

for use with Microsoft SQL Server backend:
```bash
export PDQM_DB_URL="mssql+pytds://PQDm:<password>@<server IP address>:1433/<database name>?autocommit=true&tds_version=7.4&validate_host=false"
```

IDs to test with when running pytest with Microsoft SQL Server backend:
```bash
export MSSQL_TEST_IDS=2167299,2167300,2167301
```

## Run the API

```bash
. .venv/bin/activate  # Windows: .venv\Scripts\activate
uvicorn app:main:app --host 0.0.0.0 --port 8001
```

```text
pdqm-mini/
+- app/
¦  +- __init__.py
¦  +- db.py
¦  +- models.py
¦  +- fhir_utils.py
¦  +- main.py
+- requirements.txt
+- README.md
```

## Environment variables
export PDQM_DB_URL="mssql+pytds://USER:PASSWORD@SQLHOST:1433/YourDatabase?autocommit=true"

### Temporarily skip validation (not recommended; for lab use only):
export PDQM_DB_URL="mssql+pytds://USER:PASSWORD@SQLHOST:1433/YourDatabase?autocommit=true&tds_version=7.4&validate_host=false"

### Common useful params you can set in the URL:
autocommit=true (or manage transactions yourself)
tds_version=7.4
timeout=<seconds>
login_timeout=<seconds>
appname=<string>
cafile=/path/to/ca.pem
validate_host=true|false
