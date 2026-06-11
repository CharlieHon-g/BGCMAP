"""
PostgreSQL build script for the Spire BGC database.
Replaces the SQLite version (build_spire_sqlite_db.py).

Usage:
    python3 db/build_spire_pg_db.py

Requires environment variables:
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.pg_config import ensure_database, get_conn

GENOME_METADATA = ROOT / "data" / "spire_v1_genome_metadata.tsv"
FULL_SCAPE_ENV = ROOT / "data" / "spire_full_scape_env.tsv"
GEM_SRA_METADATA = ROOT / "data" / "gem_sra.tsv"
GCF_SORTED = ROOT / "data" / "spire_gcf_sorted.tsv"
SAMPLE_ENV_NEW = ROOT / "data" / "sample_env_new.csv"
NPCLASSIFIER_TSV = ROOT / "data" / "merged_with_npclassifier_final.tsv"
MAP_FILTERS = ROOT / "config" / "sample_global_distribution_filters.json"

SAMPLE_PREFIXES = ("SAMN", "SAMEA", "SAMD")
DATE_YEAR_RE = re.compile(r"^(\d{4})")
ORIG_FILENAME_RE = re.compile(
    r"^(?P<genome_id>.+?)__(?P<contig_name>.+?)\.region(?P<region_number>\d+)\.gbk$"
)
LOCATION_RE = re.compile(r"[\[\(]?(\d+):(\d+)[\]\)]")


def batched(rows: Iterable[Tuple], size: int = 10000) -> Iterable[List[Tuple]]:
    chunk: List[Tuple] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def is_ncbi_biosample(sample_id: str) -> bool:
    return sample_id.startswith(SAMPLE_PREFIXES)


def clean_text(value: Optional[str], extra_missing_tokens: Optional[Iterable[str]] = None) -> str:
    text = (value or "").strip()
    missing_tokens = {"na", "n/a"}
    if extra_missing_tokens:
        missing_tokens.update(token.lower() for token in extra_missing_tokens)
    if text.lower() in missing_tokens:
        return ""
    return text


def normalize_date(raw: Optional[str]) -> tuple:
    text = clean_text(raw, extra_missing_tokens={"NA", "N/A", "na"})
    if not text:
        return "", None, None, None
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})T", text)
    if iso_match:
        d = iso_match.group(1)
        return d, None, None, int(d[:4]) if d[:4].isdigit() else None
    slash_range = re.match(r"^(\d{4}/\d{4})$", text)
    if slash_range:
        parts = text.split("/")
        return f"{parts[0]}-{parts[1]}", parts[0], parts[1], int(parts[0])
    dash_range = re.match(r"^(\d{4}-\d{2})/(\d{4}-\d{2})$", text)
    if dash_range:
        s, e = dash_range.group(1), dash_range.group(2)
        return f"{s}-{e}", s, e, int(s[:4])
    ymd_range = re.match(r"^(\d{4}-\d{2}-\d{2})/(\d{4}-\d{2}-\d{2})$", text)
    if ymd_range:
        s, e = ymd_range.group(1), ymd_range.group(2)
        return f"{s}-{e}", s, e, int(s[:4])
    us_date = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$", text)
    if us_date:
        m, d, y = int(us_date.group(1)), int(us_date.group(2)), us_date.group(3)
        if len(y) == 2:
            y = "20" + y
        year = int(y)
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{year}-{m:02d}-{d:02d}", None, None, year
    year_match = DATE_YEAR_RE.match(text)
    year = int(year_match.group(1)) if year_match else None
    if year is not None and 0 < year < 1000:
        year = 2000 + (year % 100)
        text = text.replace(year_match.group(0), f"{year:04d}", 1)
    if re.match(r"^\d{4}$", text):
        return text, None, None, year
    if re.match(r"^\d{4}-\d{2}$", text):
        return text, None, None, year
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text, None, None, year
    return text, None, None, year


def split_pipe(value, extra_missing_tokens=None) -> List[str]:
    value = clean_text(value, extra_missing_tokens)
    if not value:
        return []
    parts = [clean_text(part, extra_missing_tokens) for part in re.split(r"\s*\|\s*", value)]
    return [part for part in parts if part]


def pick_list_value(values: List[str], index: int = 0) -> Optional[str]:
    if not values:
        return None
    if 0 <= index < len(values):
        return values[index]
    return values[0]


def to_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def to_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def to_bool(value) -> Optional[bool]:
    if value is None or value == "":
        return None
    value_l = str(value).strip().lower()
    if value_l in {"true", "1", "yes"}:
        return True
    if value_l in {"false", "0", "no"}:
        return False
    return None


def parse_coord(value) -> Optional[float]:
    text = (str(value) if value else "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def parse_coord_from_fields(*values: str) -> Optional[float]:
    for value in values:
        parsed = parse_coord(value)
        if parsed is not None:
            return parsed
    return None


def drop_and_init_schema(conn) -> None:
    """Drop all tables/views and run the schema DDL."""
    cur = conn.cursor()
    # Drop materialized views first
    cur.execute("""
        DROP MATERIALIZED VIEW IF EXISTS mv_gcf_page CASCADE;
        DROP MATERIALIZED VIEW IF EXISTS mv_bgc_page CASCADE;
        DROP MATERIALIZED VIEW IF EXISTS mv_mag_page CASCADE;
        DROP MATERIALIZED VIEW IF EXISTS mv_sample_page CASCADE;
        DROP MATERIALIZED VIEW IF EXISTS mv_home_stats CASCADE;
    """)
    # Drop tables in reverse dependency order
    cur.execute("""
        DROP TABLE IF EXISTS bgc_gcf_membership CASCADE;
        DROP TABLE IF EXISTS gcf CASCADE;
        DROP TABLE IF EXISTS bgc CASCADE;
        DROP TABLE IF EXISTS mag CASCADE;
        DROP TABLE IF EXISTS sample_run CASCADE;
        DROP TABLE IF EXISTS run CASCADE;
        DROP TABLE IF EXISTS sample_project CASCADE;
        DROP TABLE IF EXISTS sample CASCADE;
        DROP TABLE IF EXISTS download_asset CASCADE;
        DROP TABLE IF EXISTS release_version CASCADE;
    """)
    conn.commit()
    cur.close()

    # Run the schema DDL
    schema_path = ROOT / "db" / "spire_postgres_schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    cur = conn.cursor()
    # Remove BEGIN/COMMIT if present, we manage transactions ourselves
    schema_sql = re.sub(r'^\s*BEGIN\s*;?\s*', '', schema_sql, flags=re.MULTILINE)
    schema_sql = re.sub(r'\s*COMMIT\s*;?\s*$', '', schema_sql)
    cur.execute(schema_sql)
    conn.commit()
    cur.close()


def build_sample_seed() -> Dict[str, Dict[str, Optional[str]]]:
    samples: Dict[str, Dict[str, Optional[str]]] = {}

    def ensure(sample_id: str) -> Dict[str, Optional[str]]:
        if sample_id not in samples:
            samples[sample_id] = {
                "sample_id": sample_id,
                "biosample_accession": sample_id if is_ncbi_biosample(sample_id) else None,
                "primary_sample_accession": None,
                "sample_name": None,
                "biome3": None,
                "biome2": None,
                "biome1": None,
                "collection_date_raw": None,
                "collection_date_start": None,
                "collection_date_end": None,
                "collection_year": None,
                "latitude": None,
                "longitude": None,
                "has_coordinates": False,
                "is_ncbi_biosample": is_ncbi_biosample(sample_id),
            }
        return samples[sample_id]

    with GEM_SRA_METADATA.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sample_id = clean_text(row.get("sample_id"))
            if not sample_id:
                continue
            record = ensure(sample_id)
            biosample = clean_text(row.get("biosample_accession"))
            sra_samples = split_pipe(row.get("primary_sample_accession"))
            sample_names = split_pipe(row.get("identifier_sample_name"))
            raw = clean_text(row.get("collection_date"))
            if biosample:
                record["biosample_accession"] = biosample
            if sra_samples and not record["primary_sample_accession"]:
                record["primary_sample_accession"] = sra_samples[0]
            if sample_names and not record["sample_name"]:
                record["sample_name"] = sample_names[0]
            if raw:
                record["collection_date_raw"], record["collection_date_start"], \
                    record["collection_date_end"], record["collection_year"] = normalize_date(raw)

    with GENOME_METADATA.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sample_id = (row.get("derived_from_sample") or "").strip()
            if not sample_id:
                continue
            ensure(sample_id)

    return samples


def load_samples(conn) -> Dict[str, int]:
    print("Loading samples...")
    samples = build_sample_seed()

    # Fix swapped lat/lon in source data (lat outside -90..90 means it was swapped)
    for info in samples.values():
        lat = info["latitude"]
        lon = info["longitude"]
        if lat is not None and (lat > 90 or lat < -90):
            info["latitude"], info["longitude"] = lon, lat

    cur = conn.cursor()
    rows = [
        (
            info["sample_id"],
            info["biosample_accession"],
            info["primary_sample_accession"],
            info["sample_name"],
            info["biome3"],
            info["biome2"],
            info["biome1"],
            info["collection_date_raw"],
            info["collection_date_start"],
            info["collection_date_end"],
            info["collection_year"],
            info["latitude"],
            info["longitude"],
            info["has_coordinates"],
            info["is_ncbi_biosample"],
        )
        for info in samples.values()
    ]

    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO sample (
            sample_id, biosample_accession, primary_sample_accession, sample_name,
            biome3, biome2, biome1, collection_date_raw, collection_date_start,
            collection_date_end, collection_year, latitude, longitude,
            has_coordinates, is_ncbi_biosample
        ) VALUES %s
        """,
        rows,
        page_size=10000,
    )
    conn.commit()

    cur.execute("SELECT sample_id, sample_pk FROM sample")
    sample_map = {row["sample_id"]: row["sample_pk"] for row in cur}
    cur.close()
    print(f"  Loaded {len(sample_map)} samples")
    return sample_map


def load_release_and_assets(conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO release_version
        (release_name, release_label, released_on, is_current, antismash_version, bigslice_version, bgc_membership_threshold, description)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING release_id
        """,
        (
            "v1.0",
            "Spire BGC Database v1.0",
            "2026-04-10",
            True,
            "antiSMASH 8.0",
            "BiG-SLiCE 2.0",
            0.4,
            "PostgreSQL build generated from local source files.",
        ),
    )
    release_id = cur.fetchone()["release_id"]

    asset_rows = [
        (
            release_id,
            "gcf-membership-tsv",
            "GCF",
            "spire_gcf_sorted.tsv",
            "tsv",
            str(GCF_SORTED.name),
            None,
            GCF_SORTED.stat().st_size if GCF_SORTED.exists() else None,
            "BGC to GCF membership source file.",
            True,
        ),
        (
            release_id,
            "gem-sra-tsv",
            "Sample",
            "gem_sra.tsv",
            "tsv",
            str(GEM_SRA_METADATA.name),
            None,
            GEM_SRA_METADATA.stat().st_size if GEM_SRA_METADATA.exists() else None,
            "Latest curated sample and SRA metadata table.",
            True,
        ),
    ]
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO download_asset
        (release_id, asset_key, module_name, title, file_format, file_path, md5, bytes, description, is_public)
        VALUES %s
        """,
        asset_rows,
    )
    conn.commit()
    cur.close()
    return int(release_id)


def load_sra(conn, sample_map: Dict[str, int]) -> None:
    print("Loading SRA data...")
    sample_project_rows = []
    sample_run_rows = []
    run_rows = []
    seen_sample_projects = set()
    seen_sample_runs = set()
    seen_runs = set()

    with GEM_SRA_METADATA.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sample_id = clean_text(row.get("sample_id"))
            if not sample_id or sample_id not in sample_map:
                continue
            sample_pk = sample_map[sample_id]
            projects = split_pipe(row.get("PRJ"), {"no_id"})
            experiments = split_pipe(row.get("Experiment"))
            runs = split_pipe(row.get("Run"))
            sra_studies = split_pipe(row.get("SRAStudy"))
            sra_samples = split_pipe(row.get("primary_sample_accession"))
            release_dates = split_pipe(row.get("ReleaseDate"))
            load_dates = split_pipe(row.get("LoadDate"))
            download_paths = split_pipe(row.get("download_path"))
            library_names = split_pipe(row.get("LibraryName"))
            library_strategies = split_pipe(row.get("LibraryStrategy"))
            platforms = split_pipe(row.get("Platform"))
            models = split_pipe(row.get("Model"))
            scientific_names = split_pipe(row.get("ScientificName"))
            center_names = split_pipe(row.get("CenterName"))
            submissions = split_pipe(row.get("Submission"))
            consents = split_pipe(row.get("Consent"))

            for idx, bioproject in enumerate(projects):
                row_key = (sample_pk, bioproject)
                if row_key in seen_sample_projects:
                    continue
                seen_sample_projects.add(row_key)
                sample_project_rows.append(
                    (sample_pk, bioproject, pick_list_value(sra_studies, idx), idx + 1)
                )

            for idx, run in enumerate(runs):
                sample_run_key = (sample_pk, run)
                if sample_run_key not in seen_sample_runs:
                    seen_sample_runs.add(sample_run_key)
                    sample_run_rows.append((sample_pk, run, idx + 1))
                if run in seen_runs:
                    continue
                seen_runs.add(run)
                run_rows.append(
                    (
                        run,
                        pick_list_value(experiments, idx),
                        pick_list_value(projects, idx),
                        pick_list_value(sra_studies, idx),
                        pick_list_value(sra_samples, idx),
                        pick_list_value(release_dates, idx),
                        pick_list_value(load_dates, idx),
                        pick_list_value(download_paths, idx),
                        pick_list_value(library_names, idx),
                        pick_list_value(library_strategies, idx),
                        pick_list_value(platforms, idx),
                        pick_list_value(models, idx),
                        pick_list_value(scientific_names, idx),
                        pick_list_value(center_names, idx),
                        pick_list_value(submissions, idx),
                        pick_list_value(consents, idx),
                    )
                )

    cur = conn.cursor()

    if sample_project_rows:
        for batch in batched(sample_project_rows, 20000):
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO sample_project
                (sample_pk, bioproject_accession, sra_study_accession, project_rank)
                VALUES %s
                ON CONFLICT (sample_pk, bioproject_accession) DO NOTHING
                """,
                batch,
                page_size=20000,
            )
            conn.commit()
    print(f"  Loaded {len(sample_project_rows)} sample-project links")

    if run_rows:
        for batch in batched(run_rows, 20000):
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO run
                (run_accession, experiment_accession, bioproject_accession, sra_study_accession,
                 primary_sample_accession, release_date, load_date, download_path, library_name,
                 library_strategy, platform, model, scientific_name, center_name,
                 submission_accession, consent)
                VALUES %s
                ON CONFLICT (run_accession) DO UPDATE SET
                    experiment_accession = EXCLUDED.experiment_accession,
                    bioproject_accession = EXCLUDED.bioproject_accession,
                    sra_study_accession = EXCLUDED.sra_study_accession,
                    primary_sample_accession = EXCLUDED.primary_sample_accession,
                    release_date = EXCLUDED.release_date,
                    load_date = EXCLUDED.load_date,
                    download_path = EXCLUDED.download_path,
                    library_name = EXCLUDED.library_name,
                    library_strategy = EXCLUDED.library_strategy,
                    platform = EXCLUDED.platform,
                    model = EXCLUDED.model,
                    scientific_name = EXCLUDED.scientific_name,
                    center_name = EXCLUDED.center_name,
                    submission_accession = EXCLUDED.submission_accession,
                    consent = EXCLUDED.consent
                """,
                batch,
                page_size=20000,
            )
            conn.commit()
    print(f"  Loaded {len(run_rows)} runs")

    if sample_run_rows:
        for batch in batched(sample_run_rows, 20000):
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO sample_run
                (sample_pk, run_accession, run_rank)
                VALUES %s
                ON CONFLICT (sample_pk, run_accession) DO NOTHING
                """,
                batch,
                page_size=20000,
            )
            conn.commit()
    print(f"  Loaded {len(sample_run_rows)} sample-run links")

    cur.close()


def load_mag(conn, sample_map: Dict[str, int]) -> None:
    print("Loading MAGs...")
    rows = []
    with GENOME_METADATA.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            sample_id = (row.get("derived_from_sample") or "").strip()
            sample_pk = sample_map.get(sample_id)
            if sample_pk is None:
                continue
            rows.append(
                (
                    row["genome_id"],
                    sample_pk,
                    row["spire_cluster"] or None,
                    row["spire_cluster_assignment"] or None,
                    to_int(row["genome_size"]),
                    to_int(row["genome_size_est"]),
                    to_float(row["gs_est_ratio"]),
                    to_int(row["n_contigs"]),
                    to_int(row["n50"]),
                    to_int(row["max_contig_length"]),
                    to_int(row["translation_table"]),
                    to_float(row["completeness"]),
                    to_float(row["contamination"]),
                    to_float(row["drep"]),
                    to_int(row["n_genes"]),
                    row["gunc_taxlevel"] or None,
                    to_float(row["clade_separation_score"]),
                    to_float(row["gunc_contamination"]),
                    to_float(row["reference_representation_score"]),
                    to_bool(row["gunc_pass"]),
                    to_bool(row["gunc_pass_5"]),
                    row["classification"] or None,
                    row["domain"] or None,
                    row["phylum"] or None,
                    row["class"] or None,
                    row["order"] or None,
                    row["family"] or None,
                    row["genus"] or None,
                    row["species"] or None,
                    to_float(row["red_value"]),
                )
            )
            if len(rows) >= 20000:
                _flush_mag_batch(conn, rows)
                rows = []

    if rows:
        _flush_mag_batch(conn, rows)

    cur = conn.cursor()
    cur.execute("SELECT count(*) AS cnt FROM mag")
    total = cur.fetchone()["cnt"]
    cur.close()
    print(f"  Loaded {total} MAGs")


def _flush_mag_batch(conn, rows):
    cur = conn.cursor()
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO mag
        (genome_id, sample_pk, spire_cluster, spire_cluster_assignment, genome_size,
         genome_size_est, gs_est_ratio, n_contigs, n50, max_contig_length,
         translation_table, completeness, contamination, drep, n_genes,
         gunc_taxlevel, clade_separation_score, gunc_contamination,
         reference_representation_score, gunc_pass, gunc_pass_5, classification,
         domain, phylum, class_name, order_name, family, genus, species, red_value)
        VALUES %s
        """,
        rows,
        page_size=10000,
    )
    conn.commit()
    cur.close()


def enrich_samples_from_sample_env_new(conn) -> None:
    if not SAMPLE_ENV_NEW.exists():
        return
    print("Enriching samples with environment data...")
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS sample_env_new_raw")
    cur.execute(
        """
        CREATE TEMP TABLE sample_env_new_raw (
            sample_id TEXT PRIMARY KEY,
            biome1 TEXT,
            biome2 TEXT,
            biome3 TEXT,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            has_coordinates BOOLEAN
        )
        """
    )

    payload: Dict[str, Dict] = {}
    with SAMPLE_ENV_NEW.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            sample_id = clean_text(row.get("Sample_id"))
            if not sample_id:
                continue
            entry = payload.setdefault(
                sample_id,
                {"biome1": None, "biome2": None, "biome3": None, "latitude": None, "longitude": None, "has_coordinates": False},
            )
            for source_key, dest_key in (("group1", "biome1"), ("group2", "biome2"), ("group3", "biome3")):
                value = clean_text(row.get(source_key))
                if value:
                    value = value.replace("_", " ")
                if value and not entry[dest_key]:
                    entry[dest_key] = value
            lat = parse_coord_from_fields(row.get("Lat"), row.get("Lat_metalog"))
            lon = parse_coord_from_fields(row.get("Lon"), row.get("Lon_metalog"))
            if lat is not None and entry["latitude"] is None:
                entry["latitude"] = lat
            if lon is not None and entry["longitude"] is None:
                entry["longitude"] = lon
            if entry["latitude"] is not None and entry["longitude"] is not None:
                entry["has_coordinates"] = True

    raw_rows = [
        (sample_id, info["biome1"], info["biome2"], info["biome3"],
         info["latitude"], info["longitude"], info["has_coordinates"])
        for sample_id, info in sorted(payload.items())
    ]
    for batch in batched(raw_rows, 50000):
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO sample_env_new_raw
            (sample_id, biome1, biome2, biome3, latitude, longitude, has_coordinates)
            VALUES %s
            ON CONFLICT (sample_id) DO UPDATE SET
                biome1 = EXCLUDED.biome1,
                biome2 = EXCLUDED.biome2,
                biome3 = EXCLUDED.biome3,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                has_coordinates = EXCLUDED.has_coordinates
            """,
            batch,
            page_size=50000,
        )

    # Fix swapped lat/lon in staging data
    cur.execute(
        """
        UPDATE sample_env_new_raw
        SET latitude = longitude, longitude = latitude
        WHERE latitude > 90 OR latitude < -90
        """
    )
    conn.commit()

    cur.execute(
        """
        UPDATE sample s
        SET biome1 = COALESCE(s.biome1, r.biome1),
            biome2 = COALESCE(s.biome2, r.biome2),
            biome3 = COALESCE(s.biome3, r.biome3),
            latitude = COALESCE(s.latitude, r.latitude),
            longitude = COALESCE(s.longitude, r.longitude),
            has_coordinates = CASE
                WHEN s.has_coordinates THEN TRUE
                WHEN r.has_coordinates THEN TRUE
                ELSE s.has_coordinates
            END
        FROM sample_env_new_raw r
        WHERE s.sample_id = r.sample_id
        """
    )
    conn.commit()
    cur.execute("DROP TABLE IF EXISTS sample_env_new_raw")
    conn.commit()
    cur.close()


def load_bgc_and_gcf(conn, release_id: int) -> None:
    print("Loading BGC and GCF data...")
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TEMP TABLE gcf_stage (
            bgc_source_id BIGINT,
            gcf_id BIGINT,
            length_nt INTEGER,
            membership_value DOUBLE PRECISION,
            orig_filename TEXT,
            genome_id TEXT,
            bgc_name TEXT,
            contig_name TEXT,
            region_number INTEGER
        )
        """
    )

    rows = []
    with GCF_SORTED.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            orig_filename = row["orig_filename"]
            match = ORIG_FILENAME_RE.match(orig_filename)
            genome_id = match.group("genome_id") if match else None
            contig_name = match.group("contig_name") if match else None
            region_number = int(match.group("region_number")) if match else None
            bgc_name = orig_filename[:-4] if orig_filename.endswith(".gbk") else orig_filename
            rows.append(
                (
                    to_int(row["id"]),
                    to_int(row["gcf_id"]),
                    to_int(row["length_nt"]),
                    to_float(row["membership_value"]),
                    orig_filename,
                    genome_id,
                    bgc_name,
                    contig_name,
                    region_number,
                )
            )
            if len(rows) >= 50000:
                _flush_gcf_stage(cur, rows)
                conn.commit()
                rows = []

    if rows:
        _flush_gcf_stage(cur, rows)
        conn.commit()

    cur.execute(
        "INSERT INTO gcf (gcf_id) SELECT DISTINCT gcf_id FROM gcf_stage ORDER BY gcf_id"
        " ON CONFLICT (gcf_id) DO NOTHING"
    )
    conn.commit()

    # Indexes for fast JOINs
    cur.execute("CREATE INDEX ON gcf_stage (genome_id)")
    cur.execute("CREATE INDEX ON gcf_stage (bgc_source_id)")
    conn.commit()

    cur.execute(
        """
        INSERT INTO bgc
        (bgc_source_id, bgc_name, mag_pk, sample_pk, orig_filename,
         contig_name, region_number, length_nt)
        SELECT
            gs.bgc_source_id,
            gs.bgc_name,
            m.mag_pk,
            m.sample_pk,
            gs.orig_filename,
            gs.contig_name,
            gs.region_number,
            gs.length_nt
        FROM gcf_stage gs
        JOIN mag m ON m.genome_id = gs.genome_id
        ON CONFLICT (bgc_name) DO NOTHING
        """
    )
    conn.commit()

    cur.execute(
        """
        INSERT INTO bgc_gcf_membership
        (release_id, bgc_pk, gcf_id, membership_value, membership_status,
         is_core, is_backbone, is_peripheral)
        SELECT
            %s,
            b.bgc_pk,
            gs.gcf_id,
            gs.membership_value,
            CASE
                WHEN gs.membership_value <= 0.1 THEN 'backbone'
                WHEN gs.membership_value <= 0.4 THEN 'core'
                ELSE 'peripheral'
            END,
            CASE WHEN gs.membership_value <= 0.4 THEN TRUE ELSE FALSE END,
            CASE WHEN gs.membership_value <= 0.1 THEN TRUE ELSE FALSE END,
            CASE WHEN gs.membership_value > 0.4 THEN TRUE ELSE FALSE END
        FROM gcf_stage gs
        JOIN bgc b ON b.bgc_source_id = gs.bgc_source_id
        ON CONFLICT (release_id, bgc_pk) DO NOTHING
        """,
        (release_id,),
    )
    conn.commit()

    cur.execute("DROP TABLE gcf_stage")
    conn.commit()
    cur.close()

    # Print counts
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS cnt FROM bgc")
    bgc_count = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) AS cnt FROM gcf")
    gcf_count = cur.fetchone()["cnt"]
    cur.execute("SELECT count(*) AS cnt FROM bgc_gcf_membership")
    memb_count = cur.fetchone()["cnt"]
    cur.close()
    print(f"  Loaded {bgc_count} BGCs, {gcf_count} GCFs, {memb_count} memberships")


def _flush_gcf_stage(cur, rows):
    psycopg2.extras.execute_values(
        cur,
        """
        INSERT INTO gcf_stage
        (bgc_source_id, gcf_id, length_nt, membership_value, orig_filename,
         genome_id, bgc_name, contig_name, region_number)
        VALUES %s
        """,
        rows,
        page_size=50000,
    )


def enrich_bgc_from_full_scape(conn) -> None:
    if not FULL_SCAPE_ENV.exists():
        return
    print("Enriching BGCs from spire_full_scape_env.tsv (via COPY)...")
    cur = conn.cursor()

    # Drop old staging table if exists
    cur.execute("DROP TABLE IF EXISTS _full_scape_raw")
    # Create staging table with all 61 columns from the TSV (all TEXT for fast COPY)
    cur.execute("""
        CREATE TEMP TABLE _full_scape_raw (
            genome_id TEXT, record_id TEXT, region TEXT, start TEXT, "end" TEXT,
            contig_edge_raw TEXT, product TEXT, KCB_hit TEXT, KCB_acc TEXT, KCB_sim TEXT,
            record_desc TEXT, category TEXT, bigscape_type TEXT, spire_cluster TEXT,
            spire_cluster_assignment TEXT, genome_size TEXT, genome_size_est TEXT,
            gs_est_ratio TEXT, n_contigs TEXT, n50 TEXT, max_contig_length TEXT,
            translation_table TEXT, completeness TEXT, contamination TEXT, drep TEXT,
            n_genes TEXT, gunc_taxlevel TEXT, clade_separation_score TEXT,
            gunc_contamination TEXT, reference_representation_score TEXT,
            gunc_pass TEXT, gunc_pass_5 TEXT, classification TEXT, domain TEXT,
            phylum TEXT, class TEXT, "order" TEXT, family TEXT, genus TEXT, species TEXT,
            red_value TEXT, derived_from_sample TEXT, Habitat2_metalog TEXT,
            Habitat3_metalog TEXT, Habitat4_metalog TEXT, group2 TEXT, group1 TEXT,
            group3 TEXT, Habitat_new_1 TEXT, Habitat_new_2 TEXT, Habitat1_metalog TEXT,
            Spire_tag TEXT, Sample_id TEXT, MAGs TEXT, Lat TEXT, Lon TEXT,
            Lat_metalog TEXT, Lon_metalog TEXT, env_level_1 TEXT, env_level_2 TEXT,
            row_number TEXT
        )
    """)

    # COPY the TSV directly into PG (extremely fast)
    with FULL_SCAPE_ENV.open("r", encoding="utf-8") as fh:
        cur.copy_expert(
            "COPY _full_scape_raw FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', HEADER true)",
            fh,
        )
    conn.commit()

    # Transform: build bgc_name and clean values, then UPDATE
    cur.execute("""
        CREATE TEMP TABLE full_scape_bgc_stage AS
        SELECT
            record_id || '.region' || lpad(round(region::numeric)::int::text, 3, '0') AS bgc_name,
            NULLIF(TRIM(product), '') AS product_primary,
            CASE WHEN NULLIF(TRIM(product), '') IS NOT NULL
                 THEN json_build_array(NULLIF(TRIM(product), ''))::text END AS products_json,
            NULLIF(TRIM(bigscape_type), '') AS category_primary,
            CASE WHEN NULLIF(TRIM(bigscape_type), '') IS NOT NULL
                 THEN json_build_array(NULLIF(TRIM(bigscape_type), ''))::text END AS categories_json,
            CASE WHEN LOWER(TRIM(contig_edge_raw)) IN ('true', '1', 'yes') THEN TRUE
                 WHEN LOWER(TRIM(contig_edge_raw)) IN ('false', '0', 'no') THEN FALSE
                 ELSE NULL END AS contig_edge
        FROM _full_scape_raw
        WHERE region ~ '^[0-9]+(\.[0-9]+)?$'
          AND record_id IS NOT NULL AND record_id <> ''
          AND (product <> '' OR bigscape_type <> '' OR contig_edge_raw <> '')
    """)
    cur.execute("CREATE INDEX ON full_scape_bgc_stage (bgc_name)")
    conn.commit()

    cur.execute("SELECT count(*) AS cnt FROM full_scape_bgc_stage")
    cnt = cur.fetchone()["cnt"]
    print(f"  Staged {cnt} enrichment rows")

    cur.execute("""
        UPDATE bgc b
        SET product_primary = COALESCE(s.product_primary, b.product_primary),
            products_json = COALESCE(s.products_json, b.products_json),
            category_primary = COALESCE(s.category_primary, b.category_primary),
            categories_json = COALESCE(s.categories_json, b.categories_json),
            contig_edge = COALESCE(s.contig_edge, b.contig_edge)
        FROM full_scape_bgc_stage s
        WHERE s.bgc_name = b.bgc_name
    """)
    conn.commit()

    cur.execute("DROP TABLE IF EXISTS _full_scape_raw")
    cur.execute("DROP TABLE IF EXISTS full_scape_bgc_stage")
    conn.commit()
    cur.close()
    print("  Done")


def enrich_local_antismash(conn) -> None:
    print("Enriching BGCs from local antiSMASH results...")
    json_paths = []
    for pattern in ("spire_mag_*/spire_mag_*.json", "spire_mag_*/spire_mag_*/spire_mag_*.json"):
        json_paths.extend(ROOT.glob(pattern))

    cur = conn.cursor()
    updates = []
    gcf_type_updates = []
    for json_path in json_paths:
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        genome_dir = json_path.parent
        if genome_dir.name.startswith("spire_mag_") is False and genome_dir.parent.name.startswith("spire_mag_"):
            genome_dir = genome_dir.parent
        html_path = str((genome_dir / "index.html").resolve()) if (genome_dir / "index.html").exists() else None
        for record in data.get("records", []):
            record_id = record.get("id")
            areas = record.get("areas") or []
            region_features = [f for f in record.get("features", []) if f.get("type") == "region"]
            for feature in region_features:
                qualifiers = feature.get("qualifiers", {})
                region_number = int((qualifiers.get("region_number") or ["1"])[0])
                bgc_name = f"{record_id}.region{region_number:03d}"
                product_primary = (qualifiers.get("product") or [None])[0]
                contig_edge = to_bool((qualifiers.get("contig_edge") or [None])[0] or "")
                antismash_tool = (qualifiers.get("tool") or [None])[0]
                start_nt = end_nt = None
                location = feature.get("location") or ""
                match = LOCATION_RE.search(location)
                if match:
                    start_nt = int(match.group(1)) + 1
                    end_nt = int(match.group(2))
                category_primary = None
                categories = []
                products = []
                raw_region = {"feature": feature}
                for area in areas:
                    products.extend(area.get("products") or [])
                    protoclusters = area.get("protoclusters") or {}
                    for cluster in protoclusters.values():
                        category = cluster.get("category")
                        if category:
                            categories.append(category)
                            if category_primary is None:
                                category_primary = category
                    if product_primary and product_primary in (area.get("products") or []):
                        raw_region["area"] = area
                if not products and product_primary:
                    products = [product_primary]
                gbk_path = genome_dir / f"{bgc_name}.gbk"
                updates.append(
                    (
                        product_primary,
                        json.dumps(products, ensure_ascii=False) if products else None,
                        category_primary,
                        json.dumps(categories, ensure_ascii=False) if categories else None,
                        contig_edge,
                        antismash_tool,
                        html_path,
                        str(gbk_path.resolve()) if gbk_path.exists() else None,
                        json.dumps(raw_region, ensure_ascii=False),
                        start_nt,
                        end_nt,
                        bgc_name,
                    )
                )
                if category_primary:
                    gcf_type_updates.append((category_primary, bgc_name))

    if updates:
        psycopg2.extras.execute_values(
            cur,
            """
            UPDATE bgc b SET
                product_primary = v.product_primary,
                products_json = v.products_json,
                category_primary = v.category_primary,
                categories_json = v.categories_json,
                contig_edge = v.contig_edge,
                antismash_tool = v.antismash_tool,
                antismash_html_path = v.antismash_html_path,
                antismash_gbk_path = v.antismash_gbk_path,
                raw_region_json = v.raw_region_json,
                start_nt = v.start_nt,
                end_nt = v.end_nt
            FROM (VALUES %s) AS v(
                product_primary, products_json, category_primary, categories_json,
                contig_edge, antismash_tool, antismash_html_path, antismash_gbk_path,
                raw_region_json, start_nt, end_nt, bgc_name
            )
            WHERE b.bgc_name = v.bgc_name
            """,
            updates,
            page_size=5000,
        )
        conn.commit()

    if gcf_type_updates:
        psycopg2.extras.execute_values(
            cur,
            """
            UPDATE gcf g
            SET representative_type = COALESCE(g.representative_type, v.representative_type)
            FROM (VALUES %s) AS v(representative_type, bgc_name)
            WHERE g.gcf_id IN (
                SELECT gm.gcf_id
                FROM bgc_gcf_membership gm
                JOIN bgc b ON b.bgc_pk = gm.bgc_pk
                WHERE b.bgc_name = v.bgc_name
            )
            """,
            [(cat, bgc_name) for cat, bgc_name in gcf_type_updates],
            page_size=5000,
        )
        conn.commit()

    cur.close()


def enrich_bgc_npclassifier(conn) -> None:
    if not NPCLASSIFIER_TSV.exists():
        return
    print("Enriching BGCs with NPClassifier data (via COPY)...")
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS _np_raw")
    cur.execute("""
        CREATE TEMP TABLE _np_raw (
            Origin_file TEXT,
            Predicted_SMILES TEXT,
            Pathway TEXT,
            Superclass TEXT,
            Class TEXT
        )
    """)

    with NPCLASSIFIER_TSV.open("r", encoding="utf-8") as fh:
        cur.copy_expert(
            "COPY _np_raw FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', HEADER true)",
            fh,
        )
    conn.commit()

    cur.execute("""
        CREATE TEMP TABLE _np AS
        SELECT
            TRIM(Origin_file) AS name,
            NULLIF(TRIM(Predicted_SMILES), '') AS smiles,
            NULLIF(TRIM(Pathway), '') AS pathway,
            CASE WHEN UPPER(TRIM(Superclass)) = 'NA' THEN NULL ELSE NULLIF(TRIM(Superclass), '') END AS superclass,
            CASE WHEN UPPER(TRIM(Class)) = 'NA' THEN NULL ELSE NULLIF(TRIM(Class), '') END AS cls
        FROM _np_raw
        WHERE Origin_file IS NOT NULL AND TRIM(Origin_file) <> ''
    """)
    cur.execute("CREATE INDEX ON _np (name)")
    conn.commit()

    cur.execute("""
        UPDATE bgc b
        SET predicted_smiles = n.smiles,
            np_classifier_pathway = n.pathway,
            np_classifier_superclass = n.superclass,
            np_classifier_class = n.cls
        FROM _np n
        WHERE n.name = b.bgc_name
    """)
    conn.commit()

    cur.execute("DROP TABLE IF EXISTS _np_raw")
    cur.execute("DROP TABLE IF EXISTS _np")
    conn.commit()
    cur.close()
    print("  Done")


def enrich_geo_region_from_map_filters(conn) -> None:
    if not MAP_FILTERS.exists():
        return
    print("Enriching geo_region from map filters...")
    try:
        payload = json.loads(MAP_FILTERS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return

    sample_board: Dict[str, str] = {}
    for key, entry in payload.items():
        kind = (entry.get("kind") or "").strip()
        label = (entry.get("label") or "").strip()
        if kind != "board" or not label:
            continue
        for sample_id in entry.get("sample_ids") or []:
            sid = str(sample_id).strip()
            if sid and sid not in sample_board:
                sample_board[sid] = label

    if not sample_board:
        return

    cur = conn.cursor()
    cur.execute("UPDATE sample SET geo_region = NULL")

    psycopg2.extras.execute_values(
        cur,
        """
        UPDATE sample s SET geo_region = v.geo_region
        FROM (VALUES %s) AS v(geo_region, sample_id)
        WHERE s.sample_id = v.sample_id
        """,
        [(board, sid) for sid, board in sample_board.items()],
        page_size=10000,
    )
    conn.commit()
    cur.close()


def refresh_materialized_views(conn) -> None:
    print("Refreshing materialized views...")
    cur = conn.cursor()
    for view in ["mv_home_stats", "mv_sample_page", "mv_mag_page", "mv_bgc_page", "mv_gcf_page"]:
        cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")
    conn.commit()
    cur.close()
    print("  Done")


def main() -> None:
    print("=" * 60)
    print("Spire BGC PostgreSQL Database Builder")
    print("=" * 60)

    # Ensure database exists
    ensure_database()

    # Connect with autocommit off for bulk loading speed
    conn = get_conn(autocommit=False)

    try:
        cur = conn.cursor()
        cur.execute("SET search_path TO spire, public")
        cur.close()

        # 1. Drop & recreate schema
        print("\n[1/9] Initializing schema...")
        drop_and_init_schema(conn)

        # 2. Release and assets
        print("\n[2/9] Creating release...")
        release_id = load_release_and_assets(conn)

        # 3. Samples
        print("\n[3/9] Loading samples...")
        sample_map = load_samples(conn)

        # 4. SRA
        print("\n[4/9] Loading SRA data...")
        load_sra(conn, sample_map)

        # 5. MAGs
        print("\n[5/9] Loading MAGs...")
        load_mag(conn, sample_map)

        # 6. Enrich samples
        print("\n[6/9] Enriching samples...")
        enrich_samples_from_sample_env_new(conn)
        enrich_geo_region_from_map_filters(conn)

        # 7. BGC + GCF
        print("\n[7/9] Loading BGCs and GCFs...")
        load_bgc_and_gcf(conn, release_id)
        enrich_bgc_from_full_scape(conn)
        enrich_local_antismash(conn)
        enrich_bgc_npclassifier(conn)

        # 8. Refresh materialized views
        print("\n[8/9] Building materialized views...")
        refresh_materialized_views(conn)

        # 9. Build stats cache
        print("\n[9/9] Building stats cache...")
        build_stats_json(conn)

        print("\n" + "=" * 60)
        print("Build complete!")
        print("=" * 60)

        # Optional: rebuild visualization assets
        import subprocess as _sp
        _sp.run(["python3", str(ROOT / "scripts" / "build_stats_charts_pg.py")], check=False)

    finally:
        conn.close()


def build_stats_json(conn) -> None:
    import json as _json

    cur = conn.cursor()

    group1_rows = [{"label": r["g"], "value": r["c"]} for r in cur.execute(
        "SELECT biome1 AS g, COUNT(*) AS c FROM sample WHERE biome1 IS NOT NULL AND biome1 <> '' GROUP BY biome1 ORDER BY c DESC"
    ).fetchall()]
    group2_rows = [{"label": r["g"], "value": r["c"]} for r in cur.execute(
        "SELECT biome2 AS g, COUNT(*) AS c FROM sample WHERE biome2 IS NOT NULL AND biome2 <> '' GROUP BY biome2 ORDER BY c DESC"
    ).fetchall()]
    group3_rows = [{"label": r["g"], "value": r["c"]} for r in cur.execute(
        "SELECT biome3 AS g, COUNT(*) AS c FROM sample WHERE biome3 IS NOT NULL AND biome3 <> '' GROUP BY biome3 ORDER BY c DESC"
    ).fetchall()]

    links_12 = []
    links_23 = []
    for row in cur.execute(
        "SELECT biome1, biome2, biome3 FROM sample WHERE biome1 IS NOT NULL AND biome2 IS NOT NULL AND biome3 IS NOT NULL"
    ).fetchall():
        links_12.append({"source": row["biome1"], "target": row["biome2"]})
        links_23.append({"source": row["biome2"], "target": row["biome3"]})

    dst = ROOT / "web" / "stats_cache.json"
    _json.dump({
        "bgc_type_rows": [{"label": r["c"], "value": r["cnt"]} for r in cur.execute(
            "SELECT category_primary AS c, COUNT(*) AS cnt FROM bgc WHERE category_primary IS NOT NULL AND category_primary <> '' GROUP BY category_primary ORDER BY cnt DESC"
        ).fetchall()],
        "group1_rows": group1_rows,
        "group2_rows": group2_rows,
        "group3_rows": group3_rows,
        "links_12": links_12,
        "links_23": links_23,
    }, open(dst, "w"), ensure_ascii=False)

    cur.close()


if __name__ == "__main__":
    main()
