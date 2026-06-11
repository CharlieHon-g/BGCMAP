# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run (PostgreSQL — Production)

```bash
# 0. Set environment variables
export PGHOST=your-pg-host
export PGPORT=5432
export PGDATABASE=spire_portal
export PGUSER=postgres
export PGPASSWORD=your-password

# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Build the PostgreSQL database from source TSVs
python3 db/build_spire_pg_db.py

# 3. Start the local web server
python3 local_site/server_pg.py --host 0.0.0.0 --port 8000

# Or use the all-in-one deploy script
bash deploy.sh
```

## Build and Run (SQLite — Development/Preview)

```bash
# Rebuild the SQLite preview database from source TSVs
python3 db/build_spire_sqlite_db.py

# Start the local web server
python3 local_site/server.py --host 127.0.0.1 --port 8000
```

## Architecture

This is a **research portal** for browsing biosynthetic gene clusters (BGCs). Data flows through three layers:

1. **Source TSVs** (`gem_sra.tsv`, `spire_v1_genome_metadata.tsv`, `spire_gcf_sorted.tsv`, `spire_full_scape_env.tsv`) — some are symlinks to a sibling directory
2. **Database** — Two options:
   - **SQLite** (`db/spire_portal_preview.db`) — built by `db/build_spire_sqlite_db.py`, served by `local_site/server.py`
   - **PostgreSQL** — built by `db/build_spire_pg_db.py`, served by `local_site/server_pg.py`. Schema in `db/spire_postgres_schema.sql`
3. **Web frontend** — static HTML + JSON APIs

The core entity chain is: **Sample → MAG → BGC → GCF**. Both `mag` and `bgc` carry `sample_pk` directly for query performance.
`bgc_gcf_membership` links BGCs to GCFs with a `membership_value` (≤0.1 backbone, ≤0.4 core, >0.4 peripheral).

## PostgreSQL vs SQLite Key Differences

| Area | SQLite | PostgreSQL |
|---|---|---|
| Placeholder | `?` | `%s` |
| Case-insensitive | `COLLATE NOCASE` | `ILIKE` |
| Pattern match | `GLOB` | `~` (regex) |
| Booleans | `INTEGER` 0/1 | `BOOLEAN` TRUE/FALSE |
| Cast | `CAST(x AS TEXT)` | `x::text` |
| Upsert | `INSERT OR REPLACE` | `INSERT ... ON CONFLICT ... DO UPDATE` |
| Auto PK | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL` |
| Connection | `sqlite3.connect(path)` | `psycopg2.connect(params)` |

## Web frontend

The local site (`local_site/server.py` or `local_site/server_pg.py`) is a single-file Python HTTP server. It serves static HTML pages from `local_site/web/` and provides JSON APIs. Each page queries a corresponding materialized view (`mv_sample_page`, `mv_mag_page`, `mv_bgc_page`, `mv_gcf_page`) rather than joining fact tables on every request.

Key pages: `index.html` (home), `sample.html`, `mag.html`, `bgc.html`, `gcf.html`, `download.html`, `help.html`, `tax.html`.

## PostgreSQL Deployment on VM

```bash
# On the VM:
sudo apt install postgresql python3-pip  # or yum/dnf equivalent
sudo systemctl start postgresql

# Create database and user
sudo -u postgres psql -c "CREATE USER spire WITH PASSWORD 'xxx';"
sudo -u postgres psql -c "CREATE DATABASE spire_portal OWNER spire;"
sudo -u postgres psql -d spire_portal -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# Clone and deploy
git clone <repo> /opt/spire
cd /opt/spire
export PGHOST=127.0.0.1 PGDATABASE=spire_portal PGUSER=spire PGPASSWORD=xxx
pip3 install -r requirements.txt
python3 db/build_spire_pg_db.py
python3 local_site/server_pg.py --host 0.0.0.0 --port 8000
```

## Schema: code vs. database on disk

**Important**: The SQLite schema is defined in `build_spire_sqlite_db.py` (`init_db()`). The actual database file may be stale — delete it and rebuild after any schema change. The PostgreSQL schema is in `db/spire_postgres_schema.sql` and `db/build_spire_pg_db.py` (`drop_and_init_schema()`).

## Scripts

`scripts/` contains visualization builders. The `*_pg.py` variants use PostgreSQL; the originals use SQLite. These are offline rendering tools, not part of the live server.
