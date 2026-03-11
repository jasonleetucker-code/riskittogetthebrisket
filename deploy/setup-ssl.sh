#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# SSL/TLS setup via Let's Encrypt + Certbot
# Run after DNS is pointed and nginx is configured.
#
# Usage (as root):
#   bash deploy/setup-ssl.sh
#   bash deploy/setup-ssl.sh you@email.com    # optional: specify email
# ──────────────────────────────────────────────────────────────
set -euo pipefail

DOMAIN="riskittogetthebrisket.org"
EMAIL="${1:-}"

if [ -z "$EMAIL" ]; then
    echo "No email provided. Certbot will use --register-unsafely-without-email."
    echo "To provide an email: bash deploy/setup-ssl.sh you@email.com"
    EMAIL_FLAG="--register-unsafely-without-email"
else
    EMAIL_FLAG="--email $EMAIL --no-eff-email"
fi

echo "=== Obtaining SSL certificate for $DOMAIN ==="
certbot --nginx \
    -d "$DOMAIN" \
    -d "www.$DOMAIN" \
    $EMAIL_FLAG \
    --agree-tos \
    --redirect \
    --non-interactive

echo ""
echo "=== SSL setup complete ==="
echo "Certificate auto-renews via certbot systemd timer."
echo "Verify: curl https://$DOMAIN/api/health"
echo "Check renewal: certbot renew --dry-run"
