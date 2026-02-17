from __future__ import annotations
import os
from datetime import date
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from .models import Base, PatientModel

class Settings(BaseSettings):
    pdqm_db_url: str = Field("sqlite:///./pdqm.db", validation_alias="PDQM_DB_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
    )

settings = Settings()

DB_URL = settings.pdqm_db_url

# --- begin minimal pytds shim (necessary for sqlalchemy_pytds) ---
import sys, types
import pytds
try:
    from pytds import tds as _tds
except Exception:
    _tds = None

m = types.ModuleType("pytds.tds_session")
if _tds is not None and hasattr(_tds, "_token_map"):
    # sqlalchemy_pytds verwacht deze naam in tds_session
    m._token_map = _tds._token_map
sys.modules.setdefault("pytds.tds_session", m)

# Zorg dat de dialect-plugin geladen wordt n� de shim
import sqlalchemy_pytds  # noqa: F401
# --- end minimal pytds shim ---

engine = create_engine(DB_URL, future=True, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

def init_db(seed: bool = True) -> None:
    """
    Create schema and optionally seed demo rows (SQLite only).
    In SQL Server, keep the same column names/types on your existing dbo.patient table,
    or point SQLAlchemy to a view that projects your schema into these columns.
    """
    Base.metadata.create_all(engine)
    if not seed:
        return
    # Seed minimal demo rows when empty (SQLite convenience)
    with SessionLocal() as s:
        exists = s.scalar(select(func.count()).select_from(PatientModel)) or 0
        if exists:
            return
        s.add_all([
            PatientModel(
                id=1,
                identifier="428889876",
                name_family="SMITH",
                name_given_0="JOHN",
                name_prefix_0=None,
                name_text="Mr John Smith",
                mothersMaidenName="BROWN",
                address_use="home",
                address_line_0="Main Street 1",
                address_city="Amsterdam",
                address_postalCode="1011 AA",
                address_country="NL",
                tel_home="+31-20-1234567",
                tel_work=None,
                tel_mobile=None,
                email="john.smith@example.org",
                birthdate=date(1980, 5, 12),
                deathdate=None,
                gender="male",
                marital_code="M",
            ),
            PatientModel(
                id="2",
                identifier="347149388",
                name_family="Jansen",
                name_given_0="Maria",
                name_prefix_0=None,
                name_text="Mevr. Maria Jansen",
                mothersMaidenName="De Vries",
                address_use="home",
                address_line_0="Kerkstraat 10",
                address_city="Amstelveen",
                address_postalCode="1181AB",
                address_country="NL",
                tel_home=None,
                tel_work="+31-20-7654321",
                tel_mobile="+31-6-12345678",
                email="maria.jansen@example.org",
                birthdate=date(1975, 1, 1),
                deathdate=None,
                gender="female",
                marital_code="S",
            ),
            PatientModel(
                id=3,
                identifier=None,
                name_family="Smythe",
                name_given_0="Jon",
                name_prefix_0=None,
                name_text="Jon Smythe",
                mothersMaidenName=None,
                address_use="home",
                address_line_0="Baker Street 221 B",
                address_city="London",
                address_postalCode="NW1",
                address_country="GB",
                tel_home=None,
                tel_work=None,
                tel_mobile=None,
                email="jon.smythe@example.org",
                birthdate=date(1980, 5, 12),
                deathdate=None,
                gender="male",
                marital_code=None,
            ),
        ])
        s.commit()
