"""Small text helpers shared by ingestion and search."""

from __future__ import annotations

import unicodedata


def normalize_name(name: str) -> str:
    """Lowercase and strip accents so "jokic" matches "Nikola Jokić"."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()
