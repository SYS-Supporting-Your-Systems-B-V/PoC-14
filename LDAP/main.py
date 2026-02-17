from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from ldap3 import Server, Connection, ALL, NONE, SUBTREE, BASE, Tls  # BASE toegevoegd
from ldap3.core.exceptions import LDAPSocketOpenError, LDAPStartTLSError, LDAPSessionTerminatedByServerError
from ldap3.utils.conv import escape_filter_chars
from typing import List, Literal
import ssl
import sys
import logging
import uuid

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

def _server(use_ssl: bool | None = None) -> Server:
    tls = None
    if settings.ldap_use_ssl or settings.ldap_start_tls:
        tls = Tls(
            validate=ssl.CERT_REQUIRED if settings.ldap_verify_tls else ssl.CERT_NONE,
            version=ssl.PROTOCOL_TLS_CLIENT,
            ca_certs_file=settings.ldap_ca_certs_file,
        )
    eff_use_ssl = settings.ldap_use_ssl if use_ssl is None else use_ssl
    return Server(settings.ldap_uri, use_ssl=eff_use_ssl, get_info=NONE, tls=tls, connect_timeout=settings.ldap_connect_timeout)

def _connect() -> Connection:
    eff_use_ssl = settings.ldap_use_ssl
    eff_start_tls = settings.ldap_start_tls
    if settings.ldap_use_ssl and settings.ldap_start_tls:
        logger.warning(
            "LDAP configuratie: zowel ldap_use_ssl als ldap_start_tls staan op True. "
            "Dit is geen geldige combinatie; er wordt nu alleen StartTLS gebruikt "
            "(ldap_use_ssl wordt genegeerd)."
        )
        eff_use_ssl = False
        eff_start_tls = True

    srv = _server(use_ssl=eff_use_ssl)
    try:
        conn = Connection(srv, user=settings.ldap_bind_dn, password=settings.ldap_bind_password, receive_timeout=settings.ldap_timeout, auto_bind=False)

        # Optioneel StartTLS
        if eff_start_tls:
            try:
                if not conn.start_tls():
                    logger.error("LDAP StartTLS mislukt op %s", settings.ldap_uri)
                    raise HTTPException(status_code=502, detail="StartTLS is mislukt bij LDAP-server.")
            except LDAPStartTLSError as e:
                logger.error("LDAP StartTLS mislukt naar %s: %r", settings.ldap_uri, e)
                raise HTTPException(status_code=502, detail="LDAP StartTLS is mislukt.") from e               
            except LDAPSessionTerminatedByServerError as e:
                logger.error("LDAP StartTLS sessie afgebroken door server %s: %r", settings.ldap_uri, e)
                raise HTTPException(status_code=502, detail="LDAP-server heeft de sessie afgebroken tijdens StartTLS. Controleer of StartTLS is ingeschakeld en of je de juiste poort/protocol gebruikt.") from e

        # Bind opent de connectie indien nodig
        eff_dn = _effective_bind_dn(conn)
        if eff_dn:
            if not conn.rebind(user=eff_dn, password=settings.ldap_bind_password):
                logger.error("LDAP bind mislukt op %s", settings.ldap_uri)
                raise HTTPException(status_code=502, detail="LDAP bind is mislukt; controleer instellingen/credentials.")
        else:
            # Anonieme bind
            if not conn.bind():
                logger.error("LDAP anonieme bind mislukt op %s", settings.ldap_uri)
                raise HTTPException(status_code=502, detail="LDAP anonieme bind is mislukt.")

        return conn

    except LDAPSocketOpenError as e:
        # Nettere fout bij Connection refused / unreachable
        logger.error("LDAP connectie naar %s faalde: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=503, detail="LDAP server niet bereikbaar.") from e
    except LDAPSessionTerminatedByServerError as e:
        logger.error("LDAP sessie afgebroken door server tijdens StartTLS of bind op %s: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=502, detail="LDAP-server heeft de sessie onverwacht afgebroken tijdens StartTLS of bind, controleer of je de juiste poort/protocol (LDAP/LDAPS, StartTLS) en TLS-instellingen gebruikt.") from e
    except OSError as e:
        # Afvangen van b.v. ConnectionRefusedError, timeout, etc.
        logger.error("LDAP netwerkfout naar %s: %r", settings.ldap_uri, e)
        raise HTTPException(status_code=503, detail="LDAP netwerkfout.") from e

def _discover_base_dn(conn: Connection) -> str | None:
    """bepaal root via RootDSE wanneer LDAP_BASE_DN=auto."""
    ok = conn.search(search_base="", search_filter="(objectClass=*)", search_scope=BASE, attributes=["namingContexts"], size_limit=1)
    if not ok or not conn.entries:
        return None
    vals = []
    if "namingContexts" in conn.entries[0]:
        vals = [str(v) for v in conn.entries[0]["namingContexts"].values]
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

def _resolve_base_root(conn: Connection) -> str:
    global _DISCOVERED_BASE
    # gebruik discovery alleen als LDAP_BASE_DN=auto
    if settings.ldap_base_dn and settings.ldap_base_dn.lower() != "auto":
        return settings.ldap_base_dn
    if not _DISCOVERED_BASE:
        _DISCOVERED_BASE = _discover_base_dn(conn)
        if not _DISCOVERED_BASE:
            raise HTTPException(status_code=502, detail="Kon namingContexts (root) niet bepalen.")
    return _DISCOVERED_BASE

def _make_filter(q: str, scope: str) -> str:
    s = escape_filter_chars((q or "").strip(), encoding="utf-8")
    # Lege zoekterm? -> geen substringdeel; lijst gewoon de eerste N binnen de OU
    if not s:
        return "(&(objectClass=inetOrgPerson))" if scope == "person" else "(objectClass=*)"
    if scope == "person":
        return f"(&(objectClass=inetOrgPerson)(|(cn=*{s}*)(sn=*{s}*)(givenName=*{s}*)(mail=*{s}*)))"
    return f"(&(objectClass=*)(|(o=*{s}*)(ou=*{s}*)(cn=*{s}*)(mail=*{s}*)))"

def _ldap_entry_to_model(entry) -> HpdEntry:
    d = entry.entry_attributes_as_dict
    out_dict = {}
    for a in ALLOWED_ATTRS:
        val = d.get(a)
        if val is None:
            out_dict[a] = []
        elif isinstance(val, list):
            out_dict[a] = [str(x) for x in val if x is not None]
        else:
            out_dict[a] = [str(val)]
    return HpdEntry(dn=entry.entry_dn, **out_dict)

def _effective_bind_dn(conn: Connection) -> str | None:
    dn = settings.ldap_bind_dn
    if not dn:
        return None  # anonieme bind
    # {base} placeholder
    if "{base}" in dn:
        base = _resolve_base_root(conn)  # gebruikt discovery als LDAP_BASE_DN=auto
        return dn.replace("{base}", base)
    # RDN zonder komma? (bv. "cn=readonly")
    if "," not in dn:
        base = _resolve_base_root(conn)
        return f"{dn},{base}"
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
        ou_exists = conn.search(search_base=base_dn, search_filter="(objectClass=*)", search_scope=BASE, attributes=["objectClass"], size_limit=1)
        if not ou_exists or not conn.entries:
            logger.warning("LDAP OU ontbreekt: %s", base_dn)
            return SearchResponse(count=0, items=[])

        ldap_filter = _make_filter(req.q, req.scope)
        ok = conn.search(search_base=base_dn, search_filter=ldap_filter, search_scope=SUBTREE, attributes=ALLOWED_ATTRS, size_limit=req.limit)
        if not ok:
            return SearchResponse(count=0, items=[])
        items = [_ldap_entry_to_model(e) for e in conn.entries]
        return SearchResponse(count=len(items), items=items)
    finally:
        try:
            if conn:
                conn.unbind()
        except Exception as e:
            logger.debug("LDAP unbind gaf een uitzondering: %r", e)
            pass

@app.get("/hpd/search", response_model=SearchResponse, dependencies=[Depends(verify_api_key)])
def hpd_search_get(q: str, scope: Literal["person", "org"] = "person", limit: int = settings.default_size_limit):
    req = SearchRequest(q=q, scope=scope, limit=limit)
    return hpd_search(req)
