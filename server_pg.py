"""
PostgreSQL version of the Spire local site server.

Usage:
    python3 local_site/server_pg.py --host 127.0.0.1 --port 8000

Requires environment variables:
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

from __future__ import annotations

import argparse
import json
import time
import mimetypes
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from db.pg_config import get_conn, get_pg_config

WEB_ROOT = ROOT / "web"
ANTISMASH_ROOT = ROOT / "antismash_results"
BIOSAMPLE_OVERRIDE_PATH = ROOT / "config" / "biosample_url_overrides.json"
MAP_FILTERS_PATHS = (
    ROOT / "config" / "sample_global_distribution_filters.json",
)
PAGE_ROUTES = {
    "/": "BGCMAP.html",
    "/BGCMAP": "BGCMAP.html",
    "/BGCMAP.html": "BGCMAP.html",
    "/stats": "stats.html",
    "/stats.html": "stats.html",
    "/stat.html": "stats.html",
    "/sample": "sample.html",
    "/sample.html": "sample.html",
    "/tax": "tax.html",
    "/tax.html": "tax.html",
    "/bgc": "bgc.html",
    "/bgc.html": "bgc.html",
    "/download": "download.html",
    "/download.html": "download.html",
    "/np": "np.html",
    "/np.html": "np.html",
    "/help": "help.html",
    "/help.html": "help.html",
}
VALID_PAGE_SIZES = {10, 25, 50, 100}
NCBI_BIOSAMPLE_RE = re.compile(r"^(SAMN|SAMEA|SAMD)")
NCBI_SRA_RE = re.compile(r"^(SRR|ERR|DRR|SRX|ERX|DRX|SRS|ERS|DRS|SRP|ERP|DRP)")


# ── Count cache (MV is read-only, counts never change) ────
_count_cache: dict = {}

def cached_count(conn, sql: str, params: list) -> int:
    key = (sql, tuple(params))
    if key in _count_cache:
        return _count_cache[key]
    cnt = pg_query_one(conn, sql, params)["cnt"]
    _count_cache[key] = cnt
    return cnt


def estimated_count(conn, sql: str, params: list) -> int:
    key = ("est", sql, tuple(params))
    if key in _count_cache:
        return _count_cache[key]
    import json
    row = pg_query_one(conn, f"EXPLAIN (FORMAT JSON) {sql}", params)
    raw = row["QUERY PLAN"]
    if isinstance(raw, str):
        raw = json.loads(raw)

    def find_scan_rows(node):
        nt = node.get("Node Type", "")
        if nt in {"Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Index Scan",
                   "Bitmap Heap Scan", "Parallel Seq Scan", "Parallel Index Scan",
                   "Parallel Index Only Scan", "Parallel Bitmap Heap Scan"}:
            return int(node.get("Plan Rows", 0))
        for child in node.get("Plans", []):
            r = find_scan_rows(child)
            if r:
                return r
        return int(node.get("Plan Rows", 0))

    plan = raw[0]["Plan"]
    cnt = find_scan_rows(plan)
    if cnt < 1:
        cnt = int(plan.get("Plan Rows", 0))
    _count_cache[key] = cnt
    return cnt


def open_db() -> psycopg2.extensions.connection:
    conn = get_conn(autocommit=True, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    cur.execute("SET search_path TO bgcmap, public")
    cur.close()
    return conn


def pg_query(conn, sql: str, params=None):
    """Execute query and return all rows as RealDictRow list."""
    cur = conn.cursor()
    try:
        if params is not None:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur.fetchall()
    finally:
        cur.close()


def pg_query_one(conn, sql: str, params=None):
    """Execute query and return one row as RealDictRow or None."""
    cur = conn.cursor()
    try:
        if params is not None:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return cur.fetchone()
    finally:
        cur.close()



def row_to_dict(row) -> dict:
    """Convert a RealDictRow to a JSON-safe plain dict."""
    if row is None:
        return {}
    from datetime import date, datetime
    from decimal import Decimal
    result = {}
    for k, v in dict(row).items():
        if isinstance(v, Decimal):
            result[k] = float(v)
        elif isinstance(v, (date, datetime)):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ── Environment helpers ───────────────────────────────────

def canonicalize_group_text(value: str) -> str:
    text = (value or "").strip().replace("_", " ")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text)
    return text.lower()


GROUP_LABELS = {
    "A": "aquatic environment",
    "A1": "marine/saline water environment",
    "A2": "fresh water environment",
    "A3": "groundwater environment",
    "A4": "special aquatic environment",
    "B": "terrestrial environment",
    "B1": "natural terrestrial environment",
    "B2": "soil environment",
    "B3": "cave/subterranean environment",
    "C": "artificial/engineered environment",
    "C1": "agriculture/aquaculture environment",
    "C2": "industrial/treatment facilities",
    "C3": "building/urban environment",
    "C4": "other artificial environment",
    "D": "host-associated environment",
    "D1": "animal host (internal/surface)",
    "D2": "plant-associated environment",
    "D3": "microbe-associated environment",
    "D4": "food/feed environment",
    "E": "special/extreme environment",
    "E1": "high temperature/geothermal environment",
    "E2": "contaminated/degraded environment",
    "E3": "artificial simulation environment",
    "F": "other environment",
    "F1": "mixed/composite environment",
    "F2": "developmental stage",
    "F3": "process environment",
}

@dataclass
class AntismashCatalog:
    html_urls: Dict[str, str]
    anchor_urls: Dict[str, str]


def safe_page_size(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 25
    return value if value in VALID_PAGE_SIZES else 25


def safe_page(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def load_biosample_overrides() -> Dict[str, str]:
    if not BIOSAMPLE_OVERRIDE_PATH.exists():
        return {}
    try:
        payload = json.loads(BIOSAMPLE_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(sample_id).strip(): str(url).strip()
        for sample_id, url in payload.items()
        if str(sample_id).strip() and str(url).strip()
    }


def ncbi_url(
    sample_id: Optional[str],
    biosample_accession: Optional[str] = None,
    primary_sample_accession: Optional[str] = None,
) -> Optional[str]:
    direct_candidates = [biosample_accession, sample_id]
    for candidate in direct_candidates:
        if not candidate:
            continue
        if candidate in BIOSAMPLE_URL_OVERRIDES:
            return BIOSAMPLE_URL_OVERRIDES[candidate]
        if NCBI_BIOSAMPLE_RE.match(candidate):
            return f"https://www.ncbi.nlm.nih.gov/biosample/{quote(candidate)}"
    sra_candidates = [sample_id, primary_sample_accession]
    for candidate in sra_candidates:
        if not candidate:
            continue
        if NCBI_SRA_RE.match(candidate):
            return f"https://www.ncbi.nlm.nih.gov/sra/{quote(candidate)}"
    return None



def load_map_filters() -> Dict[str, dict]:
    for path in MAP_FILTERS_PATHS:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return payload if isinstance(payload, dict) else {}
    return {}




@lru_cache(maxsize=1)
def load_sample_env_lookup() -> Dict[str, dict]:
    conn = open_db()
    try:
        rows = pg_query(conn, """
            SELECT
              sample_id,
              COALESCE(biome1, '') AS biome1,
              COALESCE(biome2, '') AS biome2,
              COALESCE(biome3, '') AS biome3,
              latitude AS lat,
              longitude AS lon
            FROM sample
        """)
    finally:
        conn.close()
    return {
        row["sample_id"]: {
            "biome1": row["biome1"] or "",
            "biome2": row["biome2"] or "",
            "biome3": row["biome3"] or "",
            "lat": row["lat"],
            "lon": row["lon"],
        }
        for row in rows
        if row["sample_id"]
    }



def normalize_group_label(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    return GROUP_LABELS.get(value, value)


def search_sample_ids_by_env_text(search: str) -> List[str]:
    term = (search or "").strip().lower()
    if not term:
        return []
    matches: set[str] = set()
    for sample_id, env in load_sample_env_lookup().items():
        values = [
            sample_id,
            env.get("biome1") or "",
            env.get("biome2") or "",
            env.get("biome3") or "",
            normalize_group_label(env.get("biome1") or ""),
            normalize_group_label(env.get("biome2") or ""),
        ]
        if any(term in str(value).lower() for value in values if value):
            matches.add(sample_id)
    for payload in load_map_filters().values():
        label = str(payload.get("label") or "").strip().lower()
        if not label:
            continue
        if term in label:
            for sid in payload.get("sample_ids") or []:
                if sid:
                    matches.add(str(sid))
    return sorted(matches)



def expand_bigscape_type_aliases(raw: str) -> List[str]:
    value = (raw or "").strip()
    if not value:
        return []
    alias_map = {
        "pks": ["PKSother", "PKSI", "PKS-NRP_Hybrids"],
        "saccharide": ["Saccharides"],
        "other": ["Others"],
    }
    return alias_map.get(value.lower(), [value])


def build_case_insensitive_any_clause(expr: str, values: List[str]) -> Tuple[str, List]:
    clean_values = [str(v).strip() for v in values if str(v).strip()]
    if not clean_values:
        return "1 = 0", []
    return "(" + " OR ".join(f"{expr} ILIKE %s" for _ in clean_values) + ")", clean_values


def build_in_clauses(column: str, values: List[str], chunk_size: int = 800) -> Tuple[str, List]:
    chunks = [values[i:i + chunk_size] for i in range(0, len(values), chunk_size)]
    clauses = []
    params: List = []
    for chunk in chunks:
        placeholders = ",".join("%s" for _ in chunk)
        clauses.append(f"{column} IN ({placeholders})")
        params.extend(chunk)
    return "(" + " OR ".join(clauses) + ")", params


def parse_filters(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def build_text_clause(expr: str, operator: str, value: str) -> Tuple[str, List]:
    raw = (value or "").strip()
    lowered = raw.lower()
    if operator in ("contains", "equals"):
        parts = [p.strip() for p in re.split(r"\s*[，,]\s*", lowered) if p.strip()]
        if len(parts) > 1:
            clauses = [f"lower({expr}) LIKE %s" for _ in parts]
            return "(" + " AND ".join(clauses) + ")", [f"%{p}%" for p in parts]
    if operator == "contains":
        return f"lower({expr}) LIKE %s", [f"%{lowered}%"]
    if operator == "equals":
        return f"lower({expr}) = %s", [lowered]
    if operator == "not_equals":
        return f"lower({expr}) <> %s", [lowered]
    if operator == "is_null":
        return f"lower({expr}) IS NULL", []
    if operator == "is_not_null":
        return f"lower({expr}) IS NOT NULL", []
    return "1 = 1", []


def build_date_clause(expr: str, operator: str, value: str, value_secondary: str = "") -> Tuple[str, List]:
    month_ends = {
        "01": "31", "02": "28", "03": "31", "04": "30", "05": "31", "06": "30",
        "07": "31", "08": "31", "09": "30", "10": "31", "11": "30", "12": "31",
    }
    month_end_case = " CASE SUBSTR({0}, 6, 2) " + " ".join(
        f"WHEN '{m}' THEN '{d}'" for m, d in month_ends.items()
    ) + " END"
    slash_month_end = f" CASE SUBSTR({expr}, 14, 2) " + " ".join(
        f"WHEN '{m}' THEN '{d}'" for m, d in month_ends.items()
    ) + " END"

    # PG: use ~ (regex) instead of GLOB
    start_text = (
        f"CASE"
        f" WHEN {expr} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}/[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'"
        f"   THEN SUBSTR({expr}, 1, 10)"
        f" WHEN {expr} ~ '^[0-9]{{4}}-[0-9]{{2}}/[0-9]{{4}}-[0-9]{{2}}'"
        f"   THEN SUBSTR({expr}, 1, 7) || '-01'"
        # Year ranges with dash: "2013-2014"
        f" WHEN {expr} ~ '^[0-9]{{4}}-[0-9]{{4}}$'"
        f"   THEN SUBSTR({expr}, 1, 4) || '-01-01'"
        # Month ranges with dash: "2012-11-2013-11"
        f" WHEN {expr} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{4}}-[0-9]{{2}}$'"
        f"   THEN SUBSTR({expr}, 1, 7) || '-01'"
        f" WHEN {expr} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' THEN SUBSTR({expr}, 1, 10)"
        f" WHEN {expr} ~ '^[0-9]{{4}}/[0-9]{{4}}'"
        f"   THEN SUBSTR({expr}, 1, 4) || '-01-01'"
        f" WHEN {expr} ~ '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}'"
        f"   THEN SUBSTR({expr}, 7, 4) || '-' || SUBSTR({expr}, 1, 2) || '-' || SUBSTR({expr}, 4, 2)"
        f" WHEN {expr} ~ '^[0-9]{{4}}-[0-9]{{2}}' THEN {expr} || '-01'"
        f" WHEN {expr} ~ '^[0-9]{{4}}' THEN {expr} || '-01-01'"
        f" ELSE {expr} END"
    )
    end_text = (
        "CASE"
        " WHEN " + expr + " ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}'"
        "   THEN SUBSTR(" + expr + ", 12, 10)"
        " WHEN " + expr + " ~ '^[0-9]{4}-[0-9]{2}/[0-9]{4}-[0-9]{2}'"
        "   THEN SUBSTR(" + expr + ", 9, 7) || '-' || " + slash_month_end +
        # Year range with dash: "2013-2014"
        " WHEN " + expr + " ~ '^[0-9]{4}-[0-9]{4}$'"
        "   THEN SUBSTR(" + expr + ", 6, 4) || '-12-31'" +
        # Month range with dash: "2012-11-2013-11"  
        " WHEN " + expr + " ~ '^[0-9]{4}-[0-9]{2}-[0-9]{4}-[0-9]{2}$'"
        "   THEN SUBSTR(" + expr + ", 9, 7) || '-28'" +
        " WHEN " + expr + " ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN SUBSTR(" + expr + ", 1, 10)" +
        " WHEN " + expr + " ~ '^[0-9]{4}/[0-9]{4}'"
        "   THEN SUBSTR(" + expr + ", 6, 4) || '-12-31'" +
        " WHEN " + expr + " ~ '^[0-9]{2}/[0-9]{2}/[0-9]{4}'"
        "   THEN SUBSTR(" + expr + ", 7, 4) || '-' || SUBSTR(" + expr + ", 1, 2) || '-' || SUBSTR(" + expr + ", 4, 2)" +
        " WHEN " + expr + " ~ '^[0-9]{4}-[0-9]{2}'"
        "   THEN " + expr + " || '-' || " + month_end_case.format(expr) +
        " WHEN " + expr + " ~ '^[0-9]{4}' THEN " + expr + " || '-12-31'" +
        " ELSE " + expr + " END"
    )

    def _norm_lo(v: str) -> str:
        v = (v or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v): return v
        if re.match(r"^\d{4}-\d{2}$", v): return v + "-01"
        if re.match(r"^\d{4}$", v): return v + "-01-01"
        if re.match(r"^\d{4}/\d{4}$", v): return v[:4] + "-01-01"
        if re.match(r"^\d{4}-\d{2}/\d{4}-\d{2}$", v): return v[:7] + "-01"
        if re.match(r"^\d{2}/\d{2}/\d{4}$", v): return v[6:] + "-" + v[:2] + "-" + v[3:5]
        return v

    def _norm_hi(v: str) -> str:
        v = (v or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", v): return v
        if re.match(r"^\d{4}-\d{2}$", v):
            m = v[5:7]
            return v + "-" + month_ends.get(m, "28")
        if re.match(r"^\d{4}$", v): return v + "-12-31"
        if re.match(r"^\d{4}/\d{4}$", v): return v[5:] + "-12-31"
        if re.match(r"^\d{4}-\d{2}/\d{4}-\d{2}$", v):
            m = v[12:14]
            return v[8:] + "-" + month_ends.get(m, "28")
        if re.match(r"^\d{2}/\d{2}/\d{4}$", v): return v[6:] + "-" + v[:2] + "-" + v[3:5]
        return v

    if operator == "between":
        lower_raw = (value or "").strip()
        upper_raw = (value_secondary or "").strip()
        if not lower_raw and not upper_raw:
            return "1 = 0", []
        if lower_raw and upper_raw:
            lo = _norm_lo(lower_raw)
            hi = _norm_hi(upper_raw)
            if lo > hi:
                lo, hi = hi, lo
            return f"{start_text} <= %s AND {end_text} >= %s", [hi, lo]
        if lower_raw:
            lo = _norm_lo(lower_raw)
            return f"{end_text} >= %s", [lo]
        hi = _norm_hi(upper_raw)
        return f"{start_text} <= %s", [hi]

    raw = (value or "").strip()
    if operator == "equals":
        lo = _norm_lo(raw)
        hi = _norm_hi(raw)
        return f"{start_text} <= %s AND {end_text} >= %s", [hi, lo]
    if operator == "gt":
        return f"{end_text} > %s", [_norm_hi(raw)]
    if operator == "gte":
        return f"{end_text} >= %s", [_norm_lo(raw)]
    if operator == "lt":
        return f"{start_text} < %s", [_norm_lo(raw)]
    if operator == "lte":
        return f"{start_text} <= %s", [_norm_hi(raw)]
    if operator == "contains":
        return f"lower({expr}) LIKE %s", [f"%{raw.lower()}%"]
    if operator == "is_null":
        return f"COALESCE({expr}, '') = ''", []
    if operator == "is_not_null":
        return f"COALESCE({expr}, '') <> ''", []
    return "1 = 1", []


def build_numeric_clause(expr: str, operator: str, value: str, value_secondary: str = "") -> Tuple[str, List]:
    if operator == "between":
        lower_raw = (value or "").strip()
        upper_raw = (value_secondary or "").strip()
        try:
            lower = float(lower_raw) if lower_raw else None
            upper = float(upper_raw) if upper_raw else None
        except (TypeError, ValueError):
            return "1 = 0", []
        if lower is None and upper is None:
            return "1 = 0", []
        if lower is not None and upper is not None:
            lo, hi = sorted((lower, upper))
            return f"{expr} >= %s AND {expr} <= %s", [lo, hi]
        if lower is not None:
            return f"{expr} >= %s", [lower]
        return f"{expr} <= %s", [upper]
    if operator == "is_null":
        return f"COALESCE({expr}::text, '') = ''", []
    if operator == "is_not_null":
        return f"COALESCE({expr}::text, '') <> ''", []
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "1 = 0", []
    # Use int if value is integer to avoid float cast breaking btree index
    param: object = int(number) if number == int(number) else number
    op_map = {"equals": "=", "not_equals": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    sql_op = op_map.get(operator)
    if not sql_op:
        return "1 = 1", []
    return f"{expr} {sql_op} %s", [param]


def matches_text_candidates(candidates: List[str], operator: str, value: str) -> bool:
    clean_candidates = [str(c or "").strip().lower() for c in candidates]
    term = (value or "").strip().lower()
    if operator == "is_null": return not any(clean_candidates)
    if operator == "is_not_null": return any(clean_candidates)
    if not term: return False
    if operator == "contains": return any(term in c for c in clean_candidates if c)
    if operator == "equals": return any(term == c for c in clean_candidates if c)
    if operator == "not_equals": return all((not c) or term != c for c in clean_candidates)
    return False


def match_env_sample_ids(field_key: str, operator: str, value: str) -> List[str]:
    matches: List[str] = []
    for sample_id, env in load_sample_env_lookup().items():
        raw = env.get(field_key) or ""
        pretty = normalize_group_label(raw).replace("_", " ")
        candidates = [raw, normalize_group_label(raw), raw.replace("_", " "), pretty]
        if matches_text_candidates(candidates, operator, value):
            matches.append(sample_id)
    return matches


def _all_sample_ids() -> set[str]:
    return {str(sid) for sid in load_sample_env_lookup()}


def _all_map_sample_ids(kind: str) -> set[str]:
    ids: set[str] = set()
    for payload in load_map_filters().values():
        if (payload.get("kind") or "").strip() != kind: continue
        for sample_id in payload.get("sample_ids") or []:
            if sample_id: ids.add(str(sample_id))
    return ids


def match_map_sample_ids(map_kind: str, operator: str, value: str) -> List[str]:
    expected_kind = "board" if map_kind == "map_region" else "country"
    if operator == "is_null":
        all_ids = _all_map_sample_ids(expected_kind)
        return sorted(_all_sample_ids() - all_ids)
    if operator == "is_not_null":
        return sorted(_all_map_sample_ids(expected_kind))
    matches: set[str] = set()
    for payload in load_map_filters().values():
        if (payload.get("kind") or "").strip() != expected_kind: continue
        label = str(payload.get("label") or "").strip()
        if not label: continue
        if matches_text_candidates([label], operator, value):
            for sid in payload.get("sample_ids") or []:
                if sid: matches.add(str(sid))
    return sorted(matches)


def match_geo_region_ids(operator: str, value: str) -> List[str]:
    if operator == "is_null":
        all_geo = _all_map_sample_ids("board") | _all_map_sample_ids("country") | _all_map_sample_ids("ocean-range")
        return sorted(_all_sample_ids() - all_geo)
    if operator == "is_not_null":
        all_geo = _all_map_sample_ids("board") | _all_map_sample_ids("country") | _all_map_sample_ids("ocean-range")
        return sorted(all_geo)
    matches: set[str] = set()
    search = str(value or "").strip()
    if not search: return []
    for payload in load_map_filters().values():
        label = str(payload.get("label") or "").strip()
        if not label: continue
        if matches_text_candidates([label], operator, search):
            for sid in payload.get("sample_ids") or []:
                if sid: matches.add(str(sid))
    return sorted(matches)


def match_env_numeric_sample_ids(field_key: str, operator: str, value: str, value_secondary: str = "") -> List[str]:
    lower_raw = (value or "").strip()
    upper_raw = (value_secondary or "").strip()
    try:
        lower = float(lower_raw) if lower_raw else None
        upper = float(upper_raw) if upper_raw else None
    except (TypeError, ValueError):
        return []
    if operator == "between" and lower is not None and upper is not None:
        lower, upper = sorted((lower, upper))
    matches: List[str] = []
    for sample_id, env in load_sample_env_lookup().items():
        raw = env.get(field_key)
        if operator == "is_null":
            if raw is None or str(raw).strip() == "":
                matches.append(sample_id)
            continue
        if operator == "is_not_null":
            if raw is not None and str(raw).strip() != "":
                matches.append(sample_id)
            continue
        if raw is None: continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        ok = False
        if operator == "between":
            if lower is not None and upper is not None:
                ok = lower <= number <= upper
            elif lower is not None:
                ok = number >= lower
            elif upper is not None:
                ok = number <= upper
        elif lower is None:
            ok = False
        elif operator == "equals": ok = number == lower
        elif operator == "gt": ok = number > lower
        elif operator == "gte": ok = number >= lower
        elif operator == "lt": ok = number < lower
        elif operator == "lte": ok = number <= lower
        if ok: matches.append(sample_id)
    return matches


@lru_cache(maxsize=1)
def load_biome_selector_options() -> dict:
    env_lookup = load_sample_env_lookup()
    biome1_values: set[str] = set()
    biome2_values: set[str] = set()
    biome3_values: set[str] = set()
    biome2_by_biome1: dict[str, set[str]] = defaultdict(set)
    biome3_by_biome1: dict[str, set[str]] = defaultdict(set)
    biome3_by_biome2: dict[str, set[str]] = defaultdict(set)
    for env in env_lookup.values():
        b1 = (env.get("biome1") or "").strip()
        b2 = (env.get("biome2") or "").strip()
        b3 = (env.get("biome3") or "").strip()
        if b1:
            biome1_values.add(b1)
        if b2:
            biome2_values.add(b2)
            if b1: biome2_by_biome1[b1].add(b2)
        if b3:
            biome3_values.add(b3)
            if b1: biome3_by_biome1[b1].add(b3)
            if b2: biome3_by_biome2[b2].add(b3)

    def sorter(value: str) -> tuple:
        return (normalize_group_label(value).replace("_", " ").lower(), value.lower())

    return {
        "biome1": sorted(biome1_values, key=sorter),
        "biome2_all": sorted(biome2_values, key=sorter),
        "biome3_all": sorted(biome3_values, key=sorter),
        "biome2_by_biome1": {k: sorted(v, key=sorter) for k, v in sorted(biome2_by_biome1.items(), key=lambda it: sorter(it[0]))},
        "biome3_by_biome1": {k: sorted(v, key=sorter) for k, v in sorted(biome3_by_biome1.items(), key=lambda it: sorter(it[0]))},
        "biome3_by_biome2": {k: sorted(v, key=sorter) for k, v in sorted(biome3_by_biome2.items(), key=lambda it: sorter(it[0]))},
    }


_taxon_cache: Optional[dict] = None

def load_taxon_selector_options() -> dict:
    global _taxon_cache
    if _taxon_cache is not None:
        return _taxon_cache
    rank_values: dict[str, set[str]] = {
        "domain": set(), "phylum": set(), "class_name": set(),
        "order_name": set(), "genus": set(), "species": set(),
    }
    relation_keys = (
        "phylum_by_domain", "class_by_domain", "class_by_phylum",
        "order_by_domain", "order_by_phylum", "order_by_class_name",
        "genus_by_domain", "genus_by_phylum", "genus_by_class_name", "genus_by_order_name",
        "species_by_domain", "species_by_phylum", "species_by_class_name",
        "species_by_order_name", "species_by_genus",
    )
    relations: dict[str, dict[str, set[str]]] = {key: defaultdict(set) for key in relation_keys}

    conn = open_db()
    try:
        rows = pg_query(conn, """
            SELECT
              COALESCE(domain, '') AS domain,
              COALESCE(phylum, '') AS phylum,
              COALESCE(class_name, '') AS class_name,
              COALESCE(order_name, '') AS order_name,
              COALESCE(genus, '') AS genus,
              COALESCE(species, '') AS species
            FROM mv_mag_page
        """)
        for row in rows:
            d = (row["domain"] or "").strip()
            p = (row["phylum"] or "").strip()
            c = (row["class_name"] or "").strip()
            o = (row["order_name"] or "").strip()
            g = (row["genus"] or "").strip()
            s = (row["species"] or "").strip()
            if d: rank_values["domain"].add(d)
            if p:
                rank_values["phylum"].add(p)
                if d: relations["phylum_by_domain"][d].add(p)
            if c:
                rank_values["class_name"].add(c)
                if d: relations["class_by_domain"][d].add(c)
                if p: relations["class_by_phylum"][p].add(c)
            if o:
                rank_values["order_name"].add(o)
                if d: relations["order_by_domain"][d].add(o)
                if p: relations["order_by_phylum"][p].add(o)
                if c: relations["order_by_class_name"][c].add(o)
            if g:
                rank_values["genus"].add(g)
                if d: relations["genus_by_domain"][d].add(g)
                if p: relations["genus_by_phylum"][p].add(g)
                if c: relations["genus_by_class_name"][c].add(g)
                if o: relations["genus_by_order_name"][o].add(g)
            if s:
                rank_values["species"].add(s)
                if d: relations["species_by_domain"][d].add(s)
                if p: relations["species_by_phylum"][p].add(s)
                if c: relations["species_by_class_name"][c].add(s)
                if o: relations["species_by_order_name"][o].add(s)
                if g: relations["species_by_genus"][g].add(s)
        has_null = pg_query_one(conn, "SELECT 1 FROM mv_mag_page WHERE domain IS NULL OR domain = '' LIMIT 1") is not None
    finally:
        conn.close()

    if has_null:
        rank_values["domain"].add("Unclassified")

    def sorter(value: str) -> str:
        return value.lower()

    payload = {
        "domain_all": sorted(rank_values["domain"], key=sorter),
        "phylum_all": sorted(rank_values["phylum"], key=sorter),
        "class_all": sorted(rank_values["class_name"], key=sorter),
        "order_all": sorted(rank_values["order_name"], key=sorter),
        "genus_all": sorted(rank_values["genus"], key=sorter),
        "species_all": sorted(rank_values["species"], key=sorter),
    }
    payload.update({
        key: {parent: sorted(values, key=sorter) for parent, values in sorted(m.items(), key=lambda it: sorter(it[0]))}
        for key, m in relations.items()
    })
    _taxon_cache = payload
    return payload


@lru_cache(maxsize=1)
def load_home_phylo_payload() -> dict:
    conn = open_db()
    try:
        rows = pg_query(conn, """
            SELECT
              COALESCE(NULLIF(domain, ''), 'Unclassified') AS domain_name,
              COALESCE(NULLIF(phylum, ''), 'Unclassified') AS phylum_name,
              COALESCE(NULLIF(genus, ''), 'Unclassified') AS genus_name,
              COUNT(*) AS mag_count
            FROM mv_mag_page
            GROUP BY 1, 2, 3
        """)
    finally:
        conn.close()

    domain_totals: Counter = Counter()
    phylum_totals: dict[str, Counter] = defaultdict(Counter)
    genus_by_phylum: dict[tuple, Counter] = defaultdict(Counter)
    unclassified_domain_count = 0

    for row in rows:
        dn = row["domain_name"]
        pn = row["phylum_name"]
        gn = row["genus_name"]
        mc = int(row["mag_count"] or 0)
        if dn == "Unclassified":
            unclassified_domain_count += mc
            continue
        domain_totals[dn] += mc
        phylum_totals[dn][pn] += mc
        if gn != "Unclassified":
            genus_by_phylum[(dn, pn)][gn] += mc

    PRIORITY_DOMAINS = ["Bacteria", "Archaea"]
    ordered_domain_names = []
    for pd in PRIORITY_DOMAINS:
        if pd in domain_totals: ordered_domain_names.append(pd)
    for name, _ in domain_totals.most_common():
        if name not in ordered_domain_names: ordered_domain_names.append(name)

    domains = []
    for dn in ordered_domain_names:
        dmc = domain_totals[dn]
        phyla = []
        for pn, pmc in phylum_totals[dn].most_common():
            rg, rgc = ("", 0)
            if genus_by_phylum[(dn, pn)]:
                rg, rgc = genus_by_phylum[(dn, pn)].most_common(1)[0]
            phyla.append({"name": pn, "mag_count": pmc, "representative_genus": rg, "representative_genus_count": rgc})
        domains.append({"name": dn, "mag_count": dmc, "phyla": phyla})
    return {"root_label": "Cellular life", "domains": domains, "unclassified_mag_count": unclassified_domain_count,
            "note": "Phyla are sorted by MAG count within each domain."}


def build_taxon_clause(operator: str, taxon_value, table_prefix: str = "m") -> Tuple[str, List]:
    rank_targets = (
        ("domain", f"{table_prefix}.domain"),
        ("phylum", f"{table_prefix}.phylum"),
        ("class_name", f"{table_prefix}.class_name"),
        ("order_name", f"{table_prefix}.order_name"),
        ("genus", f"{table_prefix}.genus"),
        ("species", f"{table_prefix}.species"),
    )
    if operator == "is_null":
        return "(" + " AND ".join(f"COALESCE({e}, '') = ''" for _, e in rank_targets) + ")", []
    if operator == "is_not_null":
        return "(" + " OR ".join(f"COALESCE({e}, '') <> ''" for _, e in rank_targets) + ")", []
    if not isinstance(taxon_value, dict):
        return "", []
    clauses: List[str] = []
    params: List = []
    for key, expr in rank_targets:
        raw = str(taxon_value.get(key) or "").strip()
        if not raw: continue
        if raw == "Unclassified":
            clauses.append(f"{expr} IS NULL")
        else:
            clause, cp = build_text_clause(expr, operator, raw)
            clauses.append(clause)
            params.extend(cp)
    if not clauses: return "", []
    return "(" + " AND ".join(clauses) + ")", params



def build_source_match_clause(scope: str, field: str, operator: str, value: str) -> Tuple[str, List]:
    column_map = {"category": "category_primary", "product": "product", "bgc_id": "bgc_id", "gcf_id": "gcf_id"}
    col = column_map.get(field, "product")
    expr = f"src.{col}"
    if scope == "genome":
        prefix = ("EXISTS (SELECT 1 FROM bgc b2 JOIN mag m2 ON m2.mag_pk = b2.mag_pk "
                  "JOIN bgc AS src ON src.bgc_name = b2.bgc_name WHERE m2.genome_id = v.genome_id AND ")
    else:
        prefix = "EXISTS (SELECT 1 FROM bgc src WHERE src.bgc_name = v.bgc_name AND "
    if field == "category" and operator == "equals":
        clause, p = build_case_insensitive_any_clause(expr, expand_bigscape_type_aliases(value))
    else:
        clause, p = build_text_clause(expr, operator, value)
    return prefix + clause + ")", p


def compile_filter_rule(node: dict, page_kind: str, conn) -> Tuple[str, List]:
    field = (node.get("field") or "").strip()
    operator = (node.get("operator") or "contains").strip()
    value = node.get("value")
    value_secondary = node.get("value_secondary")
    if operator == "between":
        if str(value or "").strip() == "" and str(value_secondary or "").strip() == "":
            return "", []
    elif operator not in {"is_null", "is_not_null"} and str(value or "").strip() == "":
        if field == "taxon" and isinstance(node.get("taxon"), dict):
            if not any(str(node["taxon"].get(k) or "").strip() for k in ("domain", "phylum", "class_name", "order_name", "genus", "species")):
                return "", []
        else:
            return "", []

    field_maps = {
        "sample": {
            "sample_id": ("text", "sample_id"),
            "project": ("text", "COALESCE(project, '')"),
            "collection_time": ("date", "collection_time"),
            "category": ("text", "COALESCE(category, '')"),
            "map_region": ("map_sample", "map_region"),
            "country": ("map_sample", "country"),
            "geo_region": ("geo_region", "COALESCE(geo_region, '')"),
            "biome1": ("text", "biome1"),
            "biome2": ("text", "biome2"),
            "biome3": ("text", "biome"),
            "lat": ("env_number", "lat"),
            "lon": ("env_number", "lon"),
            "mag_count": ("number", "mag_count"),
            "bgc_count": ("number", "bgc_count"),
        },
        "tax": {
            "taxon": ("taxon", "taxon_v"),
            "phylum": ("text", "COALESCE(v.phylum, '')"),
            "class_name": ("text", "COALESCE(v.class_name, '')"),
            "order_name": ("text", "COALESCE(v.order_name, '')"),
            "domain": ("text", "COALESCE(v.domain, '')"),
            "genus": ("text", "COALESCE(v.genus, '')"),
            "species": ("text", "COALESCE(v.species, '')"),
            "sample_id": ("text", "v.sample_id"),
            "genome_id": ("text", "v.genome_id"),
            "biome1": ("text", "v.biome1"),
            "biome2": ("text", "v.biome2"),
            "biome3": ("text", "v.biome"),
            "category": ("text", "COALESCE(v.category_preview, '')"),
            "bgc_count": ("number", "v.bgc_count"),
            "completeness": ("number", "v.completeness"),
            "contamination": ("number", "v.contamination"),
        },
        "bgc": {
            "bgc_id": ("number", "v.bgc_source_id"),
            "genome_id": ("text", "v.genome_id"),
            "sample_id": ("text", "v.sample_id"),
            "gcf_id": ("number", "v.gcf_id"),
            "product": ("text", "v.product"),
            "category": ("text", "v.category"),
            "species": ("text", "v.species"),
            "biome1": ("text", "v.biome1"),
            "biome2": ("text", "v.biome2"),
            "biome3": ("text", "v.biome"),
            "length": ("number", "v.length"),
            "membership_value": ("number", "v.membership_value"),
            "np_pathway": ("text", "v.np_pathway"),
            "np_superclass": ("text", "v.np_superclass"),
            "np_class": ("text", "v.np_class"),
            "contig_edge": ("bool", "v.contig_edge"),
        },
        "nps": {
            "bgc_id": ("number", "v.bgc_source_id"),
            "np_pathway": ("text", "v.np_pathway"),
            "np_superclass": ("text", "v.np_superclass"),
            "np_class": ("text", "v.np_class"),
            "gcf_id": ("number", "v.gcf_id"),
            "membership_value": ("number", "v.membership_value"),
        },
    }
    kind_map = field_maps.get(page_kind, {})
    spec = kind_map.get(field)
    if not spec: return "1 = 1", []
    ftype, target = spec
    if ftype == "text" and operator == "equals":
        contains_fields = {
            "sample": {"sample_id", "project", "category"},
            "tax": {"sample_id", "category"},
            "bgc": {"product", "sample_id"},
            "nps": {"np_pathway", "np_superclass", "np_class"},
        }
        if field in contains_fields.get(page_kind, set()):
            operator = "contains"
    if ftype == "text": return build_text_clause(target, operator, str(value or ""))
    if ftype == "bool":
        val = str(value or "").strip().lower()
        if val in ("true", "1", "yes"): return f"{target} IS TRUE", []
        if val in ("false", "0", "no"): return f"{target} IS FALSE", []
        return f"{target} IS NULL", []
    if ftype == "date": return build_date_clause(target, operator, str(value or ""), str(value_secondary or ""))
    if ftype == "number": return build_numeric_clause(target, operator, str(value or ""), str(value_secondary or ""))
    if ftype == "taxon": return build_taxon_clause(operator, node.get("taxon"), "v" if target == "taxon_v" else "m")
    if ftype == "env_sample":
        sample_ids = match_env_sample_ids(target, operator, str(value or ""))
        if sample_ids:
            col = "sample_id" if page_kind == "sample" else "v.sample_id"
            return build_in_clauses(col, sample_ids)
        return "1 = 0", []
    if ftype == "env_number":
        sample_ids = match_env_numeric_sample_ids(target, operator, str(value or ""), str(value_secondary or ""))
        if sample_ids:
            col = "sample_id" if page_kind == "sample" else "v.sample_id"
            return build_in_clauses(col, sample_ids)
        return "1 = 0", []
    if ftype == "map_sample":
        sample_ids = match_map_sample_ids(target, operator, str(value or ""))
        if sample_ids:
            col = "sample_id" if page_kind == "sample" else "v.sample_id"
            return build_in_clauses(col, sample_ids)
        return "1 = 0", []
    if ftype == "geo_region":
        sample_ids = match_geo_region_ids(operator, str(value or ""))
        if sample_ids:
            col = "sample_id" if page_kind == "sample" else "v.sample_id"
            return build_in_clauses(col, sample_ids)
        return "1 = 0", []
    if ftype == "source_genome": return build_source_match_clause("genome", target, operator, str(value or ""))
    if ftype == "source_bgc": return build_source_match_clause("bgc", target, operator, str(value or ""))
    return "1 = 1", []


def compile_filter_group(node: dict, page_kind: str, conn) -> Tuple[str, List]:
    if not isinstance(node, dict): return "", []
    if node.get("type") == "rule":
        clause, params = compile_filter_rule(node, page_kind, conn)
        if clause and node.get("negated"):
            clause = f"(NOT {clause})"
        return clause, params
    children = node.get("rules") or []
    compiled = []
    params: List = []
    for child in children:
        clause, cp = compile_filter_group(child, page_kind, conn)
        if clause:
            compiled.append(clause)
            params.extend(cp)
    if not compiled: return "", []
    combinator = (node.get("combinator") or "and").lower()
    negated = node.get("negated", False)
    if combinator == "or": result = "(" + " OR ".join(compiled) + ")"
    else: result = "(" + " AND ".join(compiled) + ")"
    if negated: result = "(NOT " + result + ")"
    return result, params


def extract_record_data(text: str) -> List[dict]:
    prefix = "var recordData = "
    start = text.find(prefix)
    if start == -1: return []
    payload = text[start + len(prefix):]
    array_start = payload.find("[")
    if array_start == -1: return []
    depth = 0; in_string = False; escaped = False; end_index = None
    for idx, char in enumerate(payload[array_start:], start=array_start):
        if in_string:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == '"': in_string = False
            continue
        if char == '"': in_string = True
        elif char == "[" : depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0: end_index = idx + 1; break
    if end_index is None: return []
    return json.loads(payload[array_start:end_index])


def build_antismash_catalog() -> AntismashCatalog:
    html_urls: Dict[str, str] = {}
    anchor_urls: Dict[str, str] = {}
    if not ANTISMASH_ROOT.exists():
        return AntismashCatalog(html_urls=html_urls, anchor_urls=anchor_urls)
    for item in sorted(ANTISMASH_ROOT.iterdir()):
        if item.is_file() and item.suffix.lower() == ".html":
            html_urls[item.stem] = f"/antismash/{quote(item.name)}"
            continue
        if not item.is_dir(): continue
        genome_id = item.name
        index_file = item / "index.html"
        if index_file.exists():
            html_urls[genome_id] = f"/antismash/{quote(genome_id)}/index.html"
        regions_file = item / "regions.js"
        if not regions_file.exists(): continue
        try:
            record_data = extract_record_data(regions_file.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        base_url = html_urls.get(genome_id)
        if not base_url: continue
        for record in record_data:
            seq_id = record.get("seq_id")
            for region in record.get("regions") or []:
                anchor = region.get("anchor")
                idx = region.get("idx")
                if not seq_id or not anchor or idx is None: continue
                bgc_name = f"{seq_id}.region{int(idx):03d}"
                anchor_urls[bgc_name] = f"{base_url}#{anchor}"
    return AntismashCatalog(html_urls=html_urls, anchor_urls=anchor_urls)


CATALOG = AntismashCatalog(html_urls={}, anchor_urls={})
_cache_path = ROOT / "config" / "antismash_cache.json"
try:
    if _cache_path.exists():
        _data = json.loads(_cache_path.read_text())
        CATALOG = AntismashCatalog(html_urls=_data["html_urls"], anchor_urls=_data["anchor_urls"])
    else:
        CATALOG = build_antismash_catalog()
        _cache_path.write_text(json.dumps({"html_urls": CATALOG.html_urls, "anchor_urls": CATALOG.anchor_urls}, ensure_ascii=False))
except Exception:
    CATALOG = build_antismash_catalog()
# Pre-warm taxon cache at startup so first user doesn't wait
load_taxon_selector_options()
BIOSAMPLE_URL_OVERRIDES = load_biosample_overrides()


def antismash_url(genome_id: Optional[str], bgc_name: Optional[str]) -> Optional[str]:
    if bgc_name and bgc_name in CATALOG.anchor_urls:
        return CATALOG.anchor_urls[bgc_name]
    return None


def antismash_mag_url(genome_id: Optional[str]) -> Optional[str]:
    if not genome_id:
        return None
    # Try exact match, then with "spire_" prefix (compat with old folder names)
    if genome_id in CATALOG.html_urls:
        return CATALOG.html_urls[genome_id]
    with_prefix = f"spire_{genome_id}"
    if with_prefix in CATALOG.html_urls:
        return CATALOG.html_urls[with_prefix]
    return None


def serve_file(handler, target: Path, *, download_name: Optional[str] = None) -> None:
    if not hasattr(serve_file, '_gzip_cache'):
        serve_file._gzip_cache = {}
    if not target.exists() or not target.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND, "File not found")
        return
    ctype, _ = mimetypes.guess_type(str(target))
    ctype = ctype or "application/octet-stream"
    
    # On-the-fly gzip for text files
    if not download_name and 'gzip' in handler.headers.get('Accept-Encoding', ''):
        if target.suffix in ('.html','.css','.js','.json','.svg','.xml','.csv','.tsv'):
            import gzip as _gz
            key = str(target) + str(target.stat().st_mtime)
            cache = serve_file._gzip_cache
            if key not in cache:
                cache[key] = _gz.compress(target.read_bytes(), 6)
            compressed = cache[key]
            handler.send_response(HTTPStatus.OK)
            handler.send_header("Content-Type", ctype)
            handler.send_header("Content-Encoding", "gzip")
            handler.send_header("Content-Length", str(len(compressed)))
            handler.end_headers()
            handler.wfile.write(compressed)
            return
    
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(target.stat().st_size))
    if download_name:
        handler.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
    handler.end_headers()
    with target.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 256)
            if not chunk: break
            try:
                handler.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                return


def send_json(handler, payload: dict) -> None:
    from decimal import Decimal
    from datetime import date, datetime

    class _Encoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, Decimal):
                return float(o)
            if isinstance(o, (date, datetime)):
                return o.isoformat()
            return super().default(o)

    encoded = json.dumps(payload, ensure_ascii=False, cls=_Encoder).encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def page_payload(total: int, page: int, page_size: int, rows: List[dict]) -> dict:
    start = 0 if total == 0 else (page - 1) * page_size + 1
    end = min(total, (page - 1) * page_size + len(rows))
    return {"total": total, "page": page, "page_size": page_size, "start": start, "end": end,
            "rows": rows, "has_prev": page > 1, "has_next": end < total}


def normalize_order_dir(raw: str) -> str:
    return "desc" if (raw or "").strip().lower() == "desc" else "asc"


class SpireHandler(BaseHTTPRequestHandler):
    server_version = "SpirePG/2.0"

    def log_message(self, fmt: str, *args) -> None:
        return

    _rl: dict = {}  # rate limit: {ip: [count, start_time]}

    def _check_rate(self, path: str) -> bool:
        now = time.time()
        limit = 20 if "suggest" in path else 5
        ip = self.client_address[0]
        entry = self._rl.get(ip)
        if entry and now - entry[1] < 1:
            entry[0] += 1
            if entry[0] > limit: return False
        else:
            self._rl[ip] = [1, now]
        return True

    def do_GET(self) -> None:
        try:
            self._do_GET()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/api/") and path != "/api/health":
            if not self._check_rate(path):
                self.send_error(HTTPStatus.TOO_MANY_REQUESTS, "Rate limit exceeded"); return
        if path in PAGE_ROUTES: return self.serve_page(PAGE_ROUTES[path])
        if path.startswith("/static/"): return self.serve_static(path.removeprefix("/static/"))
        if path.startswith("/antismash/"): return self.serve_antismash(path.removeprefix("/antismash/"))
        if path.startswith("/download-asset/"):
            return self.serve_download_asset(unquote(path.removeprefix("/download-asset/")))
        if path == "/api/home": return self.api_home()
        if path == "/api/home-phylo": return self.api_home_phylo()
        if path == "/api/samples": return self.api_samples(query)
        if path == "/api/mags": return self.api_mags(query)
        if path == "/api/bgcs": return self.api_bgcs(query)
        if path == "/api/gcf-detail": return self.api_gcf_detail(query)
        if path == "/api/nps": return self.api_nps(query)
        if path == "/api/downloads": return self.api_downloads()
        if path == "/api/biome-options": return self.api_biome_options()
        if path == "/api/geo-options": return self.api_geo_options()
        if path == "/api/taxon-options": return self.api_taxon_options()
        if path == "/api/category-options": return self.api_category_options()
        if path == "/api/search-suggest": return self.api_search_suggest(query)
        if path == "/api/np-hierarchy": return self.api_np_hierarchy()
        if path == "/api/stats-charts": return self.api_stats_charts()
        if path == "/api/health": return self.api_health()
        self.send_error(HTTPStatus.NOT_FOUND, "Route not found")

    def serve_page(self, file_name: str) -> None:
        serve_file(self, WEB_ROOT / file_name)

    def serve_static(self, relative_path: str) -> None:
        if relative_path.startswith(".") or "/." in relative_path:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found"); return
        target = (WEB_ROOT / relative_path).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden"); return
        serve_file(self, target)

    def serve_antismash(self, relative_path: str) -> None:
        target = (ANTISMASH_ROOT / relative_path).resolve()
        if ANTISMASH_ROOT.resolve() not in target.parents and target != ANTISMASH_ROOT.resolve():
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden"); return
        serve_file(self, target)

    def serve_download_asset(self, asset_key: str) -> None:
        conn = open_db()
        row = pg_query_one(conn, "SELECT title, file_path FROM download_asset WHERE asset_key = %s", (asset_key,))
        conn.close()
        if row is None: self.send_error(HTTPStatus.NOT_FOUND, "Asset not found"); return
        serve_file(self, ROOT / Path(row["file_path"]), download_name=row["title"])

    def api_health(self) -> None:
        send_json(self, {"ok": True, "database": "PostgreSQL", "antismash_results": len(CATALOG.html_urls)})

    def api_home(self) -> None:
        conn = open_db()
        stats = row_to_dict(pg_query_one(conn, "SELECT * FROM mv_home_stats"))
        np_cnt = pg_query_one(conn, "SELECT count(*) AS cnt FROM mv_np_page WHERE np_pathway IS NOT NULL")["cnt"]
        stats["np_count"] = int(np_cnt)
        release = row_to_dict(pg_query_one(conn, "SELECT * FROM release_version WHERE is_current = TRUE LIMIT 1"))
        conn.close()
        stats["antismash_result_count"] = len(CATALOG.html_urls)
        send_json(self, {"stats": stats, "release": release})

    def api_home_phylo(self) -> None:
        send_json(self, load_home_phylo_payload())

    def api_biome_options(self) -> None:
        send_json(self, load_biome_selector_options())

    def api_geo_options(self) -> None:
        filters = load_map_filters()
        boards: List[str] = []
        board_sample_sets: dict[str, set] = {}
        for p in filters.values():
            kind = (p.get("kind") or "").strip(); label = (p.get("label") or "").strip()
            if not label: continue
            if kind == "board": boards.append(label); board_sample_sets[label] = set(str(s) for s in (p.get("sample_ids") or []))
        countries_by_board: dict[str, List[str]] = defaultdict(list)
        for p in filters.values():
            if (p.get("kind") or "").strip() != "country": continue
            label = (p.get("label") or "").strip()
            if not label: continue
            cs = set(str(s) for s in (p.get("sample_ids") or []))
            best_board, best_overlap = "", 0
            for board, bs in board_sample_sets.items():
                overlap = len(cs & bs)
                if overlap > best_overlap: best_overlap = overlap; best_board = board
            if best_board: countries_by_board[best_board].append(label)
        send_json(self, {"boards": sorted(boards), "countries_by_board": {k: sorted(v) for k, v in countries_by_board.items()}})

    def api_taxon_options(self) -> None:
        send_json(self, load_taxon_selector_options())

    def api_category_options(self) -> None:
        conn = open_db()
        rows = pg_query(conn, "SELECT category_primary AS label, count(*) AS value FROM bgc WHERE category_primary IS NOT NULL GROUP BY 1 ORDER BY value DESC")
        conn.close()
        send_json(self, {"categories": [row_to_dict(r) for r in rows]})


    def api_search_suggest(self, query: dict) -> None:
        stype = (query.get("type", [""])[0] or "").strip()
        q = (query.get("q", [""])[0] or "").strip()
        limit = 12
        suggestions: List[dict] = []
        conn = open_db()
        try:
            if stype == "sample_id":
                rows = pg_query(conn, "SELECT sample_id FROM sample WHERE sample_id ILIKE %s AND sample_id IS NOT NULL AND sample_id <> '' GROUP BY sample_id ORDER BY CASE WHEN sample_id LIKE 'SAMN%%' THEN 0 ELSE 1 END, sample_id LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["sample_id"], "value": r["sample_id"]} for r in rows]
            elif stype == "genome_id":
                rows = pg_query(conn, "SELECT genome_id FROM mv_mag_page WHERE genome_id LIKE %s ORDER BY genome_id LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["genome_id"], "value": r["genome_id"]} for r in rows]
            elif stype == "bgc_category":
                rows = pg_query(conn, "SELECT DISTINCT category_primary FROM bgc WHERE category_primary ILIKE %s AND category_primary IS NOT NULL AND category_primary <> '' ORDER BY category_primary LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["category_primary"], "value": r["category_primary"]} for r in rows]
            elif stype == "gcf_id":
                rows = pg_query(conn, "SELECT gcf_id::text AS gcf_text FROM gcf WHERE gcf_id::text LIKE %s ORDER BY 1 LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["gcf_text"], "value": r["gcf_text"]} for r in rows]
            elif stype == "bgc_name":
                rows = pg_query(conn, "SELECT bgc_name FROM bgc WHERE bgc_name LIKE %s ORDER BY bgc_name LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["bgc_name"], "value": r["bgc_name"]} for r in rows]
            elif stype == "bgc":
                rows = pg_query(conn, "SELECT DISTINCT product FROM mv_bgc_page WHERE product ILIKE %s AND product IS NOT NULL AND product <> '' ORDER BY product LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["product"], "value": r["product"]} for r in rows]
            elif stype == "np":
                rows = pg_query(conn, "SELECT DISTINCT v FROM (SELECT np_pathway AS v FROM mv_bgc_page WHERE np_pathway ILIKE %s AND np_pathway IS NOT NULL AND np_pathway <> '' UNION SELECT np_superclass FROM mv_bgc_page WHERE np_superclass ILIKE %s AND np_superclass IS NOT NULL AND np_superclass <> '') sub ORDER BY v LIMIT %s", (f"%{q}%", f"%{q}%", limit))
                suggestions = [{"label": r["v"], "value": r["v"]} for r in rows]
            elif stype == "tax":
                rows = pg_query(conn, "SELECT DISTINCT v FROM (SELECT species AS v FROM mv_mag_page WHERE species ILIKE %s AND species IS NOT NULL AND species <> '' UNION SELECT genus FROM mv_mag_page WHERE genus ILIKE %s AND genus IS NOT NULL AND genus <> '' UNION SELECT phylum FROM mv_mag_page WHERE phylum ILIKE %s AND phylum IS NOT NULL AND phylum <> '') sub ORDER BY v LIMIT %s", (f"%{q}%", f"%{q}%", f"%{q}%", limit))
                suggestions = [{"label": r["v"], "value": r["v"]} for r in rows]
            elif stype == "sample":
                rows = pg_query(conn, "SELECT DISTINCT v FROM (SELECT sample_id AS v FROM sample WHERE sample_id ILIKE %s AND sample_id IS NOT NULL AND sample_id <> '' UNION SELECT project FROM sample WHERE project ILIKE %s AND project IS NOT NULL AND project <> '') sub ORDER BY v LIMIT %s", (f"%{q}%", f"%{q}%", limit))
                suggestions = [{"label": r["v"], "value": r["v"]} for r in rows]
            elif stype in ("product", "bgc_product"):
                rows = pg_query(conn, "SELECT DISTINCT product FROM mv_bgc_page WHERE product ILIKE %s AND product IS NOT NULL AND product <> '' ORDER BY product LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["product"], "value": r["product"]} for r in rows]
            elif stype in ("category", "bgc_category"):
                rows = pg_query(conn, "SELECT DISTINCT category_primary FROM bgc WHERE category_primary ILIKE %s AND category_primary IS NOT NULL AND category_primary <> '' ORDER BY category_primary LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["category_primary"], "value": r["category_primary"]} for r in rows]
            elif stype in ("np_pathway",):
                rows = pg_query(conn, "SELECT DISTINCT np_pathway AS v FROM mv_np_page WHERE np_pathway ILIKE %s AND np_pathway IS NOT NULL AND np_pathway <> '' ORDER BY v LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["v"], "value": r["v"]} for r in rows]
            elif stype in ("np_class",):
                rows = pg_query(conn, "SELECT DISTINCT np_class AS v FROM mv_np_page WHERE np_class ILIKE %s AND np_class IS NOT NULL AND np_class <> '' ORDER BY v LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["v"], "value": r["v"]} for r in rows]
            elif stype in ("species", "tax_species"):
                rows = pg_query(conn, "SELECT species FROM (SELECT DISTINCT species FROM mv_mag_page WHERE species ILIKE %s AND species IS NOT NULL AND species <> '') sub ORDER BY CASE WHEN species ~ '^[A-Z][a-z]+ [a-z]' THEN 0 ELSE 1 END, species LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["species"], "value": r["species"]} for r in rows]
            elif stype == "project":
                rows = pg_query(conn, "SELECT project FROM sample WHERE project ILIKE %s AND project IS NOT NULL AND project <> '' GROUP BY project ORDER BY CASE WHEN project LIKE 'PRJ%%' THEN 0 ELSE 1 END, project LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["project"], "value": r["project"]} for r in rows]
            elif stype in ("np_superclass",):
                rows = pg_query(conn, "SELECT DISTINCT np_superclass AS v FROM mv_np_page WHERE np_superclass ILIKE %s AND np_superclass IS NOT NULL AND np_superclass <> '' ORDER BY v LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["v"], "value": r["v"]} for r in rows]
            elif stype == "phylum":
                rows = pg_query(conn, "SELECT phylum FROM (SELECT DISTINCT phylum FROM mv_mag_page WHERE phylum ILIKE %s AND phylum IS NOT NULL AND phylum <> '') sub ORDER BY CASE WHEN phylum ~ '^[A-Z][a-z]' THEN 0 ELSE 1 END, phylum LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["phylum"], "value": r["phylum"]} for r in rows]
            elif stype == "class_name":
                rows = pg_query(conn, "SELECT class_name FROM (SELECT DISTINCT class_name FROM mv_mag_page WHERE class_name ILIKE %s AND class_name IS NOT NULL AND class_name <> '') sub ORDER BY CASE WHEN class_name ~ '^[A-Z][a-z]' THEN 0 ELSE 1 END, class_name LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["class_name"], "value": r["class_name"]} for r in rows]
            elif stype == "genus":
                rows = pg_query(conn, "SELECT genus FROM (SELECT DISTINCT genus FROM mv_mag_page WHERE genus ILIKE %s AND genus IS NOT NULL AND genus <> '') sub ORDER BY CASE WHEN genus ~ '^[A-Z][a-z]' THEN 0 ELSE 1 END, genus LIMIT %s", (f"%{q}%", limit))
                suggestions = [{"label": r["genus"], "value": r["genus"]} for r in rows]
            elif stype == "bgc_species":
                if q:
                    rows = pg_query(conn, "SELECT species FROM (SELECT DISTINCT species FROM mv_bgc_page WHERE species ILIKE %s AND species IS NOT NULL AND species <> '') sub ORDER BY CASE WHEN species ~ '^[A-Z][a-z]+ [a-z]' THEN 0 ELSE 1 END, species LIMIT %s", (f"%{q}%", limit))
                else:
                    rows = pg_query(conn, "SELECT DISTINCT species FROM mv_bgc_page WHERE species IS NOT NULL AND species <> '' ORDER BY species LIMIT %s", (limit,))
                suggestions = [{"label": r["species"], "value": r["species"]} for r in rows]
            elif stype in ("biome", "biome1"):
                bo = load_biome_selector_options()
                vals = bo.get("biome1", [])
                lower_q = q.lower()
                suggestions = [{"label": v, "value": v} for v in vals if lower_q in v.lower()][:limit]
        finally:
            conn.close()
        send_json(self, {"suggestions": suggestions})

    def api_samples(self, query: dict) -> None:
        search = (query.get("q", [""])[0] or "").strip().lower()
        filters = parse_filters((query.get("filters", [""])[0] or "").strip())
        sample_id_filter = (query.get("sample_id", [""])[0] or "").strip()
        sample_accession_filter = (query.get("sample_accession", [""])[0] or "").strip()
        group1_filter = (query.get("group1", [""])[0] or query.get("biome1", [""])[0] or "").strip()
        map_filter = (query.get("map_filter", [""])[0] or "").strip()
        order_by = (query.get("order_by", [""])[0] or "").strip()
        order_dir = normalize_order_dir(query.get("order_dir", ["asc"])[0] or "asc")
        page = safe_page(query.get("page", ["1"])[0])
        page_size = safe_page_size(query.get("page_size", ["25"])[0])

        clauses = []; params: List = []
        if search:
            env_sample_ids = search_sample_ids_by_env_text(search)
            search_clause = ("(lower(sample_id) LIKE %s OR lower(COALESCE(project, '')) LIKE %s OR "
                             "lower(COALESCE(primary_sample_accession, '')) LIKE %s OR "
                             "lower(COALESCE(category, '')) LIKE %s OR lower(COALESCE(biome3, '')) LIKE %s OR "
                             "lower(COALESCE(geo_region, '')) LIKE %s")
            if env_sample_ids:
                ec, ep = build_in_clauses("sample_id", env_sample_ids)
                search_clause += f" OR {ec}"
            else:
                ep = []
            search_clause += ")"
            clauses.append(search_clause)
            like = f"%{search}%"
            params.extend([like, like, like, like, like, like])
            params.extend(ep)
        if sample_id_filter: clauses.append("sample_id = %s"); params.append(sample_id_filter)
        if sample_accession_filter: clauses.append("(primary_sample_accession = %s OR biosample_accession = %s)"); params.extend([sample_accession_filter, sample_accession_filter])
        if group1_filter:
            clauses.append("lower(biome1) = %s")
            params.append(group1_filter.lower())
        if map_filter:
            mf = load_map_filters()
            fp = mf.get(map_filter) or {}
            sample_ids = fp.get("sample_ids") or []
            if sample_ids:
                ic, ip = build_in_clauses("sample_id", [str(s) for s in sample_ids]); clauses.append(ic); params.extend(ip)
            else:
                clauses.append("1 = 0")

        conn = open_db()
        if filters:
            fc, fp = compile_filter_group(filters, "sample", conn)
            if fc: clauses.append(fc); params.extend(fp)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        if order_by not in {"lat", "lon", "mag_count", "bgc_count"}:
            order_by, order_dir = "display_order", "asc"
        order_sql = f"ORDER BY {order_by} {order_dir.upper()}"

        total = cached_count(conn, f"SELECT count(*) AS cnt FROM mv_sample_page {where}", list(params))
        if total == 0:
            conn.close()
            send_json(self, page_payload(0, page, page_size, []))
            return
        rows = pg_query(conn, f"SELECT * FROM mv_sample_page {where} {order_sql} LIMIT %s OFFSET %s",
                        params + [page_size, (page - 1) * page_size])
        conn.close()

        env_lookup = load_sample_env_lookup()
        payload_rows = []
        for row in rows:
            item = row_to_dict(row)
            env = env_lookup.get(item.get("sample_id"), {})
            item["biome1"] = env.get("biome1") or item.get("biome1")
            item["biome2"] = env.get("biome2") or item.get("biome2")
            item["biome3"] = env.get("biome3") or item.get("biome3")
            item["lat"] = env.get("lat") if env.get("lat") is not None else item.get("lat")
            item["lon"] = env.get("lon") if env.get("lon") is not None else item.get("lon")
            item["ncbi_url"] = ncbi_url(item["sample_id"], item.get("biosample_accession"), item.get("primary_sample_accession"))
            item["mag_url"] = f"/tax.html?sample_id={quote(item['sample_id'])}"
            item["bgc_url"] = f"/bgc.html?sample_id={quote(item['sample_id'])}"
            item["sample_portal_url"] = f"/sample.html?sample_id={quote(item['sample_id'])}"
            payload_rows.append(item)
        send_json(self, page_payload(total, page, page_size, payload_rows))

    def api_mags(self, query: dict) -> None:
        search = (query.get("q", [""])[0] or "").strip().lower()
        filters = parse_filters((query.get("filters", [""])[0] or "").strip())
        sample_id_filter = (query.get("sample_id", [""])[0] or "").strip()
        genome_id_filter = (query.get("genome_id", [""])[0] or "").strip()
        phylum_filter = (query.get("phylum", [""])[0] or "").strip()
        class_filter = (query.get("class_name", [""])[0] or "").strip()
        genus_filter = (query.get("genus", [""])[0] or "").strip()
        species_filter = (query.get("species", [""])[0] or "").strip()
        phylum_group_filter = (query.get("phylum_group", [""])[0] or "").strip()
        order_by = (query.get("order_by", [""])[0] or "").strip()
        order_dir = normalize_order_dir(query.get("order_dir", ["asc"])[0] or "asc")
        page = safe_page(query.get("page", ["1"])[0])
        page_size = safe_page_size(query.get("page_size", ["25"])[0])

        clauses = []; params: List = []
        conn = open_db()
        if search:
            like = f"%{search}%"
            env_sample_ids = search_sample_ids_by_env_text(search)
            sc = ("(lower(v.genome_id) LIKE %s OR lower(v.species) LIKE %s OR "
                  "lower(v.biome) LIKE %s OR lower(v.sample_id) LIKE %s OR "
                  "lower(v.phylum) LIKE %s OR lower(v.class_name) LIKE %s OR "
                  "lower(v.genus) LIKE %s OR "
                  "lower(v.biome1) LIKE %s OR lower(v.biome2) LIKE %s OR "
                  "lower(v.category_preview) LIKE %s")
            if env_sample_ids:
                ec, ep = build_in_clauses("v.sample_id", env_sample_ids); sc += f" OR {ec}"
            else:
                ep = []
            sc += ")"
            clauses.append(sc)
            params.extend([like, like, like, like, like, like, like, like, like, like])
            params.extend(ep)
        if sample_id_filter: clauses.append("lower(v.sample_id) = lower(%s)"); params.append(sample_id_filter)
        if genome_id_filter: clauses.append("lower(v.genome_id) = lower(%s)"); params.append(genome_id_filter)
        if phylum_filter: clauses.append("lower(v.phylum) = %s"); params.append(phylum_filter.lower())
        if class_filter: clauses.append("lower(v.class_name) = %s"); params.append(class_filter.lower())
        if genus_filter: clauses.append("lower(v.genus) = %s"); params.append(genus_filter.lower())
        if species_filter: clauses.append("lower(v.species) = %s"); params.append(species_filter.lower())

        if phylum_group_filter == "other_top20":
            top_phyla = [r["phylum"] for r in pg_query(conn, """
                SELECT COALESCE(NULLIF(phylum, ''), 'Unclassified') AS phylum FROM mv_mag_page GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 20
            """)]
            if top_phyla:
                phs = ",".join("%s" for _ in top_phyla)
                clauses.append(f"COALESCE(NULLIF(v.phylum, ''), 'Unclassified') NOT IN ({phs})"); params.extend(top_phyla)
        if filters:
            fc, fp = compile_filter_group(filters, "tax", conn)
            if fc: clauses.append(fc); params.extend(fp)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        mag_order_map = {"bgc_count": "v.bgc_count", "completeness": "v.completeness", "contamination": "v.contamination",
                         "genome_size": "v.genome_size", "gene_count": "v.gene_count"}
        if order_by in mag_order_map:
            e = mag_order_map[order_by]
            order_clause = f"ORDER BY CASE WHEN {e} IS NULL THEN 1 ELSE 0 END ASC, {e} {order_dir.upper()}, v.genome_id ASC"
        else:
            order_clause = "ORDER BY v.genome_id"

        total = cached_count(conn, f"SELECT count(*) AS cnt FROM mv_mag_page v {where}", list(params))
        conn.close()
        if total == 0:
            send_json(self, page_payload(0, page, page_size, []))
            return
        conn = open_db()
        rows = pg_query(conn, f"SELECT v.* FROM mv_mag_page v {where} {order_clause} LIMIT %s OFFSET %s",
                        params + [page_size, (page - 1) * page_size])
        conn.close()

        env_lookup = load_sample_env_lookup()
        payload_rows = []
        for row in rows:
            item = row_to_dict(row)
            env = env_lookup.get(item.get("sample_id"), {})
            item["biome1"] = env.get("biome1") or item.get("biome1")
            item["biome2"] = env.get("biome2") or item.get("biome2")
            item["biome3"] = env.get("biome3") or item.get("biome3")
            item["sample_url"] = f"/sample.html?sample_id={quote(item['sample_id'])}"
            item["sample_ncbi_url"] = ncbi_url(item["sample_id"], item.get("biosample_accession"), item.get("primary_sample_accession"))
            gid = (item.get("genome_id") or "")
            if gid.startswith("spire_"):
                gid = gid[6:]
            item["genome_id_display"] = gid
            item["bgc_url"] = f"/bgc.html?genome_id={quote(item['genome_id'])}"
            item["portal_url"] = f"/tax.html?genome_id={quote(item['genome_id'])}"
            item["antismash_url"] = antismash_mag_url(item["genome_id"])
            item["product_preview"] = item.get("product_preview", "NA")
            item["category_preview"] = item.get("category_preview", "NA")
            payload_rows.append(item)
        send_json(self, page_payload(total, page, page_size, payload_rows))

    def api_bgcs(self, query: dict) -> None:
        search = (query.get("q", [""])[0] or "").strip().lower()
        filters = parse_filters((query.get("filters", [""])[0] or "").strip())
        sample_id_filter = (query.get("sample_id", [""])[0] or "").strip()
        genome_id_filter = (query.get("genome_id", [""])[0] or "").strip()
        gcf_filter = (query.get("gcf_id", [""])[0] or "").strip()
        bigscape_type_filter = (query.get("category_primary", [""])[0] or "").strip()
        order_by = (query.get("order_by", [""])[0] or "").strip()
        order_dir = (query.get("order_dir", ["asc"])[0] or "asc").strip().lower()
        page = safe_page(query.get("page", ["1"])[0])
        page_size = safe_page_size(query.get("page_size", ["25"])[0])

        clauses = []; params: List = []
        conn = open_db()
        if search:
            like = f"%{search}%"
            env_sample_ids = search_sample_ids_by_env_text(search)
            sc = ("(lower(v.bgc_name) LIKE %s OR lower(v.genome_id) LIKE %s OR "
                  "lower(v.product) LIKE %s OR lower(v.sample_id) LIKE %s OR "
                  "lower(v.category) LIKE %s")
            if env_sample_ids:
                ec, ep = build_in_clauses("v.sample_id", env_sample_ids); sc += f" OR {ec}"
            else:
                ep = []
            sc += ")"
            clauses.append(sc)
            params.extend([like, like, like, like, like])
            params.extend(ep)
        if sample_id_filter: clauses.append("lower(v.sample_id) = lower(%s)"); params.append(sample_id_filter)
        if genome_id_filter: clauses.append("lower(v.genome_id) = lower(%s)"); params.append(genome_id_filter)
        if gcf_filter: clauses.append("v.gcf_id = %s"); params.append(int(gcf_filter))
        if bigscape_type_filter:
            bs_values = expand_bigscape_type_aliases(bigscape_type_filter)
            if bs_values:
                placeholders = " OR ".join(["lower(v.category) = lower(%s)"] * len(bs_values))
                clauses.append(f"({placeholders})")
                params.extend([str(v).strip() for v in bs_values])
        if filters:
            fc, fp = compile_filter_group(filters, "bgc", conn)
            if fc: clauses.append(fc); params.extend(fp)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        user_ordered = order_by in {"bgc_id", "gcf_id", "length", "membership_value"}
        if not user_ordered:
            if gcf_filter:
                order_by = "membership_value"
            else:
                order_by = "bgc_id"
        if order_dir not in {"asc", "desc"}: order_dir = "asc"
        order_map = {"bgc_id": "v.bgc_source_id", "gcf_id": "v.gcf_id", "length": "v.length", "membership_value": "v.membership_value"}
        order = f"ORDER BY {order_map[order_by]} {order_dir.upper()}, v.bgc_pk ASC"

        clauses = [c for c in clauses if c != "1 = 1"]
        has_filters = len(clauses) > 0
        total = cached_count(conn, f"""
            SELECT count(*) AS cnt FROM mv_bgc_page v
            {where}
        """, list(params))
        if total == 0:
            conn.close()
            send_json(self, page_payload(0, page, page_size, []))
            return
        rows = pg_query(conn, f"""
            SELECT v.bgc_pk, v.bgc_name, v.bgc_source_id, v.genome_id, v.sample_id, v.biome AS biome3,
                   v.species, v.biome1, v.biome2, v.domain, v.phylum, v.class_name, v.order_name,
                   v.family, v.genus, v.product, v.category, v.length, v.contig_edge,
                   v.gcf_id, v.membership_value, v.membership_status, v.antismash_html_path,
                   v.NP_pathway, v.NP_superclass, v.NP_class, v.predicted_smiles
            FROM mv_bgc_page v {where} {order} LIMIT %s OFFSET %s
        """, params + [page_size, (page - 1) * page_size])
        conn.close()

        payload_rows = []
        for row in rows:
            item = row_to_dict(row)
            item["bgc_source_id"] = item.get("bgc_source_id") or ""
            item["gcf_id"] = item.get("gcf_id") or ""
            gid = (item.get("genome_id") or "")
            if gid.startswith("spire_"):
                gid = gid[6:]
            item["genome_id_display"] = gid
            item["sample_url"] = f"/sample.html?sample_id={quote(item['sample_id'])}"
            item["sample_ncbi_url"] = ncbi_url(item["sample_id"], item.get("biosample_accession"), item.get("primary_sample_accession"))
            item["genome_url"] = f"/tax.html?genome_id={quote(item['genome_id'])}"
            item["gcf_url"] = f"/bgc.html?gcf_id={item['gcf_id']}" if item["gcf_id"] is not None else None
            item["antismash_url"] = antismash_url(item["genome_id"], item["bgc_name"])
            item["mag_antismash_url"] = antismash_mag_url(item["genome_id"])
            payload_rows.append(item)
        send_json(self, page_payload(total, page, page_size, payload_rows))

    def api_gcf_detail(self, query: dict) -> None:
        raw_gcf = (query.get("gcf_id", [""])[0] or "").strip()
        if not raw_gcf: return send_json(self, {"error": "Missing gcf_id"})
        conn = open_db()
        summary = pg_query_one(conn, "SELECT * FROM mv_gcf_page WHERE gcf_id = %s", (raw_gcf,))
        if summary is None: conn.close(); return send_json(self, {"error": "GCF not found"})
        conn.close()
        send_json(self, {"summary": row_to_dict(summary)})

    def api_nps(self, query: dict) -> None:
        filters = parse_filters((query.get("filters", [""])[0] or "").strip())
        page = safe_page(query.get("page", ["1"])[0])
        page_size = safe_page_size(query.get("page_size", ["25"])[0])
        conn = open_db()

        clauses = []; params: List = []
        if filters:
            fc, fp = compile_filter_group(filters, "nps", conn)
            if fc: clauses.append(fc); params.extend(fp)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        total = cached_count(conn, f"SELECT count(*) AS cnt FROM mv_np_page v {where}", list(params))
        if total == 0:
            conn.close()
            send_json(self, page_payload(0, page, page_size, []))
            return
        rows = pg_query(conn, f"SELECT * FROM mv_np_page v {where} ORDER BY v.bgc_source_id LIMIT %s OFFSET %s",
                        params + [page_size, (page - 1) * page_size])
        conn.close()
        payload_rows = []
        for row in rows:
            item = row_to_dict(row)
            item["bgc_url"] = f"/bgc.html?bgc_id={item['bgc_source_id']}"
            item["gcf_url"] = f"/bgc.html?gcf_id={item['gcf_id']}" if item.get("gcf_id") is not None else None
            mv = item.get("membership_value")
            if mv is not None:
                item["membership_status"] = "backbone" if mv <= 0.1 else ("core" if mv <= 0.4 else "peripheral")
            else:
                item["membership_status"] = None
            payload_rows.append(item)
        send_json(self, page_payload(total, page, page_size, payload_rows))

    def api_downloads(self) -> None:
        conn = open_db()
        rows = pg_query(conn, "SELECT * FROM download_asset ORDER BY module_name, asset_id")
        release = pg_query_one(conn, "SELECT release_name, released_on FROM release_version WHERE is_current = TRUE LIMIT 1")
        conn.close()
        payload_rows = []
        for r in rows:
            item = row_to_dict(r)
            item["download_url"] = f"/download-asset/{item['asset_key']}"
            payload_rows.append(item)
        send_json(self, {"rows": payload_rows, "release": row_to_dict(release)})

    def api_np_hierarchy(self) -> None:
        conn = open_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT np_pathway AS pathway, NULL::text AS superclass, NULL::text AS class, count(*) AS cnt
            FROM mv_np_page WHERE np_pathway IS NOT NULL
            GROUP BY np_pathway
            UNION ALL
            SELECT np_pathway, np_superclass, NULL::text, count(*)
            FROM mv_np_page WHERE np_pathway IS NOT NULL AND np_superclass IS NOT NULL
            GROUP BY np_pathway, np_superclass
            UNION ALL
            SELECT np_pathway, np_superclass, np_class, count(*)
            FROM mv_np_page WHERE np_pathway IS NOT NULL AND np_superclass IS NOT NULL AND np_class IS NOT NULL
            GROUP BY np_pathway, np_superclass, np_class
            ORDER BY pathway, superclass, class
        """)
        rows = cur.fetchall()
        conn.close()
        import json
        send_json(self, {"rows": [dict(r) for r in rows]})

    def api_stats_charts(self) -> None:
        conn = open_db()
        phylum_rows = pg_query(conn, """
            SELECT COALESCE(NULLIF(phylum, ''), 'Unclassified') AS phylum, COUNT(*) AS cnt
            FROM mv_mag_page GROUP BY phylum ORDER BY cnt DESC
        """)
        gcf_rows = pg_query(conn, """
            SELECT CASE WHEN membership_value <= 0.1 THEN 'backbone'
                        WHEN membership_value <= 0.4 THEN 'core'
                        ELSE 'peripheral' END AS grp,
                   COUNT(*) AS cnt
            FROM bgc_gcf_membership GROUP BY grp
        """)
        biome_rows = pg_query(conn, """
            SELECT COALESCE(NULLIF(biome1, ''), 'Unknown') AS g, COUNT(*) AS c
            FROM sample WHERE biome1 IS NOT NULL AND biome1 <> ''
            GROUP BY 1 ORDER BY c DESC
        """)
        bgc_rows = pg_query(conn, """
            SELECT COALESCE(NULLIF(category_primary, ''), 'Unknown') AS g, COUNT(*) AS c
            FROM bgc WHERE category_primary IS NOT NULL AND category_primary <> ''
            GROUP BY 1 ORDER BY c DESC LIMIT 8
        """)
        gcf_size = pg_query_one(conn, """
            SELECT SUM(CASE WHEN bgc_count=1 THEN 1 ELSE 0 END) AS c1,
                   SUM(CASE WHEN bgc_count BETWEEN 2 AND 4 THEN 1 ELSE 0 END) AS c2_4,
                   SUM(CASE WHEN bgc_count BETWEEN 5 AND 8 THEN 1 ELSE 0 END) AS c5_8,
                   SUM(CASE WHEN bgc_count BETWEEN 9 AND 30 THEN 1 ELSE 0 END) AS c9_30,
                   SUM(CASE WHEN bgc_count BETWEEN 31 AND 50 THEN 1 ELSE 0 END) AS c31_50,
                   SUM(CASE WHEN bgc_count>50 THEN 1 ELSE 0 END) AS c50p
            FROM mv_gcf_page
        """)
        conn.close()
        import json
        phyla = [{"name": r["phylum"], "cnt": int(r["cnt"])} for r in phylum_rows]
        gcf = [{"type": r["grp"], "cnt": int(r["cnt"])} for r in gcf_rows]
        biome = [{"name": r["g"].replace(" Environment", "").replace(" environment", ""), "cnt": int(r["c"])} for r in biome_rows]
        bgc = [{"name": r["g"], "cnt": int(r["c"])} for r in bgc_rows]
        gs = [{"label": "1", "cnt": int(gcf_size["c1"])},
              {"label": "2-4", "cnt": int(gcf_size["c2_4"])},
              {"label": "5-8", "cnt": int(gcf_size["c5_8"])},
              {"label": "9-30", "cnt": int(gcf_size["c9_30"])},
              {"label": "31-50", "cnt": int(gcf_size["c31_50"])},
              {"label": ">50", "cnt": int(gcf_size["c50p"])}]
        send_json(self, {"phylum": phyla, "gcf_membership": gcf, "biome": biome, "bgc_type": bgc, "gcf_size": gs})


def main() -> None:
    parser = argparse.ArgumentParser(description="Spire BGC Portal (PostgreSQL)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), SpireHandler)
    cfg = get_pg_config()
    print(f"Spire server at http://{args.host}:{args.port}")
    print(f"Database: {cfg.dbname} on {cfg.host}:{cfg.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


if __name__ == "__main__":
    main()
