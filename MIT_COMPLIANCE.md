# MIT Compliance Check

Date checked: 2026-02-20  
Scope: direct dependencies listed in:
- `LDAP/requirements.txt`
- `mCSD/requirements.txt`
- `PDQm/requirements.txt`

All requirement lines are covered below.

## LDAP (`LDAP/requirements.txt`)

- `fastapi[all]==0.115.5` -> MIT
- `bonsai==1.5.5` -> MIT
- `pydantic-settings==2.5.2` -> MIT

## mCSD (`mCSD/requirements.txt`)

- `fastapi>=0.115.0` -> MIT
- `uvicorn[standard]>=0.30.0` -> BSD-3-Clause
- `httpx>=0.27.0` -> BSD-3-Clause
- `pydantic-settings==2.5.2` -> MIT
- `python-dotenv>=1.0.1` -> BSD-3-Clause
- `pytest>=8.3.0` -> MIT

## PDQm (`PDQm/requirements.txt`)

- `fastapi>=0.116.2` -> MIT
- `fhir.resources==7.1.0` -> BSD-style
- `httpx` -> BSD-3-Clause
- `jinja2>=3.1.0` -> BSD-style
- `pydantic==2.9.2` -> MIT
- `pydantic-settings>=2.0.0` -> MIT
- `pytest` -> MIT
- `pytest-asyncio` -> Apache-2.0
- `python-dateutil==2.9.0.post0` -> Apache-2.0 + BSD-style
- `python-multipart>=0.0.13` -> Apache-2.0
- `python-tds==1.17.1` -> MIT
- `setuptools>=68,<81` -> MIT
- `SQLAlchemy==2.0.35` -> MIT
- `sqlalchemy-pytds==1.0.2` -> MIT
- `uvicorn==0.30.6` -> BSD-3-Clause

## Conclusion

The stack can be used in an MIT-licensed project context (permissive-license compatible).  
It is not strict MIT-only, because several dependencies are BSD/Apache licensed.
