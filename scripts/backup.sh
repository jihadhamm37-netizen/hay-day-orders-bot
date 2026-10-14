#!/usr/bin/env bash
# Manual backup:  DATABASE_URL=... ./scripts/backup.sh [output_dir]
set -euo pipefail
OUT="${1:-./backups}"
mkdir -p "$OUT"
FILE="$OUT/hdfarm-$(date -u +%Y%m%d-%H%M%S).dump"
pg_dump --format=custom --no-owner --no-privileges --file "$FILE" "$DATABASE_URL"
echo "backup written: $FILE"
