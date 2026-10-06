"""Symbole (Font Awesome, frei) mit deutschen Stichwörtern – für die Symbolauswahl mit Suche und den
automatischen Vorschlag (z. B. im Antragskatalog)."""

import re

# (Symbol, Stichwörter) – erstes passendes Stichwort beim Vorschlag gewinnt, daher Spezielles vor Allgemeinem
ICONS: list[tuple[str, str]] = [
    ("fa-dog", "hund hunde hundesteuer tier haustier leine"),
    ("fa-cat", "katze tier haustier"),
    ("fa-paw", "tier tiere tierhaltung fundtier"),
    ("fa-store", "gewerbe gewerbeanmeldung laden geschäft einzelhandel"),
    ("fa-briefcase", "gewerbe beruf arbeit unternehmen firma betrieb"),
    ("fa-industry", "industrie betrieb anlage emission"),
    ("fa-champagne-glasses", "gaststätte gaststaette ausschank alkohol schankerlaubnis fest feier"),
    ("fa-utensils", "gastronomie restaurant imbiss essen bewirtung"),
    ("fa-tents", "markt marktstand zelt veranstaltung festzelt kirmes kerwe"),
    ("fa-calendar-day", "veranstaltung termin event anmeldung veranstaltungsanzeige"),
    ("fa-music", "musik konzert lärm laerm ruhestörung"),
    ("fa-volume-high", "lärm laerm lautsprecher beschallung"),
    ("fa-road", "straße strasse sondernutzung verkehr straßenrecht"),
    ("fa-road-barrier", "absperrung sperrung baustelle straßensperrung verkehrsrechtliche anordnung"),
    ("fa-traffic-light", "verkehr ampel verkehrsrecht"),
    ("fa-square-parking", "parken parkausweis anwohnerparken parkplatz parkerleichterung"),
    ("fa-car", "auto fahrzeug kfz zulassung"),
    ("fa-truck", "lkw transport umzug schwertransport"),
    ("fa-truck-moving", "umzug halteverbot umzugswagen"),
    ("fa-bicycle", "fahrrad rad radweg"),
    ("fa-bus", "bus schülerbeförderung schuelerbefoerderung nahverkehr"),
    ("fa-trash-can", "müll muell abfall entsorgung sperrmüll tonne"),
    ("fa-recycle", "recycling wertstoff grünschnitt gruenschnitt"),
    ("fa-tree", "baum bäume baumfällung baumschutz grün garten natur"),
    ("fa-leaf", "umwelt natur grünfläche gruenflaeche"),
    ("fa-seedling", "pflanze garten kleingarten"),
    ("fa-water", "wasser abwasser kanal gewässer gewaesser"),
    ("fa-faucet-drip", "wasseranschluss hausanschluss wasserzähler wasserzaehler trinkwasser"),
    ("fa-fire", "feuer brauchtumsfeuer osterfeuer verbrennen"),
    ("fa-fire-extinguisher", "brandschutz feuerwehr"),
    ("fa-house", "haus wohnen wohnung grundstück grundstueck"),
    ("fa-house-chimney", "schornstein kamin wohngebäude"),
    ("fa-building", "gebäude gebaeude bau bauen bauantrag baugenehmigung"),
    ("fa-helmet-safety", "baustelle bauarbeiten handwerk"),
    ("fa-trowel-bricks", "bau mauer sanierung abriss"),
    ("fa-ruler-combined", "vermessung grenze bebauungsplan plan"),
    ("fa-map-location-dot", "lageplan karte ort adresse hausnummer"),
    ("fa-signs-post", "schild hinweisschild werbung werbeanlage plakat"),
    ("fa-rectangle-ad", "werbung plakat plakatierung wahlwerbung"),
    ("fa-id-card", "ausweis personalausweis meldebescheinigung melderegister"),
    ("fa-passport", "reisepass pass reise"),
    ("fa-address-card", "meldewesen anmeldung ummeldung wohnsitz adresse"),
    ("fa-people-roof", "familie haushalt wohnsitz"),
    ("fa-baby", "geburt kind kinder kita elterngeld"),
    ("fa-children", "kinder kita kindergarten betreuung ferienbetreuung"),
    ("fa-school", "schule schulanmeldung bildung"),
    ("fa-graduation-cap", "ausbildung studium bildung zeugnis"),
    ("fa-ring", "ehe heirat hochzeit trauung standesamt"),
    ("fa-cross", "friedhof grab bestattung sterbefall"),
    ("fa-hand-holding-heart", "soziales hilfe unterstützung unterstuetzung ehrenamt"),
    ("fa-hand-holding-dollar", "zuschuss förderung foerderung beihilfe"),
    ("fa-euro-sign", "geld gebühr gebuehr zahlung steuer abgabe"),
    ("fa-file-invoice-dollar", "rechnung bescheid steuerbescheid grundsteuer abgaben"),
    ("fa-piggy-bank", "sparen kasse finanzen"),
    ("fa-scale-balanced", "recht satzung widerspruch rechtsbehelf"),
    ("fa-gavel", "ordnungswidrigkeit bußgeld bussgeld verfahren"),
    ("fa-shield-halved", "sicherheit ordnung ordnungsamt gefahr"),
    ("fa-person-shelter", "obdach unterkunft notunterkunft"),
    ("fa-wheelchair", "barrierefrei behinderung schwerbehinderung"),
    ("fa-heart-pulse", "gesundheit arzt pflege"),
    ("fa-syringe", "impfung gesundheit"),
    ("fa-people-group", "verein vereine gruppe ehrenamt"),
    ("fa-futbol", "sport sportplatz sportverein"),
    ("fa-person-swimming", "schwimmbad freibad hallenbad"),
    ("fa-landmark", "rathaus verwaltung behörde behoerde amt"),
    ("fa-landmark-flag", "gemeinde ortsgemeinde verbandsgemeinde kommune"),
    ("fa-check-to-slot", "wahl wahlen briefwahl wahlschein abstimmung"),
    ("fa-envelope-open-text", "brief post schreiben mitteilung"),
    ("fa-envelope", "e-mail kontakt nachricht"),
    ("fa-phone", "telefon anruf kontakt"),
    ("fa-key", "schlüssel schluessel zugang hausmeister übergabe"),
    ("fa-lock", "datenschutz sperre sicherheit auskunft"),
    ("fa-user-shield", "datenschutz auskunft dsgvo"),
    ("fa-camera", "foto bild video überwachung ueberwachung dreharbeiten"),
    ("fa-bullhorn", "bekanntmachung beschwerde hinweis meldung"),
    ("fa-triangle-exclamation", "mängel maengel schaden gefahr störung stoerung"),
    ("fa-lightbulb", "straßenbeleuchtung strassenbeleuchtung licht laterne idee"),
    ("fa-snowflake", "winterdienst schnee streupflicht"),
    ("fa-broom", "reinigung straßenreinigung kehrpflicht"),
    ("fa-bolt", "strom energie elektro"),
    ("fa-solar-panel", "solar photovoltaik pv energie"),
    ("fa-plug-circle-bolt", "ladesäule ladesaeule elektroauto"),
    ("fa-wifi", "internet breitband glasfaser"),
    ("fa-book", "bücherei buecherei bibliothek buch"),
    ("fa-masks-theater", "kultur theater"),
    ("fa-camera-retro", "tourismus sehenswürdigkeit"),
    ("fa-campground", "camping zelten freizeit"),
    ("fa-fish", "angeln fischerei angelschein"),
    ("fa-horse", "pferd reiten"),
    ("fa-gun", "waffe waffenschein jagd jagdschein"),
    ("fa-tractor", "landwirtschaft feldweg"),
    ("fa-hammer", "handwerk reparatur"),
    ("fa-calendar-check", "buchung reservierung termin raum"),
    ("fa-file-signature", "antrag formular allgemein"),
    ("fa-file-lines", "dokument bescheinigung nachweis"),
    ("fa-file-arrow-up", "upload unterlagen einreichen"),
    ("fa-clipboard-list", "liste checkliste"),
    ("fa-circle-question", "frage auskunft information"),
    ("fa-star", "ehrung auszeichnung jubiläum jubilaeum"),
    ("fa-gift", "geschenk spende"),
]

PALETTE = ("#2563eb", "#16a34a", "#ea580c", "#9333ea", "#0891b2", "#ca8a04", "#db2777", "#475569", "#65a30d", "#dc2626")
ICON_RE = re.compile(r"^fa-[a-z0-9-]{1,40}$")
KNOWN = {i for i, _ in ICONS}
DEFAULT = "fa-file-signature"


def clean(icon: str) -> str:
    icon = str(icon or "").strip()
    return icon if icon in KNOWN else ""


def suggest(text: str) -> str:
    """Bestes Symbol zu einem Text (Titel, Kategorie, Beschreibung) – Wortanfänge zählen."""
    words = re.findall(r"[a-zäöüß0-9-]+", str(text or "").lower())
    if not words:
        return ""
    best, score = "", 0
    for icon, keys in ICONS:
        s = 0
        for k in keys.split():
            if any(w == k for w in words):
                s += 3
            elif any(w.startswith(k) or (len(w) > 4 and k.startswith(w)) or (len(k) > 4 and k in w) for w in words):
                s += 1
        if s > score:
            best, score = icon, s
    return best


def color_for(key: str) -> str:
    """Stabile Farbe zu einem Namen (z. B. Kategorie), wenn keine eingestellt ist."""
    return PALETTE[sum(map(ord, key or "")) % len(PALETTE)]


def picker_data() -> list[list[str]]:
    return [[i, k] for i, k in ICONS]
