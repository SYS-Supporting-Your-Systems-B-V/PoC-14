from __future__ import annotations
from typing import Any, Dict, Iterable, List
from urllib.parse import urlencode
from fastapi import Request
from fhir.resources.R4B.patient import Patient
from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleLink
from fhir.resources.R4B.operationoutcome import OperationOutcome, OperationOutcomeIssue

FHIR_JSON = "application/fhir+json"
FHIR_XML  = "application/fhir+xml"

def wants_xml(request: Request) -> bool:
    fmt = request.query_params.get("_format", "").lower()
    if "xml" in fmt:
        return True
    accept = request.headers.get("accept", "")
    return FHIR_XML in accept or "application/xml" in accept

def op_outcome(status: str, details: str, code: str = "not-supported") -> Dict[str, Any]:
    oo = OperationOutcome.construct(
        issue=[OperationOutcomeIssue.construct(
            severity="error", code=code, diagnostics=details
        )]
    )
    return oo.dict()

def _identifier_obj(identifier: str | None) -> List[Dict[str, Any]]:
    """
    Build a FHIR Identifier array from the single column 'identifier'.
    The column may contain either just a value, or 'system|value'.
    """
    if not identifier:
        return []
    if "|" in identifier:
        system, value = identifier.split("|", 1)
        system = system.strip()
        value = value.strip()
        return [{"system": system, "value": value}] if value else []
    return [{"value": identifier.strip()}] if identifier.strip() else []

def _name_obj(row) -> List[Dict[str, Any]]:
    parts = {
        "family": row.name_family,
        "given": [row.name_given_0] if row.name_given_0 else [],
        "prefix": [row.name_prefix_0] if row.name_prefix_0 else [],
        "text": row.name_text,
        "use": "official"
    }
    # Remove empty arrays/None keys
    return [{k: v for k, v in parts.items() if (v or (k == "use"))}]

def _address_obj(row) -> List[Dict[str, Any]]:
    has_any = any([row.address_line_0, row.address_city, row.address_postalCode, row.address_country])
    if not has_any:
        return []
    addr = {
        "use": row.address_use or "home",
        "line": [row.address_line_0] if row.address_line_0 else [],
        "city": row.address_city,
        "postalCode": row.address_postalCode,
        "country": row.address_country,
    }
    # Remove empty arrays/None keys
    return [{k: v for k, v in addr.items() if (v or (k in ("use", "line") and v == []))}]

def _telecom_obj(row) -> List[Dict[str, Any]]:
    telecom = []
    if row.tel_home:
        telecom.append({"system": "phone", "use": "home", "value": row.tel_home})
    if row.tel_work:
        telecom.append({"system": "phone", "use": "work", "value": row.tel_work})
    if row.tel_mobile:
        telecom.append({"system": "phone", "use": "mobile", "value": row.tel_mobile})
    if row.email:
        telecom.append({"system": "email", "value": row.email})
    return telecom

def _marital_status(row) -> Dict[str, Any] | None:
    """
    Map marital_code to FHIR maritalStatus as a CodeableConcept.
    We pass through the code and put a server-local system URL.
    Adjust mapping or system to your local terminology.
    """
    if not row.marital_code:
        return None
    return {
        "coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
            "code": row.marital_code
        }]
    }

def _deceased(row) -> Dict[str, Any] | None:
    if row.deathdate:
        return {"deceasedDateTime": row.deathdate.isoformat()}
    return None

def to_patient_resource(row) -> Patient:
    """
    Serialize a row from patient table to a FHIR Patient resource.
    """
    base = {
        "resourceType": "Patient",
        "id": str(row.id),
        "identifier": _identifier_obj(row.identifier),
        "name": _name_obj(row),
        "gender": row.gender,
        "birthDate": row.birthdate.isoformat() if row.birthdate else None,
        "telecom": _telecom_obj(row),
        "address": _address_obj(row),
    }

    # Mother's maiden name as an extension (optional)
    if row.mothersMaidenName:
        base.setdefault("extension", []).append({
            "url": "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName",
            "valueString": row.mothersMaidenName
        })

    # Marital status
    ms = _marital_status(row)
    if ms:
        base["maritalStatus"] = ms

    # Deceased handling
    deceased = _deceased(row)
    if deceased:
        base.update(deceased)

    # Strip None values to keep payload tidy
    clean = {k: v for k, v in base.items() if v is not None}
    return Patient.parse_obj(clean)

def bundle_from_rows(
    rows: Iterable, total: int, request: Request, page: int, count: int
) -> Dict[str, Any]:
    # Build base URL for Patient resources
    base_url = f"{request.url.scheme}://{request.url.netloc}/fhir/Patient"

    # Create entries with fullUrl for each resource
    entries: List[BundleEntry] = [
        BundleEntry.construct(
            fullUrl=f"{base_url}/{r.id}",
            resource=to_patient_resource(r)
        ) for r in rows
    ]

    links: List[BundleLink] = [BundleLink.construct(relation="self", url=str(request.url))]
    if page * count < total:
        qp = dict(request.query_params)
        qp["_page"] = str(page + 1)
        next_url = str(request.url.replace(query=urlencode(qp, doseq=True)))
        links.append(BundleLink.construct(relation="next", url=next_url))
    bundle = Bundle.construct(
        type="searchset",
        total=total,
        link=links,
        entry=entries
    )
    return bundle.dict()

def minimal_capability_statement(server_url: str) -> Dict[str, Any]:
    """
    Minimal CapabilityStatement adjusted to the parameters we actually support with this schema.
    """
    return {
      "resourceType": "CapabilityStatement",
      "status": "active",
      "kind": "instance",
      "fhirVersion": "4.3.0",
      "format": ["application/fhir+json", "application/fhir+xml"],  # XML not yet implemented
      "rest": [{
        "mode": "server",
        "resource": [{
          "type": "Patient",
          "interaction": [{"code": "read"}, {"code": "search-type"}],
          "searchParam": [
            {"name": "_id", "type": "string"},
            {"name": "family", "type": "string"},
            {"name": "given", "type": "string"},
            {"name": "identifier", "type": "token"},
            {"name": "telecom", "type": "token"},
            {"name": "birthdate", "type": "date"},
            {"name": "address", "type": "string"},
            {"name": "address-city", "type": "string"},
            {"name": "address-country", "type": "string"},
            {"name": "address-postalcode", "type": "string"},
            {"name": "gender", "type": "token"},
          ]
        }]
      }]
    }
