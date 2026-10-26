#!/bin/bash
# One-time server setup for pc_market (run once with sudo; safe to run again).
# Touches only its own files: user pcmarket, /opt/pcmarket, /var/www/pcmarket, its own nginx site and snippet,
# its own systemd units and sudoers file. Other sites, nginx.conf and the firewall are not changed.
set -euo pipefail
REPO=https://github.com/AzizArgon/-.git
HOST=pcmarket.khudoberdi.uz
APP=/opt/pcmarket/app
ADMIN=${SUDO_USER:-azi}
cd /

[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
exec > >(tee /home/"$ADMIN"/pcmarket_setup.log) 2>&1
log() { echo; echo "=== $*"; }
friend() { curl -s -o /dev/null -w "%{http_code}" -H "Host: khudoberdi.uz" http://127.0.0.1/; }

FRIEND_BEFORE=$(friend)
log "khudoberdi.uz before: $FRIEND_BEFORE"

log "1. User and folders"
id pcmarket >/dev/null 2>&1 || useradd --system --home-dir /opt/pcmarket --shell /usr/sbin/nologin pcmarket
install -d -o pcmarket -g pcmarket -m 750 /opt/pcmarket
install -d -o pcmarket -g pcmarket -m 700 /opt/pcmarket/private /opt/pcmarket/backups
install -d -o pcmarket -g pcmarket -m 755 /var/www/pcmarket
[ -d $APP/.git ] || sudo -u pcmarket -H git clone -q "$REPO" $APP
[ -f /var/www/pcmarket/index.html ] || echo "pc_market: setup in progress" > /var/www/pcmarket/index.html

log "2. Sudo rule for $ADMIN (only: act as pcmarket, restart and view our service)"
cat > /etc/sudoers.d/pcmarket <<EOF
$ADMIN ALL=(pcmarket) NOPASSWD: ALL
$ADMIN ALL=(root) NOPASSWD: /usr/bin/systemctl restart pcmarket, /usr/bin/systemctl is-active pcmarket, /usr/bin/systemctl status pcmarket --no-pager, /usr/bin/journalctl -u pcmarket --no-pager -n 200, /usr/bin/systemctl start pcmarket-backup
EOF
chmod 440 /etc/sudoers.d/pcmarket
visudo -cf /etc/sudoers.d/pcmarket || { rm -f /etc/sudoers.d/pcmarket; echo "sudoers rule rejected"; exit 1; }

log "3. systemd: backend service and daily backup"
install -m 644 $APP/deploy/systemd/pcmarket.service $APP/deploy/systemd/pcmarket-backup.service \
    $APP/deploy/systemd/pcmarket-backup.timer /etc/systemd/system/
chmod 755 $APP/deploy/backup.sh
systemctl daemon-reload
systemctl enable pcmarket.service
systemctl enable --now pcmarket-backup.timer

log "4. nginx: backup of configs, own site for $HOST"
NGINX_BACKUP=/var/backups/nginx_$(date +%F_%H%M%S)_before_pcmarket.tgz
tar czf "$NGINX_BACKUP" -C /etc nginx
echo "nginx configs saved to $NGINX_BACKUP"
rollback() {
    echo "nginx -t failed - removing pcmarket site, other sites untouched"
    rm -f /etc/nginx/sites-enabled/pcmarket /etc/nginx/sites-available/pcmarket /etc/nginx/snippets/pcmarket-app.conf
    nginx -t && systemctl reload nginx
    exit 1
}
install -m 644 $APP/deploy/nginx/pcmarket-app.conf /etc/nginx/snippets/pcmarket-app.conf
install -m 644 $APP/deploy/nginx/pcmarket-http.conf /etc/nginx/sites-available/pcmarket
ln -sf /etc/nginx/sites-available/pcmarket /etc/nginx/sites-enabled/pcmarket
nginx -t || rollback
systemctl reload nginx

log "5. Let's Encrypt certificate for $HOST (checked over :80 through Cloudflare)"
if certbot certonly --webroot -w /var/www/acme -d $HOST --cert-name pcmarket --non-interactive --agree-tos \
        --register-unsafely-without-email --keep-until-expiring --deploy-hook "systemctl reload nginx"; then
    cat $APP/deploy/nginx/pcmarket-http.conf $APP/deploy/nginx/pcmarket-ssl.conf > /etc/nginx/sites-available/pcmarket
    nginx -t || rollback
    systemctl reload nginx
    echo "HTTPS on :2053 ready"
else
    echo "Certificate not issued - the site works over :80 (Cloudflare Flexible); run this script again later"
fi

log "6. Checks"
sleep 1
FRIEND_AFTER=$(friend)
echo "khudoberdi.uz: before $FRIEND_BEFORE, after $FRIEND_AFTER"
echo "pcmarket over :80: $(curl -s -o /dev/null -w "%{http_code}" -H "Host: $HOST" http://127.0.0.1/)"
echo "firewall (not changed):"; ufw status | head -5
[ "$FRIEND_BEFORE" = "$FRIEND_AFTER" ] && echo "SETUP DONE" || echo "WARNING: khudoberdi.uz answer changed"
