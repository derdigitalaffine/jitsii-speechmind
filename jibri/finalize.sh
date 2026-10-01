#!/bin/bash
# Wird von Jibri aufgerufen, sobald eine Aufzeichnung abgeschlossen ist.
# $1 = Verzeichnis der Aufzeichnung (enthält .mp4 und metadata.json)
#
# Wir setzen nur eine Markierungsdatei. Das Portal überwacht das gemeinsame
# Aufnahmeverzeichnis und erzeugt die MP3; die Transkription startet ein Mensch.
# So braucht der Jibri-Container weder curl noch Zugangsdaten.

RECORDINGS_DIR="$1"

if [ -z "$RECORDINGS_DIR" ] || [ ! -d "$RECORDINGS_DIR" ]; then
  echo "finalize.sh: Verzeichnis fehlt: '$RECORDINGS_DIR'" >&2
  exit 1
fi

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$RECORDINGS_DIR/.finalized"
chmod 644 "$RECORDINGS_DIR/.finalized" 2>/dev/null || true
echo "finalize.sh: $RECORDINGS_DIR als fertig markiert (das Portal erzeugt jetzt die MP3)"
exit 0
