#!/usr/bin/env bash
# Erzeugt .env mit Domains und zufälligen Secrets und legt die Datenordner an.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ] && [ "${1:-}" != "--force" ]; then
  echo ".env existiert bereits. Mit '--force' überschreiben."
  exit 1
fi

gen() { openssl rand -hex 24; }

ask() {
  local prompt="$1" default="${2:-}" answer
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " answer
    echo "${answer:-$default}"
  else
    read -r -p "$prompt: " answer
    echo "$answer"
  fi
}

echo "== Videokonferenzserver der Verbandsgemeinde Otterbach-Otterberg – Setup =="
MEET_DOMAIN=$(ask "Domain für die Videokonferenz" "meet.example.com")
PORTAL_DOMAIN=$(ask "Domain für das Portal" "portal.${MEET_DOMAIN#*.}")
ACME_EMAIL=$(ask "E-Mail für Zertifikats-Warnungen (Let's Encrypt, später im Portal einschaltbar)")
DETECTED_IP=$(curl -fs4 --max-time 5 https://api.ipify.org 2>/dev/null || true)
PUBLIC_IP=$(ask "Öffentliche IP des Servers" "${DETECTED_IP}")
ADMIN_EMAIL=$(ask "E-Mail des ersten Portal-Admins" "${ACME_EMAIL}")
ADMIN_PASSWORD=$(gen | cut -c1-20)

cp .env.example .env

set_var() {
  local key="$1" value="$2"
  # Trennzeichen | , weil Werte Punkte und Slashes enthalten können
  sed -i.bak "s|^${key}=.*|${key}=${value}|" .env
}

set_var MEET_DOMAIN "$MEET_DOMAIN"
set_var PORTAL_DOMAIN "$PORTAL_DOMAIN"
set_var ACME_EMAIL "$ACME_EMAIL"
set_var PUBLIC_URL "https://${MEET_DOMAIN}"
set_var JVB_ADVERTISE_IPS "$PUBLIC_IP"
set_var PORTAL_ADMIN_EMAIL "$ADMIN_EMAIL"
set_var PORTAL_ADMIN_PASSWORD "$ADMIN_PASSWORD"

for key in JWT_APP_SECRET JICOFO_AUTH_PASSWORD JVB_AUTH_PASSWORD JIGASI_XMPP_PASSWORD \
           JIGASI_TRANSCRIBER_PASSWORD JIBRI_RECORDER_PASSWORD JIBRI_XMPP_PASSWORD \
           PORTAL_SECRET_KEY; do
  set_var "$key" "$(gen)"
done
rm -f .env.bak
chmod 600 .env

mkdir -p data/{web/crontabs,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb,jibri,recordings,portal,caddy/data,caddy/config,caddy/conf}
chmod +x jibri/finalize.sh
# Jibri schreibt als eigener Benutzer in das Aufnahmeverzeichnis
chmod 777 data/recordings

echo
echo "Fertig. .env wurde erzeugt."
echo
echo "  Konferenz:  https://${MEET_DOMAIN}"
echo "  Portal:     https://${PORTAL_DOMAIN}"
echo "  Admin:      ${ADMIN_EMAIL}"
echo "  Passwort:   ${ADMIN_PASSWORD}   (muss beim ersten Login geändert werden)"
echo
echo "Zertifikat: zunächst selbst signiert (Browser warnt). Let's Encrypt schalten Sie danach im"
echo "             Portal ein: Admin > HTTPS & Zertifikat (DNS muss auf diesen Server zeigen)."
echo
echo "Firewall: TCP 80, 443 und UDP ${JVB_PORT:-10000} freigeben."
echo "Start:     docker compose up -d --build"
