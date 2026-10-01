#!/usr/bin/env bash
# Prüft, warum eine Aufnahme keinen Ton hat, und sagt, wo das Problem liegt.
#
# Aufruf (im Projektordner):   ./scripts/diagnose-recording.sh
# Nur lesend: es wird nichts verändert. Die Ausgabe kann 1:1 weitergegeben werden.
set -uo pipefail
cd "$(dirname "$0")/.."

dc() { docker compose "$@"; }
hr() { printf '\n==================== %s\n' "$*"; }

hr "1. Container"
dc ps jibri portal 2>&1 | cut -c1-140

hr "2. Neueste Aufnahme (Dateien)"
LAST=$(dc exec -T portal sh -c 'ls -1dt /recordings/*/ 2>/dev/null | head -1' | tr -d '\r')
if [ -z "$LAST" ]; then
  echo "Keine Aufnahme gefunden. Erst eine Testaufnahme machen (Konferenz, Aufnahme starten, sprechen, beenden)."
  exit 1
fi
echo "Ordner: $LAST"
dc exec -T portal sh -c "ls -la '$LAST'"
MP4=$(dc exec -T portal sh -c "ls -1S '$LAST'*.mp4 2>/dev/null | head -1" | tr -d '\r')
if [ -z "$MP4" ]; then echo "FEHLER: keine MP4-Datei in der Aufnahme."; exit 1; fi

hr "3. Inhalt der Videodatei"
dc exec -T portal ffprobe -v error -show_entries stream=index,codec_type,codec_name,sample_rate,channels:format=duration,size \
  -of default=noprint_wrappers=1 "$MP4" 2>&1
HAS_AUDIO=$(dc exec -T portal ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "$MP4" 2>/dev/null | tr -d '\r')
echo
echo "Lautstärke der Tonspur:"
VOL=$(dc exec -T portal ffmpeg -hide_banner -nostdin -i "$MP4" -af volumedetect -vn -f null - 2>&1 | grep -E "mean_volume|max_volume" || true)
echo "${VOL:-  (keine Tonspur messbar)}"
MAXV=$(printf '%s' "$VOL" | sed -n 's/.*max_volume: \(-\?[0-9.]*\) dB.*/\1/p' | head -1)

hr "4. Tonsystem im Jibri-Container (PulseAudio)"
dc exec -T jibri sh -c 'echo "-- pactl info"; pactl info 2>&1 | grep -E "Server String|Default Sink|Default Source|Server Name|refused|failed" ; echo "-- sinks"; pactl list short sinks 2>&1; echo "-- sources"; pactl list short sources 2>&1' 2>&1 | head -30

hr "5. Aufnahme-Protokoll von Jibri (ffmpeg), letzte Zeilen"
dc exec -T jibri sh -c 'f=$(ls -1t /var/log/jitsi/jibri/ffmpeg*.txt 2>/dev/null | head -1); if [ -n "$f" ]; then echo "$f"; grep -E "Input #|Stream #|Audio|pulse|Error|error|refused|Connection" "$f" | tail -15; else echo "(kein ffmpeg-Protokoll gefunden)"; fi' 2>&1

hr "AUSWERTUNG"
if [ -z "$HAS_AUDIO" ]; then
  cat <<'MSG'
Die Videodatei hat KEINE Tonspur. Jibri hat den Ton nicht erfasst.
-> Abschnitt 4 und 5 ansehen: Fehlt dort ein Standard-Sink/-Source oder steht "Connection refused",
   läuft das Tonsystem (PulseAudio) im Jibri-Container nicht. Dann die Ausgabe an die Betreuung geben.
MSG
elif [ -n "$MAXV" ] && awk "BEGIN{exit !($MAXV < -50)}"; then
  cat <<'MSG'
Die Tonspur ist vorhanden, aber STUMM (digitale Stille).
Zwei mögliche Ursachen:
 a) In der Testkonferenz hat niemand hörbar gesprochen (Mikrofon stumm, Lautsprecher/Mikro defekt,
    oder man war allein im Raum und hat nichts abgespielt). Test wiederholen: mit ZWEI Geräten in
    den Raum, ein Gerät spricht (Mikrofon an) oder spielt Musik ab, dann 20 Sekunden aufnehmen.
 b) Wenn das auch dann stumm bleibt, erfasst Jibri den Ton nicht: Abschnitt 4 und 5 weitergeben.
MSG
else
  echo "Die Aufnahme enthält hörbaren Ton (lauteste Stelle: ${MAXV:-?} dB). Alles in Ordnung."
  echo "Ist die MP3 im Portal trotzdem stumm, in der Aufnahme auf 'MP3 neu erzeugen' klicken."
fi
