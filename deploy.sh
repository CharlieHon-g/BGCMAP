#!/usr/bin/env bash
# ─────────────────────────────────────────────
# Spire BGC Portal — PostgreSQL Deployment
# ─────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 1. Environment check ─────────────────────
echo ">>> Checking environment..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi

# Check required env vars
REQUIRED_VARS=("PGHOST" "PGPORT" "PGDATABASE" "PGUSER" "PGPASSWORD")
MISSING=()
for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR:-}" ]; then
        MISSING+=("$VAR")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "❌ Missing required environment variables: ${MISSING[*]}"
    echo ""
    echo "Set them before running:"
    echo "  export PGHOST=your-pg-host"
    echo "  export PGPORT=5432"
    echo "  export PGDATABASE=spire_portal"
    echo "  export PGUSER=postgres"
    echo "  export PGPASSWORD=your-password"
    exit 1
fi

echo "  PGHOST=$PGHOST"
echo "  PGPORT=$PGPORT"
echo "  PGDATABASE=$PGDATABASE"
echo "  PGUSER=$PGUSER"

# ── 2. Install dependencies ──────────────────
echo ""
echo ">>> Installing Python dependencies..."
pip3 install -r requirements.txt

# ── 3. Build database ────────────────────────
echo ""
echo ">>> Building PostgreSQL database..."
python3 db/build_spire_pg_db.py

# ── 4. Start server ──────────────────────────
HOST="${SPIRE_HOST:-0.0.0.0}"
PORT="${SPIRE_PORT:-8000}"

echo ""
echo ">>> Starting Spire BGC Portal..."
echo "    http://$HOST:$PORT"
python3 server_pg.py --host "$HOST" --port "$PORT"
