"""Транслитерация имён 1С в ASCII-идентификаторы DataHub.

URN строятся на UUID, поэтому транслитерация используется только для
``SchemaField.fieldPath``, ``attributesUuidMap``, ``oneCDbMapping`` и legacy
display-полей. Русские имена сохраняются в display/label/description.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

import cyrtranslit  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

_ASCII_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
_APOSTROPHE_MARKS_RE = re.compile(r"[`'’ʼ]")
_NON_IDENTIFIER_RE = re.compile(r"[^A-Za-z0-9_]")


def is_ascii_identifier(name: str) -> bool:
    return bool(_ASCII_ID_RE.match(name))


def _normalize_identifier(name: str, transliterated: str) -> str:
    without_sign_markers = _APOSTROPHE_MARKS_RE.sub("", transliterated)
    unknown_chars = sorted(set(_NON_IDENTIFIER_RE.findall(without_sign_markers)))
    if unknown_chars:
        logger.warning(
            "translit: символы %r в имени %r не распознаны, заменены на '_'",
            "".join(unknown_chars),
            name,
        )
    return _NON_IDENTIFIER_RE.sub("_", without_sign_markers)


def transliterate(
    name: str,
    *,
    overrides: Mapping[str, str] | None = None,
) -> str:
    if not name:
        return name

    if overrides and name in overrides:
        override = overrides[name]
        if not is_ascii_identifier(override):
            raise ValueError(
                f"transliteration override for {name!r} must match ^[A-Za-z0-9_]+$; "
                f"got {override!r}"
            )
        return override

    if is_ascii_identifier(name):
        return name

    return _normalize_identifier(name, cyrtranslit.to_latin(name, "ru"))
