#!/bin/bash
# Updates the public site with one command (run through deploy.bat on the laptop).
# push -> backup of the server DB -> git pull -> dependencies -> frontend built here and uploaded -> restart -> check.
# The server database is never replaced: only code and built files change.
set -euo pipefail
cd "$(dirname "$0")/.."
SITE=https://pcmarket.khudoberdi.uz
SSH_HOST=pcmarket   # alias from ~/.ssh/config (docs/deploy.md)

step() { echo; echo "=== $*"; }

step "1/6 git push"
if [ -n "$(git status --porcelain)" ]; then
    echo "Warning: uncommitted changes are NOT deployed (only commits are):"
    git status --short
fi
git push origin main

step "2/6 build frontend"
(cd frontend && VITE_API_URL=/api VITE_PUBLIC_DEMO=1 npm run build --silent)
tar czf "${TMPDIR:-/tmp}/pcm_dist.tgz" -C frontend/dist .
scp -q "${TMPDIR:-/tmp}/pcm_dist.tgz" "$SSH_HOST:/tmp/pcm_dist.tgz"
rm -f "${TMPDIR:-/tmp}/pcm_dist.tgz"

step "3/6 server: backup, code, dependencies, files"
ssh "$SSH_HOST" 'chmod 644 /tmp/pcm_dist.tgz && cd /tmp && sudo -u pcmarket -H bash -s' <<'EOF'
set -euo pipefail
/opt/pcmarket/app/deploy/backup.sh before_deploy 5
cd /opt/pcmarket/app
git pull -q --ff-only
git log --oneline -1
backend/.venv/bin/pip install -q -r backend/requirements.txt
rm -rf /opt/pcmarket/dist_new && mkdir /opt/pcmarket/dist_new
tar xmzf /tmp/pcm_dist.tgz -C /opt/pcmarket/dist_new
# New files first, then old assets are removed: the site never misses a file during the update
cp -r /opt/pcmarket/dist_new/. /var/www/pcmarket/
for f in /var/www/pcmarket/assets/*; do
    [ -e "/opt/pcmarket/dist_new/assets/$(basename "$f")" ] || rm -f "$f"
done
chmod -R a+rX /var/www/pcmarket
rm -rf /opt/pcmarket/dist_new
EOF
ssh "$SSH_HOST" 'rm -f /tmp/pcm_dist.tgz'

step "4/6 restart backend"
ssh "$SSH_HOST" 'sudo systemctl restart pcmarket'

step "5/6 wait for the backend"
for i in $(seq 1 30); do
    if ssh "$SSH_HOST" 'curl -sf http://127.0.0.1:8020/api/health >/dev/null'; then echo "backend is up"; break; fi
    [ "$i" = 30 ] && { echo "Backend did not start, logs:"; ssh "$SSH_HOST" 'sudo journalctl -u pcmarket --no-pager -n 200' | tail -30; exit 1; }
    sleep 2
done

step "6/6 check $SITE"
api=$(curl -s -o /dev/null -w "%{http_code}" -m 20 "$SITE/api/health")
page=$(curl -s -o /dev/null -w "%{http_code}" -m 20 "$SITE/")
echo "site: $page, api: $api"
[ "$api" = 200 ] && [ "$page" = 200 ] || { echo "DEPLOY CHECK FAILED"; exit 1; }
echo "DEPLOY OK"
