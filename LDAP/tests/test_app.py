from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from bonsai import LDAPSearchScope
from bonsai.errors import AuthenticationError as LDAPAuthenticationError
from bonsai.errors import ConnectionError as LDAPConnectionError
from bonsai.errors import NoSuchObjectError as LDAPNoSuchObjectError
import main as appmod

client = TestClient(appmod.app)

class FakeEntry:
    def __init__(self, dn, attrs):
        self.dn = dn
        self._attrs = attrs

    def get(self, key, default=None):
        return self._attrs.get(key, default)

class FakeConn:
    def __init__(self, entries):
        self._entries = entries

    def search(self, base, scope, filter_str=None, attrlist=None, timeout=None, sizelimit=None):
        if scope == LDAPSearchScope.BASE:
            # OU-existence check: altijd een niet-leeg resultaat teruggeven
            return [object()]
        if sizelimit is not None and sizelimit < len(self._entries):
            return self._entries[:sizelimit]
        return list(self._entries)

    def close(self):
        return True

@pytest.fixture
def monkey_connect(monkeypatch):
    entries = [
        FakeEntry(
            "uid=bob01,ou=HCProfessional,dc=HPD",
            {
                "uid": ["bob01"],
                "objectClass": ["inetOrgPerson"],
                "cn": ["Bob Example"],
                "sn": ["Example"],
                "givenName": ["Bob"],
                "mail": ["bob@example.org", "b@example.org"],
                "displayName": ["Bob Example"],
                "telephoneNumber": ["012-3456789"],
                "mobile": [],
                "title": ["Specialist"],
                "o": ["Acme Hospital"],
                "ou": ["Cardiology"],
            },
        ),
        FakeEntry(
            "uid=ann02,ou=HCProfessional,dc=HPD",
            {
                "uid": ["ann02"],
                "objectClass": ["inetOrgPerson"],
                "cn": ["Ann Example"],
                "sn": ["Example"],
                "givenName": ["Ann"],
                "mail": ["ann@example.org"],
                "displayName": ["Ann Example"],
                "telephoneNumber": [],
                "mobile": [],
                "title": ["Nurse"],
                "o": ["Acme Hospital"],
                "ou": ["Oncology"],
            },
        ),
    ]
    fake = FakeConn(entries)
    monkeypatch.setattr(appmod, "_connect", lambda: fake)
    return fake

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_post_search_person(monkey_connect):
    payload = {"q": "bob", "scope": "person", "limit": 50}
    r = client.post("/hpd/search", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert "items" in data
    assert isinstance(data["items"][0]["mail"], list)
    assert "bob@example.org" in data["items"][0]["mail"]

def test_get_search_org(monkey_connect, monkeypatch):
    # Voor organisaties retourneren we dezelfde fake entries; we testen alleen het GET-pad en limit
    r = client.get("/hpd/search", params={"q": "acme", "scope": "org", "limit": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert len(data["items"]) == 1
    assert "dn" in data["items"][0]

def test_limit_applied(monkey_connect):
    r = client.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 1})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1

def test_empty_ok(monkeypatch):
    empty_conn = FakeConn(entries=[])
    monkeypatch.setattr(appmod, "_connect", lambda: empty_conn)
    r = client.post("/hpd/search", json={"q": "none", "scope": "person", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []

def test_items_without_mail(monkeypatch):
    entries = [
        FakeEntry("o=Gamma Hospital,ou=HCRegulatedOrganization,dc=HPD", {
            "o": ["Gamma Hospital"], "cn": ["Gamma Hospital"], "telephoneNumber": ["020-9090909"]
            # mail ontbreekt bewust
        })
    ]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client_local = TestClient(appmod.app)
    r = client_local.get("/hpd/search", params={"q":"Gamma","scope":"org","limit":10})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert "mail" in data["items"][0]
    assert data["items"][0]["mail"] == []  # leeg is ok

def test_unicode_query_passthrough(monkeypatch):
    entries = [FakeEntry("uid=jose07,ou=HCProfessional,dc=HPD", {
        "uid": ["jose07"],
        "objectClass": ["inetOrgPerson"],
        "cn": ["José Álvarez"],
        "sn": ["Álvarez"],
        "givenName": ["José"],
        "displayName": ["Dr. José Álvarez"],
        "mail": ["jose.alvarez@gamma-hospital.example"],
    })]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client_local = TestClient(appmod.app)
    r = client_local.get("/hpd/search", params={"q":"Álvarez","scope":"person","limit":10})
    assert r.status_code == 200
    assert r.json()["items"][0]["cn"][0] == "José Álvarez"

def test_orgunit_without_cn(monkeypatch):
    entries = [FakeEntry(
        "ou=Admissions,o=Beta Clinic,ou=HCRegulatedOrganization,dc=HPD",
        {"ou": ["Admissions"], "displayName": ["Admissions Desk"], "telephoneNumber": ["020-7777000"]}
    )]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client_local = TestClient(appmod.app)
    r = client_local.get("/hpd/search", params={"q":"Admissions","scope":"org","limit":5})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["cn"] == []  # geen cn aanwezig
    assert data["items"][0]["displayName"] == ["Admissions Desk"]

def test_empty_mail_value(monkeypatch):
    entries = [FakeEntry(
        "ou=NoMailbox,o=Beta Clinic,ou=HCRegulatedOrganization,dc=HPD",
        {"ou": ["NoMailbox"], "mail": ["", "alt-nomailbox@beta-clinic.example"]}
    )]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client_local = TestClient(appmod.app)
    r = client_local.get("/hpd/search", params={"q":"NoMailbox","scope":"org","limit":5})
    assert r.status_code == 200
    mails = r.json()["items"][0]["mail"]
    assert "" in mails and "alt-nomailbox@beta-clinic.example" in mails


def test_ldap_zoek_page_uses_same_origin_base_url():
    r = client.get("/ldap_zoek/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "E-mailadres zoeken (HPD LDAP)" in html
    assert "window.location.origin" in html
    assert "10.10.10.199" not in html

def test_missing_ou_returns_empty(monkeypatch):
    """Als de basis-OU ontbreekt in LDAP (LDAPNoSuchObjectError), retourneert de API 0 resultaten."""
    class FakeConnMissingOU:
        def search(self, base, scope, filter_str=None, attrlist=None, timeout=None, sizelimit=None):
            if scope == LDAPSearchScope.BASE:
                raise LDAPNoSuchObjectError()
            return []
        def close(self):
            return True

    monkeypatch.setattr(appmod, "_connect", lambda: FakeConnMissingOU())
    r = client.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    assert data["items"] == []

def test_ldap_bind_error_returns_502(monkeypatch):
    """_connect() converteert LDAPAuthenticationError naar HTTP 502."""
    class _FakeClient:
        def connect(self, timeout=None):
            raise LDAPAuthenticationError()

    monkeypatch.setattr(appmod, "_create_client", lambda *a, **kw: _FakeClient())
    r = client.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 10})
    assert r.status_code == 502

def test_ldap_connection_error_returns_503(monkeypatch):
    """_connect() converteert LDAPConnectionError naar HTTP 503."""
    class _FakeClient:
        def connect(self, timeout=None):
            raise LDAPConnectionError()

    monkeypatch.setattr(appmod, "_create_client", lambda *a, **kw: _FakeClient())
    r = client.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 10})
    assert r.status_code == 503


def test_api_key_missing_returns_401(monkeypatch):
    monkeypatch.setattr(appmod.settings, "api_key", "supersecret")
    monkeypatch.setattr(appmod, "_connect", lambda: pytest.fail("_connect should not be called when API key is invalid"))
    r = client.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 10})
    assert r.status_code == 401
    assert r.json()["detail"] == "Ongeldige API key."


def test_api_key_wrong_returns_401(monkeypatch):
    monkeypatch.setattr(appmod.settings, "api_key", "supersecret")
    monkeypatch.setattr(appmod, "_connect", lambda: pytest.fail("_connect should not be called when API key is invalid"))
    r = client.post(
        "/hpd/search",
        json={"q": "x", "scope": "person", "limit": 10},
        headers={"X-API-Key": "wrong"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Ongeldige API key."


def test_api_key_correct_allows_request(monkeypatch):
    monkeypatch.setattr(appmod.settings, "api_key", "supersecret")
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries=[]))
    r = client.post(
        "/hpd/search",
        json={"q": "x", "scope": "person", "limit": 10},
        headers={"X-API-Key": "supersecret"},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_health_ignores_api_key(monkeypatch):
    monkeypatch.setattr(appmod.settings, "api_key", "supersecret")
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.parametrize(
    "payload",
    [
        {"q": "x" * 65, "scope": "person", "limit": 10},
        {"q": "x", "scope": "person", "limit": 0},
        {"q": "x", "scope": "person", "limit": 501},
        {"q": "x", "scope": "invalid", "limit": 10},
    ],
)
def test_post_search_validation_errors(payload):
    r = client.post("/hpd/search", json=payload)
    assert r.status_code == 422


def test_get_search_invalid_scope_returns_422():
    r = client.get("/hpd/search", params={"q": "x", "scope": "invalid", "limit": 10})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "params",
    [
        {"q": "x" * 65, "scope": "person", "limit": 10},
        {"q": "x", "scope": "person", "limit": 0},
        {"q": "x", "scope": "person", "limit": 501},
    ],
)
def test_get_search_validation_should_return_422(params):
    r = client.get("/hpd/search", params=params)
    assert r.status_code == 422


def test_escape_ldap_filter_special_chars():
    out = appmod._escape_ldap_filter("a*b(c)\\d\x00")
    assert out == "a\\2ab\\28c\\29\\5cd\\00"


def test_make_filter_for_empty_query():
    assert appmod._make_filter("", "person") == "(&(objectClass=inetOrgPerson))"
    assert appmod._make_filter("   ", "org") == "(objectClass=*)"


def test_make_filter_escapes_user_input():
    filt = appmod._make_filter("*)(x", "person")
    assert "\\2a\\29\\28x" in filt
    assert filt.startswith("(&(objectClass=inetOrgPerson)")


def test_search_uses_empty_query_filter_for_person(monkeypatch):
    class RecordingConn:
        def __init__(self):
            self.calls = []

        def search(self, base, scope, filter_str=None, attrlist=None, timeout=None, sizelimit=None):
            self.calls.append(
                {
                    "base": base,
                    "scope": scope,
                    "filter": filter_str,
                    "sizelimit": sizelimit,
                }
            )
            if scope == LDAPSearchScope.BASE:
                return [object()]
            return []

        def close(self):
            return True

    conn = RecordingConn()
    monkeypatch.setattr(appmod, "_connect", lambda: conn)
    r = client.post("/hpd/search", json={"q": "   ", "scope": "person", "limit": 7})
    assert r.status_code == 200
    subtree_calls = [c for c in conn.calls if c["scope"] == LDAPSearchScope.SUBTREE]
    assert len(subtree_calls) == 1
    assert subtree_calls[0]["filter"] == "(&(objectClass=inetOrgPerson))"
    assert subtree_calls[0]["sizelimit"] == 7


def test_discover_base_dn_prefers_dc_hpd_when_multiple_contexts():
    class RootDseEntry:
        def get(self, key, default=None):
            if key == "namingContexts":
                return ["dc=example", "dc=HPD"]
            return default

    class RootDseConn:
        def search(self, base, scope, filter_str=None, attrlist=None, timeout=None, sizelimit=None):
            return [RootDseEntry()]

    assert appmod._discover_base_dn(RootDseConn()) == "dc=HPD"


def test_resolve_base_root_uses_cache(monkeypatch):
    monkeypatch.setattr(appmod.settings, "ldap_base_dn", "auto")
    monkeypatch.setattr(appmod, "_DISCOVERED_BASE", None)
    calls = {"n": 0}

    def fake_discover(_conn):
        calls["n"] += 1
        return "dc=HPD"

    monkeypatch.setattr(appmod, "_discover_base_dn", fake_discover)
    assert appmod._resolve_base_root(object()) == "dc=HPD"
    assert appmod._resolve_base_root(object()) == "dc=HPD"
    assert calls["n"] == 1


def test_resolve_base_root_cached_raises_when_missing(monkeypatch):
    monkeypatch.setattr(appmod.settings, "ldap_base_dn", "auto")
    monkeypatch.setattr(appmod, "_DISCOVERED_BASE", None)
    with pytest.raises(appmod.HTTPException) as exc:
        appmod._resolve_base_root_cached()
    assert exc.value.status_code == 502


@pytest.mark.parametrize(
    "bind_dn,base_dn,expected",
    [
        (None, "dc=HPD", None),
        ("cn=readonly,{base}", "dc=HPD", "cn=readonly,dc=HPD"),
        ("cn=readonly", "dc=HPD", "cn=readonly,dc=HPD"),
        ("cn=readonly,dc=HPD", "dc=HPD", "cn=readonly,dc=HPD"),
    ],
)
def test_effective_bind_dn_variants(monkeypatch, bind_dn, base_dn, expected):
    monkeypatch.setattr(appmod.settings, "ldap_bind_dn", bind_dn)
    assert appmod._effective_bind_dn(base_dn) == expected


def test_connect_maps_generic_ldap_error_to_502(monkeypatch):
    class FakeLDAPError(Exception):
        pass

    class _FakeClient:
        def connect(self, timeout=None):
            raise FakeLDAPError("boom")

    monkeypatch.setattr(appmod, "LDAPError", FakeLDAPError)
    monkeypatch.setattr(appmod.settings, "ldap_bind_dn", None)
    monkeypatch.setattr(appmod.settings, "ldap_base_dn", "dc=HPD")
    monkeypatch.setattr(appmod.settings, "ldap_uri", "ldap://example:389")
    monkeypatch.setattr(appmod, "_create_client", lambda *a, **kw: _FakeClient())
    with pytest.raises(appmod.HTTPException) as exc:
        appmod._connect()
    assert exc.value.status_code == 502


def test_connect_maps_oserror_to_503(monkeypatch):
    class _FakeClient:
        def connect(self, timeout=None):
            raise OSError("network down")

    monkeypatch.setattr(appmod.settings, "ldap_bind_dn", None)
    monkeypatch.setattr(appmod.settings, "ldap_base_dn", "dc=HPD")
    monkeypatch.setattr(appmod.settings, "ldap_uri", "ldap://example:389")
    monkeypatch.setattr(appmod, "_create_client", lambda *a, **kw: _FakeClient())
    with pytest.raises(appmod.HTTPException) as exc:
        appmod._connect()
    assert exc.value.status_code == 503


def test_connect_disables_starttls_for_ldaps_uri(monkeypatch):
    calls = []

    class _FakeClient:
        def connect(self, timeout=None):
            return FakeConn(entries=[])

    def fake_create_client(use_ssl=None, start_tls=None):
        calls.append((use_ssl, start_tls))
        return _FakeClient()

    monkeypatch.setattr(appmod.settings, "ldap_use_ssl", False)
    monkeypatch.setattr(appmod.settings, "ldap_start_tls", True)
    monkeypatch.setattr(appmod.settings, "ldap_uri", "ldaps://ldap.example:636")
    monkeypatch.setattr(appmod.settings, "ldap_bind_dn", None)
    monkeypatch.setattr(appmod.settings, "ldap_base_dn", "dc=HPD")
    monkeypatch.setattr(appmod, "_create_client", fake_create_client)

    conn = appmod._connect()
    assert isinstance(conn, FakeConn)
    assert calls == [(False, False)]


def test_connect_prefers_starttls_when_ssl_and_starttls_both_true(monkeypatch):
    calls = []

    class _FakeClient:
        def connect(self, timeout=None):
            return FakeConn(entries=[])

    def fake_create_client(use_ssl=None, start_tls=None):
        calls.append((use_ssl, start_tls))
        return _FakeClient()

    monkeypatch.setattr(appmod.settings, "ldap_use_ssl", True)
    monkeypatch.setattr(appmod.settings, "ldap_start_tls", True)
    monkeypatch.setattr(appmod.settings, "ldap_uri", "ldap://ldap.example:389")
    monkeypatch.setattr(appmod.settings, "ldap_bind_dn", None)
    monkeypatch.setattr(appmod.settings, "ldap_base_dn", "dc=HPD")
    monkeypatch.setattr(appmod, "_create_client", fake_create_client)

    conn = appmod._connect()
    assert isinstance(conn, FakeConn)
    assert calls == [(False, True)]


def test_ldap_zoek_missing_file_returns_404(monkeypatch):
    missing_root = Path(__file__).resolve().parent / "__missing_app_root__"
    monkeypatch.setattr(appmod, "APP_ROOT", missing_root)
    r = client.get("/ldap_zoek/")
    assert r.status_code == 404
    assert "HTML page not found" in r.json()["detail"]


def test_request_id_header_present_on_success(monkeypatch):
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries=[]))
    r = client.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 10})
    assert r.status_code == 200
    assert "X-Request-ID" in r.headers
    assert r.headers["X-Request-ID"]


def test_unhandled_exception_returns_generic_500(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(appmod, "_connect", _boom)
    client_no_raise = TestClient(appmod.app, raise_server_exceptions=False)
    r = client_no_raise.post("/hpd/search", json={"q": "x", "scope": "person", "limit": 10})
    assert r.status_code == 500
    assert r.json()["detail"] == "Interne serverfout. Neem contact op met de beheerder."
    assert "X-Request-ID" in r.headers
