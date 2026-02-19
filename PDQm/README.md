# PDQm Minimal Server (FastAPI)

Deze applicatie is een kleine **Python/FastAPI** server die een **minimal subset van HL7 FHIR PDQm** aanbiedt voor het resource type **Patient**.

De server stelt  FHIR-endpoints beschikbaar onder `/fhir` en voert **FHIR-zoekopdrachten** uit op een database via **SQLAlchemy**.  
Standaard draait hij op **SQLite** (incl. demo/seed-data), maar hij kunt ook gekoppeld worden aan een **SQL Server** view/tabel met hetzelfde schema.

De FHIR resources worden opgebouwd conform **FHIR R4B** (versie 4.3.0) via de `fhir.resources.R4B`-bibliotheek.

---

## Bekende beperkingen en afwijkingen van de FHIR-standaard

- **XML niet geïmplementeerd.** De server retourneert HTTP 406 als de client XML vraagt.
- **`PDQmWhereBuilder`** in `pdqm_where.py` is nog niet geïntegreerd in de API. Alleen `_parse_fhir_date_bounds` wordt vanuit die module gebruikt voor het parsen van partiële FHIR-datums. De `PDQmWhereBuilder` is een T-SQL WHERE-builder voor toekomstig gebruik.
- **Slechts één `name`, `address`, en `identifier` per patiënt.** Het schema ondersteunt één naam (`name_given_0`, `name_prefix_0`), één adres, en één identifier.
- **Alleen Patient** is geïmplementeerd (read + search-type).

---

## Operator / deploy

### Installatie (lokaal)

#### Installeer bij gebruik onder OpenBSD de onderstaande packages (onder Linux is dit niet nodig)
```bash
pkg_add rust py3-setuptools freetds gcc gmake py3-cython
```

Maak een virtualenv en installeer dependencies:

```bash
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
```

Installeer daarna dependencies via `requirements.txt` :

```bash
pip install -r requirements.txt
```

### Configuratie

De app leest de configuratie uit environment variabelen (en optioneel uit `.env` via `pydantic-settings`).

#### Database (SQLite of SQL Server)

Extra frontend-configuratie:
- `PDQM_LDAP_BASE` - base URL die `ldap_zoek.html` gebruikt voor LDAP-calls (default: `http://localhost:8002`)
- `PDQM_MCSD_BASE` - base URL die `mcsd_zoek.html` gebruikt voor mCSD-calls (default: `http://localhost:8000`)

**Environment variable:**
- `PDQM_DB_URL` – SQLAlchemy database URL

**Default (als `PDQM_DB_URL` niet gezet is):**
- `sqlite:///./pdqm.db`

Voorbeelden:

```bash
# SQLite (default)
export PDQM_DB_URL="sqlite:///./pdqm.db"

# SQL Server (voorbeeld; vul zelf host/user/db in)
export PDQM_DB_URL="mssql+pytds://USER:PASSWORD@SQLHOST:1433/DATABASE?autocommit=true"

# LDAP proxy voor ldap_zoek.html
export PDQM_LDAP_BASE="http://localhost:8002"

# mCSD proxy voor mcsd_zoek.html
export PDQM_MCSD_BASE="http://localhost:8000"
```

##### Nuttige parameters voor gebruik in PDQM_DB_URL

```
autocommit=true (or manage transactions yourself)
tds_version=7.4
timeout=<seconds>
login_timeout=<seconds>
appname=<string>
cafile=/path/to/ca.pem
validate_host=true|false
```

**Belangrijk bij SQL Server:**
- De ORM mapping verwacht een view/tabel `dbo.viewPatientPDQm` met de kolommen zoals beschreven in "Database schema".  
- Bij SQLite maakt de app (op startup) automatisch de tabel `viewPatientPDQm` aan en seed demo-data als de tabel leeg is.

##### Voorbeeld van specificeren ID's voor pytest om mee te testen als de test wordt uitgevoerd met een Microsoft SQL Server backend
```bash
export MSSQL_TEST_IDS=2167299,2167300,2167301
```

### Run

Start de server met uvicorn.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Voeg `--reload` toe tijdens ontwikkeling om de server automatisch te herstarten bij codewijzigingen:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

FastAPI documentatie:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI spec: `http://localhost:8000/openapi.json`

---

## Gebruik van de API

### Zoeksemantiek in het kort

- **AND:** herhaalde parameters (bijv. `family=SMI&family=SMY`)
- **OR (string/token):** komma-lijsten binnen één parameter (bijv. `family=SMI,SMY`)
- `family:exact` / `given:exact` voor exacte (case-insensitive) match; zonder modifier is **contains** (case-insensitive, afwijkend van de FHIR-standaard die `starts-with` voorschrijft).
- `birthdate` ondersteunt prefixes `eq` (default), `ge`, `le`, `gt`, `lt` en partiële datums (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`).
  - Voor een range: herhaal `birthdate`, bv. `birthdate=ge1975-01-01&birthdate=le1985-12-31`
- `identifier`:
  - `identifier=<value>` matcht bare value én `system|value` met dezelfde value
  - `identifier=<system>|<value>` matcht exact `system|value`
  - `identifier=<system>|` (zonder value) matcht alle identifiers die beginnen met `system|`
  - Shorthand: `identifier=<system1>,<system2>|<value1>,<value2>` (alle combinaties)

### Content negotiation

De server ondersteunt **FHIR JSON** responses.  
Als de client XML vraagt (via `_format=...xml...` of `Accept: application/fhir+xml` / `application/xml`), retourneert de server **HTTP 406** met een FHIR `OperationOutcome`.

Aanbevolen header:

```text
Accept: application/fhir+json
```

### Endpoints

#### `GET /fhir/metadata`

Retourneert een minimale `CapabilityStatement` met o.a. de ondersteunde search parameters.

Voorbeeld:

```bash
curl -H "Accept: application/fhir+json" http://localhost:8000/fhir/metadata
```

#### `GET /fhir/Patient`

FHIR search endpoint voor Patient.  
Retourneert een `Bundle` van type `searchset` met:

- `total` (COUNT(*) over dezelfde filters)
- `link[self]` en (indien van toepassing) `link[next]`
- `entry[].resource` als FHIR `Patient`

**Paginering**
- `_count` (default `20`, min `1`, max `100`)
- `_page` (default `1`)

**Zoeksemantiek**
- Herhaalde parameters = **AND** (FHIR search rules)
- Komma's binnen één parameter = **OR**
  - Voorbeeld: `family=SMI,SMY` betekent "SMI **of** SMY"
  - Voorbeeld: `family=SMI&family=SMY` betekent "SMI **en** SMY" (strenger)

**Ondersteunde search parameters**
- `_id` – match op `Patient.id`; kommalijst = OR (bijv. `_id=1,2,3`)
- `family` / `family:exact`
- `given` / `given:exact`
- `gender`
- `birthdate` – ondersteunt `eq` (default), `ge`, `le`, `gt`, `lt` + partiële datums (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`)
- `identifier` – token, gemapt op één kolom die óf `value` óf `system|value` kan bevatten
- `telecom` – token (bijv. `phone|...`, `email|...` of zonder system)
- `address` / `address:exact` – zoekt breed over `line/city/postalCode/country` (OR over alle vier velden)
- `address-city` / `address-city:exact`
- `address-postalcode` / `address-postalcode:exact`
- `address-country` / `address-country:exact`

**Voorbeelden**

Alle voorbeelden gaan uit van: `http://localhost:8000` en header `Accept: application/fhir+json`.

**1) Metadata (CapabilityStatement)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/metadata"
```

**2) Patient read (op id)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient/1"
```

**3) Zoeken op achternaam (contains)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family=smi"
```

**4) Zoeken op achternaam (exact)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family:exact=SMITH"
```

**5) AND vs OR (family)**

```bash
# OR binnen één parameter
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family=SMI,SMY"

# AND door herhaling (meestal strenger)
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family=SMI&family=SMY"
```

**6) Zoeken op identifier**

```bash
# "bare" value (matcht ook system|value records met dezelfde value)
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?identifier=428889876"

# system|value (exact match op "system|value" in de identifier-kolom)
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?identifier=http://example.org/ns|12345"
```

**7) Identifier met OR-waarden (handig met -G + --data-urlencode i.v.m. | en http://)**

```bash
curl -G -H "Accept: application/fhir+json" \
  --data-urlencode "identifier=urn:oid:1.2.3.4.5,http://hospital.example/national-id|ABC123,999-88-7777" \
  "http://localhost:8000/fhir/Patient"
```

**8) Telecom token**

```bash
curl -G -H "Accept: application/fhir+json" \
  --data-urlencode "telecom=phone|+31-20-123" \
  "http://localhost:8000/fhir/Patient"
```

**9) Zoeken op geboortedatum (partiële datums + prefixen)**

```bash
# exact date
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?birthdate=1980-05-12"

# "ge" = greater-or-equal: alles vanaf 1980 (vanaf 1980-01-01)
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?birthdate=ge1980"

# "eq" (default) op maand: alle geboortes in mei 1980
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?birthdate=1980-05"
```

**10) Birthdate range met prefixen (ge/le) via herhaalde parameter**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?birthdate=ge1975-01-01&birthdate=le1985-12-31"
```

**11) Paginering**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family=smi&_count=10&_page=2"
```

**12) Search (meerdere filters + paging)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family=smi,smy&gender=male&_count=2&_page=1"
```

**13) Search (family:exact & given:exact)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?family:exact=SMITH&given:exact=JOHN"
```

**14) POST search (form-encoded) retourneert direct een Bundle (zelfde logica als GET)**

```bash
curl -i -X POST "http://localhost:8000/fhir/Patient/_search" \
  -H "Accept: application/fhir+json" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "family=SMI" \
  --data-urlencode "_count=10" \
  --data-urlencode "_page=1"
```

**15) Zoeken op meerdere ID's (OR)**

```bash
curl -H "Accept: application/fhir+json" "http://localhost:8000/fhir/Patient?_id=1,2,3"
```

---

## Database schema

De server verwacht één view/tabel `viewPatientPDQm` (SQL Server: `dbo.viewPatientPDQm`) met minimaal de volgende kolommen:

- `id` (PK, string) – FHIR logical id
- `identifier` (string, nullable) – óf `value` óf `system|value`
- `name_use` (string, nullable)
- `name_family` (string, nullable)
- `name_given_0` (string, nullable)
- `name_prefix_0` (string, nullable)
- `name_text` (string, nullable)
- `mothersMaidenName` (string, nullable)
- `address_use` (string, nullable)
- `address_line_0` (string, nullable)
- `address_city` (string, nullable)
- `address_postalCode` (string, nullable)
- `address_country` (string, nullable)
- `tel_home` (string, nullable)
- `tel_work` (string, nullable)
- `tel_mobile` (string, nullable)
- `email` (string, nullable)
- `birthdate` (date, nullable)
- `deathdate` (date, nullable)
- `gender` (string, nullable; verwacht: `male|female|other|unknown`)
- `marital_code` (string, nullable)

**FHIR mapping (globaal)**
- `identifier` → `Patient.identifier[]`
- naamvelden → `Patient.name[]` (`use=official`, `family`, `given[0]`, `text`)
  - `name_use` is aanwezig in het schema maar de output gebruikt altijd `"official"`
- `birthdate` → `Patient.birthDate`
- `gender` → `Patient.gender`
- addressvelden → `Patient.address[]`
- telecomvelden → `Patient.telecom[]`
- `marital_code` → `Patient.maritalStatus` (HL7 v3 MaritalStatus, incl. `display`-label voor de bekende codes A/D/I/L/M/P/S/T/U/W)
- `mothersMaidenName` → extension `patient-mothersMaidenName`

---

## Bestanden en directories
```text
pdqm-mini/
+- app/
¦  +- __init__.py
¦  +- db.py
¦  +- fhir_utils.py
¦  +- main.py
¦  +- models.py
¦  +- pdqm_where.py
+- requirements.txt
+- README.md
```

---

## Foutafhandeling / statuscodes

- **406** – XML gevraagd (`_format=xml` of `Accept: application/fhir+xml`): `OperationOutcome` met melding dat XML nog niet wordt ondersteund.
- **400** – ongeldige `birthdate` waarde: `OperationOutcome` met `code=invalid`.
- **404** – `GET /fhir/Patient/{id}` en patiënt bestaat niet: `OperationOutcome` met `code=not-found`.
- **500** – database niet bereikbaar (`OperationalError` of `OSError`): `OperationOutcome` met neutrale databasefoutmelding.

