# HPD LDAP E-mailadres zoeken (FastAPI + HTML frontend)

Deze repo bevat een kleine **FastAPI**-service (v1.2.0) die LDAP/HPD-directory searches aanbiedt als eenvoudige JSON API, plus een standalone HTML pagina om e-mailadressen op te zoeken.
Deze service maakt het makkelijker voor een client zoals een EPD (de standalone HTML pagina demonstreert dat) om LDAP queries te doen.

- `main.py` — **backend** (FastAPI): vertaalt zoekacties naar LDAP searches en retourneert JSON.
- `ldap_zoek.html` — **frontend** (static HTML): UI voor zoeken op **persoon** of **organisatie** en (indien beschikbaar) direct een e-mail starten via `mailto:`.

---

## Operator / deploy

### Installatie (lokaal)

Vereisten:
- **Python 3.10+** (de backend gebruikt `str | None` type hints).

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

De backend leest configuratie uit **environment variabelen** en optioneel uit een **`.env`-bestand** in de projectroot (via `pydantic-settings`).
Variabelen in de environment hebben voorrang op `.env`.

#### LDAP verbinding

Belangrijkste instellingen:

| Variabele | Default | Toelichting |
|---|---|---|
| `HPD_LDAP_URI` | `ldap://localhost:389` | LDAP/LDAPS host + poort |
| `HPD_LDAP_USE_SSL` | `false` | Gebruik LDAPS (TLS vanaf connect) |
| `HPD_LDAP_START_TLS` | `false` | Gebruik StartTLS (upgrade na connect) |
| `HPD_LDAP_VERIFY_TLS` | `true` | Certificaatvalidatie bij TLS |
| `HPD_LDAP_CA_CERTS_FILE` | *(leeg)* | Pad naar CA bundle (bij `VERIFY_TLS=true`) |
| `HPD_LDAP_CONNECT_TIMEOUT` | `5` | Connect-timeout (seconden) |
| `HPD_LDAP_TIMEOUT` | `10` | Receive-timeout (seconden) |

> Let op: **zet niet tegelijk** `HPD_LDAP_USE_SSL=true` én `HPD_LDAP_START_TLS=true`. Als je dit toch doet, gebruikt de service StartTLS en negeert `USE_SSL`.

#### Bind / credentials

| Variabele | Default | Toelichting |
|---|---|---|
| `HPD_LDAP_BIND_DN` | *(leeg)* | Bind DN (leeg = anonieme bind) |
| `HPD_LDAP_BIND_PASSWORD` | *(leeg)* | Wachtwoord voor bind |

Extra gedrag:
- `HPD_LDAP_BIND_DN` ondersteunt een `{base}` placeholder: bijvoorbeeld `cn=readonly,{base}`.
- Als je een *RDN* geeft zonder komma (bv. `cn=readonly`), dan wordt automatisch `,<base>` toegevoegd.

#### Base DN en directory-structuur

| Variabele | Default | Toelichting |
|---|---|---|
| `HPD_LDAP_BASE_DN` | `dc=HPD` | Root/base van de directory; zet op `auto` voor RootDSE discovery |

De service zoekt in twee OU's (onder de root/base):

- **personen**: `ou=HCProfessional,<base_root>`
- **organisaties**: `ou=HCRegulatedOrganization,<base_root>`

Als de OU niet bestaat, retourneert de API gewoon **0 resultaten** (geen hard error).

#### Query-limieten

| Variabele | Default | Toelichting |
|---|---|---|
| `HPD_LDAP_DEFAULT_SIZE_LIMIT` | `50` | Default `limit` voor search (per request max 500) |

#### CORS en allowed hosts

Voor lokale ontwikkeling staan deze standaard "open". Voor productie: dichtzetten.

| Variabele | Default | Toelichting |
|---|---|---|
| `HPD_LDAP_ALLOW_ORIGINS` | `["*"]` | CORS allow-list (origins) |
| `HPD_LDAP_ALLOWED_HOSTS` | `["*"]` | Trusted hosts allow-list |

Voorbeeld (JSON string):

```bash
export HPD_LDAP_ALLOW_ORIGINS='["https://jouw-frontend.example"]'
export HPD_LDAP_ALLOWED_HOSTS='["jouw-proxy.example"]'
```

#### API key (optioneel)

Als je `HPD_LDAP_API_KEY` zet, zijn alle endpoints behalve `GET /health` beveiligd met een header:

- Header: `X-API-Key: <jouw key>`

```bash
export HPD_LDAP_API_KEY="supersecret"
```

#### Logging

| Variabele | Default | Toelichting |
|---|---|---|
| `HPD_LDAP_LOG_LEVEL` | `INFO` | Logniveau: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Run

Start de API met uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Voeg `--reload` toe tijdens ontwikkeling om de server automatisch te herstarten bij codewijzigingen:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

FastAPI documentatie:
- Swagger UI: `http://localhost:8000/docs`
- OpenAPI spec: `http://localhost:8000/openapi.json`

### Observability / request-id

De service voegt bij elke response een `X-Request-ID` header toe (UUID). Gebruik deze ID om requests te correleren met logregels.

---

## Gebruik van de API

### Authenticatie

Als `HPD_LDAP_API_KEY` is ingesteld, stuur dan bij elke call (behalve `GET /health`) de header mee:

```text
X-API-Key: <jouw key>
```

### Basis endpoints

#### `GET /health`

Liveness/readiness voor de service zelf (controleert niet of LDAP bereikbaar is).

Voorbeeld:

```bash
curl http://localhost:8000/health
```

#### `GET /hpd/search`

Query parameters:
- `q` — zoektekst (max 64 tekens; lege waarde retourneert de eerste N entries in de OU)
- `scope` — `person` of `org` (default `person`)
- `limit` — max aantal resultaten (default `HPD_LDAP_DEFAULT_SIZE_LIMIT`, max 500)

Voorbeeld:

```bash
curl "http://localhost:8000/hpd/search?q=Jansen&scope=person&limit=50"
```

#### `POST /hpd/search`

Zelfde functionaliteit als `GET`, maar met JSON body.

Voorbeeld:

```bash
curl -X POST "http://localhost:8000/hpd/search" \
  -H "Content-Type: application/json" \
  -d '{"q":"cardiologie","scope":"org","limit":50}'
```

### Response formaat

De response heeft altijd deze vorm:

```json
{
  "count": 1,
  "items": [
    {
      "uid": ["..."],
      "objectClass": ["..."],
      "cn": ["..."],
      "sn": ["..."],
      "givenName": ["..."],
      "mail": ["..."],
      "displayName": ["..."],
      "telephoneNumber": ["..."],
      "mobile": ["..."],
      "title": ["..."],
      "o": ["..."],
      "ou": ["..."],
      "dn": "cn=...,ou=...,dc=..."
    }
  ]
}
```

Opmerkingen:
- Attributen worden als **arrays** teruggegeven (LDAP kan multivalued attributen hebben). De frontend pakt doorgaans het **eerste** element per attribuut.
- Uitzondering: `dn` is altijd een **string** (geen array).

### Zoeklogica

- De zoekterm wordt veilig ge-escaped voor LDAP filter-constructie.
- `scope=person` zoekt (substring match) in `cn`, `sn`, `givenName`, `mail` en filtert op `objectClass=inetOrgPerson`.
- `scope=org` zoekt (substring match) in `o`, `ou`, `cn`, `mail` zonder objectClass-filter (alle objectklassen komen in aanmerking).
- Een lege zoekterm retourneert de eerste entries in de betreffende OU (tot het ingestelde `limit`).

---

## Frontend: `ldap_zoek.html`

`ldap_zoek.html` is een standalone HTML pagina voor eindgebruikers:

- kies **persoon** of **organisatie**
- vul een zoekterm in
- klik **Zoek**
- dubbelklik op een resultaat om een e-mail te starten (`mailto:`), als er een e-mailadres is

### Configuratie in de HTML

Bovenaan het `<script>`-blok staan instellingen die je per omgeving aanpast:

```javascript
const BASE_URL = "http://10.10.10.199:8000"; // bv. "http://hostname:8000"
const API_KEY = "";                          // laat leeg als geen API key vereist is
const HPD_LIMIT = 50;                        // max resultaten per zoekopdracht
```

### Gebruikte endpoint

De pagina gebruikt één endpoint:

- `GET /hpd/search?q=...&scope=...&limit=...`

### HTML hosten vs. file:// openen

- Met de standaard serverinstelling `HPD_LDAP_ALLOW_ORIGINS=["*"]` werkt openen via `file://` vaak al.
- Als je CORS-origins wilt beperken, host de HTML dan via HTTP(S) (bijv. `python -m http.server`) en zet `HPD_LDAP_ALLOW_ORIGINS` op de juiste origin(s).

---

## Troubleshooting

### 401 — Ongeldige API key

- Oorzaak: `HPD_LDAP_API_KEY` staat aan, maar de frontend (of curl) stuurt geen of de verkeerde `X-API-Key`.
- Oplossing: zet `API_KEY` in `ldap_zoek.html` gelijk aan `HPD_LDAP_API_KEY` of stuur de header mee.

### 500 — Interne serverfout

- Oorzaak: een onverwachte fout in de backend. De response bevat geen technische details; deze staan in de serverlog.
- Oplossing: gebruik de `X-Request-ID` uit de response header om de bijbehorende logregel te vinden.

### 502 — StartTLS of bind mislukt

- Oorzaak: verkeerde combinatie van poort/protocol (LDAP vs LDAPS), StartTLS niet enabled op server, certificaatketen ontbreekt, of credentials kloppen niet.
- Oplossing:
  - kies óf `HPD_LDAP_USE_SSL=true` óf `HPD_LDAP_START_TLS=true` (niet beide)
  - zet `HPD_LDAP_VERIFY_TLS=true` en configureer `HPD_LDAP_CA_CERTS_FILE`
  - controleer `HPD_LDAP_BIND_DN` en `HPD_LDAP_BIND_PASSWORD`

### 503 — LDAP server niet bereikbaar

- Oorzaak: host/poort niet bereikbaar, firewall, DNS, of connect-timeout.
- Oplossing: controleer `HPD_LDAP_URI`, netwerk/firewall, en eventueel `HPD_LDAP_CONNECT_TIMEOUT`.

### 0 resultaten terwijl je iets verwacht

- Controleer of de OU's bestaan:
  - `ou=HCProfessional,<base_root>` voor personen
  - `ou=HCRegulatedOrganization,<base_root>` voor organisaties
- Controleer `HPD_LDAP_BASE_DN` (of gebruik `auto` als je directory RootDSE `namingContexts` goed aanbiedt).
- Kijk in de logs (en gebruik `X-Request-ID` om een call terug te vinden).

---

## Security checklist (productie)

- Stel **`HPD_LDAP_API_KEY`** in.
- Beperk **CORS**: `HPD_LDAP_ALLOW_ORIGINS` niet op `["*"]`.
- Beperk **hosts**: `HPD_LDAP_ALLOWED_HOSTS` niet op `["*"]`.
- Gebruik TLS naar LDAP:
  - kies **LDAPS** (`HPD_LDAP_USE_SSL=true`) of **StartTLS** (`HPD_LDAP_START_TLS=true`)
  - laat **`HPD_LDAP_VERIFY_TLS=true`** aan en configureer een geldige **CA bundle** (`HPD_LDAP_CA_CERTS_FILE`)
- Draai de API bij voorkeur achter een reverse proxy met HTTPS.
