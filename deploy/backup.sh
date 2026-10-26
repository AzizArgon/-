#!/bin/bash
# Consistent copy of the SQLite database (safe while the site runs); keeps the last 14 copies.
set -euo pipefail
DB=/opt/pcmarket/app/backend/database.db
DIR=/opt/pcmarket/backups
KEEP=14

mkdir -p "$DIR"
target="$DIR/$(date +%F_%H%M)_daily.db"
sqlite3 "$DB" ".backup '$target'"
gzip -f "$target"
ls -1t "$DIR"/*_daily.db.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup: $target.gz"
