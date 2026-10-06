"""Rechtstexte: Markdown in Gliederung (Teile, Abschnitte, §§, Artikel) zerlegen, darstellen und durchsuchen.

Gliederung im Markdown
  # Titel                        erste Überschrift = Titel des Rechtstexts (wird nicht als Abschnitt geführt)
  ## Erster Teil – Allgemeines   Gliederungsebene (Teil, Kapitel, Abschnitt …), beliebig tief über ## … ######
  ### § 1 Name                   Norm (§ oder Artikel) mit Überschrift
  (1) Text …                     Absätze mit Nummer werden als Absätze gesetzt (hängender Einzug)

Ohne Markdown-Überschriften (z. B. aus einer Webseite oder Word kopiert) werden allein stehende Zeilen wie
„§ 3 Ortsbezirke“, „Artikel 5“ oder „Zweiter Abschnitt“ automatisch als Gliederung erkannt.
"""

import html as htmllib
import re
import unicodedata
from dataclasses import dataclass, field

from markupsafe import Markup, escape
from markdown_it import MarkdownIt
from sqlalchemy import func, or_, select

from .db import LawLevel, LawSection, LawText

LEVEL_KINDS = {
    "eu": ("Europäische Union", "fa-earth-europe"),
    "bund": ("Bund", "fa-landmark-flag"),
    "land": ("Land", "fa-map"),
    "landkreis": ("Landkreis", "fa-map-location-dot"),
    "vg": ("Verbandsgemeinde", "fa-building-columns"),
    "og": ("Ortsgemeinde / Stadt", "fa-house-flag"),
    "sonstige": ("Sonstige", "fa-folder"),
}
DOC_TYPES = {
    "gesetz": "Gesetz",
    "verordnung": "Rechtsverordnung",
    "satzung": "Satzung",
    "richtlinie": "Richtlinie",
    "geschaeftsordnung": "Geschäftsordnung",
    "vertrag": "Vertrag / Vereinbarung",
    "bekanntmachung": "Bekanntmachung",
    "sonstiges": "Sonstiges",
}
MAX_SIZE = 2_000_000
RESERVED_SLUGS = {"suche", "ebene"}   # belegte Pfade unter /recht

_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable(["table", "strikethrough"])

_SEP = r"\.?\s*(?:[-–—:]\s*)?"
_NUM = r"\d+(?:\s?[a-z](?![a-zäöüß]))?"
NORM_RE = re.compile(r"^(?P<num>(?:§§?|Art\.|ART\.|Artikel|ARTIKEL)\s*" + _NUM + r"(?:\s*(?:bis|-|–|und)\s*" + _NUM
                     + r")?)(?![\d])" + _SEP + r"(?P<title>.*)$")
_ORDINAL = r"(?:[A-ZÄÖÜ][a-zäöü]+(?:t|st)(?:er|es|e))"
_GROUP_WORDS = r"(?:Buch|Teil|Kapitel|Abschnitt|Unterabschnitt|Titel|Untertitel|Anlage|Anhang)"
GROUP_RE = re.compile(r"^(?P<num>" + _GROUP_WORDS + r"\s+(?:\d+[a-z]?|[IVXLC]+)\b|" + _ORDINAL + r"\s+" + _GROUP_WORDS
                      + r")" + _SEP + r"(?P<title>.*)$")
_GROUP_RANK = {"buch": 2, "anlage": 2, "anhang": 2, "teil": 3, "kapitel": 4, "titel": 4, "abschnitt": 5,
               "unterabschnitt": 6, "untertitel": 6}
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
ABS_LINE_RE = re.compile(r"^\s{0,3}\(\d+[a-z]?\)\s")
ABS_RE = re.compile(r"<p>\((\d+[a-z]?)\)\s*")
AUTO_NORM_LEVEL = 7
_PROSE_RE = re.compile(r"\b(?:Abs\.|Satz|gilt|gelten|ist|sind|findet|finden|werden|wird|bleibt|bleiben|tritt|treten)\b")


@dataclass
class Node:
    level: int
    kind: str            # intro | group | norm
    number: str
    title: str
    lines: list[str] = field(default_factory=list)
    anchor: str = ""
    html: str = ""
    plain: str = ""
    position: int = 0
    depth: int = 0
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)

    @property
    def label(self) -> str:
        return " ".join(p for p in (self.number, self.title) if p) or "Eingangsformel"


def slugify(text: str, limit: int = 80) -> str:
    text = text.replace("ß", "ss").replace("§", "p")
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")


def _norm_anchor(number: str) -> str:
    n = re.sub(r"\s+", "", number.lower())
    n = n.replace("§§", "p").replace("§", "p").replace("artikel", "art").replace("art.", "art")
    return slugify(n) or "norm"


def _classify(text: str) -> tuple[str, str, str]:
    """Überschriftstext → (Art, Nummer, Titel)."""
    m = NORM_RE.match(text)
    if m:
        return "norm", " ".join(m.group("num").split()), m.group("title").strip()
    m = GROUP_RE.match(text)
    if m:
        return "group", " ".join(m.group("num").split()), m.group("title").strip()
    return "group", "", text.strip()


def _is_title_line(line: str) -> bool:
    s = line.strip()
    return bool(s) and len(s) <= 140 and not s.endswith((".", ",", ";", ":")) and not s.startswith(("(", "-", "*", "|", ">"))


def _preprocess(lines: list[str]) -> list[tuple[int, str] | str]:
    """Zeilen → Liste aus Text und erkannten Überschriften (Ebene, Text)."""
    explicit = [HEADING_RE.match(x) for x in lines]
    headings = [m.group(2) for m in explicit if m]
    has_norm_heads = any(_classify(h)[0] == "norm" for h in headings)
    has_group_heads = any(_classify(h)[0] == "group" for h in headings)
    out: list = []
    fenced, i = False, 0
    while i < len(lines):
        line = lines[i]
        if FENCE_RE.match(line):
            fenced = not fenced
        prev = lines[i - 1].strip() if i else ""
        prev_blank = not prev or prev.endswith((".", ":", ";"))
        if not fenced and explicit[i]:
            out.append((len(explicit[i].group(1)), explicit[i].group(2)))
            i += 1
            continue
        s = line.strip()
        if not fenced and prev_blank and s and len(s) <= 160:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            nxt2 = lines[i + 2] if i + 2 < len(lines) else ""
            kind = None
            m = NORM_RE.match(s)
            if m and not has_norm_heads:
                kind = "norm"
            elif not has_group_heads and GROUP_RE.match(s):
                kind = "group"
            if kind:
                title = (m.group("title") if kind == "norm" else GROUP_RE.match(s).group("title")).strip()
                ends_sentence = s.endswith((".", ";", ",")) and not re.fullmatch(r".*\d+\s*[a-z]?\.", s)
                word = re.search(_GROUP_WORDS, s)
                level = AUTO_NORM_LEVEL if kind == "norm" else _GROUP_RANK.get(word.group().lower() if word else "", 5)
                # „§ 3 Name“ allein oder direkt vor dem Text („(1) …“); kein Satz wie „§ 3 gilt entsprechend.“
                heading_like = not ends_sentence and (not title or (title[:1].isupper() and not _PROSE_RE.search(title)))
                if heading_like and (not nxt.strip() or (title and len(s) <= 120)):
                    out.append((level, s))
                    i += 1
                    continue
                # „§ 3“ und in der nächsten Zeile die Überschrift
                if not title and _is_title_line(nxt) and (not nxt2.strip() or nxt2.lstrip().startswith("(")):
                    out.append((level, s.rstrip(".") + " " + nxt.strip()))
                    i += 2
                    continue
        # Absätze „(2) …“ ohne Leerzeile davor als eigenen Absatz setzen
        if not fenced and ABS_LINE_RE.match(line) and i and lines[i - 1].strip() and out and isinstance(out[-1], str):
            out.append("")
        out.append(line)
        i += 1
    return out


def _render(lines: list[str]) -> tuple[str, str]:
    source = "\n".join(lines).strip()
    if not source:
        return "", ""
    html = _md.render(source)
    html = ABS_RE.sub(lambda m: f'<p class="lex-abs"><span class="lex-absnr">({m.group(1)})</span> ', html)
    plain = htmllib.unescape(re.sub(r"<[^>]+>", " ", html))
    return html, " ".join(plain.split())


@dataclass
class Parsed:
    title: str
    nodes: list[Node]          # alle Abschnitte in Dokumentreihenfolge
    roots: list[Node]

    @property
    def norms(self) -> int:
        return sum(1 for n in self.nodes if n.kind == "norm")

    @property
    def groups(self) -> int:
        return sum(1 for n in self.nodes if n.kind == "group")


def parse(markdown: str) -> Parsed:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").replace("﻿", "").split("\n")
    title = ""
    first = next((i for i, x in enumerate(lines) if x.strip()), None)
    if first is not None:
        m = HEADING_RE.match(lines[first])
        if m and len(m.group(1)) == 1 and _classify(m.group(2))[1] == "":
            title = m.group(2).strip()
            lines = lines[first + 1:]
        elif (_is_title_line(lines[first]) and not NORM_RE.match(lines[first].strip())
              and not GROUP_RE.match(lines[first].strip()) and not HEADING_RE.match(lines[first])
              and (first + 1 >= len(lines) or not lines[first + 1].strip())):
            title = lines[first].strip()     # einfacher Text: erste allein stehende Zeile ist der Titel
            lines = lines[first + 1:]
    intro = Node(level=0, kind="intro", number="", title="")
    nodes: list[Node] = []
    current = intro
    for item in _preprocess(lines):
        if isinstance(item, tuple):
            kind, number, text = _classify(item[1])
            current = Node(level=item[0], kind=kind, number=number, title=text)
            nodes.append(current)
        else:
            current.lines.append(item)
    if any(x.strip() for x in intro.lines):
        nodes.insert(0, intro)
    roots: list[Node] = []
    stack: list[Node] = []
    used: set[str] = set()
    for pos, node in enumerate(nodes):
        node.position = pos
        node.html, node.plain = _render(node.lines)
        if node.kind == "intro":
            roots.append(node)
            node.anchor = "eingang"
            used.add(node.anchor)
            continue
        while stack and stack[-1].level >= node.level:
            stack.pop()
        node.parent = stack[-1] if stack else None
        node.depth = len(stack)
        (node.parent.children if node.parent else roots).append(node)
        stack.append(node)
        if node.kind == "norm":
            base = _norm_anchor(node.number)
        else:
            own = slugify(node.number) or slugify(node.title, 40) or f"g{pos}"
            parent_group = node.parent.anchor if node.parent and node.parent.kind == "group" else ""
            base = f"{parent_group}-{own}" if parent_group and node.number else own
        anchor, n = base, 2
        while anchor in used:
            anchor, n = f"{base}-{n}", n + 1
        node.anchor = anchor
        used.add(anchor)
    return Parsed(title=title, nodes=nodes, roots=roots)


def store(db, law: LawText) -> Parsed:
    """Gliederung neu berechnen und als LawSection-Zeilen speichern."""
    parsed = parse(law.body_md or "")
    law.sections.clear()
    db.flush()
    for node in parsed.nodes:
        law.sections.append(LawSection(position=node.position, parent_position=node.parent.position if node.parent else None,
                                       depth=node.depth, kind=node.kind, number=node.number[:80],
                                       title=node.title[:400], anchor=node.anchor, html=node.html,
                                       plain=" ".join(p for p in (node.number, node.title, node.plain) if p)))
    return parsed


@dataclass
class View:
    """Baum aus gespeicherten Abschnitten für die Anzeige."""
    section: LawSection
    children: list["View"] = field(default_factory=list)
    parent: "View | None" = None

    @property
    def label(self) -> str:
        s = self.section
        return " ".join(p for p in (s.number, s.title) if p) or "Eingangsformel"

    @property
    def html(self) -> Markup:
        return Markup(self.section.html)   # beim Speichern aus Markdown ohne HTML erzeugt

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def ancestors(self) -> list["View"]:
        out, node = [], self.parent
        while node:
            out.insert(0, node)
            node = node.parent
        return out


def tree(law: LawText) -> tuple[list[View], list[View]]:
    """(Wurzeln, alle in Reihenfolge)."""
    by_pos: dict[int, View] = {}
    roots, flat = [], []
    for s in law.sections:
        v = View(section=s)
        by_pos[s.position] = v
        flat.append(v)
        parent = by_pos.get(s.parent_position) if s.parent_position is not None else None
        if parent:
            v.parent = parent
            parent.children.append(v)
        else:
            roots.append(v)
    return roots, flat


# --- Ebenen ------------------------------------------------------------------

def level_tree(db) -> list[LawLevel]:
    return list(db.scalars(select(LawLevel).where(LawLevel.parent_id.is_(None))
                           .order_by(LawLevel.position, LawLevel.name)))


def level_options(db, exclude: LawLevel | None = None) -> list[tuple[LawLevel, int]]:
    """Ebenen eingerückt für Auswahllisten (ohne exclude und dessen Unterebenen)."""
    out: list[tuple[LawLevel, int]] = []

    def walk(level: LawLevel, depth: int):
        if exclude is not None and level.id == exclude.id:
            return
        out.append((level, depth))
        for child in level.children:
            walk(child, depth + 1)

    for root in level_tree(db):
        walk(root, 0)
    return out


def level_path(level: LawLevel | None) -> list[LawLevel]:
    out = []
    while level is not None:
        out.insert(0, level)
        level = level.parent
    return out


def descendant_ids(level: LawLevel) -> list[int]:
    ids = [level.id]
    for child in level.children:
        ids.extend(descendant_ids(child))
    return ids


def law_counts(db, published_only: bool) -> dict[int, int]:
    """Anzahl Rechtstexte je Ebene einschließlich aller Unterebenen."""
    q = select(LawText.level_id, func.count(LawText.id)).group_by(LawText.level_id)
    if published_only:
        q = q.where(LawText.published.is_(True))
    direct = {lid: n for lid, n in db.execute(q) if lid}
    totals: dict[int, int] = {}

    def walk(level: LawLevel) -> int:
        total = direct.get(level.id, 0) + sum(walk(c) for c in level.children)
        totals[level.id] = total
        return total

    for root in level_tree(db):
        walk(root)
    return totals


# --- Suche -------------------------------------------------------------------

def terms(query: str) -> list[str]:
    words = re.findall(r"(?:§+|Art\.)\s*\d+[a-z]?\b|[\wÄÖÜäöüß-]+", query or "")
    return [w.strip() for w in words if len(w.strip()) >= 2 or w.strip().isdigit()][:8]


def snippet(text: str, words: list[str], width: int = 110) -> Markup:
    """Ausschnitt um den ersten Treffer, Fundstellen markiert (sicher maskiert)."""
    if not text:
        return Markup("")
    pattern = re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)), re.I) if words else None
    m = pattern.search(text) if pattern else None
    start = max(0, (m.start() if m else 0) - width)
    end = min(len(text), (m.end() if m else 0) + width * 2)
    piece = text[start:end]
    if pattern is None:
        out = escape(piece)
    else:
        out, last = Markup(""), 0
        for hit in pattern.finditer(piece):
            out += escape(piece[last:hit.start()]) + Markup("<mark>") + escape(hit.group()) + Markup("</mark>")
            last = hit.end()
        out += escape(piece[last:])
    return Markup(("… " if start > 0 else "")) + out + Markup(" …" if end < len(text) else "")


def search(db, query: str, published_only: bool = True, level: LawLevel | None = None,
           law: LawText | None = None, limit: int = 200, doc_type: str = "",
           in_force_only: bool = False) -> tuple[list[LawText], list[tuple[LawSection, Markup]]]:
    words = terms(query)
    if not words:
        return [], []
    law_q = select(LawText)
    sec_q = select(LawSection).join(LawText)
    if published_only:
        law_q = law_q.where(LawText.published.is_(True))
        sec_q = sec_q.where(LawText.published.is_(True))
    if doc_type in DOC_TYPES:
        law_q = law_q.where(LawText.doc_type == doc_type)
        sec_q = sec_q.where(LawText.doc_type == doc_type)
    if in_force_only:
        today = today_iso()
        law_q = law_q.where(or_(LawText.valid_until == "", LawText.valid_until > today))
        sec_q = sec_q.where(or_(LawText.valid_until == "", LawText.valid_until > today))
    if level is not None:
        ids = descendant_ids(level)
        law_q = law_q.where(LawText.level_id.in_(ids))
        sec_q = sec_q.where(LawText.level_id.in_(ids))
    if law is not None:
        law_q = law_q.where(LawText.id == law.id)
        sec_q = sec_q.where(LawText.id == law.id)
    for w in words:
        like = f"%{w}%"
        law_q = law_q.where(or_(LawText.title.ilike(like), LawText.short_title.ilike(like)))
        compact = re.sub(r"\s+", "", w)
        sec_q = sec_q.where(or_(LawSection.plain.ilike(like), func.replace(LawSection.number, " ", "").ilike(f"%{compact}%"),
                                LawText.title.ilike(like), LawText.short_title.ilike(like)))
    laws = list(db.scalars(law_q.order_by(LawText.title).limit(50)))
    sections = list(db.scalars(sec_q.where(LawSection.kind != "group").order_by(LawText.title, LawSection.position)
                               .limit(limit)))
    return laws, [(s, snippet(s.plain, words)) for s in sections]


def unique_slug(db, base: str, law_id: int | None = None) -> str:
    base = slugify(base, 70) or "rechtstext"
    if base in RESERVED_SLUGS:
        base += "-text"
    slug, n = base, 2
    while True:
        other = db.scalar(select(LawText).where(LawText.slug == slug))
        if other is None or other.id == law_id:
            return slug
        slug, n = f"{base}-{n}", n + 1


def decode_upload(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --- Geltung, Fassungen, geplante Fassung --------------------------------------------------------

def today_iso() -> str:
    from .db import to_local, utcnow
    return to_local(utcnow()).date().isoformat()


def expired(law: LawText, today: str | None = None) -> bool:
    """Außer Kraft getreten (Datum „außer Kraft ab“ erreicht)."""
    return bool(law.valid_until) and law.valid_until <= (today or today_iso())


def snapshot(db, law: LawText, *, public: bool, valid_until: str = "", saved_by: str = "") -> None:
    """Bisherigen Stand sichern. public: als frühere Fassung (mit Geltungszeitraum) öffentlich abrufbar."""
    from .db import LawVersion
    if not law.id or not law.body_md:
        return
    db.add(LawVersion(law_id=law.id, saved_by=saved_by or (law.editor.name if law.editor else ""), body_md=law.body_md,
                      version_note=law.version_note, saved_at=law.updated_at, public=public, title=law.title,
                      valid_from=law.valid_from, valid_until=valid_until if public else ""))


def public_versions(law: LawText) -> list:
    return [v for v in law.versions if v.public]


def version_for_date(law: LawText, day: str):
    """Fassung, die an einem Tag galt: None = aktuelle Fassung."""
    if not day or (law.valid_from and day >= law.valid_from) or not law.valid_from:
        return None
    for v in public_versions(law):
        if (not v.valid_from or v.valid_from <= day) and (not v.valid_until or day < v.valid_until):
            return v
    return None


def apply_planned() -> int:
    """Hintergrunddienst: vorbereitete Fassungen am Tag des Inkrafttretens übernehmen."""
    from .db import SessionLocal
    n = 0
    today = today_iso()
    with SessionLocal() as db:
        for law in db.scalars(select(LawText).where(LawText.planned_valid_from != "", LawText.planned_valid_from <= today)):
            if not law.planned_md.strip():
                law.planned_valid_from = ""
                continue
            snapshot(db, law, public=True, valid_until=law.planned_valid_from, saved_by="automatisch (Inkrafttreten)")
            law.body_md, law.valid_from = law.planned_md, law.planned_valid_from
            law.version_note = law.planned_note or law.version_note
            law.planned_md, law.planned_valid_from, law.planned_note = "", "", ""
            store(db, law)
            n += 1
        db.commit()
    return n


@dataclass
class Section:
    """Abschnitt einer nicht gespeicherten Fassung – gleiche Felder wie LawSection für die Anzeige."""
    id: int
    position: int
    kind: str
    number: str
    title: str
    anchor: str
    html: str
    plain: str


def tree_of(markdown: str) -> tuple[list[View], list[View]]:
    """Wie tree(), aber für eine frühere Fassung direkt aus dem Markdown."""
    parsed = parse(markdown or "")
    by_node: dict[int, View] = {}
    roots, flat = [], []
    for node in parsed.nodes:
        v = View(section=Section(id=-node.position - 1, position=node.position, kind=node.kind, number=node.number,
                                 title=node.title, anchor=node.anchor, html=node.html,
                                 plain=" ".join(p for p in (node.number, node.title, node.plain) if p)))
        by_node[id(node)] = v
        flat.append(v)
        parent = by_node.get(id(node.parent)) if node.parent else None
        if parent:
            v.parent = parent
            parent.children.append(v)
        else:
            roots.append(v)
    return roots, flat


# --- Vergleich zweier Fassungen ----------------------------------------------------------------

_TOKEN_RE = re.compile(r"\s+|\w+|[^\w\s]")


def _word_diff(a: str, b: str) -> Markup:
    import difflib
    ta, tb = _TOKEN_RE.findall(a), _TOKEN_RE.findall(b)
    out = Markup("")
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op == "equal":
            out += escape("".join(ta[i1:i2]))
            continue
        if i2 > i1:
            out += Markup("<del>") + escape("".join(ta[i1:i2])) + Markup("</del>")
        if j2 > j1:
            out += Markup("<ins>") + escape("".join(tb[j1:j2])) + Markup("</ins>")
    return out


def _body_text(v: View) -> str:
    """Text eines Abschnitts ohne Nummer und Überschrift, Absätze „(1)“ in eigenen Zeilen."""
    s = v.section
    text = s.plain
    head = " ".join(x for x in (s.number, s.title) if x)
    if head and text.startswith(head):
        text = text[len(head):].strip()
    return re.sub(r"\s(\(\d+[a-z]?\))\s", r"\n\1 ", text)


def compare(old_md: str, new_md: str) -> list[dict]:
    """Abschnittsweiser Vergleich: geändert (mit Wortänderungen), neu, entfallen, unverändert."""
    _, old_flat = tree_of(old_md)
    _, new_flat = tree_of(new_md)
    old_by = {v.section.anchor: v for v in old_flat}
    new_anchors = {v.section.anchor for v in new_flat}
    out = []
    for v in new_flat:
        o = old_by.get(v.section.anchor)
        if o is None:
            out.append({"view": v, "status": "added", "diff": escape(_body_text(v))})
        elif (o.section.plain, o.section.title) != (v.section.plain, v.section.title):
            title_note = (Markup("<del>") + escape(o.section.title) + Markup("</del> ")) if o.section.title != v.section.title else Markup("")
            out.append({"view": v, "status": "changed", "diff": title_note + _word_diff(_body_text(o), _body_text(v))})
        else:
            out.append({"view": v, "status": "same", "diff": None})
    for o in old_flat:
        if o.section.anchor not in new_anchors:
            out.append({"view": o, "status": "removed", "diff": escape(_body_text(o))})
    return out


# --- Querverweise und Kurzschreibweise [[ABK § 4]] ------------------------------------------------

_ref_cache: dict = {"at": 0.0, "map": {}}
REF_RE = re.compile(
    r"(?P<all>(?P<kind>§§?|Art\.|Artikel)\s*(?P<num>\d+[a-z]?)(?![\d])"
    r"(?P<sub>(?:\s+(?:Abs\.|Absatz)\s*\d+[a-z]?)?(?:\s+(?:S\.|Satz)\s*\d+)?(?:\s+(?:Nr\.|Nummer)\s*\d+[a-z]?)?)"
    r"(?:\s+(?P<abbr>[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]*[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]*\b))?)")
SHORT_RE = re.compile(r"\[\[\s*([^\]\n]{1,80}?)\s*\]\]")


def ref_map(db=None) -> dict[str, tuple[str, str, set[str]]]:
    """Abkürzung bzw. Adresse (klein) → (Adresse, Titel, Anker) aller veröffentlichten Texte; 30 s zwischengespeichert."""
    import time as _t
    if _t.monotonic() - _ref_cache["at"] < 30 and _ref_cache["map"]:
        return _ref_cache["map"]
    from .db import SessionLocal
    own = db is None
    db = db or SessionLocal()
    try:
        anchors: dict[int, set[str]] = {}
        for law_id, anchor in db.execute(select(LawSection.law_id, LawSection.anchor).join(LawText)
                                         .where(LawText.published.is_(True))):
            anchors.setdefault(law_id, set()).add(anchor)
        out = {}
        for law in db.scalars(select(LawText).where(LawText.published.is_(True))):
            entry = (law.slug, law.short_title or law.title, anchors.get(law.id, set()))
            out[law.slug.lower()] = entry
            if law.short_title:
                out[law.short_title.strip().lower()] = entry
    finally:
        if own:
            db.close()
    _ref_cache.update(at=_t.monotonic(), map=out)
    return out


def invalidate_refs() -> None:
    """Nach Änderungen an Texten: Verweise und Wortschatz für Suchvorschläge neu aufbauen."""
    _ref_cache["at"] = 0.0
    _vocab_cache["at"] = 0.0


def norm_anchor(kind: str, num: str) -> str:
    return _norm_anchor(("art" if kind.lower().startswith("art") else "§") + num)


def link_refs(html: str, own_slug: str, own_anchors: set[str], base: str = "/recht") -> Markup:
    """Verweise wie „§ 5 GemO“ oder „§ 3 Abs. 2“ im Text verlinken: mit bekannter Abkürzung auf den anderen Text,
    ohne Abkürzung innerhalb desselben Texts. Unbekannte Abkürzungen (z. B. „BauGB“, wenn nicht eingestellt) bleiben
    unverlinkt. Gearbeitet wird nur auf Textteilen außerhalb von Tags und vorhandenen Links."""
    refs = ref_map()
    parts = re.split(r"(<[^>]+>)", html)
    out, in_link = [], 0
    for part in parts:
        if part.startswith("<"):
            low = part[:3].lower()
            if low == "<a " or low == "<a>":
                in_link += 1
            elif part.lower().startswith("</a"):
                in_link = max(0, in_link - 1)
            out.append(part)
            continue
        if in_link or "§" not in part and "Art" not in part:
            out.append(part)
            continue

        def repl(m):
            full = m.group(0)
            anchor = norm_anchor(m.group("kind"), m.group("num"))
            abbr = m.group("abbr")
            if abbr:
                target = refs.get(abbr.lower())
                if target is None:
                    return full                       # fremdes Kürzel, hier nicht eingestellt
                slug, _label, anchors = target
                href = f"{base}/{slug}/{anchor}" if anchor in anchors else f"{base}/{slug}"
            else:
                # „§ 4 der Hundesteuersatzung“ meint einen anderen Text – nicht auf den eigenen § 4 zeigen
                if re.match(r"\s+(?:der|des|eines|einer)\s+[A-ZÄÖÜ]", m.string[m.end():m.end() + 40]):
                    return full
                if anchor not in own_anchors:
                    return full
                href = f"{base}/{own_slug}/{anchor}"
            return f'<a class="law-ref" href="{href}" data-preview="{href}">{full}</a>'
        out.append(REF_RE.sub(repl, part))
    return Markup("".join(out))


def shortcodes(escaped: str, base: str = "/recht") -> str:
    """[[HStS § 4]], [[HStS]] oder [[hundesteuersatzung § 4 Abs. 2]] in (bereits maskiertem) Text als Link mit
    Vorschau. Unbekannte Texte bleiben als Klartext ohne Klammern stehen."""
    if "[[" not in escaped:
        return escaped
    refs = ref_map()

    def repl(m):
        inner = htmllib.unescape(m.group(1))
        ref = re.match(r"^(?P<name>.+?)(?:\s+(?P<kind>§§?|Art\.|Artikel)\s*(?P<num>\d+[a-z]?)(?P<rest>.*))?$", inner)
        name = ref.group("name").strip() if ref else inner
        target = refs.get(name.lower())
        if target is None:
            return str(escape(inner))
        slug, label, anchors = target
        href = f"{base}/{slug}"
        if ref.group("kind"):
            anchor = norm_anchor(ref.group("kind"), ref.group("num"))
            if anchor in anchors:
                href += f"/{anchor}"
        return f'<a class="law-ref" href="{escape(href)}" data-preview="{escape(href)}" target="_blank" rel="noopener">{escape(inner)}</a>'
    return SHORT_RE.sub(repl, escaped)


# --- Vorschläge (Tippfehler, Eingabe) -------------------------------------------------------------

_vocab_cache: dict = {"at": 0.0, "words": []}


def _vocabulary(db) -> list[str]:
    import time as _t
    if _t.monotonic() - _vocab_cache["at"] < 120 and _vocab_cache["words"]:
        return _vocab_cache["words"]
    seen: dict[str, int] = {}
    for title, plain in db.execute(select(LawSection.title, LawSection.plain).join(LawText)
                                   .where(LawText.published.is_(True)).limit(20000)):
        for w in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", f"{title} {plain}"):
            key = w.lower()
            seen[key] = seen.get(key, 0) + 1
    for t, st in db.execute(select(LawText.title, LawText.short_title).where(LawText.published.is_(True))):
        for w in re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", f"{t} {st}"):
            seen[w.lower()] = seen.get(w.lower(), 0) + 5
    words = sorted(seen, key=lambda k: -seen[k])[:30000]
    _vocab_cache.update(at=_t.monotonic(), words=words)
    return words


def did_you_mean(db, query: str) -> str:
    """Für Wörter ohne Treffer das ähnlichste Wort aus allen Texten vorschlagen („Hundsteuer“ → „Hundesteuer“)."""
    import difflib
    vocab = _vocabulary(db)
    known = set(vocab)
    changed, out = False, []
    for w in terms(query):
        if re.match(r"(?:§|Art\.)", w) or w.isdigit() or w.lower() in known:
            out.append(w)
            continue
        close = difflib.get_close_matches(w.lower(), vocab, n=1, cutoff=0.75)
        if close:
            out.append(close[0][:1].upper() + close[0][1:] if w[:1].isupper() else close[0])
            changed = True
        else:
            out.append(w)
    return " ".join(out) if changed else ""


def quick(db, query: str, published_only: bool = True, limit: int = 8) -> list[dict]:
    """Vorschläge beim Tippen: Titel, Abkürzungen und Paragrafen („§ 3 HS“)."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    out = []
    lq = select(LawText).where(or_(LawText.title.ilike(like), LawText.short_title.ilike(like)))
    if published_only:
        lq = lq.where(LawText.published.is_(True))
    for law in db.scalars(lq.order_by(LawText.title).limit(limit)):
        out.append({"label": law.title + (f" ({law.short_title})" if law.short_title else ""), "slug": law.slug, "anchor": ""})
    m = re.match(r"^(§§?|Art\.?|Artikel)\s*(\d+[a-z]?)\s*(.*)$", q)
    if m and len(out) < limit:
        anchor = norm_anchor(m.group(1), m.group(2))
        sq = select(LawSection).join(LawText).where(LawSection.anchor == anchor)
        rest = m.group(3).strip()
        if rest:
            sq = sq.where(or_(LawText.short_title.ilike(f"%{rest}%"), LawText.title.ilike(f"%{rest}%")))
        if published_only:
            sq = sq.where(LawText.published.is_(True))
        for sec in db.scalars(sq.limit(limit - len(out))):
            out.append({"label": f"{sec.number} {sec.title} – {sec.law.short_title or sec.law.title}".strip(),
                        "slug": sec.law.slug, "anchor": sec.anchor})
    elif len(out) < limit:
        sq = select(LawSection).join(LawText).where(LawSection.kind == "norm", LawSection.title.ilike(like))
        if published_only:
            sq = sq.where(LawText.published.is_(True))
        for sec in db.scalars(sq.limit(limit - len(out))):
            out.append({"label": f"{sec.number} {sec.title} – {sec.law.short_title or sec.law.title}",
                        "slug": sec.law.slug, "anchor": sec.anchor})
    return out[:limit]


def check_outline(parsed: Parsed) -> list[str]:
    """Hinweise zur erkannten Gliederung: leere Paragrafen, doppelte Nummern, Lücken in der Zählung."""
    out = []
    seen: dict[str, int] = {}
    last = None
    for n in parsed.nodes:
        if n.kind != "norm":
            continue
        if not n.plain:
            out.append(f"{n.number} hat keinen Text.")
        key = n.number.replace(" ", "").lower()
        seen[key] = seen.get(key, 0) + 1
        if seen[key] == 2:
            out.append(f"{n.number} kommt mehrfach vor.")
        m = re.search(r"(\d+)", n.number)
        num = int(m.group(1)) if m else None
        if num is not None and last is not None and num not in (last, last + 1) and not re.search(r"\d+\s*[a-z]\b", n.number):
            out.append(f"Nach {last} folgt {n.number} – fehlt etwas oder ist die Reihenfolge falsch?")
        if num is not None:
            last = num
    if parsed.nodes and not any(n.kind == "norm" for n in parsed.nodes) and len(parsed.nodes) < 2:
        out.append("Keine Paragrafen oder Artikel erkannt – der Text wird als ein Block angezeigt.")
    return out[:20]


# --- Rechtsgrundlagen an Online-Anträgen --------------------------------------------------------

def clean_form_refs(db, law_ids: list, paras: list) -> list[dict]:
    """Auswahl aus dem Antragsformular: [(Rechtstext, „§ 4“ oder „Art. 3“ oder leer)] → gespeicherte Liste."""
    out = []
    for raw_id, para in zip(law_ids, paras):
        if not str(raw_id).isdigit():
            continue
        law = db.get(LawText, int(raw_id))
        if law is None:
            continue
        para = " ".join(str(para or "").split())[:40]
        m = re.match(r"^(§§?|Art\.?|Artikel)?\s*(\d+[a-z]?)", para)
        anchor = norm_anchor(m.group(1) or "§", m.group(2)) if m else ""
        out.append({"law_id": law.id, "anchor": anchor, "para": para})
    return out[:10]


def form_refs(db, form, base: str = "/recht") -> list[dict]:
    """Rechtsgrundlagen eines Antrags zum Anzeigen: [{label, url, preview}] – nur veröffentlichte Texte."""
    import json as _json
    try:
        refs = _json.loads(getattr(form, "legal_json", "") or "[]")
    except ValueError:
        return []
    out = []
    for r in refs if isinstance(refs, list) else []:
        law = db.get(LawText, r.get("law_id")) if isinstance(r, dict) and isinstance(r.get("law_id"), int) else None
        if law is None or not law.published:
            continue
        anchors = {s.anchor for s in law.sections}
        url = f"{base}/{law.slug}" + (f"/{r['anchor']}" if r.get("anchor") in anchors else "")
        label = (f"{r['para']} " if r.get("para") else "") + (law.short_title or law.title)
        out.append({"label": label, "title": law.title, "url": url})
    return out
