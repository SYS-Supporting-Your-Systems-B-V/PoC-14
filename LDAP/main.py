from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from bonsai import LDAPClient, LDAPSearchScope
from bonsai import LDAPError
from bonsai.errors import AuthenticationError as LDAPAuthenticationError
from bonsai.errors import ConnectionError as LDAPConnectionError
from bonsai.errors import NoSuchObjectError as LDAPNoSuchObjectError
from typing import List, Literal
import sys
import logging
import uuid
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s:%(filename)s:%(lineno)d %(message)s", stream=sys.stdout)
logger = logging.getLogger("hpd.ldap")

class Settings(BaseSettings):
    ldap_uri: str = Field("ldap://localhost:389", validation_alias="HPD_LDAP_URI")
    ldap_bind_dn: str | None = Field(None, validation_alias="HPD_LDAP_BIND_DN")
    ldap_bind_password: str | None = Field(None, validation_alias="HPD_LDAP_BIND_PASSWORD")
    ldap_base_dn: str = Field("dc=HPD", validation_alias="HPD_LDAP_BASE_DN")  # zet op 'auto' om RootDSE discovery te gebruiken
    ldap_use_ssl: bool = Field(False, validation_alias="HPD_LDAP_USE_SSL")
    ldap_start_tls: bool = Field(False, validation_alias="HPD_LDAP_START_TLS")
    ldap_verify_tls: bool = Field(True, validation_alias="HPD_LDAP_VERIFY_TLS")
    ldap_ca_certs_file: str | None = Field(None, validation_alias="HPD_LDAP_CA_CERTS_FILE")
    ldap_connect_timeout: int = Field(5, validation_alias="HPD_LDAP_CONNECT_TIMEOUT")
    ldap_timeout: int = Field(10, validation_alias="HPD_LDAP_TIMEOUT")
    default_size_limit: int = Field(50, validation_alias="HPD_LDAP_DEFAULT_SIZE_LIMIT")
    allow_origins: List[str] = Field(["*"], validation_alias="HPD_LDAP_ALLOW_ORIGINS")
    allowed_hosts: List[str] = Field(["*"], validation_alias="HPD_LDAP_ALLOWED_HOSTS")
    api_key: str | None = Field(None, validation_alias="HPD_LDAP_API_KEY")
    log_level: str = Field("INFO", validation_alias="HPD_LDAP_LOG_LEVEL")
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )

try:
    settings = Settings()
except ValidationError as e:
    unknown_keys = sorted(
        {
            err["loc"][0]
            for err in e.errors()
            if err.get("type") == "extra_forbidden" and err.get("loc")
        }
    )

    if unknown_keys:
        msg_unknown = ", ".join(unknown_keys)
        msg = (
            "Configuratiefout in HPD_LDAP_ instellingen. Onbekende variabelen: "
            f"{msg_unknown}. Controleer je .env of environment op verkeerd gespelde "
            "HPD_LDAP_* variabelen en op ongeldige waarden."
        )
        logger.error(msg)
        print(msg, file=sys.stderr)
    else:
        msg = (
            "Configuratiefout in HPD_LDAP_ instellingen. Controleer je .env of "
            "environment op verkeerd gespelde HPD_LDAP_* variabelen en op ongeldige "
            "waarden. Zie de logging voor details."
        )
        logger.error("%s Details: %s", msg, e)
        print(msg, file=sys.stderr)

    sys.exit(1)

logger.setLevel(settings.log_level.upper())

def verify_api_key(x_api_key: str | None = Header(default=None)):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Ongeldige API key.")

ALLOWED_ATTRS = [
    "uid", "objectClass", "cn", "sn", "givenName", "mail",
    "displayName", "telephoneNumber", "mobile", "title", "o", "ou",
]

# cache voor discovered base
_DISCOVERED_BASE: str | None = None

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            status_code = response.status_code if response is not None else 500
            logger.info(
                "req_id=%s method=%s path=%s status=%s",
                request_id,
                request.method,
                request.url.path,
                status_code,
            )
            if response is not None:
                response.headers["X-Request-ID"] = request_id

@asynccontextmanager
async def lifespan(app):
    startup()
    yield
    # SHUTDOWN (optioneel)
    # shutdown()

def startup():
    logger.info(
        "LDAP_URI=%s use_ssl=%s start_tls=%s connect_timeout=%ss receive_timeout=%ss base_dn=%s",
        settings.ldap_uri,
        settings.ldap_use_ssl,
        settings.ldap_start_tls,
        getattr(settings, "ldap_connect_timeout", "n/a"),
        settings.ldap_timeout,
        settings.ldap_base_dn,
    )
    if not settings.api_key:
        logger.warning(
            "HPD_LDAP_API_KEY is niet ingesteld; de service draait zonder API-beveiliging. "
            "Stel een sterke API key in voor productie."
        )
    if (settings.ldap_use_ssl or settings.ldap_start_tls) and not settings.ldap_verify_tls:
        logger.warning(
            "HPD_LDAP_VERIFY_TLS staat uit terwijl TLS is ingeschakeld (HPD_LDAP_USE_SSL of "
            "HPD_LDAP_START_TLS). Dit is onveilig voor productie; schakel certificaatvalidatie in."
        )
    if (settings.ldap_use_ssl or settings.ldap_start_tls) and settings.ldap_verify_tls and not settings.ldap_ca_certs_file:
        logger.warning(
            "HPD_LDAP_CA_CERTS_FILE is niet ingesteld terwijl TLS met certificaatvalidatie is "
            "ingeschakeld. Zorg voor een vertrouwde CA-bundel in productie."
        )
    if "*" in settings.allow_origins:
        logger.warning(
            "HPD_LDAP_ALLOW_ORIGINS bevat '*'. Beperk CORS-origins voor productie."
        )
    if "*" in settings.allowed_hosts:
        logger.warning(
            "HPD_LDAP_ALLOWED_HOSTS bevat '*'. Beperk toegestane hosts voor productie."
        )

app = FastAPI(
    title="HPD LDAP Proxy",
    version="1.2.0",
    description="HPD/ITI-58 stijl LDAP search via FastAPI, met JSON geschikt voor VBA-JSON."
)

app.router.lifespan_context = lifespan

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.allowed_hosts,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestIdMiddleware)


def _serve_html_page(path: Path) -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"HTML page not found: {path.name}")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@app.get("/ldap_zoek/", response_class=FileResponse, include_in_schema=False)
def ldap_zoek_page():
    return _serve_html_page(APP_ROOT / "ldap_zoek.html")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Onverwachte fout bij %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Interne serverfout. Neem contact op met de beheerder."},
    )

class SearchRequest(BaseModel):
    q: str = Field(..., description="Zoektekst, bv. 'bob'", max_length=64)
    scope: Literal["person", "org"] = "person"
    limit: int = Field(default=settings.default_size_limit, ge=1, le=500)

class HpdEntry(BaseModel):
    uid: List[str] = []
    objectClass: List[str] = []
    cn: List[str] = []
    sn: List[str] = []
    givenName: List[str] = []
    mail: List[str] = []
    displayName: List[str] = []
    telephoneNumber: List[str] = []
    mobile: List[str] = []
    title: List[str] = []
    o: List[str] = []
    ou: List[str] = []
    dn: str = ""

class SearchResponse(BaseModel):
    count: int
    items: List[HpdEntry]

def _normalize_ldap_uri(uri: str, use_ssl: bool) -> str:
    uri = uri.strip()
    if "://" not in uri:
        uri = ("ldaps://" if use_ssl else "ldap://") + uri
    if use_ssl and uri.lower().startswith("ldap://"):
        uri = "ldaps://" + uri[len("ldap://"):]
    return uri

def _create_client(use_ssl: bool | None = None, start_tls: bool | None = None) -> LDAPClient:
    eff_ssl = settings.ldap_use_ssl if use_ssl is None else use_ssl
    eff_tls = settings.ldap_start_tls if start_tls is None else start_tls
    uri = _normalize_ldap_uri(settings.ldap_uri, eff_ssl)
    client = LDAPClient(uri, eff_tls)
    if eff_ssl or eff_tls:
        client.set_cert_policy("demand" if settings.ldap_verify_tls else "never")
        if settings.ldap_ca_certs_file:
            client.set_ca_cert(settings.ldap_ca_certs_file)
    return client

def _connect():
    eff_use_ssl = settings.ldap_use_ssl
    eff_start_tls = settings.ldap_start_tls
    uri_raw = settings.ldap_uri.strip()
    if eff_start_tls and uri_raw.lower().startswith("ldaps://"):
        logger.warning(
            "LDAP configuratie: ldap_start_tls staat op True maar HPD_LDAP_URI gebruikt al ldaps://. "
            "StartTLS is dan niet van toepassing; StartTLS wordt genegeerd."
        )
        eff_start_tls = False
    if eff_use_ssl and eff_start_tls:
        logger.warning(
            "LDAP configuratie: zowel ldap_use_ssl als ldap_start_tls staan op True. "
            "Dit is geen geldige combinatie; er wordt nu alleen StartTLS gebruikt "
            "(ldap_use_ssl wordt genegeerd)."
        )
        eff_use_ssl = False
        eff_start_tls = True

    client = _create_client(use_ssl=eff_use_ssl, start_tls=eff_start_tls)

    try:
        # Bepaal of we base DN nodig hebben om de bind DN op te bouwen (placeholder of RDN)
        needs_base_for_bind = settings.ldap_bind_dn and (
            "{base}" in settings.ldap_bind_dn or "," not in settings.ldap_bind_dn
        )
        needs_discovery = settings.ldap_base_dn.lower() == "auto"

        if needs_discovery and needs_base_for_bind and not _DISCOVERED_BASE:
            # Anonieme connectie voor RootDSE discovery (alleen nodig om bind DN op te bouwen)
            anon_conn = client.connect(timeout=settings.ldap_connect_timeout)
            try:
                _resolve_base_root(anon_conn)
            finally:
                anon_conn.close()

        # Bind DN oplossen
        eff_dn = None
        if settings.ldap_bind_dn:
            if needs_base_for_bind:
                base_root = _resolve_base_root_cached()
                eff_dn = _effective_bind_dn(base_root)
            else:
                eff_dn = settings.ldap_bind_dn

        if eff_dn:
            client.set_credentials("SIMPLE", user=eff_dn, password=settings.ldap_bind_password or "")

        conn = client.connect(timeout=settings.ldap_connect_timeout)
        return conn

    except LDAPAuthenticationError as e:
        logger.error("LDAP bind mislukt op %s: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=502, detail="LDAP bind is mislukt; controleer instellingen/credentials.") from e
    except LDAPConnectionError as e:
        logger.error("LDAP connectie naar %s faalde: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=503, detail="LDAP server niet bereikbaar.") from e
    except LDAPError as e:
        logger.error("LDAP fout naar %s: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=502, detail="LDAP fout bij verbinden.") from e
    except OSError as e:
        # Afvangen van b.v. ConnectionRefusedError, timeout, etc.
        logger.error("LDAP netwerkfout naar %s: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=503, detail="LDAP server niet bereikbaar.") from e

def _discover_base_dn(conn) -> str | None:
    """bepaal root via RootDSE wanneer LDAP_BASE_DN=auto."""
    results = conn.search("", LDAPSearchScope.BASE, "(objectClass=*)", attrlist=["namingContexts"], timeout=settings.ldap_timeout, sizelimit=1)
    if not results:
        return None
    vals = [str(v) for v in results[0].get("namingContexts", [])]
    if not vals:
        return None
    # meerdere contexts? log en kies dc=HPD als die aanwezig is, anders de eerste
    if len(vals) > 1:
        choice = None
        for v in vals:
            if v.lower() == "dc=hpD".lower():
                choice = v
                break
        choice = choice or vals[0]
        logger.info("RootDSE multiple namingContexts: %s -> gekozen: %s", vals, choice)
        return choice
    else:
        logger.info("RootDSE namingContexts -> %s", vals[0])
        return vals[0]

def _resolve_base_root(conn) -> str:
    global _DISCOVERED_BASE
    # gebruik discovery alleen als LDAP_BASE_DN=auto
    if settings.ldap_base_dn and settings.ldap_base_dn.lower() != "auto":
        return settings.ldap_base_dn
    if not _DISCOVERED_BASE:
        _DISCOVERED_BASE = _discover_base_dn(conn)
        if not _DISCOVERED_BASE:
            raise HTTPException(status_code=502, detail="Kon namingContexts (root) niet bepalen.")
    return _DISCOVERED_BASE

def _resolve_base_root_cached() -> str:
    """Geeft de base DN terug zonder connectie (moet al ontdekt zijn of statisch geconfigureerd)."""
    if settings.ldap_base_dn and settings.ldap_base_dn.lower() != "auto":
        return settings.ldap_base_dn
    if _DISCOVERED_BASE:
        return _DISCOVERED_BASE
    raise HTTPException(status_code=502, detail="Kon namingContexts (root) niet bepalen.")

def _escape_ldap_filter(value: str) -> str:
    """Escape speciale tekens voor LDAP filter (RFC 4515)."""
    return (value
            .replace("\\", "\\5c")
            .replace("*", "\\2a")
            .replace("(", "\\28")
            .replace(")", "\\29")
            .replace("\x00", "\\00"))

def _make_filter(q: str, scope: str) -> str:
    s = _escape_ldap_filter((q or "").strip())
    # Lege zoekterm? -> geen substringdeel; lijst gewoon de eerste N binnen de OU
    if not s:
        return "(&(objectClass=inetOrgPerson))" if scope == "person" else "(objectClass=*)"
    if scope == "person":
        return f"(&(objectClass=inetOrgPerson)(|(cn=*{s}*)(sn=*{s}*)(givenName=*{s}*)(mail=*{s}*)))"
    return f"(&(objectClass=*)(|(o=*{s}*)(ou=*{s}*)(cn=*{s}*)(mail=*{s}*)))"

def _ldap_entry_to_model(entry) -> HpdEntry:
    out_dict = {}
    for a in ALLOWED_ATTRS:
        val = entry.get(a)
        if val is None:
            out_dict[a] = []
        elif isinstance(val, list):
            out_dict[a] = [str(x) for x in val if x is not None]
        else:
            out_dict[a] = [str(val)]
    return HpdEntry(dn=str(entry.dn), **out_dict)

def _effective_bind_dn(base_dn: str) -> str | None:
    dn = settings.ldap_bind_dn
    if not dn:
        return None  # anonieme bind
    # {base} placeholder
    if "{base}" in dn:
        return dn.replace("{base}", base_dn)
    # RDN zonder komma? (bv. "cn=readonly")
    if "," not in dn:
        return f"{dn},{base_dn}"
    # Volledige DN zoals opgegeven
    return dn

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/hpd/search", response_model=SearchResponse, dependencies=[Depends(verify_api_key)])
def hpd_search(req: SearchRequest):
    conn = None
    try:
        conn = _connect()

        # root automatisch bepalen indien gevraagd
        base_root = _resolve_base_root(conn)
        # OU opbouwen met gevonden root
        if req.scope == "person":
            base_dn = f"ou=HCProfessional,{base_root}"
        else:
            base_dn = f"ou=HCRegulatedOrganization,{base_root}"

        # OU existence check (404 + LDIF-hint)
        try:
            ou_check = conn.search(base_dn, LDAPSearchScope.BASE, "(objectClass=*)", attrlist=["objectClass"], timeout=settings.ldap_timeout, sizelimit=1)
        except LDAPNoSuchObjectError:
            logger.warning("LDAP OU ontbreekt: %s", base_dn)
            return SearchResponse(count=0, items=[])
        if not ou_check:
            logger.warning("LDAP OU ontbreekt: %s", base_dn)
            return SearchResponse(count=0, items=[])

        ldap_filter = _make_filter(req.q, req.scope)
        results = conn.search(base_dn, LDAPSearchScope.SUBTREE, ldap_filter, attrlist=ALLOWED_ATTRS, timeout=settings.ldap_timeout, sizelimit=req.limit)
        items = [_ldap_entry_to_model(e) for e in results]
        return SearchResponse(count=len(items), items=items)
    finally:
        try:
            if conn:
                conn.close()
        except Exception as e:
            logger.debug("LDAP close gaf een uitzondering: %r", e)
            pass

@app.get("/hpd/search", response_model=SearchResponse, dependencies=[Depends(verify_api_key)])
def hpd_search_get(
    q: str = Query(..., max_length=64),
    scope: Literal["person", "org"] = "person",
    limit: int = Query(settings.default_size_limit, ge=1, le=500),
):
    req = SearchRequest(q=q, scope=scope, limit=limit)
    return hpd_search(req)
