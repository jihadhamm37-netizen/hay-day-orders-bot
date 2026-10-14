#!/usr/bin/env bash
# Restore a backup into a database (DESTRUCTIVE for that database):
#   DATABASE_URL=postgresql://.../hdfarm ./scripts/restore.sh backups/<file>.dump
# Stop the bot first, restore, then start it again with the SAME ENCRYPTION_KEY.
set -euo pipefail
FILE="$1"
[ -f "$FILE" ] || { echo "file not found: $FILE"; exit 1; }
read -r -p "This will REPLACE all data in the target database. Type YES to continue: " ok
[ "$ok" = "YES" ] || { echo "aborted"; exit 1; }
pg_restore --clean --if-exists --no-owner --no-privileges --single-transaction --dbname "$DATABASE_URL" "$FILE"
echo "restore complete"
