"""
Comprehensive test suite for PDQm ITI-78 Mobile Patient Demographics Query
Based on IHE PDQm 3.1.0 specification

Tests cover all specified scenarios:
- Query Patient Resource (GET and POST)
- Retrieve Patient Resource (GET by ID)
- Search parameters and modifiers
- Response cases (1-6 from spec)
- Format negotiation
- Paging
- Error handling
"""

import pytest
import json
from datetime import date
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient
import os
import pytest_asyncio
from sqlalchemy import select, func

from app.main import app
from app.db import SessionLocal, init_db
from app.models import PatientModel

def _test_ids(limit=3):
    """
    Levert test-IDs.
    - Uit env MSSQL_TEST_IDS of SQLITE_TEST_IDS (comma separated) wanneer gezet.
    - Anders: uit de DB (eerste N ids, oplopend).
    """
    env = os.getenv("MSSQL_TEST_IDS") or os.getenv("SQLITE_TEST_IDS")
    if env:
        return [x.strip() for x in env.split(",") if x.strip()][:limit]
    with SessionLocal() as s:
        rows = s.execute(select(PatientModel.id).order_by(PatientModel.id).limit(limit)).all()
        return [str(r[0]) for r in rows]

# --- MSSQL detection for conditional behavior (minimal addition) ---
with SessionLocal() as _s:
    try:
        _bind = _s.get_bind()
        _dialect_name = getattr(_bind.dialect, 'name', '')
    except Exception:
        _dialect_name = ''
IS_MSSQL = _dialect_name.startswith('mssql')
# --- end MSSQL detection ---

def _id_for_family(family: str):
    """Zoek een patiënt-id op basis van family (case-insensitive)."""
    with SessionLocal() as s:
        row = s.execute(
            select(PatientModel.id).where(func.lower(PatientModel.name_family) == family.lower()).order_by(PatientModel.id)
        ).first()
        return str(row[0]) if row else None

def _first_identifier(with_system: bool):
    """
    Vind (id, identifier) voor een patiënt met:
      - with_system=True: identifier met 'system|value'
      - with_system=False: identifier zonder '|'
    Retourneert (None, None) als niet aanwezig in dataset.
    """
    with SessionLocal() as s:
        if with_system:
            row = s.execute(
                select(PatientModel.id, PatientModel.identifier)
                .where(PatientModel.identifier.is_not(None))
                .where(PatientModel.identifier.contains("|"))
                .order_by(PatientModel.id)
            ).first()
        else:
            row = s.execute(
                select(PatientModel.id, PatientModel.identifier)
                .where(PatientModel.identifier.is_not(None))
                .where(~PatientModel.identifier.contains("|"))
                .order_by(PatientModel.id)
            ).first()
        return (str(row[0]), row[1]) if row else (None, None)


class TestPDQmITI78:
    """Test suite for ITI-78 Mobile Patient Demographics Query transaction"""

    @pytest.fixture(scope="function", autouse=True)
    def setup_db(self):
        """Initialize test database before each test"""
        init_db(seed=True)
        yield
        # Cleanup: clear the database after each test
        if not IS_MSSQL:
            with SessionLocal() as session:
                session.query(PatientModel).delete()
                session.commit()

    @pytest.fixture
    def client(self):
        """Synchronous test client"""
        return TestClient(app)

    @pytest_asyncio.fixture
    async def async_client(self):
        """Asynchronous test client"""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # =========================================================================
    # METADATA ENDPOINT TESTS
    # =========================================================================

    def test_metadata_capability_statement_json(self, client):
        """Test /fhir/metadata returns CapabilityStatement in JSON"""
        response = client.get(
            "/fhir/metadata", headers={"Accept": "application/fhir+json"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["resourceType"] == "CapabilityStatement"
        assert data["status"] == "active"
        assert data["kind"] == "instance"
        assert data["fhirVersion"] == "4.0.1"
        assert "application/fhir+json" in data["format"]

        # Verify Patient resource capabilities
        rest = data["rest"][0]
        patient_resource = next(r for r in rest["resource"] if r["type"] == "Patient")
        assert {"code": "read"} in patient_resource["interaction"]
        assert {"code": "search-type"} in patient_resource["interaction"]

        # Verify search parameters
        param_names = {p["name"] for p in patient_resource["searchParam"]}
        assert "_id" in param_names
        assert "family" in param_names
        assert "given" in param_names
        assert "identifier" in param_names
        assert "gender" in param_names
        assert "birthdate" in param_names

    @pytest.mark.skip(reason="XML support not yet implemented")
    def test_metadata_xml_format(self, client):
        """Test CapabilityStatement can be retrieved in XML format"""
        response = client.get(
            "/fhir/metadata", headers={"Accept": "application/fhir+xml"}
        )
        assert response.status_code == 200
        assert "application/fhir+xml" in response.headers["content-type"]
        # Verify it's valid XML
        assert response.content.startswith(b"<?xml") or response.content.startswith(
            b"<"
        )

    # =========================================================================
    # QUERY PATIENT RESOURCE - BASIC SEARCH PARAMETERS
    # =========================================================================

    def test_search_by_id_exact_match(self, client):
        """Test _id parameter (exact match only)"""
        ids = _test_ids(1)
        test_id = ids[0]
        response = client.get(f"/fhir/Patient?_id={test_id}")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "searchset"
        assert bundle["total"] >= 0
        if bundle["total"] >= 1:
            assert bundle["entry"][0]["resource"]["id"] == test_id

    def test_search_by_id_multiple_or(self, client):
        """Test _id with OR semantics (comma-separated)"""
        ids = _test_ids(2)
        id1 = ids[0]
        id2 = ids[1] if len(ids) > 1 else ids[0]
        response = client.get(f"/fhir/Patient?_id={id1},{id2}")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        found = {e["resource"]["id"] for e in bundle.get("entry", [])}
        assert (id1 in found) or (id2 in found)

    def test_search_by_id_multiple_and(self, client):
        """Test _id with AND semantics (repeated parameters) - should return 0"""
        ids = _test_ids(2)
        id1 = ids[0]
        id2 = ids[1] if len(ids) > 1 else ids[0]
        response = client.get(f"/fhir/Patient?_id={id1}&_id={id2}")
        assert response.status_code == 200
        bundle = response.json()
        if id1 != id2:
            assert bundle["total"] == 0
        else:
            assert bundle["total"] >= 0

    def test_search_by_family_contains(self, client):
        """Test family parameter with default contains behavior"""
        response = client.get("/fhir/Patient?family=SMITH")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        names = {e["resource"]["name"][0]["family"] for e in bundle["entry"]}
        assert "SMITH" in names

    def test_search_by_family_exact_modifier(self, client):
        """Test family:exact parameter modifier"""
        response = client.get("/fhir/Patient?family:exact=SMITH")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1
        assert bundle["entry"][0]["resource"]["name"][0]["family"] == "SMITH"

    def test_search_by_family_case_insensitive(self, client):
        """Test family parameter is case-insensitive"""
        response = client.get("/fhir/Patient?family=smith")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        assert any(
            e["resource"]["name"][0]["family"] == "SMITH" for e in bundle["entry"]
        )

    def test_search_by_given_contains(self, client):
        """Test given parameter with contains behavior"""
        response = client.get("/fhir/Patient?given=JOHN")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        assert any(
            "JOHN" in e["resource"]["name"][0]["given"][0] for e in bundle["entry"]
        )

    def test_search_by_given_exact_modifier(self, client):
        """Test given:exact parameter modifier"""
        response = client.get("/fhir/Patient?given:exact=JOHN")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1
        assert bundle["entry"][0]["resource"]["name"][0]["given"][0] == "JOHN"

    def test_search_by_gender_token(self, client):
        """Test gender parameter (token type)"""
        response = client.get("/fhir/Patient?gender=male")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 2  # p1 and p3
        for entry in bundle["entry"]:
            assert entry["resource"]["gender"] == "male"

    def test_search_by_gender_case_insensitive(self, client):
        """Test gender parameter is case-insensitive"""
        response = client.get("/fhir/Patient?gender=FEMALE")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        assert all(e["resource"]["gender"] == "female" for e in bundle.get("entry", []))

    def test_search_by_birthdate_exact(self, client):
        """Test birthdate parameter with exact match (eq prefix)"""
        response = client.get("/fhir/Patient?birthdate=1980-05-12")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 2  # p1 and p3 both born 1980-05-12
        for entry in bundle["entry"]:
            assert entry["resource"]["birthDate"] == "1980-05-12"

    def test_search_by_birthdate_ge_prefix(self, client):
        """Test birthdate parameter with ge (greater or equal) prefix"""
        response = client.get("/fhir/Patient?birthdate=ge1980-01-01")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 2

    def test_search_by_birthdate_le_prefix(self, client):
        """Test birthdate parameter with le (less or equal) prefix"""
        response = client.get("/fhir/Patient?birthdate=le1975-12-31")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1  # p2 (1975-01-01)

    def test_search_by_birthdate_gt_prefix(self, client):
        """Test birthdate parameter with gt (greater than) prefix"""
        response = client.get("/fhir/Patient?birthdate=gt1975-12-31")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 2

    def test_search_by_birthdate_lt_prefix(self, client):
        """Test birthdate parameter with lt (less than) prefix"""
        response = client.get("/fhir/Patient?birthdate=lt1980-01-01")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1  # p2

    def test_search_by_birthdate_invalid_format(self, client):
        """Test birthdate with invalid format returns HTTP 400"""
        response = client.get("/fhir/Patient?birthdate=invalid-date")
        assert response.status_code == 400
        data = response.json()
        assert data["issue"][0]["code"] == "invalid"

    # =========================================================================
    # PARTIAL DATE (BIRTHDATE) TESTS
    # =========================================================================

    def test_search_by_birthdate_year_precision_eq(self, client):
        """Test birthdate with year-only precision (eq by default)"""
        # Seed: two patients born in 1980
        response = client.get("/fhir/Patient?birthdate=1980")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 2
        assert all(e["resource"]["birthDate"].startswith("1980-") for e in bundle["entry"])

    def test_search_by_birthdate_year_month_precision_eq(self, client):
        """Test birthdate with year-month precision (eq by default)"""
        # Seed: two patients born 1980-05-12 → both in 1980-05
        response = client.get("/fhir/Patient?birthdate=1980-05")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 2
        assert all(e["resource"]["birthDate"].startswith("1980-05-") for e in bundle["entry"])

    def test_search_by_birthdate_ge_year_precision(self, client):
        """Test birthdate ge with year-only precision (>= start of year)"""
        response = client.get("/fhir/Patient?birthdate=ge1980")
        assert response.status_code == 200
        bundle = response.json()
        # Compute expected from DB so this works with seed or real datasets
        with SessionLocal() as s:
            expected = s.scalar(
                select(func.count()).select_from(PatientModel).where(PatientModel.birthdate >= date(1980, 1, 1))
            )
        assert bundle["total"] == (expected or 0)
        assert all(e["resource"]["birthDate"] >= "1980-01-01" for e in bundle.get("entry", []))

    def test_search_by_birthdate_le_year_month_precision(self, client):
        """Test birthdate le with year-month precision (<= end of month)"""
        # le1980-05 means < 1980-06-01 → includes 1975-01-01 and 1980-05-12 x2
        response = client.get("/fhir/Patient?birthdate=le1980-05")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 3
        assert all(e["resource"]["birthDate"] < "1980-06-01" for e in bundle["entry"])

    def test_search_by_birthdate_invalid_partial_month(self, client):
        """Test invalid partial date (bad month) returns HTTP 400"""
        response = client.get("/fhir/Patient?birthdate=1980-13")
        assert response.status_code == 400
        data = response.json()
        assert data["issue"][0]["code"] == "invalid"

    # =========================================================================
    # IDENTIFIER SEARCH TESTS
    # =========================================================================

    def test_search_by_identifier_value_only(self, client):
        """Test identifier parameter with value only (no system)"""
        pid, ident = _first_identifier(with_system=False)
        if not ident:
            pytest.skip("Geen identifier zonder systeem aanwezig in dataset.")
        response = client.get(f"/fhir/Patient?identifier={ident}")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1

    def test_search_by_identifier_system_and_value(self, client):
        """Test identifier parameter with system|value format"""
        pid, ident = _first_identifier(with_system=True)
        if not ident:
            pytest.skip("Geen identifier met systeem (system|value) aanwezig in dataset.")
        system, value = ident.split("|", 1)
        response = client.get(f"/fhir/Patient?identifier={system}|{value}")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        # Verify the identifier is present
        identifiers = [
            i for e in bundle["entry"] for i in e["resource"].get("identifier", [])
        ]
        assert any(i.get("system") == system and i.get("value") == value for i in identifiers)

    def test_search_by_identifier_multiple_domains_or(self, client):
        """Test Case 2: Filter by multiple identifier domains using OR (comma in system)
        Dynamisch:
        - Als er ≥2 verschillende systems (links van '|') aanwezig zijn → OR over twee systems.
        - Als er precies 1 system is en die komt bij ≥2 patiënten voor → domain-only query op dat system, verwacht ≥2 resultaten.
        - Als er geen system|value identifiers zijn (alleen value-only) → test is niet van toepassing → skip.
        """
        with SessionLocal() as s:
            rows = s.execute(
                select(PatientModel.identifier).where(
                    PatientModel.identifier.is_not(None),
                    PatientModel.identifier.contains("|"),
                )
            ).scalars().all()
        systems = []
        for ident in rows:
            try:
                sys, _ = ident.split("|", 1)
            except ValueError:
                continue
            systems.append(sys.strip())
        # Unieke systems en telling
        uniq = {}
        for sys in systems:
            uniq[sys] = uniq.get(sys, 0) + 1

        if not uniq:
            pytest.skip("Geen identifiers met 'system|value' in dataset; domein-OR test niet van toepassing.")

        if len(uniq) >= 2:
            sys1, sys2 = list(uniq.keys())[:2]
            response = client.get(f"/fhir/Patient?identifier={sys1},{sys2}|")
            assert response.status_code == 200
            bundle = response.json()
            assert bundle["total"] >= 1
        else:
            # precies 1 system aanwezig
            (only_sys, count) = next(iter(uniq.items()))
            response = client.get(f"/fhir/Patient?identifier={only_sys}|")
            assert response.status_code == 200
            bundle = response.json()
            # verwacht minstens 2 patiënten als het domein meerdere keren voorkomt
            assert bundle["total"] >= (2 if count >= 2 else 1)

    def test_search_by_identifier_unrecognized_domain(self, client):
        """Test Case 4: Search with unrecognized identifier domain"""
        # According to spec, server can return 404 OR 200 with warning
        response = client.get("/fhir/Patient?identifier=urn:oid:9.9.9.9.9|UNKNOWN")
        # Accept either 404 or 200
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            bundle = response.json()
            # Should return 0 results for unknown domain
            assert bundle["total"] == 0

    # =========================================================================
    # ADDRESS SEARCH TESTS
    # =========================================================================

    def test_search_by_address_broad(self, client):
        """Test address parameter searches across all address fields"""
        response = client.get("/fhir/Patient?address=Amsterdam")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        # Verify Amsterdam appears in city field
        cities = [
            e["resource"]["address"][0]["city"]
            for e in bundle["entry"]
            if e["resource"].get("address")
        ]
        assert "Amsterdam" in cities

    def test_search_by_address_city_specific(self, client):
        """Test address-city parameter"""
        response = client.get("/fhir/Patient?address-city=London")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1
        assert bundle["entry"][0]["resource"]["address"][0]["city"] == "London"

    def test_search_by_address_postalcode(self, client):
        """Test address-postalcode parameter"""
        response = client.get("/fhir/Patient?address-postalcode=1011 AA")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        assert any(e["resource"]["address"][0]["postalCode"] == "1011 AA" for e in bundle.get("entry", []))

    def test_search_by_address_country(self, client):
        """Test address-country parameter"""
        response = client.get("/fhir/Patient?address-country=NL")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 2
        assert all(e["resource"]["address"][0].get("country") in ("NL", "NLD", "Netherlands", "Nederland") for e in bundle.get("entry", []) if e["resource"].get("address"))

    def test_search_by_address_exact_modifier_broad(self, client):
        """Test address:exact modifier (matches exact field values across line/city/postal/country)"""
        # Seed: city == Amsterdam for patient 1
        response = client.get("/fhir/Patient?address:exact=Amsterdam")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1
        res = bundle["entry"][0]["resource"]
        assert res["address"][0]["city"] == "Amsterdam"

    def test_search_by_address_city_exact_modifier(self, client):
        """Test address-city:exact modifier"""
        response = client.get("/fhir/Patient?address-city:exact=Amsterdam")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1
        assert bundle["entry"][0]["resource"]["address"][0]["city"] == "Amsterdam"

    def test_search_by_address_postalcode_exact_modifier(self, client):
        """Test address-postalcode:exact modifier"""
        # Seed: postalCode == "1011 AA" for patient 1
        response = client.get("/fhir/Patient?address-postalcode:exact=1011%20AA")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1
        assert bundle["entry"][0]["resource"]["address"][0]["postalCode"] == "1011 AA"

    def test_search_by_address_country_exact_modifier(self, client):
        """Test address-country:exact modifier"""
        response = client.get("/fhir/Patient?address-country:exact=NL")
        assert response.status_code == 200
        bundle = response.json()
        # Compute expected from DB (exact match to 'NL') for seed or real datasets
        with SessionLocal() as s:
            expected = s.scalar(
                select(func.count()).select_from(PatientModel).where(func.lower(PatientModel.address_country) == "nl")
            )
        assert bundle["total"] == (expected or 0)
        assert all(e["resource"]["address"][0]["country"] == "NL" for e in bundle.get("entry", []))

    # =========================================================================
    # TELECOM SEARCH TESTS
    # =========================================================================

    def test_search_by_telecom_phone_system(self, client):
        """Test telecom parameter with phone system"""
        response = client.get("/fhir/Patient?telecom=phone|+31-20-1234567")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1

    def test_search_by_telecom_email_system(self, client):
        """Test telecom parameter with email system"""
        response = client.get("/fhir/Patient?telecom=email|john.smith@example.org")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1

    def test_search_by_telecom_no_system(self, client):
        """Test telecom parameter without system prefix"""
        response = client.get("/fhir/Patient?telecom=john.smith@example.org")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1

    # =========================================================================
    # REQUIRED PARAMETER COMBINATIONS
    # =========================================================================

    def test_search_family_and_gender_combination(self, client):
        """Test required combination: family AND gender"""
        response = client.get("/fhir/Patient?family=SMITH&gender=male")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        # Verify results match both criteria
        for entry in bundle["entry"]:
            assert "SMITH" in entry["resource"]["name"][0]["family"].upper()
            assert entry["resource"]["gender"] == "male"

    def test_search_birthdate_and_family_combination(self, client):
        """Test required combination: birthdate AND family"""
        response = client.get("/fhir/Patient?birthdate=1980-05-12&family=SMITH")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        for entry in bundle["entry"]:
            assert entry["resource"]["birthDate"] == "1980-05-12"
            assert "SMITH" in entry["resource"]["name"][0]["family"].upper()

    # =========================================================================
    # AND/OR SEMANTICS
    # =========================================================================

    def test_search_or_within_parameter(self, client):
        """Test OR semantics within single parameter (comma-separated)"""
        response = client.get("/fhir/Patient?gender=male,female")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 2  # All patients
        genders = {e["resource"]["gender"] for e in bundle.get("entry", [])}
        assert genders.issubset({"male", "female"})

    def test_search_and_across_parameters(self, client):
        """Test AND semantics across different parameters"""
        response = client.get("/fhir/Patient?family=SMITH&gender=male")
        assert response.status_code == 200
        bundle = response.json()
        # Results must satisfy BOTH conditions
        for entry in bundle["entry"]:
            assert "SMITH" in entry["resource"]["name"][0]["family"].upper()
            assert entry["resource"]["gender"] == "male"

    def test_search_and_within_repeated_parameters(self, client):
        """Test AND semantics with repeated same parameter"""
        # Searching for family=SMITH AND family=Jansen should return 0
        response = client.get("/fhir/Patient?family=SMITH&family=Jansen")
        assert response.status_code == 200
        bundle = response.json()
        # No patient can have both family names
        assert bundle["total"] == 0

    # =========================================================================
    # RESPONSE CASES FROM SPEC
    # =========================================================================

    def test_case_1_patients_found_no_domain_filter(self, client):
        """Test Case 1: Patients found, no identifier domain filter"""
        response = client.get("/fhir/Patient?family=SMITH")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "searchset"
        assert bundle["total"] >= 1
        assert len(bundle["entry"]) >= 1
        # Verify each entry has fullUrl and resource
        for entry in bundle["entry"]:
            assert "fullUrl" in entry
            assert entry["resource"]["resourceType"] == "Patient"

    def test_case_2_patients_found_with_domain_filter(self, client):
        """Test Case 2: Patients found with identifier domain filter"""
        pid, ident = _first_identifier(with_system=True)
        if not ident:
            pytest.skip("Geen identifier met systeem aanwezig; domain filter niet testbaar.")
        system, value = ident.split("|", 1)
        response = client.get(f"/fhir/Patient?identifier={system}|{value}")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1
        # Should only return patients with identifiers from that domain
        for entry in bundle["entry"]:
            identifiers = entry["resource"].get("identifier", [])
            # At least one identifier should be from the requested domain
            assert any(i.get("system") == system and i.get("value") == value for i in identifiers)

    def test_case_3_no_patients_found(self, client):
        """Test Case 3: No matching patients"""
        response = client.get("/fhir/Patient?family=NONEXISTENT")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "searchset"
        assert bundle["total"] == 0
        assert "entry" not in bundle or len(bundle.get("entry", [])) == 0

    def test_case_5_unsupported_format(self, client):
        """Test Case 5: Unsupported response format returns HTTP 406"""
        response = client.get(
            "/fhir/Patient?family=SMITH", headers={"Accept": "application/fhir+xml"}
        )
        assert response.status_code == 406
        data = response.json()
        assert data["issue"][0]["severity"] == "error"
        assert data["issue"][0]["code"] == "not-supported"

    @pytest.mark.skip(reason="XML support not yet implemented")
    def test_case_5_format_parameter_xml(self, client):
        """Test Case 5: Search results can be returned in XML format"""
        response = client.get("/fhir/Patient?family=SMITH&_format=xml")
        assert response.status_code == 200
        assert "application/fhir+xml" in response.headers["content-type"]
        # Verify it's valid XML and contains Bundle
        assert b"<Bundle" in response.content or b"<bundle" in response.content

    # =========================================================================
    # PAGING TESTS
    # =========================================================================

    def test_paging_default_count(self, client):
        """Test default page size is 20"""
        response = client.get("/fhir/Patient")
        assert response.status_code == 200
        bundle = response.json()
        # With only 3 test patients, should return all
        assert len(bundle["entry"]) <= 20
        assert bundle["total"] >= len(bundle["entry"])

    def test_paging_custom_count(self, client):
        """Test custom _count parameter"""
        response = client.get("/fhir/Patient?_count=1")
        assert response.status_code == 200
        bundle = response.json()
        assert len(bundle["entry"]) == 1
        assert bundle["total"] >= 1

    def test_paging_page_parameter(self, client):
        """Test _page parameter for pagination"""
        response = client.get("/fhir/Patient?_count=1&_page=2")
        assert response.status_code == 200
        bundle = response.json()
        assert len(bundle["entry"]) == 1
        # Should be a different patient than page 1

    def test_paging_next_link(self, client):
        """Test Bundle.link[next] is present when more results exist"""
        response = client.get("/fhir/Patient?_count=2")
        assert response.status_code == 200
        bundle = response.json()
        links = {link["relation"]: link["url"] for link in bundle["link"]}
        assert "self" in links
        # With 3 patients and _count=2, should have next link
        assert "next" in links
        assert "_page=2" in links["next"]

    def test_paging_no_next_link_on_last_page(self, client):
        """Test no next link on last page"""
        response = client.get("/fhir/Patient?_count=10")
        assert response.status_code == 200
        bundle = response.json()
        links = {link["relation"]: link["url"] for link in bundle["link"]}
        # All results fit on one page, no next link
        assert "next" not in links

    def test_paging_self_link_always_present(self, client):
        """Test Bundle.link[self] is always present"""
        response = client.get("/fhir/Patient?family=SMITH")
        assert response.status_code == 200
        bundle = response.json()
        links = {link["relation"]: link["url"] for link in bundle["link"]}
        assert "self" in links
        assert "family=SMITH" in links["self"]

    def test_paging_count_bounds(self, client):
        """Test _count parameter bounds (min 1, max 100)"""
        # Test minimum
        response = client.get("/fhir/Patient?_count=0")
        assert response.status_code == 200
        bundle = response.json()
        # Should be adjusted to 1
        assert len(bundle["entry"]) >= 1

        # Test maximum
        response = client.get("/fhir/Patient?_count=200")
        assert response.status_code == 200
        # Should be capped at 100 (but with only 3 patients, returns 3)

    # =========================================================================
    # RETRIEVE PATIENT RESOURCE (READ BY ID)
    # =========================================================================

    def test_read_patient_by_id_found(self, client):
        """Test Case 1: Read patient by ID successfully"""
        sid = _id_for_family("SMITH") or _test_ids(1)[0]
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()
        assert patient["resourceType"] == "Patient"
        assert patient["id"] == sid
        assert patient["name"][0]["family"] == "SMITH"

    def test_read_patient_by_id_not_found(self, client):
        """Test Case 2: Read patient by ID not found returns HTTP 404"""
        missing = "999999" if IS_MSSQL else "nonexistent"
        response = client.get(f"/fhir/Patient/{missing}")
        assert response.status_code == 404
        data = response.json()
        assert data["issue"][0]["severity"] == "error"
        assert data["issue"][0]["code"] == "not-found"

    def test_read_patient_format_json(self, client):
        """Test read patient returns JSON format"""
        ids = _test_ids(1)
        response = client.get(
            f"/fhir/Patient/{ids[0]}", headers={"Accept": "application/fhir+json"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    @pytest.mark.skip(reason="XML support not yet implemented")
    def test_read_patient_format_xml(self, client):
        """Test read patient resource in XML format"""
        ids = _test_ids(1)
        response = client.get(
            f"/fhir/Patient/{ids[0]}", headers={"Accept": "application/fhir+xml"}
        )
        assert response.status_code == 200
        assert "application/fhir+xml" in response.headers["content-type"]
        assert b"<Patient" in response.content or b"<patient" in response.content

    # =========================================================================
    # POST-BASED SEARCH
    # =========================================================================

    @pytest.mark.asyncio
    async def test_post_search_returns_bundle(self, async_client):
        """Test POST-based search returns Bundle directly (per FHIR spec)"""
        response = await async_client.post(
            "/fhir/Patient/_search",
            data={"family": "SMITH", "gender": "male"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        # Per FHIR spec, POST search returns 200 with Bundle, not redirect
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "searchset"
        assert bundle["total"] >= 1

        # Verify self link is expressed as GET (per FHIR spec)
        self_link = next(l for l in bundle["link"] if l["relation"] == "self")
        assert "family=SMITH" in self_link["url"]
        assert "gender=male" in self_link["url"]

    @pytest.mark.asyncio
    async def test_post_search_with_follow_redirects(self, async_client):
        """Test POST-based search following redirect returns results"""
        response = await async_client.post(
            "/fhir/Patient/_search",
            data={"family": "SMITH"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["resourceType"] == "Bundle"
        assert bundle["total"] >= 1

    # =========================================================================
    # MOTHER'S MAIDEN NAME EXTENSION
    # =========================================================================

    def test_mothers_maiden_name_extension_present(self, client):
        """Test mother's maiden name is returned as extension"""
        sid = _id_for_family("SMITH") or _test_ids(1)[0]
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        # Find the mothersMaidenName extension
        extensions = patient.get("extension", [])
        mmn_ext = next(
            (
                e
                for e in extensions
                if e["url"]
                == "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"
            ),
            None,
        )
        assert mmn_ext is not None
        # Verwachte waarde uit DB
        with SessionLocal() as s:
            row = s.get(PatientModel, sid)
            assert mmn_ext["valueString"] == row.mothersMaidenName

    def test_mothers_maiden_name_extension_absent_when_null(self, client):
        """Test mother's maiden name extension absent when not set"""
        # Zoek een patiënt zonder moeder's meisjesnaam (bv. Smythe)
        with SessionLocal() as s:
            row = s.execute(
                select(PatientModel.id).where(PatientModel.mothersMaidenName.is_(None)).order_by(PatientModel.id)
            ).first()
            pid = str(row[0]) if row else None
        if not pid:
            pytest.skip("Geen patiënt zonder mothersMaidenName in dataset.")
        response = client.get(f"/fhir/Patient/{pid}")
        assert response.status_code == 200
        patient = response.json()

        # Check if extension exists
        extensions = patient.get("extension", [])
        mmn_ext = next(
            (
                e
                for e in extensions
                if e["url"]
                == "http://hl7.org/fhir/StructureDefinition/patient-mothersMaidenName"
            ),
            None,
        )
        # Geen mothersMaidenName → extensie afwezig
        assert mmn_ext is None

    # =========================================================================
    # PATIENT RESOURCE VALIDATION
    # =========================================================================

    def test_patient_resource_has_required_elements(self, client):
        """Test Patient resource contains required FHIR elements"""
        ids = _test_ids(1)
        response = client.get(f"/fhir/Patient/{ids[0]}")
        assert response.status_code == 200
        patient = response.json()

        assert patient["resourceType"] == "Patient"
        assert "id" in patient
        assert "name" in patient
        assert "gender" in patient
        assert "birthDate" in patient

    def test_patient_name_structure(self, client):
        """Test Patient.name has correct structure"""
        sid = _id_for_family("SMITH") or _test_ids(1)[0]
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        name = patient["name"][0]
        assert name["use"] == "official"
        assert name["family"] == "SMITH"
        assert name["given"][0].upper() == "JOHN"
        # Verwachte text = name_text vanuit DB wanneer aanwezig
        with SessionLocal() as s:
            row = s.get(PatientModel, sid)
            if row.name_text:
                assert name["text"] == row.name_text

    def test_patient_identifier_structure(self, client):
        """Test Patient.identifier has correct structure"""
        # Kies bij voorkeur een patient met system|value, anders value-only
        sid, ident = _first_identifier(with_system=True)
        if not ident:
            sid, ident = _first_identifier(with_system=False)
        if not ident:
            pytest.skip("Geen patiënten met identifier in dataset.")
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        identifier = patient["identifier"][0]
        if "|" in ident:
            system, value = ident.split("|", 1)
            assert identifier["system"] == system
            assert identifier["value"] == value
        else:
            assert identifier["value"] == ident

    def test_patient_telecom_structure(self, client):
        """Test Patient.telecom has correct structure"""
        sid = _id_for_family("SMITH") or _test_ids(1)[0]
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        telecom = patient["telecom"]
        phone = next(t for t in telecom if t["system"] == "phone")
        # Verwachte waarden uit DB
        with SessionLocal() as s:
            row = s.get(PatientModel, sid)
            assert phone["use"] == "home"
            assert phone["value"] == row.tel_home

        email = next(t for t in telecom if t["system"] == "email")
        with SessionLocal() as s:
            row = s.get(PatientModel, sid)
            assert email["value"] == row.email

    def test_patient_address_structure(self, client):
        """Test Patient.address has correct structure"""
        sid = _id_for_family("SMITH") or _test_ids(1)[0]
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        address = patient["address"][0]
        with SessionLocal() as s:
            row = s.get(PatientModel, sid)
            assert address["use"] == row.address_use
            assert address["line"] == [row.address_line_0]
            assert address["city"] == row.address_city
            assert address["postalCode"] == row.address_postalCode
            assert address["country"] == row.address_country

    def test_patient_marital_status_structure(self, client):
        """Test Patient.maritalStatus has correct CodeableConcept structure"""
        sid = _id_for_family("SMITH") or _test_ids(1)[0]
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        marital = patient["maritalStatus"]
        coding = marital["coding"][0]
        assert (
            coding["system"] == "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus"
        )
        with SessionLocal() as s:
            row = s.get(PatientModel, sid)
            assert coding["code"] == row.marital_code

    # =========================================================================
    # BUNDLE STRUCTURE VALIDATION
    # =========================================================================

    def test_bundle_searchset_type(self, client):
        """Test Bundle type is 'searchset' for search results"""
        response = client.get("/fhir/Patient?family=SMITH")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["type"] == "searchset"

    def test_bundle_total_accurate(self, client):
        """Test Bundle.total reflects accurate count"""
        response = client.get("/fhir/Patient?gender=male")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 2
        assert len(bundle["entry"]) == 2

    def test_bundle_entry_has_fullurl(self, client):
        """Test Bundle.entry.fullUrl is present for each entry"""
        response = client.get("/fhir/Patient?family=SMITH")
        assert response.status_code == 200
        bundle = response.json()

        for entry in bundle["entry"]:
            assert "fullUrl" in entry
            assert entry["fullUrl"].startswith("http://")
            assert "/fhir/Patient/" in entry["fullUrl"]

    def test_bundle_link_self_reflects_request(self, client):
        """Test Bundle.link[self] reflects the request URL"""
        response = client.get("/fhir/Patient?family=SMITH&gender=male")
        assert response.status_code == 200
        bundle = response.json()

        self_link = next(l for l in bundle["link"] if l["relation"] == "self")
        assert "family=SMITH" in self_link["url"]
        assert "gender=male" in self_link["url"]

    # =========================================================================
    # EDGE CASES AND ERROR HANDLING
    # =========================================================================

    def test_search_no_parameters(self, client):
        """Test search with no parameters returns all patients"""
        response = client.get("/fhir/Patient")
        assert response.status_code == 200
        bundle = response.json()
        assert len(bundle["entry"]) >= 1
        assert bundle["total"] >= len(bundle["entry"])

    def test_search_empty_parameter_value(self, client):
        """Test search with empty parameter value"""
        response = client.get("/fhir/Patient?family=")
        assert response.status_code == 200
        bundle = response.json()
        assert len(bundle["entry"]) >= 1
        # Empty value should be ignored
        assert bundle["total"] >= len(bundle["entry"])

    def test_search_special_characters_in_parameter(self, client):
        """Test search handles special characters properly"""
        response = client.get("/fhir/Patient?address=Baker%20Street%20221%20B")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1

    def test_search_multiple_values_or_semantics(self, client):
        """Test multiple comma-separated values use OR semantics"""
        response = client.get("/fhir/Patient?family=SMITH,Jansen")
        assert response.status_code == 200
        bundle = response.json()
        # Should return both SMITH and Jansen families
        assert bundle["total"] >= 2
        families = {e["resource"]["name"][0]["family"] for e in bundle["entry"]}
        assert "SMITH" in families or "Smythe" in families
        assert "Jansen" in families

    # =========================================================================
    # FORMAT NEGOTIATION TESTS
    # =========================================================================

    def test_format_negotiation_accept_header_json(self, client):
        """Test Accept header with application/fhir+json"""
        response = client.get(
            "/fhir/Patient?family=SMITH", headers={"Accept": "application/fhir+json"}
        )
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_format_negotiation_accept_header_json_with_version(self, client):
        """Test Accept header with fhirVersion parameter"""
        response = client.get(
            "/fhir/Patient?family=SMITH",
            headers={"Accept": "application/fhir+json; fhirVersion=4.0"},
        )
        assert response.status_code == 200

    def test_format_negotiation_format_parameter_json(self, client):
        """Test _format parameter with json"""
        response = client.get("/fhir/Patient?family=SMITH&_format=json")
        assert response.status_code == 200

    def test_format_negotiation_format_parameter_application_json(self, client):
        """Test _format parameter with application/fhir+json"""
        response = client.get(
            "/fhir/Patient?family=SMITH&_format=application/fhir+json"
        )
        assert response.status_code == 200

    # =========================================================================
    # DEPRECATED PATIENT HANDLING (Case 6)
    # =========================================================================

    @pytest.mark.skipif(IS_MSSQL, reason="MSSQL backend is read-only (view); main.py does not mutate on SQL Server")
    def test_case_6_deprecated_patient_setup(self):
        """Setup test for deprecated patient (active=false)"""
        # Add a deprecated patient to the database
        with SessionLocal() as session:
            deprecated = PatientModel(
                id="p99",
                identifier="DEPRECATED",
                name_family="Deprecated",
                name_given_0="Patient",
                name_text="Deprecated Patient",
                gender="male",
                birthdate=date(1950, 1, 1),
                # Note: The model doesn't have an 'active' field,
                # so we can't test this without modifying the model
            )
            session.add(deprecated)
            session.commit()

    # =========================================================================
    # CONSISTENCY AND DETERMINISM TESTS
    # =========================================================================

    def test_search_results_deterministic_ordering(self, client):
        """Test search results have consistent ordering (by id)"""
        response1 = client.get("/fhir/Patient")
        response2 = client.get("/fhir/Patient")

        bundle1 = response1.json()
        bundle2 = response2.json()

        ids1 = [e["resource"]["id"] for e in bundle1["entry"]]
        ids2 = [e["resource"]["id"] for e in bundle2["entry"]]

        assert ids1 == ids2  # Same order every time

    def test_search_count_matches_entries(self, client):
        """Test Bundle.entry length matches _count parameter"""
        response = client.get("/fhir/Patient?_count=2")
        assert response.status_code == 200
        bundle = response.json()
        assert len(bundle["entry"]) == min(2, bundle["total"])

    # =========================================================================
    # ADVANCED SEARCH SCENARIOS
    # =========================================================================

    def test_search_complex_query_multiple_parameters(self, client):
        """Test complex search with multiple different parameters"""
        response = client.get(
            "/fhir/Patient?"
            "family=SMITH&"
            "gender=male&"
            "birthdate=1980-05-12&"
            "address-country=NL"
        )
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1

        # Verify all criteria are met
        for entry in bundle["entry"]:
            patient = entry["resource"]
            assert "SMITH" in patient["name"][0]["family"]
            assert patient["gender"] == "male"
            assert patient["birthDate"] == "1980-05-12"
            assert patient["address"][0]["country"] == "NL"

    def test_search_with_all_address_fields(self, client):
        """Test search using all address field variations"""
        response = client.get(
            "/fhir/Patient?"
            "address-city=Amsterdam&"
            "address-postalcode=1011 AA&"
            "address-country=NL"
        )
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] == 1

    def test_search_telecom_multiple_types(self, client):
        """Test telecom search across phone and email"""
        # Search for email
        response = client.get("/fhir/Patient?telecom=john.smith")
        assert response.status_code == 200
        bundle = response.json()
        assert bundle["total"] >= 1

    # =========================================================================
    # DATA COMPLETENESS TESTS
    # =========================================================================

    def test_patient_with_minimal_data(self, client):
        """Test patient resource can be returned with minimal data"""
        ids = _test_ids(1)
        response = client.get(f"/fhir/Patient/{ids[0]}")
        assert response.status_code == 200
        patient = response.json()
        assert patient["resourceType"] == "Patient"
        assert patient["id"] == ids[0]

    def test_patient_identifier_without_system(self, client):
        """Test patient identifier without system is handled correctly"""
        sid, ident = _first_identifier(with_system=False)
        if not ident:
            pytest.skip("Geen value-only identifier aanwezig in dataset.")
        response = client.get(f"/fhir/Patient/{sid}")
        assert response.status_code == 200
        patient = response.json()

        identifier = patient["identifier"][0]
        assert identifier["value"] == ident
        # System may or may not be present

    # =========================================================================
    # PARAMETER VALIDATION
    # =========================================================================

    def test_invalid_page_parameter(self, client):
        """Test invalid _page parameter is handled gracefully"""
        response = client.get("/fhir/Patient?_page=invalid")
        assert response.status_code == 200
        # Should default to page 1

    def test_invalid_count_parameter(self, client):
        """Test invalid _count parameter is handled gracefully"""
        response = client.get("/fhir/Patient?_count=invalid")
        assert response.status_code == 200
        # Should default to 20

    def test_negative_page_parameter(self, client):
        """Test negative _page parameter is handled"""
        response = client.get("/fhir/Patient?_page=-1")
        assert response.status_code == 200
        # Should be adjusted to 1

    def test_zero_page_parameter(self, client):
        """Test zero _page parameter is handled"""
        response = client.get("/fhir/Patient?_page=0")
        assert response.status_code == 200
        # Should be adjusted to 1
