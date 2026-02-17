# app/pdqm_where.py
# (source: your PDQm_to_WHERE.txt, moved into a module)
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, List, Tuple, Any, Optional
import re

ParamList = List[Tuple[str, Any]]  # [(name, value)]
SQL = str

# ---- Utilities ---------------------------------------------------------------

def _flatten_values(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        raw = [str(x) for x in v]
    else:
        raw = [str(v)]
    out: List[str] = []
    for s in raw:
        out.extend([p for p in (x.strip() for x in s.split(',')) if p])
    return out

def _add_param(params: ParamList, value: Any) -> str:
    name = f"@p{len(params)}"
    params.append((name, value))
    return name

def _sql_like_prefix(column: str, value: str, params: ParamList) -> SQL:
    p = _add_param(params, value + '%')
    return f"{column} COLLATE Latin1_General_CI_AI LIKE {p}"

def _sql_like_contains(column: str, value: str, params: ParamList) -> SQL:
    p = _add_param(params, f"%{value}%")
    return f"{column} COLLATE Latin1_General_CI_AI LIKE {p}"

def _sql_equals_ci(column: str, value: str, params: ParamList) -> SQL:
    p = _add_param(params, value)
    return f"{column} COLLATE Latin1_General_CI_AI = {p}"

# ---- FHIR birthdate parsing --------------------------------------------------

_date_re = re.compile(r'^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$')

def _parse_fhir_date_bounds(s: str):
    m = _date_re.match(s)
    if not m:
        raise ValueError(f"Invalid FHIR date: {s}")
    y = int(m.group(1))
    mo = int(m.group(2)) if m.group(2) else None
    d = int(m.group(3)) if m.group(3) else None

    if mo is None:
        start = date(y, 1, 1)
        end   = date(y + 1, 1, 1)
    elif d is None:
        if not (1 <= mo <= 12):
            raise ValueError(f"Invalid month in FHIR date: {s}")
        start = date(y, mo, 1)
        end = date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)
    else:
        start = date(y, mo, d)
        end   = start + timedelta(days=1)
    return start, end

def _parse_prefix_and_value(raw: str):
    if raw[:2] in ('lt', 'le', 'gt', 'ge', 'ne'):
        return raw[:2], raw[2:]
    if raw[:2] == 'eq':
        return 'eq', raw[2:]
    return 'eq', raw

def _birthdate_condition(column: str, raw_value: str, params: ParamList) -> SQL:
    prefix, datestr = _parse_prefix_and_value(raw_value.strip())
    start, end = _parse_fhir_date_bounds(datestr)
    p_start = _add_param(params, start)
    p_end   = _add_param(params, end)

    if prefix == 'eq':
        return f"({column} >= {p_start} AND {column} < {p_end})"
    if prefix == 'ne':
        return f"({column} < {p_start} OR {column} >= {p_end})"
    if prefix == 'lt':
        return f"{column} < {p_start}"
    if prefix == 'le':
        return f"{column} < {p_end}"
    if prefix == 'gt':
        return f"{column} >= {p_end}"
    if prefix == 'ge':
        return f"{column} >= {p_start}"
    raise ValueError(f"Unsupported birthdate prefix: {prefix}")

# ---- Main builder ------------------------------------------------------------

class PDQmWhereBuilder:
    def __init__(
        self,
        family_column: str = "p.FamilyName",
        gender_column: str = "p.GenderCode",
        birthdate_column: str = "p.BirthDate",
    ):
        self.family_col = family_column
        self.gender_col = gender_column
        self.birthdate_col = birthdate_column

    def build(self, query_params: Dict[str, Any]) -> Tuple[SQL, ParamList]:
        params: ParamList = []
        and_clauses: List[SQL] = []

        # family (string)
        family_sets: List[List[Tuple[str, str]]] = []
        for mode_key in ("family", "family:exact", "family:contains"):
            values = _flatten_values(query_params.get(mode_key))
            if values:
                mode = mode_key.split(':')[1] if ':' in mode_key else 'prefix'
                family_sets.append([(mode, v) for v in values])

        if family_sets:
            group_clauses: List[SQL] = []
            for group in family_sets:
                or_parts: List[SQL] = []
                for mode, v in group:
                    if mode == 'prefix':
                        or_parts.append(_sql_like_prefix(self.family_col, v, params))
                    elif mode == 'contains':
                        or_parts.append(_sql_like_contains(self.family_col, v, params))
                    elif mode == 'exact':
                        or_parts.append(_sql_equals_ci(self.family_col, v, params))
                    else:
                        raise ValueError(f"Unsupported family mode: {mode}")
                group_clauses.append("(" + " OR ".join(or_parts) + ")")
            and_clauses.append("(" + " AND ".join(group_clauses) + ")")

        # gender (token)
        gender_values = _flatten_values(query_params.get("gender"))
        if gender_values:
            or_parts: List[SQL] = []
            for g in gender_values:
                or_parts.append(_sql_equals_ci(self.gender_col, g.lower(), params))
            and_clauses.append("(" + " OR ".join(or_parts) + ")")

        # birthdate (date)
        birthdate_values = _flatten_values(query_params.get("birthdate"))
        if birthdate_values:
            or_parts: List[SQL] = []
            for bd in birthdate_values:
                or_parts.append(_birthdate_condition(self.birthdate_col, bd, params))
            and_clauses.append("(" + " OR ".join(or_parts) + ")")

        where_sql = "WHERE " + " AND ".join(and_clauses) if and_clauses else ""
        return where_sql, params
