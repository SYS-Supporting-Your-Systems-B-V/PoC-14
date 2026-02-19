import types
import pytest
from fastapi.testclient import TestClient
import main as appmod

client = TestClient(appmod.app)

class FakeEntry:
    def __init__(self, dn, attrs):
        self.entry_dn = dn
        self.entry_attributes_as_dict = attrs

class FakeConn:
    def __init__(self, entries):
        self._entries = entries
        self.entries = []

    def search(self, search_base, search_filter, search_scope, attributes, size_limit):
        if size_limit < len(self._entries):
            self.entries = self._entries[:size_limit]
        else:
            self.entries = self._entries
        return True

    def unbind(self):
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
    from main import app, HpdEntry, SearchResponse
    from fastapi.testclient import TestClient
    import main as appmod

    class FakeEntry:
        def __init__(self, dn, attrs):
            self.entry_dn = dn
            self.entry_attributes_as_dict = attrs

    class FakeConn:
        def __init__(self, entries):
            self._entries = entries
            self.entries = []
        def search(self, **kwargs):
            self.entries = self._entries
            return True
        def unbind(self): return True

    entries = [
        FakeEntry("o=Gamma Hospital,ou=HCRegulatedOrganization,dc=HPD", {
            "o": ["Gamma Hospital"], "cn": ["Gamma Hospital"], "telephoneNumber": ["020-9090909"]
            # mail ontbreekt bewust
        })
    ]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client = TestClient(app)
    r = client.get("/hpd/search", params={"q":"Gamma","scope":"org","limit":10})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert "mail" in data["items"][0]
    assert data["items"][0]["mail"] == []  # leeg is ok

def test_unicode_query_passthrough(monkeypatch):
    from fastapi.testclient import TestClient
    import main as appmod

    class FakeEntry:
        def __init__(self, dn, attrs):
            self.entry_dn = dn
            self.entry_attributes_as_dict = attrs

    class FakeConn:
        def __init__(self, entries):
            self._entries = entries
            self.entries = []
        def search(self, **kwargs):
            self.entries = self._entries
            return True
        def unbind(self): return True

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
    client = TestClient(appmod.app)
    r = client.get("/hpd/search", params={"q":"Álvarez","scope":"person","limit":10})
    assert r.status_code == 200
    assert r.json()["items"][0]["cn"][0] == "José Álvarez"

def test_orgunit_without_cn(monkeypatch):
    import main as appmod
    from fastapi.testclient import TestClient

    class FakeEntry:
        def __init__(self, dn, attrs):
            self.entry_dn = dn
            self.entry_attributes_as_dict = attrs

    class FakeConn:
        def __init__(self, entries):
            self._entries = entries
            self.entries = []
        def search(self, **kwargs):
            self.entries = self._entries
            return True
        def unbind(self): return True

    entries = [FakeEntry(
        "ou=Admissions,o=Beta Clinic,ou=HCRegulatedOrganization,dc=HPD",
        {"ou": ["Admissions"], "displayName": ["Admissions Desk"], "telephoneNumber": ["020-7777000"]}
    )]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client = TestClient(appmod.app)
    r = client.get("/hpd/search", params={"q":"Admissions","scope":"org","limit":5})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    assert data["items"][0]["cn"] == []  # geen cn aanwezig
    assert data["items"][0]["displayName"] == ["Admissions Desk"]

def test_empty_mail_value(monkeypatch):
    import main as appmod
    from fastapi.testclient import TestClient

    class FakeEntry:
        def __init__(self, dn, attrs):
            self.entry_dn = dn
            self.entry_attributes_as_dict = attrs

    class FakeConn:
        def __init__(self, entries):
            self._entries = entries
            self.entries = []
        def search(self, **kwargs):
            self.entries = self._entries
            return True
        def unbind(self): return True

    entries = [FakeEntry(
        "ou=NoMailbox,o=Beta Clinic,ou=HCRegulatedOrganization,dc=HPD",
        {"ou": ["NoMailbox"], "mail": ["", "alt-nomailbox@beta-clinic.example"]}
    )]
    monkeypatch.setattr(appmod, "_connect", lambda: FakeConn(entries))
    client = TestClient(appmod.app)
    r = client.get("/hpd/search", params={"q":"NoMailbox","scope":"org","limit":5})
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
