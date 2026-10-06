"""Live-Umfragen (Teil des Moduls „Umfragen & Abstimmungen“).

Teilnehmende scannen den QR-Code und antworten sofort – ohne Einladungslink, ohne Anmeldung, ohne Namen. Jedes
Gerät bekommt eine zufällige Kennung (Cookie); gespeichert wird nur deren Hash. Je Gerät und Frage gibt es eine
Antwort, die sich bis zum Sperren der Frage ändern lässt. Ablauf je Umfrage wählbar:
  * moderiert – alle sehen die Frage, die die Moderation gerade zeigt (Präsentationsmodus, Pfeiltasten),
  * frei – alle Fragen auf einmal, in eigenem Tempo.
Ergebnisse für Teilnehmende je Frage: sofort, erst nach Freigabe oder nie.
"""

import hashlib
import json
import re
import secrets
import unicodedata
import statistics

from sqlalchemy import select

from .db import LiveAnswer, LivePoll, LiveQuestion

# Art → (Bezeichnung, Symbol, mögliche Darstellungen)
KINDS = {
    "single": ("Auswahl (eine Antwort)", "fa-circle-dot", ("bar", "column", "pie", "donut")),
    "multi": ("Auswahl (mehrere Antworten)", "fa-square-check", ("bar", "column", "pie", "donut")),
    "yesno": ("Ja / Nein", "fa-thumbs-up", ("pie", "donut", "bar", "column")),
    "scale": ("Skala (z. B. 1–5)", "fa-sliders", ("column", "bar", "number")),
    "stars": ("Sterne (1–5)", "fa-star", ("number", "column", "bar")),
    "slider": ("Schieberegler (Zahl)", "fa-ruler-horizontal", ("number", "column")),
    "words": ("Wortwolke (Begriffe sammeln)", "fa-cloud", ("cloud", "table", "bar")),
}
CHARTS = {"bar": "Balken liegend", "column": "Säulen", "pie": "Torte", "donut": "Ring", "number": "Kennzahlen",
          "cloud": "Wortwolke", "table": "Tabelle"}
SHOW_RESULTS = {"immediate": "sofort nach der Antwort", "release": "erst nach Freigabe", "never": "nie (nur Beamer)"}
PACING = {"moderated": ("Moderiert", "Alle sehen die Frage, die Sie gerade zeigen – Frage für Frage."),
          "free": ("Frei", "Alle Fragen auf einmal, jede:r im eigenen Tempo.")}
STATUSES = {"draft": ("Vorbereitung", "secondary"), "open": ("läuft", "primary"), "closed": ("beendet", "success")}
DEVICE_COOKIE = "jsm_live"
MAX_QUESTIONS = 50
MAX_OPTIONS = 20


def opts(q: LiveQuestion) -> list[dict]:
    if q.kind == "yesno":
        return [{"id": "y", "label": "Ja"}, {"id": "n", "label": "Nein"}]
    try:
        data = json.loads(q.options_json or "[]")
    except ValueError:
        return []
    return [o for o in data if isinstance(o, dict) and o.get("id") and o.get("label")]


def settings(q: LiveQuestion) -> dict:
    try:
        data = json.loads(q.settings_json or "{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    if q.kind == "scale":
        lo = _int(data.get("min"), 0, 10, 1)
        return {**data, "min": lo, "max": _int(data.get("max"), lo + 1, 10, max(lo + 1, 5)),
                "low": str(data.get("low", ""))[:40], "high": str(data.get("high", ""))[:40]}
    if q.kind == "stars":
        return {**data, "min": 1, "max": 5}
    if q.kind == "slider":
        lo = _int(data.get("min"), -100000, 100000, 0)
        hi = _int(data.get("max"), lo + 1, 1000000, max(lo + 1, 100))
        return {**data, "min": lo, "max": hi, "step": _int(data.get("step"), 1, max(1, hi - lo), 1),
                "unit": str(data.get("unit", ""))[:12]}
    if q.kind == "multi":
        return {**data, "max_choices": _int(data.get("max_choices"), 1, MAX_OPTIONS, 3)}
    if q.kind == "words":
        merge = data.get("merge") if isinstance(data.get("merge"), dict) else {}
        hidden = data.get("hidden") if isinstance(data.get("hidden"), list) else []
        return {**data, "max_words": _int(data.get("max_words"), 1, 10, 3), "max_len": _int(data.get("max_len"), 5, 60, 30),
                "merge": {str(k): str(v) for k, v in merge.items()}, "hidden": [str(h) for h in hidden],
                "filter": data.get("filter", True) is not False}
    return data


def _int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def device_hash(raw: str) -> str:
    return hashlib.sha256(f"live:{raw}".encode()).hexdigest()


def new_device() -> str:
    return secrets.token_hex(16)


# --- Fragen anlegen ---------------------------------------------------------------------------------

def apply_question(q: LiveQuestion, data) -> str:
    """Formularfelder → Frage. Gibt eine Fehlermeldung oder ''."""
    title = " ".join(str(data.get("title", "")).split())[:500]
    if not title:
        return "Bitte die Frage eintragen."
    kind = data.get("kind") if data.get("kind") in KINDS else q.kind or "single"
    q.kind, q.title = kind, title
    if kind in ("single", "multi"):
        labels = [" ".join(line.split())[:200] for line in str(data.get("options", "")).splitlines() if line.strip()]
        if len(labels) < 2:
            return "Bitte mindestens zwei Antwortmöglichkeiten angeben (eine je Zeile)."
        old = {o["label"]: o["id"] for o in opts(q)} if q.options_json else {}
        out, used = [], set()
        for label in labels[:MAX_OPTIONS]:
            oid = old.get(label) or f"o{len(out) + 1}"
            while oid in used:
                oid = f"o{secrets.token_hex(2)}"
            used.add(oid)
            out.append({"id": oid, "label": label})
        q.options_json = json.dumps(out, ensure_ascii=False)
    sett = {k: str(data.get(k, "")) for k in ("min", "max", "low", "high", "step", "unit", "max_choices", "max_words",
                                               "max_len")}
    if kind == "words":   # Moderation (zusammengefasst/ausgeblendet) beim Bearbeiten behalten
        old = settings(q) if q.settings_json and q.kind == "words" else {}
        sett.update(merge=old.get("merge", {}), hidden=old.get("hidden", []), filter=data.get("filter") == "1")
    tmp = LiveQuestion(kind=kind, settings_json=json.dumps(sett))
    q.settings_json = json.dumps(settings(tmp), ensure_ascii=False)
    chart = data.get("chart")
    q.chart = chart if chart in KINDS[kind][2] else KINDS[kind][2][0]
    q.show_results = data.get("show_results") if data.get("show_results") in SHOW_RESULTS else "immediate"
    return ""


# --- Antworten -------------------------------------------------------------------------------------

def read_answer(q: LiveQuestion, raw) -> tuple[dict | None, str]:
    """Antwort eines Geräts prüfen. raw: dict aus JSON."""
    raw = raw if isinstance(raw, dict) else {}
    ids = {o["id"] for o in opts(q)}
    if q.kind in ("single", "yesno"):
        choice = str(raw.get("o", ""))
        return ({"o": choice}, "") if choice in ids else (None, "Bitte eine Antwort wählen.")
    if q.kind == "multi":
        chosen = [str(x) for x in (raw.get("o") or []) if str(x) in ids] if isinstance(raw.get("o"), list) else []
        chosen = list(dict.fromkeys(chosen))
        mx = settings(q)["max_choices"]
        if not chosen:
            return None, "Bitte mindestens eine Antwort wählen."
        if len(chosen) > mx:
            return None, f"Bitte höchstens {mx} Antworten wählen."
        return {"o": chosen}, ""
    if q.kind in ("scale", "stars", "slider"):
        s = settings(q)
        try:
            n = float(str(raw.get("n", "")).replace(",", "."))
        except ValueError:
            return None, "Bitte einen Wert wählen."
        if not s["min"] <= n <= s["max"]:
            return None, "Der Wert liegt außerhalb der Skala."
        return {"n": int(n) if q.kind != "slider" or n.is_integer() else round(n, 2)}, ""
    if q.kind == "words":
        s = settings(q)
        raw_words = raw.get("w")
        if isinstance(raw_words, str):
            raw_words = re.split(r"[,;\n]+", raw_words)
        words, seen, rejected = [], set(), 0
        for w in raw_words if isinstance(raw_words, list) else []:
            key, display = normalize(str(w), s["max_len"])
            if not key or key in seen:
                continue
            if s["filter"] and is_bad(key):
                rejected += 1
                continue
            seen.add(key)
            words.append(display)
        if not words:
            return None, ("Bitte einen anderen Begriff wählen." if rejected else "Bitte mindestens einen Begriff eingeben.")
        if len(words) > s["max_words"]:
            return None, f"Bitte höchstens {s['max_words']} Begriffe."
        return {"w": words}, ""
    return None, "Unbekannte Frageart."


def save_answer(db, poll: LivePoll, q: LiveQuestion, device: str, value: dict) -> LiveAnswer:
    """Eine Antwort je Gerät und Frage – erneutes Antworten ändert die eigene Antwort."""
    a = db.scalar(select(LiveAnswer).where(LiveAnswer.question_id == q.id, LiveAnswer.device == device))
    if a is None:
        a = LiveAnswer(poll_id=poll.id, question_id=q.id, device=device)
        db.add(a)
    a.value_json = json.dumps(value, ensure_ascii=False)
    return a


def my_answers(db, poll: LivePoll, device: str) -> dict[int, dict]:
    out = {}
    for a in db.scalars(select(LiveAnswer).where(LiveAnswer.poll_id == poll.id, LiveAnswer.device == device)):
        try:
            out[a.question_id] = json.loads(a.value_json or "{}")
        except ValueError:
            pass
    return out


# --- Auswertung ------------------------------------------------------------------------------------

def tally(db, q: LiveQuestion) -> dict:
    """Ergebnis einer Frage: {total, rows: [{label, count, pct}], stats: {avg, median, min, max}}."""
    values = []
    for raw in db.scalars(select(LiveAnswer.value_json).where(LiveAnswer.question_id == q.id,
                                                             LiveAnswer.hidden.is_(False))):
        try:
            values.append(json.loads(raw or "{}"))
        except ValueError:
            continue
    total = len(values)
    out: dict = {"total": total, "rows": [], "stats": {}}
    if q.kind in ("single", "multi", "yesno"):
        counts = {o["id"]: 0 for o in opts(q)}
        for v in values:
            chosen = v.get("o")
            for c in (chosen if isinstance(chosen, list) else [chosen]):
                if c in counts:
                    counts[c] += 1
        out["rows"] = [{"label": o["label"], "count": counts[o["id"]],
                        "pct": round(100 * counts[o["id"]] / total) if total else 0} for o in opts(q)]
    elif q.kind == "words":
        s = settings(q)
        counts: dict[str, int] = {}
        forms: dict[str, dict[str, int]] = {}
        for v in values:
            for w in v.get("w") or []:
                key, display = normalize(str(w), 200)
                key = s["merge"].get(key, key)
                if not key or key in s["hidden"]:
                    continue
                counts[key] = counts.get(key, 0) + 1
                forms.setdefault(key, {})[display] = forms.setdefault(key, {}).get(display, 0) + 1
        rows = [{"key": k, "label": max(forms[k], key=lambda f: (forms[k][f], f[:1].isupper())), "count": c,
                 "pct": round(100 * c / total) if total else 0} for k, c in counts.items()]
        out["rows"] = sorted(rows, key=lambda r: (-r["count"], r["label"].casefold()))[:200]
        out["stats"] = {"words": sum(counts.values()), "distinct": len(counts)}
    elif q.kind in ("scale", "stars", "slider"):
        nums = [v["n"] for v in values if isinstance(v.get("n"), (int, float))]
        s = settings(q)
        if q.kind == "slider":
            span = s["max"] - s["min"]
            buckets = 10 if span >= 10 else max(1, int(span))
            width = span / buckets
            counts = [0] * buckets
            for n in nums:
                counts[min(buckets - 1, int((n - s["min"]) / width))] += 1
            out["rows"] = [{"label": f"{s['min'] + i * width:g}–{s['min'] + (i + 1) * width:g}", "count": c,
                            "pct": round(100 * c / total) if total else 0} for i, c in enumerate(counts)]
        else:
            out["rows"] = [{"label": ("★" * i) if q.kind == "stars" else str(i),
                            "count": sum(1 for n in nums if n == i),
                            "pct": round(100 * sum(1 for n in nums if n == i) / total) if total else 0}
                           for i in range(s["min"], s["max"] + 1)]
        if nums:
            out["stats"] = {"avg": round(statistics.fmean(nums), 2), "median": statistics.median(nums),
                            "min": min(nums), "max": max(nums), "unit": s.get("unit", "")}
    return out


def visible_to_participants(q: LiveQuestion) -> bool:
    return q.show_results == "immediate" or (q.show_results == "release" and q.released)


def question_payload(db, q: LiveQuestion, mine: dict | None = None, staff: bool = False) -> dict:
    """Frage für die Teilnehmer- bzw. Präsentationsansicht (JSON)."""
    data = {"id": q.id, "kind": q.kind, "title": q.title, "options": opts(q), "settings": settings(q),
            "chart": q.chart, "locked": q.locked, "answered": mine is not None, "mine": mine}
    if staff or (mine is not None and visible_to_participants(q)):
        data["results"] = tally(db, q)
    if staff:
        data["show_results"], data["released"] = q.show_results, q.released
    return data


def state(db, poll: LivePoll, device: str | None = None, staff: bool = False) -> dict:
    """Zustand für die Teilnehmerseite (Abfrage alle paar Sekunden) bzw. die Präsentation."""
    mine = my_answers(db, poll, device) if device else {}
    if poll.pacing == "moderated" and not staff:
        current = next((q for q in poll.questions if q.id == poll.current_id), None)
        shown = [current] if current else []
    else:
        shown = list(poll.questions)
    return {"status": poll.status, "pacing": poll.pacing, "title": poll.title, "current": poll.current_id,
            "questions": [question_payload(db, q, mine.get(q.id), staff) for q in shown],
            "participants": len(set(db.scalars(select(LiveAnswer.device).where(LiveAnswer.poll_id == poll.id))))}


def step(poll: LivePoll, direction: int) -> LiveQuestion | None:
    """Moderation: zur nächsten (1) bzw. vorigen (-1) Frage."""
    qs = poll.questions
    if not qs:
        return None
    idx = next((i for i, q in enumerate(qs) if q.id == poll.current_id), -1)
    idx = max(0, min(len(qs) - 1, idx + direction)) if idx >= 0 else 0
    poll.current_id = qs[idx].id
    return qs[idx]



# --- Wortwolke: Begriffe vereinheitlichen, Schimpfwörter herausfiltern, moderieren ---------------------

_EDGE = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)
# Kleine Grundliste (deutsch/englisch); ganze Wörter, Groß-/Kleinschreibung egal. Weitere Begriffe blendet die
# Moderation aus.
BAD_WORDS = {
    "arsch", "arschloch", "wichser", "fotze", "hurensohn", "hure", "schlampe", "fick", "ficken", "ficker", "scheiße",
    "scheisse", "scheiß", "scheiss", "missgeburt", "spast", "spasti", "mongo", "behindert", "schwuchtel", "kanake",
    "neger", "nazi", "penner", "vollidiot", "idiot", "depp", "trottel", "wixer", "kacke", "pisser",
    "fuck", "fucking", "shit", "bitch", "asshole", "dick", "cunt", "bastard", "motherfucker", "retard", "nigger",
}


def normalize(word: str, max_len: int = 30) -> tuple[str, str]:
    """(Schlüssel zum Zählen, Anzeigeform): Leerzeichen zusammenfassen, Satzzeichen am Rand entfernen, kürzen.
    Der Schlüssel ignoriert Groß-/Kleinschreibung und Unicode-Varianten („Café“ = „café“)."""
    display = " ".join(unicodedata.normalize("NFC", str(word or "")).split())
    display = _EDGE.sub("", display)[:max_len].strip()
    return display.casefold(), display


def is_bad(key: str) -> bool:
    parts = re.split(r"[\s\-]+", key)
    return any(p in BAD_WORDS for p in parts) or key in BAD_WORDS


def moderate(q: LiveQuestion, action: str, key: str, into: str = "") -> str:
    """Wortwolke moderieren: Begriff ausblenden/wieder zeigen oder in einen anderen zusammenfassen."""
    s = settings(q)
    key = normalize(key, 200)[0]
    if not key:
        return "Kein Begriff gewählt."
    if action == "hide" and key not in s["hidden"]:
        s["hidden"].append(key)
    elif action == "unhide":
        s["hidden"] = [h for h in s["hidden"] if h != key]
    elif action == "merge":
        target = normalize(into, 200)[0]
        if not target or target == key:
            return "Bitte einen anderen Zielbegriff wählen."
        s["merge"] = {k: (target if v == key else v) for k, v in s["merge"].items()}
        s["merge"][key] = target
    elif action == "unmerge":
        s["merge"].pop(key, None)
    else:
        return "Unbekannte Aktion."
    q.settings_json = json.dumps(s, ensure_ascii=False)
    return ""


def raw_words(db, q: LiveQuestion) -> list[dict]:
    """Für die Moderation: alle Begriffe (auch ausgeblendete) mit Anzahl und Zusammenfassung."""
    s = settings(q)
    counts: dict[str, list] = {}
    for raw in db.scalars(select(LiveAnswer.value_json).where(LiveAnswer.question_id == q.id)):
        try:
            words = json.loads(raw or "{}").get("w") or []
        except ValueError:
            continue
        for w in words:
            key, display = normalize(str(w), 200)
            entry = counts.setdefault(key, [display, 0])
            entry[1] += 1
    return sorted(({"key": k, "label": v[0], "count": v[1], "hidden": k in s["hidden"], "into": s["merge"].get(k, "")}
                   for k, v in counts.items()), key=lambda r: (-r["count"], r["label"].casefold()))


def to_csv(db, q: LiveQuestion) -> str:
    """Ergebnis einer Frage als CSV (Excel: Semikolon, UTF-8 mit BOM)."""
    import io
    from . import csvsafe
    res = tally(db, q)
    buf = io.StringIO()
    w = csvsafe.writer(buf, delimiter=";")
    w.writerow([q.title])
    w.writerow(["Begriff" if q.kind == "words" else "Antwort", "Anzahl", "Anteil %"])
    for r in res["rows"]:
        w.writerow([r["label"], r["count"], r["pct"]])
    w.writerow([])
    w.writerow(["Antworten", res["total"]])
    for k, v in (res.get("stats") or {}).items():
        w.writerow([k, v])
    return "\ufeff" + buf.getvalue()


def cloud_png(db, q: LiveQuestion, width: int = 1600, height: int = 900, dark: bool = False) -> bytes:
    """Wortwolke als PNG (für Berichte und zum Teilen): Begriffe zeilenweise zentriert, je häufiger desto größer."""
    import io
    import os
    import reportlab
    from PIL import Image, ImageDraw, ImageFont
    rows = tally(db, q)["rows"][:80]
    font_path = os.path.join(os.path.dirname(reportlab.__file__), "fonts", "VeraBd.ttf")
    bg, fg = ("#1b1f24", "#e9ecef") if dark else ("#ffffff", "#212529")
    colors = ["#1f5fa8", "#f59f00", "#2fb344", "#d63939", "#ae3ec9", "#17a2b8", "#fd7e14", "#6c757d", "#e83e8c",
              "#20c997"]
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    title_font = ImageFont.truetype(font_path, 40)
    draw.text((40, 30), q.title[:90], font=title_font, fill=fg)
    if not rows:
        draw.text((40, 120), "Noch keine Begriffe.", font=ImageFont.truetype(font_path, 32), fill=fg)
    top = max(r["count"] for r in rows) if rows else 1
    # wie die Live-Ansicht: gemischt (stabil je Begriff), der häufigste in der Mitte
    items = []
    for i, r in enumerate(rows):
        size = int(22 + 90 * (r["count"] / top) ** 0.75)
        font = ImageFont.truetype(font_path, size)
        items.append((int(hashlib.md5(r["key"].encode()).hexdigest()[:6], 16), r["label"], font,
                      colors[i % len(colors)], draw.textlength(r["label"], font=font)))
    if items:
        first = items.pop(0)
        items.sort(key=lambda x: x[0])
        items.insert(len(items) // 2, first)
    lines, line, line_w, max_w = [], [], 0, width - 80
    for _h, text, font, color, w in items:
        if line and line_w + w + 30 > max_w:
            lines.append(line)
            line, line_w = [], 0
        line.append((text, font, color, w))
        line_w += w + 30
    if line:
        lines.append(line)
    heights = [int(max(f.size for _t, f, _c, _w in ln) * 1.25) for ln in lines]
    while lines and sum(heights) > height - 140:      # zu viele Begriffe: kleinste Zeilen weglassen
        lines.pop()
        heights.pop()
    y = 110 + max(0, (height - 140 - sum(heights)) // 2)
    for ln, h in zip(lines, heights):
        x = (width - sum(w for _t, _f, _c, w in ln) - 30 * (len(ln) - 1)) / 2
        for text, font, color, w in ln:
            draw.text((x, y + (h / 1.25 - font.size) * 0.8), text, font=font, fill=color)
            x += w + 30
        y += h
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
