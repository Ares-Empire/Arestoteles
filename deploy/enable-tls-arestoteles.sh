#!/usr/bin/env bash
# Finish arestoteles.de: issue a Let's Encrypt cert and switch the vhost to HTTPS.
#
# Run this ONCE arestoteles.de + www resolve to this server (178.105.214.242).
# It is idempotent-ish and validates nginx before reloading, so it will not take
# down the other sites (insureares, aresium) on the shared gateway.
#
#   sudo bash deploy/enable-tls-arestoteles.sh
#
set -euo pipefail

DOMAIN=arestoteles.de
WWW=www.arestoteles.de
EMAIL=you@example.com
CONF=/root/insureai/InsureAI/backend/nginx/conf.d/arestoteles.conf
CERTBOT_CONF=/root/insureai/InsureAI/backend/certbot/conf
CERTBOT_WWW=/root/insureai/InsureAI/backend/certbot/www

echo "==> Checking DNS resolves to this host..."
for d in "$DOMAIN" "$WWW"; do
  ip=$(getent hosts "$d" | awk '{print $1}' | head -1 || true)
  echo "    $d -> ${ip:-<unresolved>}"
  if [ -z "$ip" ]; then
    echo "!! $d does not resolve yet. Wait for DNS propagation, then re-run." >&2
    exit 1
  fi
done

echo "==> Requesting cert via webroot (HTTP-01)..."
docker run --rm \
  -v "$CERTBOT_CONF":/etc/letsencrypt \
  -v "$CERTBOT_WWW":/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" -d "$WWW" \
  --email "$EMAIL" --agree-tos --no-eff-email --non-interactive

echo "==> Writing HTTPS vhost..."
cat > "$CONF" <<NGINX
# ============================================================
# Arestoteles — arestoteles.de (HTTPS). Additive vhost on insureai_nginx.
# Proxies to the arestoteles web container on the bridge gateway 172.18.0.1:5180.
# ============================================================

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN $WWW;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name $DOMAIN $WWW;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL_arestoteles:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    location = /live.json {
        proxy_pass http://172.18.0.1:5180;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        add_header Cache-Control "no-cache" always;
    }
    location / {
        proxy_pass http://172.18.0.1:5180;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_connect_timeout 10s;
        proxy_read_timeout    30s;
        proxy_send_timeout    30s;
    }
}
NGINX

echo "==> Validating + reloading nginx..."
docker exec insureai_nginx nginx -t
docker exec insureai_nginx nginx -s reload
echo "==> Done. https://$DOMAIN should now be live."
