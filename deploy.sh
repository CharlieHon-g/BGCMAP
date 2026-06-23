#!/bin/bash
set -e

# Clean local .DS_Store before deploy
find . -name '.DS_Store' -delete 2>/dev/null

# Deploy steps
export PGHOST=${PGHOST:-127.0.0.1}
export PGPORT=${PGPORT:-5432}
export PGDATABASE=${PGDATABASE:-spire_portal}
export PGUSER=${PGUSER:-spire}
export PGPASSWORD=${PGPASSWORD:-}

pip3 install -r requirements.txt
python3 db/build_spire_pg_db.py
python3 server_pg.py --host 0.0.0.0 --port 8000
