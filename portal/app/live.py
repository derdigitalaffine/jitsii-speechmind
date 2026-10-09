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
from datetime import datetime, timezone

from sqlalchemy import select

from .db import LiveAnswer, LivePoll, LiveQuestion

# Art → (Bezeichnung, Symbol, mögliche Darstellungen)
KINDS = {
    "single": ("Auswahl (eine Antwort)", "fa-circle-dot", ("bar", "column", "pie", "donut")),
    "multi": ("Auswahl (mehrere Antworten)", "fa-square-check", ("bar", "column", "pie", "donut")),
    "quiz": ("Quiz (Wissen prüfen)", "fa-graduation-cap", ("table",)),
    "rank": ("Rangfolge (priorisieren)", "fa-ranking-star", ("table",)),
    "yesno": ("Ja / Nein", "fa-thumbs-up", ("pie", "donut", "bar", "column")),
    "scale": ("Skala (z. B. 1–5)", "fa-sliders", ("column", "bar", "number")),
    "stars": ("Sterne (1–5)", "fa-star", ("number", "column", "bar")),
    "slider": ("Schieberegler (Zahl)", "fa-ruler-horizontal", ("number", "column")),
    "words": ("Wortwolke (Begriffe sammeln)", "fa-cloud", ("cloud", "table", "bar")),
    "open": ("Offene Antworten (Pinnwand)", "fa-note-sticky", ("wall",)),
    "qa": ("Fragen ans Podium (Q&A)", "fa-comments", ("qa",)),
}
ENTRY_KINDS = ("open", "qa")      # mehrere Beiträge je Gerät statt einer Antwort
CHARTS = {"bar": "Balken liegend", "column": "Säulen", "pie": "Torte", "donut": "Ring", "number": "Kennzahlen",
          "cloud": "Wortwolke", "table": "Tabelle", "wall": "Pinnwand", "qa": "Fragenliste"}
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
    if q.kind == "quiz":
        return {**data, "correct": data.get("correct", []) if isinstance(data.get("correct"), list) else [],
                "points": _int(data.get("points"), 0, 1000, 1), "partial": data.get("partial") is True,
                "nickname": data.get("nickname") is True, "top_n": _int(data.get("top_n"), 1, 50, 10),
                "seconds": _int(data.get("seconds"), 0, 3600, 0), "max_choices": MAX_OPTIONS}
    if q.kind == "rank":
        return {**data, "top_n": _int(data.get("top_n"), 1, max(1, len(opts(q))), max(1, len(opts(q))))}
    if q.kind == "multi":
        return {**data, "max_choices": _int(data.get("max_choices"), 1, MAX_OPTIONS, 3)}
    if q.kind in ENTRY_KINDS:
        return {**data, "max_entries": _int(data.get("max_entries"), 1, 20, 3 if q.kind == "open" else 5),
                "max_len": _int(data.get("max_len"), 20, 1000, 280),
                "approve": (data.get("approve", q.kind == "qa") in (True, "1", 1)),
                "filter": data.get("filter", True) is not False}
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
    previous_settings = settings(q) if q.kind == "quiz" else {}
    kind = data.get("kind") if data.get("kind") in KINDS else q.kind or "single"
    q.kind, q.title = kind, title
    if kind in ("single", "multi", "quiz", "rank"):
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
                                               "max_len", "max_entries")}
    if kind in ENTRY_KINDS:
        sett.update(approve=data.get("approve") == "1", filter=data.get("filter") == "1")
    if kind == "words":   # Moderation (zusammengefasst/ausgeblendet) beim Bearbeiten behalten
        old = settings(q) if q.settings_json and q.kind == "words" else {}
        sett.update(merge=old.get("merge", {}), hidden=old.get("hidden", []), filter=data.get("filter") == "1")
    if kind == "quiz":
        indices = str(data.get("correct", "")).replace(";", ",").split(",")
        try:
            correct = list(dict.fromkeys(int(x.strip()) for x in indices if x.strip()))
        except ValueError:
            return "Richtige Lösung: Nummern der Antworten mit Komma trennen (z. B. 1, 3)."
        options = opts(q)
        if not correct or any(x < 1 or x > len(options) for x in correct):
            return "Bitte mindestens eine gültige Antwortnummer als richtige Lösung angeben."
        sett.update(correct=[options[i-1]["id"] for i in correct], points=data.get("points", 1),
                    partial=data.get("partial") == "1", nickname=data.get("nickname") == "1",
                    seconds=data.get("seconds", 0), top_n=data.get("top_n", 10))
        if previous_settings.get("started"):
            sett["started"] = previous_settings["started"]
    if kind == "rank":
        sett["top_n"] = _int(data.get("top_n"), 1, len(opts(q)), len(opts(q)))
    tmp = LiveQuestion(kind=kind, options_json=q.options_json, settings_json=json.dumps(sett))
    q.settings_json = json.dumps(settings(tmp), ensure_ascii=False)
    chart = data.get("chart")
    q.chart = chart if chart in KINDS[kind][2] else KINDS[kind][2][0]
    q.show_results = data.get("show_results") if data.get("show_results") in SHOW_RESULTS else "immediate"
    if kind == "quiz":
        q.show_results = "never" if data.get("show_results") == "never" else "release"
        q.released = False
    return ""


# --- Antworten -------------------------------------------------------------------------------------

def read_answer(q: LiveQuestion, raw) -> tuple[dict | None, str]:
    """Antwort eines Geräts prüfen. raw: dict aus JSON."""
    raw = raw if isinstance(raw, dict) else {}
    ids = {o["id"] for o in opts(q)}
    if q.kind in ("single", "yesno"):
        choice = str(raw.get("o", ""))
        return ({"o": choice}, "") if choice in ids else (None, "Bitte eine Antwort wählen.")
    if q.kind == "rank":
        ranked = raw.get("r")
        n = settings(q)["top_n"]
        if not isinstance(ranked, list) or len(ranked) != n or any(not isinstance(x, str) or x not in ids for x in ranked) or len(set(ranked)) != n:
            return None, f"Bitte genau {n} unterschiedliche Optionen in eine Rangfolge bringen."
        return {"r": ranked}, ""
    if q.kind in ("multi", "quiz"):
        if q.kind == "quiz" and (not isinstance(raw.get("o"), list) or any(not isinstance(x, str) or x not in ids for x in raw["o"])):
            return None, "Bitte gültige Antworten wählen."
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
    if q.kind in ENTRY_KINDS:
        s = settings(q)
        text = " ".join(str(raw.get("t", "")).split())[:s["max_len"]]
        if len(text) < 2:
            return None, "Bitte einen Text eingeben." if q.kind == "open" else "Bitte Ihre Frage eingeben."
        if s["filter"] and any(is_bad(normalize(w, 200)[0]) for w in text.split()):
            return None, "Bitte formulieren Sie Ihren Beitrag ohne beleidigende Wörter."
        return {"t": text}, ""
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
            if a.nickname:
                out[a.question_id]["nickname"] = a.nickname
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
    if q.kind in ("single", "multi", "yesno", "quiz"):
        counts = {o["id"]: 0 for o in opts(q)}
        for v in values:
            chosen = v.get("o")
            for c in (chosen if isinstance(chosen, list) else [chosen]):
                if c in counts:
                    counts[c] += 1
        out["rows"] = [{"label": o["label"], "count": counts[o["id"]],
                        "pct": round(100 * counts[o["id"]] / total) if total else 0} for o in opts(q)]
    elif q.kind == "rank":
        n = len(opts(q))
        rows = []
        for o in opts(q):
            ranks = [v["r"].index(o["id"]) + 1 for v in values if o["id"] in v.get("r", [])]
            points = sum(n-r+1 for r in ranks)
            rows.append({"label": o["label"], "count": points, "pct": round(100*points/(total*n), 1) if total else 0,
                         "avg_rank": round(statistics.fmean(ranks), 2) if ranks else None, "votes": len(ranks)})
        out["rows"] = sorted(rows, key=lambda r: (-r["count"], r["label"].casefold()))
    elif q.kind in ENTRY_KINDS:
        out["rows"] = []        # Beiträge liefert entries()
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
    if q.kind == "quiz":
        return q.released and q.show_results != "never"
    return q.show_results == "immediate" or (q.show_results == "release" and q.released)


def question_payload(db, q: LiveQuestion, mine: dict | None = None, staff: bool = False, device: str | None = None) -> dict:
    """Frage für die Teilnehmer- bzw. Präsentationsansicht (JSON)."""
    data = {"id": q.id, "kind": q.kind, "title": q.title, "options": opts(q), "settings": settings(q),
            "chart": q.chart, "locked": q.locked, "answered": mine is not None, "mine": mine}
    if q.kind == "quiz":
        data["settings"] = {k: settings(q)[k] for k in ("points", "partial", "nickname", "top_n", "seconds", "max_choices")}
        data["locked"] = q.locked or q.released or timed_out(q)
        data["remaining"] = remaining(q)
        if q.released and (staff or q.show_results != "never"):
            data["solution"] = settings(q)["correct"]
            if mine is not None:
                data["score"] = quiz_score(q, mine)
            data["scoreboard"] = scoreboard(db, q)
    if q.kind in ENTRY_KINDS:
        return {**data, **entry_payload(db, q, device, staff)}
    if (staff and (q.kind != "quiz" or q.released)) or ((mine is not None or q.kind == "quiz") and visible_to_participants(q)):
        data["results"] = tally(db, q)
    if staff:
        data["answer_count"] = tally(db, q)["total"]
        data["show_results"], data["released"] = q.show_results, q.released
    return data


def state(db, poll: LivePoll, device: str | None = None, staff: bool = False) -> dict:
    """Zustand für die Teilnehmerseite (Abfrage alle paar Sekunden) bzw. die Präsentation."""
    mine = my_answers(db, poll, device) if device else {}
    if poll.pacing == "moderated" and not staff:
        current = next((q for q in poll.questions if q.id == poll.current_id), None)
        shown = ([current] if current else []) + [q for q in poll.questions if q.kind == "quiz" and q.released and q.id != poll.current_id]
    else:
        shown = list(poll.questions)
    return {"status": poll.status, "pacing": poll.pacing, "title": poll.title, "current": poll.current_id,
            "questions": [question_payload(db, q, mine.get(q.id), staff, device) for q in shown],
            "participants": len(set(db.scalars(select(LiveAnswer.device).where(LiveAnswer.poll_id == poll.id))))}


def step(poll: LivePoll, direction: int) -> LiveQuestion | None:
    """Moderation: zur nächsten (1) bzw. vorigen (-1) Frage."""
    qs = poll.questions
    if not qs:
        return None
    idx = next((i for i, q in enumerate(qs) if q.id == poll.current_id), -1)
    idx = max(0, min(len(qs) - 1, idx + direction)) if idx >= 0 else 0
    previous = next((q for q in qs if q.id == poll.current_id), None)
    if previous and previous.kind == "quiz" and previous.id != qs[idx].id:
        previous.released, previous.locked = True, True
    poll.current_id = qs[idx].id
    start_timer(qs[idx])
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
    if q.kind in ("quiz", "rank"):
        w.writerow(["Antwort Nr.", "Rohantwort / Rangfolge", "Punkte" if q.kind == "quiz" else "Ränge"])
        labels = {o["id"]: o["label"] for o in opts(q)}
        for i, a in enumerate(db.scalars(select(LiveAnswer).where(LiveAnswer.question_id == q.id).order_by(LiveAnswer.id)), 1):
            value = json.loads(a.value_json or "{}")
            chosen = value.get("o" if q.kind == "quiz" else "r", [])
            w.writerow([i, json.dumps(chosen, ensure_ascii=False), quiz_score(q, value) if q.kind == "quiz" else
                        " | ".join(f"{rank}: {labels.get(oid, oid)}" for rank, oid in enumerate(chosen, 1))])
        return "\ufeff" + buf.getvalue()
    if q.kind in ENTRY_KINDS:
        w.writerow(["Beitrag", "Stimmen", "Status", "Zeit"])
        for e in entry_payload(db, q, None, True)["entries"]:
            status = "ausgeblendet" if e.get("hidden") else ("beantwortet" if e["answered"] else
                                                               ("freigegeben" if e["approved"] else "wartet"))
            w.writerow([e["text"], e["upvotes"], status, e["at"][:16].replace("T", " ")])
        return "\ufeff" + buf.getvalue()
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


# --- Pinnwand und Q&A: mehrere Beiträge je Gerät, Freigabe, Upvotes ---------------------------------

def add_entry(db, poll: LivePoll, q: LiveQuestion, device: str, value: dict) -> tuple[LiveAnswer | None, str]:
    s = settings(q)
    mine = db.scalars(select(LiveAnswer).where(LiveAnswer.question_id == q.id, LiveAnswer.device == device)).all()
    if len(mine) >= s["max_entries"]:
        return None, f"Höchstens {s['max_entries']} Beiträge je Person."
    if any(json.loads(a.value_json or "{}").get("t", "").casefold() == value["t"].casefold() for a in mine):
        return None, "Diesen Beitrag haben Sie schon geschickt."
    a = LiveAnswer(poll_id=poll.id, question_id=q.id, device=device, value_json=json.dumps(value, ensure_ascii=False),
                   approved=not s["approve"])
    db.add(a)
    return a, ""


def upvote(db, q: LiveQuestion, answer_id: int, device: str) -> str:
    """Q&A: Stimme für einen freigegebenen Beitrag setzen bzw. zurücknehmen (je Gerät einmal)."""
    from .db import LiveUpvote
    a = db.get(LiveAnswer, answer_id)
    if a is None or a.question_id != q.id or a.hidden or not a.approved or q.kind != "qa":
        return "Diesen Beitrag gibt es nicht."
    if a.device == device:
        return "Eigene Fragen lassen sich nicht hochstimmen."
    existing = db.get(LiveUpvote, (a.id, device))
    if existing is None:
        db.add(LiveUpvote(answer_id=a.id, device=device))
        a.upvotes += 1
    else:
        db.delete(existing)
        a.upvotes = max(0, a.upvotes - 1)
    return ""


def entry_payload(db, q: LiveQuestion, device: str | None, staff: bool) -> dict:
    """Beiträge für Teilnehmende (freigegebene + eigene) bzw. die Moderation (alle)."""
    from .db import LiveUpvote
    rows = db.scalars(select(LiveAnswer).where(LiveAnswer.question_id == q.id)).all()
    voted = set(db.scalars(select(LiveUpvote.answer_id).where(
        LiveUpvote.device == device, LiveUpvote.answer_id.in_([a.id for a in rows] or [-1])))) if device else set()
    out = []
    for a in rows:
        own = device is not None and a.device == device
        if not staff and (a.hidden or not (a.approved or own)):
            continue
        try:
            text = json.loads(a.value_json or "{}").get("t", "")
        except ValueError:
            continue
        item = {"id": a.id, "text": text, "upvotes": a.upvotes, "answered": a.answered, "approved": a.approved,
                "mine": own, "voted": a.id in voted, "at": a.created_at.isoformat() if a.created_at else ""}
        if staff:
            item["hidden"] = a.hidden
        out.append(item)
    if q.kind == "qa":
        out.sort(key=lambda x: (x["answered"], -x["upvotes"], x["at"]))
    else:
        out.sort(key=lambda x: x["at"], reverse=True)
    visible = [x for x in out if x["approved"] and not x.get("hidden")]
    return {"entries": out, "results": {"total": len(visible), "rows": [],
                                        "pending": sum(1 for x in out if not x["approved"] and not x.get("hidden"))},
            "answered": any(x["mine"] for x in out), "mine": None}


def moderate_entry(a: LiveAnswer, action: str) -> str:
    if action == "approve":
        a.approved, a.hidden = True, False
    elif action == "hide":
        a.hidden = True
    elif action == "unhide":
        a.hidden = False
    elif action == "answered":
        a.answered = not a.answered
    else:
        return "Unbekannte Aktion."
    return ""


def quiz_score(q, value):
    s = settings(q)
    correct, chosen = set(s["correct"]), set(value.get("o", []))
    if not correct:
        return 0
    if not s["partial"]:
        return s["points"] if correct == chosen else 0
    return round(s["points"] * max(0, len(chosen & correct) - len(chosen - correct)) / len(correct), 2)


def scoreboard(db, q):
    if not settings(q)["nickname"]:
        return []
    rows = [{"name": a.nickname, "points": quiz_score(q, json.loads(a.value_json or "{}"))}
            for a in db.scalars(select(LiveAnswer).where(LiveAnswer.question_id == q.id, LiveAnswer.hidden.is_(False))) if a.nickname]
    return sorted(rows, key=lambda r: (-r["points"], r["name"].casefold()))[:settings(q)["top_n"]]


def remaining(q):
    s = settings(q)
    if q.kind != "quiz" or not s["seconds"] or not s.get("started"):
        return None
    return max(0, int(s["seconds"] - (datetime.now(timezone.utc).timestamp() - s["started"])))


def timed_out(q):
    return remaining(q) == 0


def start_timer(q, restart=False):
    if q.kind != "quiz":
        return
    s = settings(q)
    if s["seconds"] and (restart or not s.get("started")):
        s["started"] = datetime.now(timezone.utc).timestamp()
        q.settings_json = json.dumps(s)
