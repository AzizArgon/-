#!/bin/bash
# Downloads the newest server DB backup to F:\claudy\backups\server\ (run through get_backup.bat).
set -euo pipefail
SSH_HOST=pcmarket
DEST=/f/claudy/backups/server
mkdir -p "$DEST"
latest=$(ssh "$SSH_HOST" 'cd /tmp && sudo -u pcmarket bash -c "ls -1t /opt/pcmarket/backups/*.db.gz | head -1"')
name=$(basename "$latest")
ssh "$SSH_HOST" "cd /tmp && sudo -u pcmarket cat '$latest'" > "$DEST/$name"
gzip -df "$DEST/$name"
echo "saved: $DEST/${name%.gz}"
