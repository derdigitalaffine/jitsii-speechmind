#!/usr/bin/env bash
# Richtet auf dem Server den Ton für Jibri-Aufnahmen ein und startet Jibri neu.
#
# Jibri nimmt den Ton über die virtuelle Soundkarte "snd-aloop" des Host-Kernels auf.
# Fehlt sie, enthalten Aufnahmen und MP3-Dateien nur Stille.
#
# Aufruf (im Projektordner):   ./scripts/setup-recording-audio.sh
# Mehrfaches Ausführen ist unbedenklich.
set -euo pipefail

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

say() { printf '\n==> %s\n' "$*"; }

say "1/4  Kernelmodul snd-aloop prüfen"
if ! lsmod | grep -q '^snd_aloop'; then
  if ! $SUDO modprobe snd-aloop 2>/dev/null; then
    echo "Das Modul fehlt in diesem Kernel. Versuche, es nachzuinstallieren ..."
    if command -v apt-get >/dev/null; then
      $SUDO apt-get update -qq || true
      # Ubuntu: Zusatzmodule zum laufenden Kernel; Debian-Cloud-Kernel enthalten es oft nicht
      $SUDO apt-get install -y "linux-modules-extra-$(uname -r)" 2>/dev/null || true
    fi
    if ! $SUDO modprobe snd-aloop 2>/dev/null; then
      cat >&2 <<'MSG'

FEHLER: Das Kernelmodul snd-aloop ist nicht verfügbar.
  - Ubuntu:  sudo apt install linux-modules-extra-$(uname -r)   (danach dieses Skript erneut starten)
  - Debian:  Bei einem "cloud"-Kernel auf den normalen Kernel wechseln:
             sudo apt install linux-image-amd64 && sudo reboot
  - Virtuelle Server (LXC/OpenVZ-Container) teilen den Kernel mit dem Host: dort kann das Modul
    nur der Anbieter/Host laden. Dann ist ein anderer Servertyp (KVM/VM) nötig.
MSG
      exit 1
    fi
  fi
fi
echo "snd-aloop ist geladen."

say "2/4  Beim Neustart automatisch laden"
if [ ! -f /etc/modules-load.d/snd-aloop.conf ]; then
  echo "snd-aloop" | $SUDO tee /etc/modules-load.d/snd-aloop.conf >/dev/null
  echo "Eingetragen in /etc/modules-load.d/snd-aloop.conf"
else
  echo "Bereits eingetragen."
fi

say "3/4  Audio-Gerät prüfen"
if [ ! -e /dev/snd ]; then
  echo "FEHLER: /dev/snd existiert nicht, obwohl das Modul geladen ist." >&2
  exit 1
fi
ls /dev/snd

say "4/4  Jibri neu starten"
docker compose up -d --force-recreate jibri
sleep 8
if docker compose exec -T jibri sh -c 'cat /proc/asound/cards' 2>/dev/null | grep -qi loopback; then
  echo "Jibri sieht die virtuelle Soundkarte (Loopback)."
else
  echo "HINWEIS: Konnte die Soundkarte im Jibri-Container nicht bestätigen."
  echo "         Prüfen: docker compose logs jibri  und  docker compose exec jibri cat /proc/asound/cards"
fi

cat <<'MSG'

Fertig. Machen Sie jetzt eine kurze Testaufnahme (sprechen Sie ein paar Sätze).
Im Portal unter "Aufnahmen" darf die neue Aufnahme NICHT mit "kein Ton" markiert sein.
Bereits vorhandene stumme Aufnahmen lassen sich nicht retten: der Ton wurde nie aufgezeichnet.
MSG
