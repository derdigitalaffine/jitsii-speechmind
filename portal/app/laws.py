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
           law: LawText | None = None, limit: int = 200) -> tuple[list[LawText], list[tuple[LawSection, Markup]]]:
    words = terms(query)
    if not words:
        return [], []
    law_q = select(LawText)
    sec_q = select(LawSection).join(LawText)
    if published_only:
        law_q = law_q.where(LawText.published.is_(True))
        sec_q = sec_q.where(LawText.published.is_(True))
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
