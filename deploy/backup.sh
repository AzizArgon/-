#!/bin/bash
# Consistent copy of the SQLite database (safe while the site runs).
# Usage: backup.sh [label] [keep] - daily copies keep the last 14, copies before a deploy - the last 5.
set -euo pipefail
DB=/opt/pcmarket/app/backend/database.db
DIR=/opt/pcmarket/backups
LABEL=${1:-daily}
KEEP=${2:-14}

mkdir -p "$DIR"
target="$DIR/$(date +%F_%H%M)_$LABEL.db"
sqlite3 "$DB" ".backup '$target'"
gzip -f "$target"
ls -1t "$DIR"/*_"$LABEL".db.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "backup: $target.gz"
