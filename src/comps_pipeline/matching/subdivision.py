"""Subdivision tiers.

0 = identical after normalization, 1 = manual alias match, 2 = fuzzy score >= threshold
(SUBDIVISION_UNCERTAIN), 3 = below threshold. Differing phase/section/unit numbers can never
be tier 0 or 1.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from comps_pipeline.config.schema import Settings
from comps_pipeline.matching.normalize import normalize, numbered_parts
from comps_pipeline.models import (
    AuditEntry,
    Cell,
    Comp,
    Decision,
    FlagReason,
    Source,
    StageOutput,
    Subject,
)

STAGE = "subdivision"
_LEGAL_NOISE = re.compile(r"\b(?:LOT|LT|BLK|BLOCK)\s+[0-9A-Z-]+\b")


def strip_legal_lot_block(legal_text: str) -> str:
    """Remove LOT/BLK tokens from a tax legal description before subdivision matching."""
    return _LEGAL_NOISE.sub(" ", legal_text.upper())


@dataclass(frozen=True)
class Match:
    normalized: str
    tier: int
    score: float
    number_conflict: dict[str, tuple[str, str]]


def alias_index(aliases: dict[str, list[str]], noise_words: list[str]) -> dict[str, str]:
    """normalized variant -> normalized canonical name."""
    index = {}
    for canonical, variants in aliases.items():
        target = normalize(canonical, noise_words)
        for name in [canonical, *variants]:
            index[normalize(name, noise_words)] = target
    return index


def match_subdivision(
    comp_name: str, subject_name: str, settings: Settings, index: dict[str, str] | None = None
) -> Match:
    noise = settings.matching.noise_words
    index = alias_index(settings.subdivision_aliases, noise) if index is None else index
    nc, ns = normalize(comp_name, noise), normalize(subject_name, noise)
    pc, ps = numbered_parts(nc), numbered_parts(ns)
    conflict = {k: (pc[k], ps[k]) for k in pc.keys() & ps.keys() if pc[k] != ps[k]}
    if not conflict:
        if nc == ns:
            return Match(nc, 0, 100.0, conflict)
        if index.get(nc, nc) == index.get(ns, ns):
            return Match(nc, 1, 100.0, conflict)
    score = round(fuzz.token_sort_ratio(nc, ns), 2)
    tier = 2 if score >= settings.filters.subdivision_min_score else 3
    return Match(nc, tier, score, conflict)


def match_all(comps: list[Comp], subject: Subject, settings: Settings) -> StageOutput:
    """Annotates tier and score. Exclusion of tier 3 happens in the hard filters."""
    out = StageOutput()
    index = alias_index(settings.subdivision_aliases, settings.matching.noise_words)
    for comp in comps:
        raw = comp.subdivision_raw.value
        if raw is None:
            out.comps.append(comp)  # cleaner already flagged it; tier stays null
            continue
        m = match_subdivision(raw, subject.subdivision, settings, index)
        legal = comp.extra_str("Legal Description", "LegalDescription", "Tax Legal Description")
        if m.tier == 3 and legal:
            m_legal = match_subdivision(
                strip_legal_lot_block(legal), subject.subdivision, settings, index
            )
            if m_legal.tier < m.tier or (m_legal.tier == m.tier and m_legal.score > m.score):
                m = m_legal
        update = {
            "subdivision_normalized": Cell(value=m.normalized, source=Source.COMPUTED),
            "subdivision_tier": Cell(value=m.tier, source=Source.COMPUTED),
            "subdivision_score": Cell(value=m.score, source=Source.COMPUTED),
        }
        if m.tier == 2:
            parts = ", ".join(f"{k} {c} vs {s}" for k, (c, s) in sorted(m.number_conflict.items()))
            msg = f"{raw!r} ~ {subject.subdivision!r}, fuzzy score {m.score}" + (
                f"; number mismatch: {parts}" if parts else ""
            )
            out.flags.append(
                settings.flag(
                    FlagReason.SUBDIVISION_UNCERTAIN,
                    comp.mls_number,
                    msg,
                    "subdivision_raw",
                    evidence=raw,
                )
            )
            update["subdivision_tier"] = Cell(
                value=2, source=Source.COMPUTED, flag=FlagReason.SUBDIVISION_UNCERTAIN, note=msg
            )
            out.audit.append(
                AuditEntry(
                    mls_number=comp.mls_number,
                    stage=STAGE,
                    decision=Decision.FLAGGED,
                    rule=FlagReason.SUBDIVISION_UNCERTAIN.value,
                    detail={"message": msg, "score": m.score},
                )
            )
        out.comps.append(comp.model_copy(update=update))
    return out
