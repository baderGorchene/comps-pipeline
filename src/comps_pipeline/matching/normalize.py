import re
from collections.abc import Iterable

KEYWORDS = {
    "PH": "PHASE",
    "PHS": "PHASE",
    "PHASE": "PHASE",
    "SEC": "SECTION",
    "SECT": "SECTION",
    "SECTION": "SECTION",
    "UNIT": "UNIT",
}
NUMBERED = {"PHASE", "SECTION", "UNIT"}
ROMAN = {
    "I": "1",
    "II": "2",
    "III": "3",
    "IV": "4",
    "V": "5",
    "VI": "6",
    "VII": "7",
    "VIII": "8",
    "IX": "9",
    "X": "10",
}
_GLUED = re.compile(r"\b(PHASE|PHS|PH|SECTION|SECT|SEC|UNIT)(\d+)\b")


def normalize(name: str, noise_words: Iterable[str] = ()) -> str:
    """'Brushy Creek Ph. II' -> 'BRUSHY CREEK PHASE 2'."""
    s = name.upper().replace("'", "")
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = _GLUED.sub(r"\1 \2", s)
    noise = {w.upper() for w in noise_words}
    tokens = (ROMAN.get(t, t) for t in (KEYWORDS.get(t, t) for t in s.split()))
    return " ".join(t for t in tokens if t not in noise)


def numbered_parts(normalized: str) -> dict[str, str]:
    """{'PHASE': '2'} for 'BRUSHY CREEK PHASE 2'."""
    tokens = normalized.split()
    return {
        tok: nxt
        for tok, nxt in zip(tokens, tokens[1:], strict=False)
        if tok in NUMBERED and (nxt.isdigit() or len(nxt) == 1)
    }
