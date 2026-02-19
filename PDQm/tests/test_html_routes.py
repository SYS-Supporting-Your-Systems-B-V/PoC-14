from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_ldap_zoek_page_uses_same_origin_base_url():
    r = client.get("/ldap_zoek/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "E-mailadres zoeken (HPD LDAP)" in html
    assert "window.location.origin" in html
    assert "10.10.10.199" not in html


def test_mscd_zoek_page_uses_same_origin_base_url():
    r = client.get("/mscd_zoek/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "E-mailadres zoeken (mCSD)" in html
    assert "window.location.origin" in html
    assert "10.10.10.199" not in html
