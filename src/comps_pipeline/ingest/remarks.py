"""Step 3 Master Guidance: Deterministic NLP & Heuristic Feature Detection on MLS Remarks.

Extracts condition (C1-C6) & quality (Q1-Q6) cues, distressed/fixer keywords, 55+ age
restrictions, non-conforming garage conversions, ADUs/casitas, solar panel lease vs. ownership,
site influences (waterfront/resaca/golf/highway/commercial), and fallback school districts (ISD).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import Comp, Flag, FlagReason, Subject

# Distressed / non-arm's-length / uninhabitable fixer keywords in remarks
DISTRESSED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "foreclosure",
        re.compile(r"\b(?:foreclos(?:ure|ed)|bank[\s-]*owned|reo\s+property)\b", re.I),
    ),
    ("short_sale", re.compile(r"\bshort[\s-]+sale\b", re.I)),
    ("relocation", re.compile(r"\brelocation\s+(?:sale|company)\b", re.I)),
    (
        "below_market_estate",
        re.compile(r"\b(?:probate|estate\s+sale\s+sold\s+below|must\s+liquidate)\b", re.I),
    ),
    (
        "cash_only_fixer",
        re.compile(
            r"\b(?:cash\s+only|investor\s+special|handyman\s+special|"
            r"sold\s+as[\s-]is\s+where[\s-]is)\b",
            re.I,
        ),
    ),
    (
        "uninhabitable",
        re.compile(
            r"\b(?:uninhabitable|tear[\s-]*down|condemned|fire\s+damage|"
            r"severe\s+mold|foundation\s+failure|needs\s+full\s+rehab)\b",
            re.I,
        ),
    ),
)

# 55+ Age-Restricted community detection
AGE_55_PATTERN = re.compile(
    r"\b(?:55\s*\+|55\s*and\s*(?:over|older|better)|age[\s-]+restricted|"
    r"senior\s+community|active\s+adult\s+community)\b",
    re.I,
)

# Non-conforming garage conversion detection
GARAGE_CONVERSION_PATTERN = re.compile(
    r"\b(?:garage\s+(?:has\s+been\s+|was\s+|is\s+)?converted|"
    r"converted\s+garage|enclosed\s+garage|garage\s+enclosure)\b",
    re.I,
)

# Accessory Dwelling Unit (ADU) / Guest House / Casita detection
ADU_PATTERN = re.compile(
    r"\b(?:a\.?d\.?u\.?|accessory\s+dwelling|guest\s+house|guest\s+quarters|casita|"
    r"mother[\s-]+in[\s-]+law\s+(?:suite|quarters)|garage\s+apartment|detached\s+apartment)\b",
    re.I,
)

# Solar panel detection (distinguishing leased/financed vs owned/paid-off)
SOLAR_PATTERN = re.compile(r"\bsolar\s+panels?\b|\bsolar\s+system\b", re.I)
SOLAR_OWNED_PATTERN = re.compile(
    r"\b(?:owned\s+solar|solar\s+(?:panels?\s+)?(?:are\s+|is\s+)?"
    r"(?:paid\s+off|owned\s+free|free\s+and\s+clear))\b",
    re.I,
)
SOLAR_LEASED_PATTERN = re.compile(
    r"\b(?:leased\s+solar|solar\s+lease|assume\s+solar|solar\s+loan|ppa\s+solar)\b",
    re.I,
)

# Site / View / External Obsolescence influences
SITE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "waterfront/resaca",
        re.compile(r"\b(?:resaca|waterfront|lakefront|canal\s+front|riverfront)\b", re.I),
    ),
    ("golf_course", re.compile(r"\bgolf\s+course\b", re.I)),
    (
        "greenbelt/cul-de-sac",
        re.compile(r"\b(?:greenbelt|cul[\s-]+de[\s-]+sac|corner\s+lot)\b", re.I),
    ),
    (
        "external_obsolescence",
        re.compile(
            r"\b(?:busy\s+highway|backs\s+to\s+highway|commercial\s+adjacent|"
            r"high[\s-]+voltage\s+power)\b",
            re.I,
        ),
    ),
)

# Renovation / C2 / C3 / C4 condition cues
C1_NEW_PATTERN = re.compile(
    r"\b(?:brand\s+new\s+construction|never\s+occupied|never\s+lived\s+in|"
    r"new\s+build\s+202[4-9]|under\s+construction)\b",
    re.I,
)
C2_RENOVATED_PATTERN = re.compile(
    r"\b(?:completely\s+remodeled|fully\s+renovated|taken\s+to\s+the\s+studs|"
    r"brand\s+new\s+kitchen\s+and\s+bath|total\s+remodel)\b",
    re.I,
)
C3_UPDATED_PATTERN = re.compile(
    r"\b(?:updated\s+kitchen|quartz\s+countertops?|granite\s+countertops?|new\s+roof|"
    r"updated\s+bath|remodeled|move[\s-]+in\s+ready|well\s+maintained)\b",
    re.I,
)
C5_FIXER_PATTERN = re.compile(
    r"\b(?:needs\s+tlc|needs\s+cosmetic|original\s+condition|dated\s+interior|fixer[\s-]+upper)\b",
    re.I,
)

# Fallback School District (ISD / CISD) extraction from remarks
ISD_PATTERN = re.compile(
    r"\b(Sharyland|McAllen|Edinburg|Pharr[\s-]+San\s+Juan[\s-]+Alamo|PSJA|Mission|"
    r"Hidalgo|Valley\s+View|La\s+Joya|Weslaco|Harlingen|Brownsville|"
    r"Round\s+Rock|Leander|Austin)\s+(?:C?ISD|School\s+District)\b",
    re.I,
)


@dataclass
class RemarksAnalysis:
    distressed_matches: list[str] = field(default_factory=list)
    is_55_plus: bool = False
    has_garage_conversion: bool = False
    has_adu: bool = False
    solar_status: str | None = None  # "owned" | "leased_or_unverified" | None
    site_influences: list[str] = field(default_factory=list)
    detected_condition: str | None = None  # "C1".."C6"
    detected_quality: str | None = None  # "Q1".."Q6"
    extracted_school_district: str | None = None


def _truthy(val: str) -> bool:
    return val.strip().casefold() in {"y", "yes", "true", "1"}


def analyze_comp_remarks(
    comp: Comp, subject: Subject, settings: Settings
) -> tuple[Comp, list[Flag]]:
    """Run deterministic NLP over public + private remarks and structured extras."""
    pub = comp.public_remarks.value or ""
    priv = comp.extra_str("Private Remarks", "Agent Remarks", "PrivateRemarks")
    sub_raw = comp.subdivision_raw.value or ""
    text = f"{pub} {priv}".strip()
    flags: list[Flag] = []
    signals: dict[str, Any] = dict(comp.remarks_signals)

    # 1. Distressed keywords in remarks
    distressed: list[str] = []
    for label, pat in DISTRESSED_PATTERNS:
        m = pat.search(text)
        if m:
            distressed.append(f"{label} ({m.group(0)!r})")
    if distressed:
        signals["_distressed_remarks"] = "; ".join(distressed)

    # 2. 55+ Age restriction (check both remarks and subdivision name)
    is_55_extra = _truthy(comp.extra_str("Age Restricted", "55+", "Senior Community"))
    if AGE_55_PATTERN.search(text) or AGE_55_PATTERN.search(sub_raw) or is_55_extra:
        signals["_is_55_plus"] = True

    # 3. Non-conforming garage conversion
    m_conv = GARAGE_CONVERSION_PATTERN.search(text)
    if m_conv:
        snippet = m_conv.group(0)
        signals["_garage_conversion"] = snippet
        msg = (
            f"Potential non-conforming garage conversion detected in remarks ({snippet!r}); "
            "verify permits vs GLA."
        )
        flags.append(
            settings.flag(
                FlagReason.NON_CONFORMING_CONVERSION,
                comp.mls_number,
                msg,
                field="public_remarks",
                evidence=snippet,
            )
        )

    # 4. ADU / Guest house / Casita
    m_adu = ADU_PATTERN.search(text)
    if m_adu:
        snippet = m_adu.group(0)
        signals["_has_adu"] = True
        msg = (
            f"Accessory dwelling unit / guest quarters mentioned in remarks ({snippet!r}); "
            "separate ADU from main GLA."
        )
        flags.append(
            settings.flag(
                FlagReason.ADU_DETECTED,
                comp.mls_number,
                msg,
                field="public_remarks",
                evidence=snippet,
            )
        )

    # 5. Solar panels (leased/unverified vs owned)
    if SOLAR_PATTERN.search(text):
        if SOLAR_OWNED_PATTERN.search(text) and not SOLAR_LEASED_PATTERN.search(text):
            signals["_solar_status"] = "owned"
        else:
            signals["_solar_status"] = "leased_or_unverified"
            msg = (
                "Solar panels mentioned without confirmed free-and-clear ownership; "
                "leased/financed solar gives $0 value under UAD 3.6."
            )
            flags.append(
                settings.flag(
                    FlagReason.SOLAR_LEASE_REVIEW,
                    comp.mls_number,
                    msg,
                    field="public_remarks",
                )
            )

    # 6. Site influences (resaca, waterfront, golf, external obsolescence)
    influences: list[str] = []
    for label, pat in SITE_PATTERNS:
        m = pat.search(text)
        if m:
            influences.append(f"{label}: {m.group(0)}")
    if influences:
        joined = ", ".join(influences)
        signals["_site_influences"] = joined
        flags.append(
            settings.flag(
                FlagReason.SITE_INFLUENCE_NOTE,
                comp.mls_number,
                f"Site/location influence noted in remarks ({joined}).",
                field="public_remarks",
                evidence=joined,
            )
        )

    # 7. Condition (C1-C6) & Quality (Q1-Q6) inference if not already in CSV columns
    explicit_cond = comp.extra_str("Condition", "Condition Rating", "UAD Condition")
    if explicit_cond:
        c_norm = explicit_cond.upper()
        if c_norm.isdigit():
            c_norm = f"C{c_norm}"
        signals["_detected_condition"] = c_norm
    else:
        new_const = _truthy(
            comp.extra_str("New Construction", "New Construction Y/N", "NewConstructionYN")
        )
        yb = comp.year_built.value
        eff_year = subject.effective_date.year
        age = (eff_year - yb) if yb else None
        if new_const or C1_NEW_PATTERN.search(text) or (age is not None and age <= 0):
            signals["_detected_condition"] = "C1"
        elif C2_RENOVATED_PATTERN.search(text) or (age is not None and age <= 3):
            signals["_detected_condition"] = "C2"
        elif distressed:
            signals["_detected_condition"] = "C6"
        elif C5_FIXER_PATTERN.search(text):
            signals["_detected_condition"] = "C5"
        elif C3_UPDATED_PATTERN.search(text) or (age is not None and age <= 15):
            signals["_detected_condition"] = "C3"
        elif age is not None:
            signals["_detected_condition"] = "C4"

    explicit_qual = comp.extra_str("Quality", "Quality Rating", "UAD Quality")
    if explicit_qual:
        q_norm = explicit_qual.upper()
        if q_norm.isdigit():
            q_norm = f"Q{q_norm}"
        signals["_detected_quality"] = q_norm
    elif comp.living_area.value is not None:
        signals["_detected_quality"] = subject.quality.upper() if subject.quality else "Q4"

    # 8. Fallback School District extraction from remarks if column is absent/blank
    if not comp.extra_str("School District", "ISD", "SchoolDistrict", "High School District"):
        m_isd = ISD_PATTERN.search(text)
        if m_isd:
            signals["_extracted_isd"] = m_isd.group(1).strip()

    return comp.model_copy(update={"remarks_signals": signals}), flags
