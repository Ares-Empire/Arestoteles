"""Arestoteles's interface sentences, English and German side by side (ares-empire/docs/LANGUAGES.md).

Only the server's own sentences are here: error messages and the edit warnings it writes itself. Vault content
(titles, text, glossary) and the vault check's own output are never translated.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Text:
    en: str
    de: str

    def get(self, language: str = "en") -> str:
        return self.de if language == "de" else self.en


# Keys are internal; only their values reach the app.
TEXTS: dict[str, tuple[str, str]] = {
    # login (docs/API.md → Auth)
    "unauthenticated": ("Please sign in again.", "Bitte melde dich erneut an."),
    "forbidden": ("This account has no access to Arestoteles.", "Dieses Konto hat keinen Zugang zu Arestoteles."),
    "login_unavailable": ("Login service unavailable, try again in a minute.",
                          "Anmeldedienst nicht erreichbar, versuch es in einer Minute noch einmal."),
    # routes
    "unknown_route": ("Unknown route.", "Unbekannte Route."),
    "bad_request": ("Bad request.", "Ungültige Anfrage."),
    "not_ready": ("The Weltbild is still loading, try again in a minute.",
                  "Das Weltbild wird noch geladen, versuch es in einer Minute noch einmal."),
    "unknown_note": ("Unknown note.", "Unbekannte Notiz."),
    "unknown_position": ("Unknown position.", "Unbekannte Position."),
    "unknown_callout": ("Unknown callout.", "Unbekannter Hinweis."),
    # 409: changed elsewhere
    "note_changed": ("This note was changed elsewhere; here is the current version.",
                     "Diese Notiz wurde woanders geändert; hier ist die aktuelle Fassung."),
    "position_gone": ("This position no longer exists; it was changed elsewhere.",
                      "Diese Position gibt es nicht mehr; sie wurde woanders geändert."),
    "conflict": ("The note was changed elsewhere at the same time, so your edit was not saved.",
                 "Die Notiz wurde gleichzeitig woanders geändert, deshalb wurde deine Änderung nicht gespeichert."),
    # 422: an edit that cannot apply
    "empty_text": ("The text is empty.", "Der Text ist leer."),
    "position_one_line": ("A position is one line, without line breaks, → or **.",
                          "Eine Position ist eine Zeile, ohne Zeilenumbrüche, → oder **."),
    "empty_why": ("Say what changed your view.", "Schreib, was deine Sicht geändert hat."),
    "not_position_note": ("Positions can only be added to a topic overview or to Positions.",
                          "Positionen gehen nur auf eine Themenübersicht oder auf Positions."),
    "unknown_evidence": ("The evidence names a note that does not exist: {note}.",
                         "Der Beleg nennt eine Notiz, die es nicht gibt: {note}."),
    "no_confidence": ("This kind of note has no confidence.", "Diese Art Notiz hat keine Einschätzung."),
    "check_errors": ("The vault check found errors, so the edit was undone: {errors}",
                     "Die Prüfung hat Fehler gefunden, deshalb wurde die Änderung rückgängig gemacht: {errors}"),
    # warnings the server adds to an edit result
    "check_no_ruby": ("The vault check did not run: Ruby is not installed on the server.",
                      "Die Prüfung lief nicht: Auf dem Server ist Ruby nicht installiert."),
    "check_missing": ("The vault check did not run: the vault has no .tools/check.rb.",
                      "Die Prüfung lief nicht: Das Weltbild hat keine .tools/check.rb."),
    "check_broken": ("The vault check did not run: it stopped with an error.",
                     "Die Prüfung lief nicht: Sie ist mit einem Fehler abgebrochen."),
}


def text(key: str, **values: object) -> Text:
    en, de = TEXTS[key]
    return Text(en.format(**values), de.format(**values))


def language(header: str | None) -> str:
    """`de` when the highest-weighted de/en tag is German (ties keep the first); anything else is `en`."""
    best, weight = "en", -1.0
    for item in (header or "").split(","):
        parts = item.strip().split(";")
        tag = parts[0].strip().lower()
        if not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*", tag):
            continue
        primary = tag.split("-")[0]
        if primary not in ("en", "de"):
            continue
        q = 1.0
        if len(parts) > 1:
            if len(parts) != 2 or not re.fullmatch(r"q\s*=\s*(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)", parts[1].strip(), re.I):
                continue
            q = float(parts[1].split("=", 1)[1])
        if math.isfinite(q) and q > 0 and q > weight:
            best, weight = primary, q
    return best
