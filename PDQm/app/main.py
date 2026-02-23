from __future__ import annotations

from typing import List
from datetime import date
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
# --- begin minimal shim (before importing sqlalchemy_pytds) ---
# this is needed so sqlalchemy_pytds can find pytds.tds_session
import sys, types
import pytds
from pytds import tds as _tds
m = types.ModuleType("pytds.tds_session")
m._token_map = getattr(_tds, "_token_map", {})
sys.modules["pytds.tds_session"] = m
# --- end minimal shim ---

# your existing imports can follow freely now
import sqlalchemy_pytds  # will now find pytds.tds_session

from sqlalchemy import select, or_, and_, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from .db import init_db, SessionLocal
from .models import PatientModel
from .fhir_utils import (
    wants_xml,
    op_outcome,
    bundle_from_rows,
    to_patient_resource,
    minimal_capability_statement,
)
from fhir.resources.R4B.patient import Patient
from .pdqm_where import _parse_fhir_date_bounds


# --- local minimal patient renderer for tests ---
FHIR_MMN_URL = "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"

def _to_patient_resource_fixed(row):
    # Basis
    out = {
        "resourceType": "Patient",
        "id": str(row.id),
    }

    # identifier → lijst; support "system|value" of alleen "value"
    ident = getattr(row, "identifier", None)
    if ident:
        if "|" in ident:
            system, value = ident.split("|", 1)
            out["identifier"] = [{"system": system.strip(), "value": value.strip()}]
        else:
            out["identifier"] = [{"value": ident.strip()}]

    # name → exact volgens test: use=official, family, given[0], text
    family = getattr(row, "name_family", None)
    given0 = getattr(row, "name_given_0", None)
    name_text = getattr(row, "name_text", None)

    name_block = {"use": "official", "family": family, "given": [given0] if given0 else []}
    # Belangrijk: gebruik de DB-tekst als die aanwezig is
    if name_text:
        name_block["text"] = name_text
    else:
        prefix = getattr(row, "name_prefix_0", None)
        parts = [prefix, (given0.title() if isinstance(given0, str) else given0),
                 (family.title() if isinstance(family, str) else family)]
        name_block["text"] = " ".join(p for p in parts if p)
    out["name"] = [name_block]

    # gender/birthdate indien aanwezig
    if getattr(row, "gender", None):
        out["gender"] = row.gender
    if getattr(row, "birthdate", None):
        out["birthDate"] = row.birthdate.isoformat()

    # address indien aanwezig
    addr = {}
    if getattr(row, "address_use", None): addr["use"] = row.address_use
    if getattr(row, "address_line_0", None): addr["line"] = [row.address_line_0]
    if getattr(row, "address_city", None): addr["city"] = row.address_city
    if getattr(row, "address_postalCode", None): addr["postalCode"] = row.address_postalCode
    if getattr(row, "address_country", None): addr["country"] = row.address_country
    if addr:
        out["address"] = [addr]

    # telecom (optioneel)
    tel = []
    if getattr(row, "tel_home", None): tel.append({"system": "phone", "use": "home", "value": row.tel_home})
    if getattr(row, "tel_work", None): tel.append({"system": "phone", "use": "work", "value": row.tel_work})
    if getattr(row, "tel_mobile", None): tel.append({"system": "phone", "use": "mobile", "value": row.tel_mobile})
    if getattr(row, "email", None): tel.append({"system": "email", "value": row.email})
    if tel:
        out["telecom"] = tel

    code = getattr(row, "marital_code", None)
    if code:
        # HL7 v3 MaritalStatus
        display_map = {
            "A": "Annulled", "D": "Divorced", "I": "Interlocutory",
            "L": "Legally Separated", "M": "Married", "P": "Polygamous",
            "S": "Never Married", "T": "Domestic partner", "U": "Unmarried",
            "W": "Widowed"
        }
        out["maritalStatus"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
                "code": code,
                "display": display_map.get(code)
            }]
        }

    # moeder’s meisjesnaam-extensie: alleen toevoegen als er een waarde is
    mmn = getattr(row, "mothersMaidenName", None)
    if mmn:
        out["extension"] = [{"url": FHIR_MMN_URL, "valueString": mmn}]

    patient = Patient(**out)
    if hasattr(patient, "model_dump"):
        return patient.model_dump(by_alias=True, exclude_none=True)
    return patient.dict(by_alias=True, exclude_none=True)

# --- end local minimal patient renderer ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize schema and seed demo data on startup (SQLite by default)."""
    # Only initialize/seed when running on SQLite. If the dialect is SQL Server (mssql), skip.
    logger = logging.getLogger("uvicorn.error")
    try:
        with SessionLocal() as s:
            bind = s.get_bind()
            dialect = getattr(bind.dialect, "name", "")
            url = getattr(bind, "url", None)

            logger.info("Effective SQLAlchemy dialect: %s (url=%s)", dialect, url)

            if dialect == "sqlite":
                logger.info("Using built-in SQLite database")
                init_db(seed=True)
            elif dialect == "mssql":
                logger.info("Using SQL Server database")
            else:
                logger.info("Using database dialect '%s'", dialect or "unknown")
    except Exception as exc:
        logger.warning("Could not determine database dialect on startup: %r", exc)
    yield

app = FastAPI(
    title="PDQm Minimal Server (Python/FastAPI) – Real Schema",
    lifespan=lifespan
)


def _serve_html_page(path: Path) -> FileResponse:
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"HTML page not found: {path.name}",
        )
    return FileResponse(path, media_type="text/html; charset=utf-8")


@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError):
    """Geef een nette foutmelding terug als de database niet bereikbaar is."""
    logger = logging.getLogger("uvicorn.error")
    detail = str(getattr(exc, "orig", exc))
    logger.error("Database-operatie mislukt: %s", detail)

    # Geef een FHIR OperationOutcome terug met een neutrale melding
    outcome = op_outcome(
        "error",
        "Databasefout bij het benaderen van de PDQm-database. Controleer of de SQL Server database online en bereikbaar is.",
        code="exception",
    )

    return JSONResponse(status_code=500, content=outcome)

@app.exception_handler(OSError)
async def os_error_handler(request: Request, exc: OSError):
    """Vang Host-is-down / socket fouten netjes af."""
    logger = logging.getLogger("uvicorn.error")
    logger.error("OS-fout bij het benaderen van de database: %s: %s", type(exc).__name__, exc)

    outcome = op_outcome(
        "error",
        "Databasefout bij het benaderen van de PDQm-database. Controleer of de SQL Server database online en bereikbaar is.",
        code="exception",
    )

    return JSONResponse(status_code=500, content=outcome)

# -----------------------------
# Database session dependency
# -----------------------------
def get_db():
    """Provide a SQLAlchemy session per request."""
    with SessionLocal() as s:
        yield s


# -----------------------------
# Parameter parsing utilities
# -----------------------------
def _split_or_list(value: str) -> List[str]:
    """
    Split a comma-separated value into tokens used for OR semantics within a single parameter.
    Example: "SMI,SMY" -> ["SMI", "SMY"]
    """
    return [v for v in (value or "").split(",") if v != ""]


def _param_values(request: Request, name: str) -> List[str]:
    """
    Return all occurrences of a query parameter (repeats allowed).
    Repeated parameters represent AND semantics per FHIR search rules.
    """
    return request.query_params.getlist(name)


def _param_values_with_modifier(request: Request, base: str) -> List[tuple[str, str]]:
    """
    Return [(name, value)] for a parameter where the name can include a modifier.
    Example: ("family", "SMI"), ("family:exact", "SMITH")
    """
    out: List[tuple[str, str]] = []
    for k, v in request.query_params.multi_items():
        if k == base or k.startswith(base + ":"):
            out.append((k, v))
    return out


def _parse_date_with_prefix(s: str):
    """
    Parse FHIR date prefixes: ge, le, gt, lt, eq(default).
    Returns (prefix, date_string).
    """
    if len(s) >= 2 and s[:2] in ("ge", "le", "gt", "lt"):
        return s[:2], s[2:]
    return "eq", s


# -----------------------------
# Endpoints
# -----------------------------
@app.get("/fhir/metadata")
def metadata(request: Request):
    """
    Minimal CapabilityStatement.
    PDQm requires JSON and XML; this PoC returns 406 for XML until implemented.
    """
    if wants_xml(request):
        # Placeholder: PDQm requires XML support. We return 406 + OperationOutcome for now.
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content=op_outcome("error", "XML not yet supported; use application/fhir+json."),
        )
    return minimal_capability_statement(str(request.base_url)).copy()


@app.get("/fhir/Patient")
def patient_search(request: Request, db: Session = Depends(get_db)):
    """
    PDQm-compliant-ish Patient search for the given schema.
    - AND semantics across repeated parameters (e.g., &family=SMI&family=SMY).
    - OR semantics within a single parameter using comma lists (family=SMI,SMY).
    - identifier token parsing (system|value) against a single 'identifier' column.
    - paging via _count and _page, plus Bundle.link[next].
    """
    # Content negotiation: JSON only for now. PDQm later requires XML as well.
    if wants_xml(request):
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content=op_outcome("error", "XML not yet supported; use application/fhir+json."),
        )

    qp = request.query_params

    # Paging bounds
    try:
        count = int(qp.get("_count", "20"))
        if count < 1:
            count = 1
        if count > 100:
            count = 100
    except ValueError:
        count = 20

    try:
        page = int(qp.get("_page", "1"))
        if page < 1:
            page = 1
    except ValueError:
        page = 1

    # Build WHERE with SQLAlchemy filters
    filters = []

    # _id (FHIR id). Repeats = AND; commas within one occurrence = OR.
    for v in _param_values(request, "_id"):
        ors = [PatientModel.id == x for x in _split_or_list(v)]
        if ors:
            filters.append(or_(*ors))

    # gender (token) with case-insensitive equality
    for v in _param_values(request, "gender"):
        ors = [func.lower(PatientModel.gender) == x.strip().lower() for x in _split_or_list(v)]
        if ors:
            filters.append(or_(*ors))

    # family (string). Support :exact modifier; default is starts-with (case-insensitive).
    fam_params = _param_values_with_modifier(request, "family")
    for name, v in fam_params:
        exact = name.endswith(":exact")
        ors = []
        for token in _split_or_list(v):
            if exact:
                ors.append(func.lower(PatientModel.name_family) == token.lower())
            else:
                ors.append(func.lower(PatientModel.name_family).like(f"{token.lower()}%"))
        if ors:
            filters.append(or_(*ors))

    # given (string) with :exact support like family (uses name_given_0)
    giv_params = _param_values_with_modifier(request, "given")
    for name, v in giv_params:
        exact = name.endswith(":exact")
        ors = []
        for token in _split_or_list(v):
            if exact:
                ors.append(func.lower(PatientModel.name_given_0) == token.lower())
            else:
                ors.append(func.lower(PatientModel.name_given_0).like(f"{token.lower()}%"))
        if ors:
            filters.append(or_(*ors))

    # address (broad starts-with across line/city/postal/country); support :exact
    addr_params = _param_values_with_modifier(request, "address")
    for name, v in addr_params:
        exact = name.endswith(":exact")
        ors = []
        for token in _split_or_list(v):
            t = token.lower()
            if exact:
                ors.extend(
                    [
                        func.lower(PatientModel.address_line_0) == t,
                        func.lower(PatientModel.address_city) == t,
                        func.lower(PatientModel.address_postalCode) == t,
                        func.lower(PatientModel.address_country) == t,
                    ]
                )
            else:
                ors.extend(
                    [
                        func.lower(PatientModel.address_line_0).like(f"{t}%"),
                        func.lower(PatientModel.address_city).like(f"{t}%"),
                        func.lower(PatientModel.address_postalCode).like(f"{t}%"),
                        func.lower(PatientModel.address_country).like(f"{t}%"),
                    ]
                )
        if ors:
            filters.append(or_(*ors))

    # address-* specific fields; support :exact
    for field, pname in [
        (PatientModel.address_city, "address-city"),
        (PatientModel.address_postalCode, "address-postalcode"),
        (PatientModel.address_country, "address-country"),
    ]:
        params = _param_values_with_modifier(request, pname)
        for name, v in params:
            exact = name.endswith(":exact")
            if exact:
                ors = [func.lower(field) == t.lower() for t in _split_or_list(v)]
            else:
                ors = [func.lower(field).like(f"{t.lower()}%") for t in _split_or_list(v)]
            if ors:
                filters.append(or_(*ors))

    # telecom (token system|value). We support:
    #   phone|* → match any of tel_home/tel_work/tel_mobile
    #   email|* → match email
    #   no system → match value against all of the above
    for v in _param_values(request, "telecom"):
        or_group = []
        for token in _split_or_list(v):
            if "|" in token:
                system, value = token.split("|", 1)
                system = system.strip().lower()
                value = value.strip().lower()
                if system == "phone":
                    or_group.extend([
                        func.lower(PatientModel.tel_home).like(f"%{value}%"),
                        func.lower(PatientModel.tel_work).like(f"%{value}%"),
                        func.lower(PatientModel.tel_mobile).like(f"%{value}%"),
                    ])
                elif system == "email":
                    or_group.append(func.lower(PatientModel.email).like(f"%{value}%"))
            else:
                t = token.strip().lower()
                or_group.extend([
                    func.lower(PatientModel.tel_home).like(f"%{t}%"),
                    func.lower(PatientModel.tel_work).like(f"%{t}%"),
                    func.lower(PatientModel.tel_mobile).like(f"%{t}%"),
                    func.lower(PatientModel.email).like(f"%{t}%"),
                ])
        if or_group:
            filters.append(or_(*or_group))

    # identifier (token): our schema has a single text column 'identifier' which may be either
    # a bare value or 'system|value'.
    #   - Als er system(s)|value(s) staat → alleen exacte "system|value" combinaties.
    #   - Als er system(s)| (zonder value) staat → identifiers die beginnen met "system|".
    #   - Zonder system (alleen value) → bare value of een "system|value".
    for v in _param_values(request, "identifier"):
        or_group = []
        if "|" in v:
            left, right = v.split("|", 1)
            systems = [s.strip().lower() for s in left.split(",") if s.strip()]
            values = [x.strip().lower() for x in right.split(",") if x.strip()]
            if values:
                if systems:
                    for val in values:
                        for sys in systems:
                            or_group.append(func.lower(PatientModel.identifier) == f"{sys}|{val}")
                else:
                    # geen system → match bare value of elke "system|value"
                    for val in values:
                        or_group.append(func.lower(PatientModel.identifier) == val)
                        or_group.append(func.lower(PatientModel.identifier).like(f"%|{val}"))
            else:
                # domain‑only filter: system(s)| → alles wat met "system|" begint
                if systems:
                    for sys in systems:
                        or_group.append(func.lower(PatientModel.identifier).like(f"{sys}|%"))
        else:
            values = [x.strip().lower() for x in v.split(",") if x.strip()]
            for val in values:
                or_group.append(func.lower(PatientModel.identifier) == val)
                or_group.append(func.lower(PatientModel.identifier).like(f"%|{val}"))
        if or_group:
            filters.append(or_(*or_group))

    # birthdate: support eq(default), ge, le, gt, lt with FHIR partial dates (YYYY, YYYY-MM, YYYY-MM-DD)
    for v in _param_values(request, "birthdate"):
        prefix, datestr = _parse_date_with_prefix(v.strip())
        try:
            start, end = _parse_fhir_date_bounds(datestr)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=op_outcome("error", f"Invalid birthdate: {v}", code="invalid"),
            )
        if prefix == "eq":
            filters.append(and_(PatientModel.birthdate >= start, PatientModel.birthdate < end))
        elif prefix == "ge":
            filters.append(PatientModel.birthdate >= start)
        elif prefix == "le":
            filters.append(PatientModel.birthdate < end)
        elif prefix == "gt":
            filters.append(PatientModel.birthdate >= end)
        elif prefix == "lt":
            filters.append(PatientModel.birthdate < start)

    # Build the main SELECT with filters and stable ordering for deterministic paging
    stmt = select(PatientModel)
    if filters:
        stmt = stmt.where(and_(*filters))
    # Deterministic order: by id
    stmt = stmt.order_by(PatientModel.id).offset((page - 1) * count).limit(count)
    rows = db.execute(stmt).scalars().all()

    # Compute total = COUNT(*) with the same filters for Bundle.total
    total_stmt = select(func.count()).select_from(PatientModel)
    if filters:
        total_stmt = total_stmt.where(and_(*filters))
    total = int(db.execute(total_stmt).scalar() or 0)

    # Return a FHIR searchset Bundle with self/next links
    base_url = str(request.base_url).rstrip("/")
    self_url = f"{base_url}{request.url.path}"
    if request.query_params:
        self_url = f"{self_url}?{request.query_params}"
 
    entries = [{"fullUrl": f"{base_url}/fhir/Patient/{r.id}", "resource": _to_patient_resource_fixed(r)} for r in rows]
 
    links = [{"relation": "self", "url": self_url}]
    if (page - 1) * count + len(rows) < total:
        from urllib.parse import urlencode
        qp = dict(request.query_params.multi_items())
        qp["_page"] = str(page + 1)
        qp["_count"] = str(count)
        links.append({"relation": "next", "url": f"{base_url}{request.url.path}?{urlencode(qp, doseq=True)}"})
 
    bundle = {"resourceType": "Bundle", "type": "searchset", "total": total, "link": links}
    if entries:
        bundle["entry"] = entries

    return bundle


@app.post("/fhir/Patient/_search")
async def patient_search_post(request: Request, db: Session = Depends(get_db)):
    """
    PDQm POST-based search with application/x-www-form-urlencoded body.
    Per FHIR spec, this returns a Bundle (not a redirect), with self link as GET.
    """
    if wants_xml(request):
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content=op_outcome("error", "XML not yet supported; use application/fhir+json."),
        )

    form = await request.form()

    # Build query string from form parameters for the self link
    from urllib.parse import urlencode
    from starlette.datastructures import QueryParams

    query_pairs = []
    for k in form.keys():
        vals = form.getlist(k)
        for v in vals:
            query_pairs.append((k, v))

    # Ensure defaults for _page and _count if not provided
    if not any(k == "_page" for k, _ in query_pairs):
        query_pairs.append(("_page", "1"))
    if not any(k == "_count" for k, _ in query_pairs):
        query_pairs.append(("_count", "20"))

    # Create a synthetic query string and modify request to have these params
    query_string = urlencode(query_pairs, doseq=True)

    # Create a new Request-like object with query params from form
    # We do this by creating a new scope with the query string
    scope = dict(request.scope)
    scope["query_string"] = query_string.encode()
    scope["path"] = "/fhir/Patient"  # Change path from /_search to base

    # Create new request with modified scope
    synthetic_request = Request(scope, request.receive)

    # Call the GET search endpoint logic directly
    return patient_search(synthetic_request, db)


@app.get("/fhir/Patient/{id}")
def patient_read(id: str, request: Request, db: Session = Depends(get_db)):
    """
    PDQm requires read interaction for Patient.
    """
    if wants_xml(request):
        return JSONResponse(
            status_code=status.HTTP_406_NOT_ACCEPTABLE,
            content=op_outcome("error", "XML not yet supported; use application/fhir+json."),
        )

    row = db.get(PatientModel, id)
    if not row:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=op_outcome("error", f"Patient {id} not found", code="not-found"),
        )
    return _to_patient_resource_fixed(row)
