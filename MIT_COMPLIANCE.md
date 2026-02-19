# MIT Compliance Report

Last checked: 2026-02-19

## Scope

This report covers:

- repository license setup for this codebase
- direct Python dependencies declared in:
  - `LDAP/requirements.txt`
  - `mCSD/requirements.txt`
  - `PDQm/requirements.txt`

## MIT License Requirements

MIT requires:

1. Include the copyright notice and permission notice in all copies/substantial portions.
2. Include the warranty disclaimer.

## Evidence in this Repository

1. `LICENSE` exists at repo root and contains the MIT text (including copyright and disclaimer).
2. Source distribution now has a single canonical license file at repo root.

## Dependency License Inventory (Direct Dependencies)

Data source:

- package metadata from local environment (`importlib.metadata`)
- requirement files listed above

| Package | Version | Detected License |
|---|---:|---|
| fastapi | 0.115.5 | MIT (classifier) |
| ldap3 | 2.9.1 | LGPL v3 |
| pydantic-settings | 2.5.2 | MIT |
| uvicorn | 0.30.6 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| jinja2 | 3.1.6 | BSD (classifier) |
| python-dotenv | 1.2.1 | BSD-3-Clause |
| pytest | 9.0.2 | MIT |
| fhir.resources | 7.1.0 | BSD |
| pydantic | 2.9.2 | MIT |
| pytest-asyncio | 1.3.0 | Apache-2.0 |
| python-dateutil | 2.9.0.post0 | BSD / Apache-2.0 (dual) |
| python-multipart | 0.0.22 | Apache-2.0 |
| python-tds | 1.17.1 | MIT |
| setuptools | 80.10.2 | MIT |
| SQLAlchemy | 2.0.35 | MIT |
| sqlalchemy-pytds | 1.0.2 | MIT |

Note:
- `jinja2` introduces transitive dependency `MarkupSafe` (BSD-3-Clause / metadata `License-Expression`).

## Compliance Conclusion

- The project source code can be licensed under MIT (now configured via `LICENSE`).
- The stack is **not MIT-only** because `ldap3` is LGPLv3.
- This is not a blocker for using MIT for your own code, but redistributing binaries/images must also respect third-party license obligations (especially LGPLv3 for `ldap3`).

## Practical Distribution Checklist

When distributing this stack (source release, artifact bundle, or Docker images):

1. Keep `LICENSE` included.
2. Preserve third-party notices/licenses for dependencies (especially LGPLv3 for `ldap3`).
3. If you need a strict MIT-only dependency policy, replace `ldap3` with an MIT-licensed alternative (functional impact must be evaluated before change).
