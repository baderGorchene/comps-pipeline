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
    "UT": "UNIT",
}
# "Unit No. 2" / "Phase Number 3": the filler word after a keyword is dropped.
NUMBER_WORDS = {"NO", "NUM", "NUMBER"}
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
_GLUED = re.compile(r"\b(PHASE|PHS|PH|SECTION|SECT|SEC|UNIT|UT)(\d+)\b")
_KEYWORD_HASH = re.compile(r"\b(PHASE|PHS|PH|SECTION|SECT|SEC|UNIT|UT)\W*#\s*(\d+)")  # "Phase #2"
_HASH = re.compile(r"#\s*(\d+)")  # bare "Parkhill Terrace #2" -> unit 2


def normalize(name: str, noise_words: Iterable[str] = ()) -> str:
    """'Brushy Creek Ph. II' -> 'BRUSHY CREEK PHASE 2'; 'Parkhill Terrace #2' -> '... UNIT 2'."""
    s = _KEYWORD_HASH.sub(r"\1 \2", name.upper().replace("'", ""))
    s = _HASH.sub(r" UNIT \1", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = _GLUED.sub(r"\1 \2", s)
    noise = {w.upper() for w in noise_words}
    tokens: list[str] = []
    for t in (ROMAN.get(t, t) for t in (KEYWORDS.get(t, t) for t in s.split())):
        if t in noise or (t in NUMBER_WORDS and tokens and tokens[-1] in NUMBERED):
            continue
        tokens.append(t)
    return " ".join(tokens)


def numbered_parts(normalized: str) -> dict[str, str]:
    """{'PHASE': '2'} for 'BRUSHY CREEK PHASE 2'."""
    tokens = normalized.split()
    return {
        tok: nxt
        for tok, nxt in zip(tokens, tokens[1:], strict=False)
        if tok in NUMBERED and (nxt.isdigit() or len(nxt) == 1)
    }
