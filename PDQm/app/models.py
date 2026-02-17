from __future__ import annotations
import os
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Date

class Base(DeclarativeBase):
    pass

class PatientModel(Base):
    """
    ORM mapping to your real table: dbo.patient (or 'patient' in SQLite for demo).
    Columns exactly as provided:

      [identifier]            -- may be either just a value or 'system|value'
      [name_use]
      [name_family]
      [name_given_0]
      [name_prefix_0]
      [name_text]
      [mothersMaidenName]
      [address_use]
      [address_line_0]
      [address_city]
      [address_postalCode]
      [address_country]
      [tel_home]
      [tel_work]
      [tel_mobile]
      [email]
      [birthdate]
      [deathdate]
      [gender]                -- 'male' | 'female' | 'other' | 'unknown' (normalize upstream if needed)
      [marital_code]          -- server-specific code; we pass through as Coding.code

    Notes:
    - We keep FHIR logical id as a synthetic text primary key 'id'.
      You can map it to your actual PK or generate a stable GUID; for PoC we use a string.
    """

    __tablename__ = "viewPatientPDQm"
    if os.getenv("PDQM_DB_URL", "sqlite:///").lower().startswith("mssql"):
        __table_args__ = {"schema": "dbo"}

    # FHIR logical id (map to your real PK or set via view); text PK for portability
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    identifier: Mapped[str | None] = mapped_column(String(512))

    name_use: Mapped[str | None] = mapped_column(String(40), default="official")
    name_family: Mapped[str | None] = mapped_column(String(200))
    name_given_0: Mapped[str | None] = mapped_column(String(200))
    name_prefix_0: Mapped[str | None] = mapped_column(String(100))
    name_text: Mapped[str | None] = mapped_column(String(400))
    mothersMaidenName: Mapped[str | None] = mapped_column(String(200))

    address_use: Mapped[str | None] = mapped_column(String(40))         # e.g., 'home', 'work', etc.
    address_line_0: Mapped[str | None] = mapped_column(String(255))
    address_city: Mapped[str | None] = mapped_column(String(120))
    address_postalCode: Mapped[str | None] = mapped_column(String(40))
    address_country: Mapped[str | None] = mapped_column(String(80))

    tel_home: Mapped[str | None] = mapped_column(String(40))
    tel_work: Mapped[str | None] = mapped_column(String(40))
    tel_mobile: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(200))

    birthdate: Mapped[Date | None] = mapped_column(Date)
    deathdate: Mapped[Date | None] = mapped_column(Date)

    gender: Mapped[str | None] = mapped_column(String(20))              # male|female|other|unknown
    marital_code: Mapped[str | None] = mapped_column(String(40))
