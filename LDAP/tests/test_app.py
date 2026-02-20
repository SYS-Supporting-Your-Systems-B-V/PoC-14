import types
import pytest
from fastapi.testclient import TestClient
from bonsai import LDAPSearchScope
from bonsai.errors import AuthenticationError as LDAPAuthenticationError
from bonsai.errors import ConnectionError as LDAPConnectionError
from bonsai.errors import NoSuchObjectError as LDAPNoSuchObjectError
import mainldap4 as appmod

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
