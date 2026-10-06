"""CSV-Export ohne Formel-Injection.

Tabellenprogramme führen Zellen, die mit = + - @ oder einem Tabulator beginnen, als Formel aus. Kommen solche
Werte aus Eingaben von außen (Formularantworten, Buchungen, Namen), ließe sich damit beim Öffnen des Exports
Code ausführen oder Daten abfließen. Solche Zellen bekommen ein vorangestelltes Hochkomma; Zahlen bleiben.
"""

import csv
import re

_DANGER = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"[+-]?\d[\d.,]*")


def cell(value):
    if isinstance(value, str) and value.startswith(_DANGER) and not _NUMBER.fullmatch(value):
        return "'" + value
    return value


class _Writer:
    def __init__(self, inner):
        self._inner = inner

    def writerow(self, row):
        return self._inner.writerow([cell(v) for v in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def writer(buf, **kwargs) -> _Writer:
    return _Writer(csv.writer(buf, **kwargs))
