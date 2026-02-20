# mCSD ITI-90 Address Book Proxy (FastAPI)

Deze app is een kleine **FastAPI**-proxy die eenvoudige queries vertaalt naar **FHIR (mCSD / ITI-90)**-searches op een upstream mCSD/FHIR-server en (waar nodig) resultaten “flattened” teruggeeft voor gebruik in een frontend.

De proxy bedient twee PoC's die onafhankelijk van elkaar ingezet kunnen worden:

- **PoC 14** — mCSD-adresboek: zoeken van organisaties, locaties, zorgverleners en e-mailadressen.
- **PoC 9** — MSZ / BgZ notified pull: organisatieonderdelen, technische endpoints, capability mapping en het versturen van BgZ-notificaties.

---

## PoC-overzicht: endpoints en configuratie

### Endpoints per PoC

| Endpoint | PoC 14 | PoC 9 | Opmerkingen |
|---|:---:|:---:|---|
| `GET /health` | ✓ | ✓ | Altijd beschikbaar |
| `GET /mcsd/search/{resource}` | ✓ | — | Pass-through FHIR search (Practitioner, PractitionerRole, HealthcareService, Location, Organization, OrganizationAffiliation) |
| `GET /addressbook/organization` | ✓ | — | Ook gebruikt door `mcsd_zoek.html` |
| `GET /addressbook/location` | ✓ | — | Ook gebruikt door `mcsd_zoek.html` |
| `GET /addressbook/search` | ✓ | — | Flattened practitioner + role search |
| `GET /addressbook/find-practitionerrole` | — | ✓ | Practitioner → PractitionerRole lookup |
| `GET /poc9/msz/organizations` | — | ✓ | MSZ-zorgorganisaties |
| `GET /poc9/msz/orgunits` | — | ✓ | Organisatieonderdelen |
| `GET /poc9/msz/endpoints` | — | ✓ | Technische endpoints |
| `GET /poc9/msz/capability-mapping` | — | ✓ | PoC 9 decision tree A–D |
| `POST /bgz/load-data` | — | ✓ | BgZ sample data laden (demo) |
| `POST /bgz/preflight` | — | ✓ | Preflight check vóór notificatie |
| `POST /bgz/task-preview` | — | ✓ | Task preview (UI/test) |
| `POST /bgz/notify` | — | ✓ | BgZ notificatie versturen |

### Configuratie per PoC

| Environment variabele | PoC 14 | PoC 9 | Toelichting |
|---|:---:|:---:|---|
| `MCSD_BASE` | **vereist** | **vereist** | Upstream mCSD/FHIR base URL |
| `MCSD_API_KEY` | optioneel | optioneel | API key beveiliging |
| `MCSD_ALLOW_ORIGINS` | aanbevolen | aanbevolen | CORS origins |
| `MCSD_ALLOWED_HOSTS` | aanbevolen | aanbevolen | Allowed hosts |
| `MCSD_IS_PRODUCTION` | optioneel | optioneel | Productie guardrails |
| `MCSD_LOG_LEVEL` | optioneel | optioneel | Loglevel |
| `MCSD_UPSTREAM_TIMEOUT` | optioneel | optioneel | Timeout upstream calls |
| `MCSD_HTTPX_MAX_CONNECTIONS` | optioneel | optioneel | HTTP client pool |
| `MCSD_HTTPX_MAX_KEEPALIVE_CONNECTIONS` | optioneel | optioneel | HTTP client pool |
| `MCSD_BEARER_TOKEN` | optioneel | optioneel | Upstream authenticatie |
| `MCSD_VERIFY_TLS` | optioneel | optioneel | TLS verificatie |
| `MCSD_CA_CERTS_FILE` | optioneel | optioneel | Custom CA bundle |
| `MCSD_MAX_QUERY_PARAMS` | optioneel | — | Limieten voor `/mcsd/search/{resource}` |
| `MCSD_MAX_QUERY_VALUE_LENGTH` | optioneel | — | Limieten voor `/mcsd/search/{resource}` |
| `MCSD_MAX_QUERY_PARAM_VALUES` | optioneel | — | Limieten voor `/mcsd/search/{resource}` |
| `MCSD_NOTIFIEDPULL_ENABLED` | — | optioneel | BgZ endpoints aan/uit (default: aan) |
| `MCSD_SENDER_URA` | — | **vereist** | BgZ sender-identiteit |
| `MCSD_SENDER_NAME` | — | **vereist** | BgZ sender-identiteit |
| `MCSD_SENDER_UZI_SYS` | — | **vereist** | BgZ sender-identiteit |
| `MCSD_SENDER_SYSTEM_NAME` | — | **vereist** | BgZ sender-identiteit |
| `MCSD_SENDER_BGZ_BASE` | — | **vereist voor verzenden** | BgZ sender FHIR base |
| `MCSD_AUDIT_HMAC_KEY` | — | optioneel | BSN pseudonimisatie in audit logs |
| `MCSD_ALLOW_TASK_PREVIEW_IN_PRODUCTION` | — | optioneel | Task preview in productie |
| `MCSD_CAPABILITY_CACHE_TTL_SECONDS` | — | optioneel | Cache TTL capability checks |
| `MCSD_DEBUG_DUMP_JSON` | — | optioneel | Debug JSON dumps |
| `MCSD_DEBUG_DUMP_DIR` | — | optioneel | Debug dump directory |
| `MCSD_DEBUG_DUMP_REDACT` | — | optioneel | Redactie in debug dumps |

### Snel starten per PoC

**Alleen PoC 14** — minimale configuratie:

```bash
export MCSD_BASE=https://hapi.fhir.org/baseR4
# optioneel: MCSD_NOTIFIEDPULL_ENABLED=false  (schakelt de BgZ/PoC 9 endpoints uit)
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Alleen PoC 9** — minimale configuratie:

```bash
export MCSD_BASE=https://hapi.fhir.org/baseR4
export MCSD_SENDER_URA=urn:oid:2.16.528.1.1007.3.3.1234567
export MCSD_SENDER_NAME="Mijn ZBC"
export MCSD_SENDER_UZI_SYS=urn:oid:2.16.528.1.1007.3.2.1234567
export MCSD_SENDER_SYSTEM_NAME="Mijn ZBC (BgZ)"
export MCSD_SENDER_BGZ_BASE=https://mijn-sender-fhir.example.org/fhir
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Beide PoC's** — combineer de bovenstaande variabelen.

---

## Operator / deploy

### Installatie (lokaal)

```bash
python -m venv .venv
. .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuratie

De app leest configuratie uit environment variabelen (en optioneel uit `.env` via `pydantic-settings`).
De tests stellen `MCSD_BASE=https://hapi.fhir.org/baseR4` automatisch in.

#### Upstream mCSD/FHIR base

`MCSD_BASE` is een **volledige base URL**.

Dat betekent het niet alleen de upstream server bepaalt, maar ook:

- het **protocol** (`http` of `https`)
- de **port** (optional)

Voorbeelden:

```bash
export MCSD_BASE=https://hapi.fhir.org/baseR4

export MCSD_BASE=https://mtls.fort365.net/address-book/admin-directory

# lokaal HTTP op port 8080
export MCSD_BASE=http://localhost:8080/mcsd

# HTTPS op port 8443
export MCSD_BASE=https://myserver:8443/mcsd

# HTTPS met default port 443
export MCSD_BASE=https://myserver/mcsd
```

Er zijn **geen** aparte variabelen voor protocol/poort; dit volgt volledig uit `MCSD_BASE`.

#### Timeouts en HTTP client

```bash
export MCSD_UPSTREAM_TIMEOUT=15
export MCSD_HTTPX_MAX_CONNECTIONS=50
export MCSD_HTTPX_MAX_KEEPALIVE_CONNECTIONS=20
```

#### Upstream authenticatie

Als je upstream een Bearer token verwacht:

```bash
export MCSD_BEARER_TOKEN="…"
```

De proxy voegt dan `Authorization: Bearer …` toe aan upstream requests.

#### TLS / certificaatverificatie

Bij gebruik van `https://`, kan je TLS verificatie instellen met:

```bash
export MCSD_VERIFY_TLS=true        # of false (niet aanbevolen)
export MCSD_CA_CERTS_FILE=/path/to/ca-bundle.pem   # optioneel
```

`MCSD_CA_CERTS_FILE` wordt alleen gebruikt als `MCSD_VERIFY_TLS=true`.

#### CORS en allowed hosts

Standaard staan CORS en host-checks “open” voor lokale ontwikkeling. Voor productie moet je dit dichtzetten.

```bash
export MCSD_ALLOW_ORIGINS='["https://jouw-frontend.example"]'
export MCSD_ALLOWED_HOSTS='["jouw-proxy.example"]'
```

> Let op: de parsing van list-waardes hangt af van je runtime/omgeving. In veel setups werkt JSON zoals hierboven; in andere setups wordt een komma-gescheiden string gebruikt. Test dit in je deployment-omgeving.

#### API key (optioneel)

Als je `MCSD_API_KEY` zet, zijn (bijna) alle endpoints beveiligd met een header:

- Header: `X-API-Key: <jouw key>`

```bash
export MCSD_API_KEY="supersecret"
```

Alleen `GET /health` blijft altijd zonder API key bereikbaar.

#### Productie guardrails

Als je `MCSD_IS_PRODUCTION=true` zet, faalt de app bij startup als één van deze onveilige defaults nog actief is:

- `MCSD_ALLOW_ORIGINS=["*"]`
- `MCSD_ALLOWED_HOSTS=["*"]`
- `MCSD_VERIFY_TLS=false`

```bash
export MCSD_IS_PRODUCTION=true
```

#### [PoC 14] Query-limieten (bescherming)

Voor `GET /mcsd/search/{resource}` (het pass-through search endpoint) kun je limieten instellen. Deze gelden niet voor de addressbook- of PoC-endpoints, die eigen validatie hebben.

```bash
export MCSD_MAX_QUERY_PARAMS=50
export MCSD_MAX_QUERY_VALUE_LENGTH=256
export MCSD_MAX_QUERY_PARAM_VALUES=20
```

#### Feature flags en logging

##### [PoC 9] Notified Pull endpoints aan/uit (BgZ)

Standaard staan de BgZ/Notified Pull endpoints **aan** en worden ook controles gedaan om te bepalen of de configuratie hiervoor in orde is.
Voor PoC 14 worden de BgZ/Notified Pull endpoints niet gebruikt. Ze kunnen daarom in één keer uit gezet worden met:

```bash
export MCSD_NOTIFIEDPULL_ENABLED=false
```

Als dit `false` is:
- `POST /bgz/load-data`, `POST /bgz/preflight`, `POST /bgz/task-preview` en `POST /bgz/notify` retourneren `503`.
- Bij startup worden de BgZ Task-templates niet gevalideerd.

##### Loglevel

```bash
export MCSD_LOG_LEVEL=INFO   # DEBUG, INFO, WARNING, ERROR
```

##### File logging

Bij startup schrijft de proxy een logbestand naar de debug dump directory (standaard `/tmp/mcsd-debug`). Dit logbestand bevat dezelfde output als stdout maar is handig als de applicatie onder systemd/journal draait. Bestandsnaam bevat een timestamp, bijv. `mcsd_20260217T120000.000000Z.log`.

##### Capability cache TTL

Voor sommige best-effort capability checks (bijv. `/metadata`) gebruikt de proxy een kleine in-memory cache:

```bash
export MCSD_CAPABILITY_CACHE_TTL_SECONDS=600
```

#### [PoC 9] BgZ sender-identiteit (voor `POST /bgz/preflight`, `POST /bgz/task-preview` en `POST /bgz/notify`)

De BgZ endpoints versturen/tonen een **notified pull**-achtige Task namens een *vaste* afzender (PoC-sender).  
Om spoofing vanuit het frontend te voorkomen komen sender-waarden uit environment variabelen:

- `MCSD_SENDER_URA` — **verplicht**
- `MCSD_SENDER_NAME` — **verplicht**
- `MCSD_SENDER_UZI_SYS` — **verplicht** (identifier.system van de requester/agent)
- `MCSD_SENDER_SYSTEM_NAME` — **verplicht** (displaynaam van de requester/agent)
- `MCSD_SENDER_BGZ_BASE` — **verplicht voor verzenden** (nodig voor `POST /bgz/preflight` en `POST /bgz/notify`, om de Workflow Task te hosten)

Voorbeeld:

```bash
export MCSD_SENDER_URA=urn:oid:2.16.528.1.1007.3.3.1234567
export MCSD_SENDER_NAME="Mijn ZBC"
export MCSD_SENDER_UZI_SYS=urn:oid:2.16.528.1.1007.3.2.1234567
export MCSD_SENDER_SYSTEM_NAME="Mijn ZBC (BgZ)"
export MCSD_SENDER_BGZ_BASE=https://mijn-sender-fhir.example.org/fhir
```

Opmerking:
- Als `MCSD_SENDER_BGZ_BASE` ontbreekt, dan blijft `POST /bgz/task-preview` bruikbaar maar zonder `sender_bgz_base` metadata/extensie; `POST /bgz/preflight` en `POST /bgz/notify` falen met `500` (misconfigured).

#### [PoC 9] Audit logging en task preview (voor `POST /bgz/notify` en `POST /bgz/task-preview`)

Voor audit logging en (optioneel) het tonen van de uiteindelijke Task vóór verzending zijn er extra variabelen:

- `MCSD_AUDIT_HMAC_KEY` — optioneel. Als gezet, wordt gevoelige patiënt-identificatie (zoals BSN) **niet** als plain value gelogd maar als **HMAC-hash** (pseudonimisatie) in de audit logs.
- `MCSD_ALLOW_TASK_PREVIEW_IN_PRODUCTION` — optioneel (default `false`). Als `true`, is `POST /bgz/task-preview` ook beschikbaar als `MCSD_IS_PRODUCTION=true`.

Voorbeeld:

```bash
export MCSD_AUDIT_HMAC_KEY="een-lange-random-secret"
export MCSD_ALLOW_TASK_PREVIEW_IN_PRODUCTION=false
```

#### [PoC 9] Debug JSON dumps (voor `POST /bgz/load-data` en `POST /bgz/notify`)

Voor debug doeleinden kan de proxy de **outgoing JSON payloads** die deze endpoints naar een externe FHIR server sturen wegschrijven als bestanden op disk.

- `POST /bgz/load-data`: schrijft per verstuurde resource (PUT) één JSON bestand.
- `POST /bgz/notify`: schrijft één JSON bestand met de Task die naar `{receiver_notification_base}/Task` wordt gepost.

Dit staat standaard **uit** en is bedoeld voor lokale ontwikkeling; gebruik dit niet in productie omdat bestanden (ook met redactie) gevoelige data kunnen bevatten.

Environment variabelen:

- `MCSD_DEBUG_DUMP_JSON` — optioneel (default `false`). Zet op `true` om dumps te schrijven.
- `MCSD_DEBUG_DUMP_DIR` — optioneel (default `/tmp/mcsd-debug`). Directory waarin bestanden worden weggeschreven (moet writable zijn).
- `MCSD_DEBUG_DUMP_REDACT` — optioneel (default `true`). Redigeert bekende BSN-identifiers/velden in de JSON voordat deze naar disk gaat.

Voorbeeld:

```bash
export MCSD_DEBUG_DUMP_JSON=true
export MCSD_DEBUG_DUMP_DIR=/tmp/mcsd-debug
export MCSD_DEBUG_DUMP_REDACT=true
```

Bestandsnamen bevatten een timestamp en (als beschikbaar) de `X-Request-ID`, zodat je dumps makkelijk kunt koppelen aan applicatie-logs.


### Run

```bash
# In deze repo-snapshot heet de module `main20260217.py`:
uvicorn main20260217:app --host 0.0.0.0 --port 8000

# Als je bestand `app.py` heet:
# uvicorn app:app --host 0.0.0.0 --port 8000
```

Je kunt ook direct runnen (zonder uvicorn commandline):

```bash
python main20260217.py
```

### Draai tests (met de **publieke HAPI FHIR R4 server** op `https://hapi.fhir.org/baseR4`)

```bash
pytest -q
```

Notes:
- Tests will **skip gracefully** if the upstream is unreachable (e.g., network/firewall issues).  
- The proxy always sends `Accept: application/fhir+json` upstream, ensuring JSON responses.

FastAPI documentatie:
- Swagger UI: `/docs`
- OpenAPI spec: `/openapi.json`

### Observability / request-id

- Als de client een `X-Request-ID` header meestuurt, wordt die doorgegeven (en ook upstream gezet).
- Als die ontbreekt, genereert de proxy er één.
- De response bevat altijd `X-Request-ID`.
- In foutresponses komt dezelfde waarde ook terug als `request_id`.

## Observability / audit logging

Naast gewone applicatie-logs (logger `mcsd.app`) schrijft de proxy ook **audit events** (logger `mcsd.audit`) als **JSON per regel**. Dit is bedoeld voor traceability van “business events” zoals het (proberen te) versturen van een Notified Pull notificatie.

Belangrijkste eigenschappen:

- Audit logs bevatten **geen** volledige Task payloads.
- Patiënt-identificatie wordt bij voorkeur **gepseudonimiseerd**: als `MCSD_AUDIT_HMAC_KEY` gezet is, wordt een HMAC-hash gelogd i.p.v. het BSN.
- De audit events bevatten o.a. `event_type`, `request_id`, `task_group_identifier`, `notification_endpoint_id` en `http_status` (bij resultaat).

Voorbeeld (conceptueel):

```json
{"event_type":"bgz.notify.attempt","request_id":"...","task_group_identifier":"urn:uuid:...","patient_ref":"hmac:...","resolved_receiver_base":"https://...","notification_endpoint_id":"Endpoint/..."}
{"event_type":"bgz.notify.result","request_id":"...","success":true,"http_status":201,"task_id":"...","task_group_identifier":"urn:uuid:..."}
```

### Audit logs scheiden van “tech logs”

Als je audit logs apart wilt wegschrijven (bijv. naar een apart bestand of een aparte log pipeline), configureer je logging zo dat logger `mcsd.audit` naar een eigen handler gaat.

Een eenvoudige manier is een eigen logging-config (JSON/YAML) voor uvicorn te gebruiken. Bijvoorbeeld: route `mcsd.audit` naar stdout of naar een file handler en zet `propagate=false` voor die logger.

---

## Frontend / API usage

### Authenticatie

Als `MCSD_API_KEY` is ingesteld, stuur dan bij elke call (behalve `GET /health`) een header mee:

```text
X-API-Key: <jouw key>
```

### Gedeelde endpoints

#### `GET /health`

Liveness/readiness voor de proxy zelf.  
Dit endpoint controleert **niet** of de upstream mCSD server bereikbaar is.

Voorbeeld:

```bash
curl http://localhost:8000/health
```

#### [PoC 14] `GET /mcsd/search/{resource}`

FHIR search “pass-through” met allow-list filtering. Alleen een vaste set resource types wordt geaccepteerd:

- `Practitioner`
- `PractitionerRole`
- `HealthcareService`
- `Location`
- `Organization`
- `Endpoint`
- `OrganizationAffiliation`

Niet-toegestane resources geven `400`.

Daarnaast wordt een allow-list per resource toegepast op query parameters (en `_count` wordt afgekapt op maximaal 200).

Voorbeeld:

```bash
curl "http://localhost:8000/mcsd/search/Organization?active=true&name:contains=ziekenhuis&_count=50"
```

### Addressbook convenience endpoints

#### [PoC 9] `GET /addressbook/find-practitionerrole`

Convenience endpoint om eerst `Practitioner` te zoeken op naam en daarna bijbehorende `PractitionerRole` te halen.

Query parameters:
- `name` (verplicht)
- `organization` (optioneel)
- `specialty` (optioneel)

Voorbeeld:

```bash
curl "http://localhost:8000/addressbook/find-practitionerrole?name=Jansen"
```

#### [PoC 14] `GET /addressbook/search`

Zoekt `Practitioner` + `PractitionerRole` en geeft "flattened" rows terug.  
Verrijkt daarnaast best-effort met:
- `HealthcareService` (op Organization of Location)
- `OrganizationAffiliation` relaties (met org-namen via `_include`)

Query parameters (selectie):
- `name`, `family`, `given`
- `organization` (bijv. `Organization/123`)
- `org_name` (client-side “contains” match)
- `specialty`
- `city`, `postal`
- `near` in vorm `lat|lng|distance|unit`
- `limit` (default `200`, max 2000)
- `mode=fast|full` (default `fast`)

Aliases (ook toegestaan): `practitioner.name`, `practitioner.family`, `practitioner.given`, `practitioner.identifier`, `organization.name(:contains)`, `location.near`, `location.near-distance`, enz.

Voorbeeld:

```bash
curl "http://localhost:8000/addressbook/search?org_name=Oost&specialty=cardio&limit=50"
```

Voorbeeld: vind zorgverleners die "Jansen" heten in organisaties waarvan de naam "Ziekenhuis" bevat.

```bash
curl "http://localhost:8000/addressbook/search?name=Jansen&org_name=Ziekenhuis&limit=50"
```

Response (globaal):
- `total`: aantal rows
- `rows`: lijst met velden zoals `practitioner_name`, `organization_name`, `email`, `phone`, `service_name`, `affiliation_*`, …

#### [PoC 14] `GET /addressbook/organization`

Zoekt **organisaties** en retourneert functionele mailboxen:
- uit `Organization.telecom` (system=email)
- en (indien aanwezig) uit `Endpoint.address` met `mailto:...` via `_include=Organization:endpoint`

Query parameters:
- `name` (optioneel) of `name:contains`
- `active` (default `true`)
- `limit` (default `20`, max `100`)
- `contains` (boolean; alternatief voor `name:contains`)

Voorbeeld:

```bash
curl "http://localhost:8000/addressbook/organization?name:contains=ziekenhuis&limit=20"
```

#### [PoC 14] `GET /addressbook/location`

Zoekt **locaties** en geeft de functionele mailbox van de zorgaanbieder (organisatie) terug:
- eerst `Location.telecom`
- daarna `Organization.telecom`
- daarna `Organization.endpoint` (mailto) indien beschikbaar

Query parameters:
- `name` (optioneel) of `name:contains`
- `limit` (default `20`, max `100`)
- `contains` (boolean; alternatief voor `name:contains`)

Voorbeeld:

```bash
curl "http://localhost:8000/addressbook/location?name:contains=polikliniek&limit=20"
```

---

## [PoC 9] Capability mapping

IG CodeSystem used in Endpoint.payloadType to declare data-exchange capabilities.
Reference: https://build.fhir.org/ig/nuts-foundation/nl-generic-functions-ig/CodeSystem-nl-gf-data-exchange-capabilities.html
IG_CAPABILITY_SYSTEM = "http://nuts-foundation.github.io/nl-generic-functions-ig/CodeSystem/nl-gf-data-exchange-capabilities"

Expected payloadType codes for PoC 9 capability mapping:

### REQUIRED for BgZ Notified Pull (TA Routering):
   - Code: "Twiin-TA-notification"
   - System: IG_CAPABILITY_SYSTEM (see above)
   - Purpose: Identifies the receiver's Task notification endpoint
   - Used in: Decision tree to find the endpoint for POST Task
   - Example mCSD entry:
     Endpoint.payloadType[].coding[] = {
       "system": "http://nuts-foundation.github.io/nl-generic-functions-ig/CodeSystem/nl-gf-data-exchange-capabilities",
       "code": "Twiin-TA-notification"
     }
### OPTIONAL for BgZ FHIR server discovery (informational):
   - Code: "http://nictiz.nl/fhir/CapabilityStatement/bgz2017-servercapabilities" (full URL as code)
   - System: "urn:ietf:rfc:3986" or may be absent
   - Purpose: Identifies the sender's BgZ FHIR server for receivers that cannot resolve via URA
   - Not required for sender-side notification flow

Note: The mCSD directory must populate Endpoint.payloadType with these codes
for the capability mapping to work correctly.

---

## PoC-specifieke endpoints

### [PoC 9] BgZ endpoints

#### `POST /bgz/load-data`

Laadt BgZ sample data (Patient/Condition/Allergy/Medication/…) naar een doel-FHIR server (bijv. HAPI) met `PUT` per resource.

Query parameters:
- `hapi_base` (verplicht): base URL van de doelsserver
- `sender_ura` (verplicht): URA/OID die in het sample bundle wordt gezet

Voorbeeld:

```bash
curl -X POST "http://localhost:8000/bgz/load-data?hapi_base=http://localhost:8080/fhir&sender_ura=12345678"
```

> PoC-only: niet bedoeld voor productie, omdat dit demo-data laadt.

#### `POST /bgz/preflight`

Preflight check om vóór verzending te bepalen:
- of de backend sender-config compleet is
- welk Twiin-TA notification endpoint en welke receiver base gebruikt gaat worden
- (optioneel) of de receiver FHIR base bereikbaar is en `Task` creation ondersteunt

Request body (JSON):
- `receiver_target_ref` (verplicht): `Organization/<id>`, `HealthcareService/<id>` of `Location/<id>`
- `receiver_org_ref` (optioneel): `Organization/<id>` (kan helpen bij capability mapping als het target zelf geen endpoints heeft)
- `receiver_notification_endpoint_id` (optioneel): `Endpoint/<id>` of `<id>` uit de UI-keuze; backend checkt of dit nog klopt met de huidige capability mapping
- `check_receiver` (optioneel, default `true`): probe `/metadata` op de resolved receiver base
- `include_oauth` (optioneel, default `false`): voeg (demo/debug) OAuth/NUTS endpoints toe aan de capability mapping response

Response:
- bevat de capability mapping output (zoals `supported`, `target`, `organization`, …)
- plus extra velden: `task_routing`, `resolved_receiver_base`, `resolved_receiver_ura`, `notification_endpoint_id`, `frontend_endpoint_id_match`, `receiver_probe`, `ready_to_send`

#### `POST /bgz/task-preview`

Bouwt een BgZ notificatie-Task (zonder te versturen). Dit is bedoeld voor UI preview/tests.

- In productie is deze endpoint standaard **uit**. Zet `MCSD_ALLOW_TASK_PREVIEW_IN_PRODUCTION=true` als je ’m bewust wilt gebruiken.

Request body: gelijk aan `POST /bgz/notify`.

Response (globaal):
- `task`: de JSON Task die verstuurd zou worden
- `resolved_receiver_base`: de resolved base URL
- `notification_endpoint_id`: het gekozen/geresolveerde notification Endpoint.id
- `workflow_task_id`: de workflow task id (zoals in `Task.basedOn`)
- `sender_bgz_base`: de sender base (als gezet)

#### `POST /bgz/notify`

Stuurt een notificatie **Task** (notified pull pattern) naar de receiver (`{receiver_notification_base}/Task`).

De sender-identiteit komt uit environment variabelen (zie “BgZ sender-identiteit”).

**Verzendproces (twee stappen):**

1. **Workflow Task aanmaken** — De backend bouwt een Workflow Task (met BgZ queries/resources in `Task.input`) en slaat deze op op de sender’s FHIR server (`MCSD_SENDER_BGZ_BASE`) via `PUT /Task/{id}` (met fallback naar `POST /Task` als de server geen client-assigned ids accepteert).
2. **Notification Task versturen** — De backend POST de notification Task naar `{receiver_notification_base}/Task`.

**SSRF-mitigatie:** de client geeft geen vrije `receiver_base` mee. In plaats daarvan resolveert de backend `receiver_notification_base` opnieuw via het mCSD-adresboek (`MCSD_BASE`) op basis van `receiver_target_ref` (en optioneel `receiver_org_ref`) met PoC 9 capability mapping. Daarbij wordt een `Endpoint` gezocht met payloadType `Twiin-TA-notification`, waarna `Endpoint.address` wordt genormaliseerd naar een base (o.a. trailing `/` en eventuele `/Task` eraf) en vervolgens wordt gevalideerd als een http(s)-URL.

**URA-resolutie:** Hoewel `receiver_ura` verplicht is in het request, resolveert de backend de URA **altijd opnieuw** vanuit de mCSD Organization resource (via `Organization.identifier` met system `http://fhir.nl/fhir/NamingSystem/ura`). De client-meegegeven `receiver_ura` wordt alleen ter controle vergeleken; bij een mismatch wordt een warning gelogd. Als er geen URA gevonden kan worden in het mCSD-adresboek, faalt het request met HTTP 400 (`no_receiver_ura`).

Audit logging: bij elke poging en uitkomst van `POST /bgz/notify` wordt een audit event gelogd via logger `mcsd.audit` (zie Observability / audit logging).

Request body (JSON):
- `receiver_target_ref` (verplicht): `Organization/<id>`, `HealthcareService/<id>` of `Location/<id>`
- `receiver_org_ref` (optioneel): `Organization/<id>` (kan helpen bij capability mapping als het target zelf geen endpoints heeft)
- `receiver_notification_endpoint_id` (optioneel): `Endpoint/<id>` of `<id>` uit preflight/UI (backend checkt op “stale” endpoint-keuze)
- `receiver_ura` (verplicht)
- `receiver_name` (verplicht): display name van receiver (bijv. “Ziekenhuis Oost – Cardiologie”)
- `receiver_org_name` (optioneel): display name van de receiver-organisatie
- `patient_bsn` (verplicht)
- `patient_name` (optioneel)
- `description` (optioneel)
- `workflow_task_id` (optioneel): als leeg, genereert de server een id en zet `Task.basedOn` naar `Task/<id>`

Voorbeeld:

```bash
curl -X POST "http://localhost:8000/bgz/notify" \
  -H "Content-Type: application/json" \
  -d '{
    "receiver_target_ref": "HealthcareService/123",
    "receiver_org_ref": "Organization/456",
    "receiver_ura": "87654321",
    "receiver_name": "Ziekenhuis Oost - Cardiologie",
    "receiver_org_name": "Ziekenhuis Oost",
    "patient_bsn": "172642863",
    "patient_name": "J.P. van der Berg",
    "description": "BgZ notified pull demo"
  }'
```

**Foutafhandeling (hard fail)**

Als er via PoC9 capability mapping géén `Endpoint` met payloadType `Twiin-TA-notification` gevonden kan worden voor het gekozen `receiver_target_ref` (en optioneel `receiver_org_ref`), dan kan de backend geen veilige `receiver_notification_base` bepalen. In dat geval wordt er **geen** notificatie verstuurd en retourneert de API een **HTTP 400**:

```json
{
  "reason": "no_notification_endpoint",
  "message": "Geen Twiin TA notification endpoint gevonden voor het gekozen target/organisatie.",
  "request_id": "..."
}
```

Dit is een “hard fail”: de caller moet eerst zorgen dat in het mCSD-adresboek een geschikt (actief) Twiin-TA-notification Endpoint aanwezig is en daarna opnieuw notificeren.

### [PoC 9] MSZ endpoints

Deze endpoints ondersteunen PoC 8/9 UI-flows (MSZ organisaties, organisatieonderdelen en technische endpoints).  
Ze hebben cursor-based paginering voor “meer laden” in de UI.

#### `GET /poc9/msz/organizations`

Zoekt MSZ-zorgorganisaties (Organization) en levert per org ook technische endpoint-info (op basis van `_include=Organization:endpoint`).

Query parameters:
- `name` (optioneel), `contains` (boolean)
- `identifier` (optioneel)
- `type` (optioneel; query-param alias)
- `limit` (default 20)
- `cursor` (optioneel; voor volgende pagina)

Response bevat o.a. `next` (opaque cursor) en `total` (upstream total, indien aanwezig).

#### `GET /poc9/msz/orgunits`

Zoekt organisatieonderdelen binnen een org:
- `kind=location|service|suborg|all`
- `organization` is verplicht in de eerste call (zonder `cursor`)
- `cursor` voor volgende pagina’s

#### `GET /poc9/msz/endpoints`

Haalt “technische endpoints” op voor een geselecteerd target (`Location/…`, `HealthcareService/…`, `Organization/…`).

Query parameters:
- `target` (verplicht zonder cursor): `ResourceType/id`
- optioneel filters: `endpoint_kind` (heuristisch), `connection_type`, `payload_type`, `payload_mime_type`
- `limit`, `cursor`

#### `GET /poc9/msz/capability-mapping`

Resolve’t endpoints voor capabilities via decision tree A–D (PoC 9).  
Required: Twiin TA notificatie capability. Optioneel: BgZ FHIR server capability en Nuts OAuth (`include_oauth=true`).

Query parameters:
- `target` (verplicht): `ResourceType/id`
- `organization` (optioneel): `Organization/id` (anders probeert de service dit af te leiden)
- `include_oauth` (optioneel)
- `limit` (max endpoints per scope)

---

## [PoC 14] Frontend: `mcsd_zoek.html`

`mcsd_zoek.html` is een standalone HTML-pagina waarmee gebruikers e-mailadressen van organisaties of locaties kunnen opzoeken in het mCSD-adresboek.

### Gebruikte endpoints

De pagina gebruikt uitsluitend twee addressbook convenience endpoints:

- **`GET /addressbook/organization`** — zoek organisaties met functionele mailboxen
- **`GET /addressbook/location`** — zoek locaties met functionele mailboxen van de gekoppelde organisatie

Beide worden aangeroepen met de query parameters `name:contains=<zoekterm>` en `limit=<max>`.

### Configuratie in de HTML

Bovenaan het `<script>`-blok staan drie constanten die per omgeving aangepast moeten worden:

```javascript
const BASE_URL = "http://10.10.10.199:8000"; // proxy base URL
const API_KEY  = "";                          // laat leeg als geen API key vereist is
const MCS_LIMIT = 50;                         // max resultaten per zoekopdracht
```

### Relevante server-instellingen

| Instelling | Van toepassing? | Toelichting |
|---|---|---|
| `MCSD_BASE` | **Ja** | Bepaalt de upstream FHIR server |
| `MCSD_API_KEY` | **Ja** | Als gezet, moet `API_KEY` in de HTML overeenkomen |
| `MCSD_ALLOW_ORIGINS` | **Ja** | Moet de origin van de HTML-pagina bevatten (of `["*"]` voor dev) |
| `MCSD_ALLOWED_HOSTS` | **Ja** | Moet de proxy-hostnaam bevatten |
| `MCSD_UPSTREAM_TIMEOUT` | **Ja** | Beïnvloedt de responstijd |
| `MCSD_BEARER_TOKEN` | **Ja** | Upstream authenticatie (transparant voor de HTML-client) |
| `MCSD_VERIFY_TLS` / `MCSD_CA_CERTS_FILE` | **Ja** | Upstream TLS (transparant voor de HTML-client) |
| `MCSD_IS_PRODUCTION` | **Ja** | Productie guardrails (CORS/hosts/TLS moeten dan dicht) |
| `MCSD_LOG_LEVEL` | **Ja** | Voor troubleshooting |
| `MCSD_HTTPX_MAX_CONNECTIONS` | **Ja** | HTTP client pool sizing |

De volgende instellingen zijn **niet van toepassing** bij gebruik van `mcsd_zoek.html`:

| Instelling | Waarom niet |
|---|---|
| `MCSD_SENDER_URA`, `MCSD_SENDER_NAME`, `MCSD_SENDER_UZI_SYS`, `MCSD_SENDER_SYSTEM_NAME`, `MCSD_SENDER_BGZ_BASE` | Alleen voor BgZ notified pull endpoints |
| `MCSD_NOTIFIEDPULL_ENABLED` | Alleen voor BgZ endpoints (`/bgz/*`) |
| `MCSD_AUDIT_HMAC_KEY` | Alleen voor BgZ audit logging |
| `MCSD_ALLOW_TASK_PREVIEW_IN_PRODUCTION` | Alleen voor `POST /bgz/task-preview` |
| `MCSD_CAPABILITY_CACHE_TTL_SECONDS` | Alleen voor PoC 9 capability mapping |
| `MCSD_MAX_QUERY_PARAMS`, `MCSD_MAX_QUERY_VALUE_LENGTH`, `MCSD_MAX_QUERY_PARAM_VALUES` | Alleen voor `GET /mcsd/search/{resource}` |
| `MCSD_DEBUG_DUMP_JSON`, `MCSD_DEBUG_DUMP_DIR`, `MCSD_DEBUG_DUMP_REDACT` | Alleen voor BgZ debug dumps |

---

## Verschillen met upstream / foutafhandeling

De proxy normaliseert foutresponses naar één vorm:

```json
{
  "reason": "...",
  "message": "...",
  "request_id": "..."
}
```

- Upstream HTTP fouten (4xx/5xx) worden met dezelfde statuscode teruggegeven, maar de response body wordt genormaliseerd (dus niet 1-op-1 “pass-through”).
- Connectieproblemen naar upstream worden als `502` teruggegeven met een `reason` zoals `timeout`, `dns`, `tls` of `network`.
- In non-production kan er een extra `details` veld aanwezig zijn; in productie (`MCSD_IS_PRODUCTION=true`) wordt `details` weggelaten.

## Upstream-ondersteuning en verrijking

### Upstream-ondersteuning varieert

De proxy kan alleen zoekparameters, ketenparameters en modifiers gebruiken die de upstream mCSD/FHIR-server daadwerkelijk ondersteunt. 

De CapabilityStatement (`GET {MCSD_BASE}/metadata`) kan helpen om te zien welke search parameters en interacties een server zegt te ondersteunen. Deze geeft echter niet altijd een volledig of betrouwbaar beeld van ondersteuning voor alle search modifiers (zoals `:contains` of `:exact`). Ondersteuning voor bijvoorbeeld geografische zoekparameters (zoals `near` met afstand) is eveneens afhankelijk van de implementatie van de upstream-server.

### OrganizationAffiliation verrijking via `_include`

Bij het ophalen van `OrganizationAffiliation`-relaties vraagt de proxy:

- `_include=OrganizationAffiliation:organization`
- `_include=OrganizationAffiliation:participating-organization`

Hierdoor kunnen organisatie-namen (indien de upstream `_include` ondersteunt) in dezelfde response worden meegeleverd, zodat er geen extra round-trips naar `Organization`-resources nodig zijn.

Indien de upstream-server `_include` niet ondersteunt of deze niet retourneert, wordt de verrijking beperkt uitgevoerd, maar er worden geen aanvullende fetch-calls gedaan.