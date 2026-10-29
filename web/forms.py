"""Forms for one run (MLS export, subject property) and full pipeline configuration."""

import copy
from typing import Any

import yaml
from django import forms

from comps_pipeline.config.schema import BRACKET_ATTRIBUTES, RANKING_KEYS
from comps_pipeline.models.comp import STANDARD_FIELDS
from comps_pipeline.models.flag import FlagReason, Severity

MISSING = [("exclude", "Exclude the comp"), ("keep_and_flag", "Keep it and flag it")]
SEVERITY_CHOICES = [(s.value, s.value) for s in Severity]

ATTRIBUTE_LABELS = {
    "gla": "Living area",
    "lot": "Lot size",
    "age": "Year built",
    "beds": "Bedrooms",
    "baths": "Baths",
}

FIELD_LABELS: dict[str, tuple[str, str]] = {
    "mls_number": ("MLS Number", "Unique listing identifier (required)"),
    "status": ("Listing Status", "Sold, Active, Pending, etc. (required)"),
    "close_price": ("Close / Sold Price", "Final sale price for sold comps"),
    "close_date": ("Close / Sold Date", "Closing date for sold comps"),
    "list_price": ("List Price", "Asking price for active/pending listings"),
    "living_area": ("Living Area (GLA)", "Gross living area in square feet (required)"),
    "year_built": ("Year Built", "Construction year of the property"),
    "lot_size_sqft": ("Lot Size (Sq Ft)", "Lot area in square feet (preferred over acres)"),
    "lot_size_acres": ("Lot Size (Acres)", "Lot area in acres (used if sq ft is absent)"),
    "bedrooms": ("Bedrooms", "Total bedroom count"),
    "baths_full": ("Full Bathrooms", "Number of full bathrooms"),
    "baths_half": ("Half Bathrooms", "Number of half bathrooms (counted as 0.5)"),
    "subdivision_raw": ("Subdivision Name", "Legal or marketing subdivision name (required)"),
    "latitude": ("Latitude", "Decimal latitude for Haversine distance"),
    "longitude": ("Longitude", "Decimal longitude for Haversine distance"),
    "reported_distance_miles": ("Reported Distance", "Fallback distance column if no coordinates"),
    "foundation_type": ("Foundation Type", "Foundation description (e.g. Slab, Crawl Space)"),
    "public_remarks": ("Public Remarks", "MLS property description / remarks text"),
}

FLAG_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "MISSING_REQUIRED_FIELD": (
        "Missing Required Field",
        "A required attribute (e.g. GLA, close price, or subject field) is blank.",
    ),
    "INVALID_VALUE": (
        "Invalid Field Value",
        "A field could not be parsed (e.g. non-numeric price or future date).",
    ),
    "DUPLICATE_LISTING": (
        "Duplicate MLS Listing",
        "The same MLS number appeared more than once; first row is kept.",
    ),
    "NO_COORDINATES": (
        "No Coordinates / Distance",
        "Neither GPS coordinates nor a reported distance column was found.",
    ),
    "SUBDIVISION_UNCERTAIN": (
        "Uncertain Subdivision Match",
        "Subdivision matched via fuzzy spelling (Tier 2) rather than exact/alias.",
    ),
    "SHORTLIST_BELOW_MINIMUM": (
        "Shortlist Below Minimum",
        "Fewer sold comps than minimum remained even after all relaxation steps.",
    ),
    "STATUS_NOT_USED": (
        "Excluded Status Code",
        "Row had an unused status such as Expired, Withdrawn, or Cancelled.",
    ),
    "CRITERIA_RELAXED": (
        "Filter Criteria Relaxed",
        "One or more relaxation steps were needed to reach the minimum sold count.",
    ),
    "NOT_BRACKETED": (
        "Attribute Not Bracketed",
        "Final picks do not have both a higher and lower comp on a target attribute.",
    ),
    "NO_LISTING_COMP": (
        "Missing Listing Comp",
        "Fewer active/pending listings were available than requested for the final pick.",
    ),
}


def _int(label: str, lo: int, hi: int, **kw: Any) -> forms.IntegerField:
    return forms.IntegerField(label=label, min_value=lo, max_value=hi, **kw)


class InputsForm(forms.Form):
    csv_source = forms.ChoiceField(
        choices=[("upload", "Upload an MLS export"), ("sample", "Use the synthetic sample")],
        widget=forms.RadioSelect,
        initial="upload",
    )
    csv_file = forms.FileField(label="MLS export (.csv)", required=False)
    subject_source = forms.ChoiceField(
        choices=[("form", "Type it in"), ("yaml", "Upload subject.yaml")],
        widget=forms.RadioSelect,
        initial="form",
    )
    subject_file = forms.FileField(label="Subject file (.yaml)", required=False)

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        if data.get("csv_source") == "upload" and not data.get("csv_file"):
            self.add_error("csv_file", "Choose the CSV exported from your MLS, or use the sample.")
        if data.get("subject_source") == "yaml" and not data.get("subject_file"):
            self.add_error("subject_file", "Choose a subject .yaml file, or type the subject in.")
        return data


class SubjectForm(forms.Form):
    address = forms.CharField(max_length=200)
    subdivision = forms.CharField(max_length=200)
    living_area = _int("Living area (sq ft)", 1, 100_000)
    effective_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    year_built = _int("Year built", 1800, 2100, required=False)
    lot_size_sqft = _int("Lot (sq ft)", 1, 100_000_000, required=False)
    lot_size_acres = forms.FloatField(
        label="Lot (acres)", min_value=0.0001, required=False, help_text="Only if no sq ft"
    )
    bedrooms = _int("Bedrooms", 0, 50, required=False)
    baths_full = _int("Full baths", 0, 50, required=False)
    baths_half = _int("Half baths", 0, 50, required=False)
    latitude = forms.FloatField(min_value=-90, max_value=90, required=False)
    longitude = forms.FloatField(min_value=-180, max_value=180, required=False)

    def subject_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.cleaned_data.items() if v not in (None, "")}


def steps_to_text(steps: list[dict[str, Any]]) -> str:
    return "\n".join(", ".join(f"{k} = {v}" for k, v in step.items()) for step in steps)


def text_to_steps(text: str) -> list[dict[str, Any]]:
    """'max_distance_miles = 4' per line; several changes in one step separated by commas."""
    steps = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        step = {}
        for part in line.split(","):
            if "=" not in part:
                raise forms.ValidationError(f"Line {n}: write each change as setting = value.")
            key, value = (p.strip() for p in part.split("=", 1))
            try:
                parsed = yaml.safe_load(value)
            except yaml.YAMLError as e:
                raise forms.ValidationError(f"Line {n}: invalid value {value!r} ({e}).") from e
            if not key or parsed is None or isinstance(parsed, (dict, list)):
                raise forms.ValidationError(f"Line {n}: write each change as setting = value.")
            step[key] = parsed
        steps.append(step)
    return steps


def kv_dict_to_text(d: dict[str, str]) -> str:
    return "\n".join(f"{k} = {v}" for k, v in d.items())


def text_to_kv_dict(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if "=" not in line:
            raise forms.ValidationError(f"Line {n}: write each requirement as field = value.")
        key, val = (p.strip() for p in line.split("=", 1))
        if not key or not val:
            raise forms.ValidationError(f"Line {n}: both field name and value are required.")
        out[key] = val.strip("\"'")
    return out


def aliases_to_text(aliases: dict[str, list[str]]) -> str:
    return "\n".join(f"{canon} = {', '.join(variants)}" for canon, variants in aliases.items())


def text_to_aliases(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if "=" not in line:
            raise forms.ValidationError(
                f"Line {n}: write each alias group as CANONICAL NAME = Alias 1, Alias 2."
            )
        canon, rest = (p.strip() for p in line.split("=", 1))
        variants = [v.strip() for v in rest.split(",") if v.strip()]
        if not canon or not variants:
            raise forms.ValidationError(
                f"Line {n}: provide a canonical name and at least one alias."
            )
        out[canon] = variants
    return out


def _words(text: str) -> list[str]:
    return [w.strip() for w in text.split(",") if w.strip()]


class RulesForm(forms.Form):
    # Filters
    gla_bracket_pct = _int("Living area within ± %", 0, 100)
    lot_bracket_pct = _int("Lot size (acres) within ± %", 0, 100)
    max_distance_miles = forms.FloatField(label="Max distance (miles)", min_value=0.01)
    sale_date_max_months = _int("Sold within (months)", 1, 120)
    require_subdivision_match = forms.BooleanField(
        label="Require the same subdivision", required=False
    )
    subdivision_min_score = _int("Spelling match needed (0-100)", 0, 100)
    missing_gla = forms.ChoiceField(label="No living area", choices=MISSING)
    missing_lot = forms.ChoiceField(label="No lot size", choices=MISSING)
    missing_distance = forms.ChoiceField(label="No distance", choices=MISSING)
    missing_close_date = forms.ChoiceField(label="Sold, no close date", choices=MISSING)
    # Shortlist sizes
    shortlist_size = _int("Sold comps to keep", 1, 500)
    min_shortlist_size = _int("Relax the rules below this many sold", 0, 500)
    listing_shortlist_size = _int("Listings to keep", 1, 500)
    escalation = forms.CharField(
        label="Relax in this order",
        widget=forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
        required=False,
    )
    # Ranking and final pick
    hierarchy = forms.CharField(label="Rank by, in order")
    sold_count = _int("Sold comps", 1, 20)
    listing_count = _int("Active / pending comps", 0, 5)
    bracket_attributes = forms.MultipleChoiceField(
        label="Bracket the subject on",
        choices=[(a, ATTRIBUTE_LABELS[a]) for a in BRACKET_ATTRIBUTES],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    equal_counts_as_bracketed = forms.BooleanField(
        label="A comp equal to the subject counts as both sides", required=False
    )
    status_sold = forms.CharField(label="Sold status codes")
    status_listing = forms.CharField(label="Active / option / pending codes")

    @classmethod
    def initial_from(cls, cfg: dict[str, Any]) -> dict[str, Any]:
        f, r, s = cfg["filters"], cfg["run"], cfg["selection"]
        initial = {k: f[k] for k in cls.base_fields if k in f}
        initial.update({k: r[k] for k in ("shortlist_size", "min_shortlist_size")})
        initial["listing_shortlist_size"] = r["listing_shortlist_size"]
        initial.update({k: s[k] for k in cls.base_fields if k in s})
        initial["subdivision_min_score"] = int(f["subdivision_min_score"])
        initial["escalation"] = steps_to_text(cfg["escalation"]["steps"])
        initial["hierarchy"] = ", ".join(cfg["ranking"]["hierarchy"])
        initial["status_sold"] = ", ".join(cfg["status"]["sold"])
        initial["status_listing"] = ", ".join(cfg["status"]["listing"])
        return initial

    def clean_escalation(self) -> list[dict[str, Any]]:
        return text_to_steps(self.cleaned_data["escalation"])

    def clean_hierarchy(self) -> list[str]:
        keys = [k.lower() for k in _words(self.cleaned_data["hierarchy"])]
        if sorted(keys) != sorted(RANKING_KEYS):
            raise forms.ValidationError(f"List each of {', '.join(RANKING_KEYS)} exactly once.")
        return keys

    def apply_to(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """A copy of the settings dict with this form's values written in."""
        d = self.cleaned_data
        cfg = copy.deepcopy(cfg)
        for k in cfg["filters"]:
            if k in d:
                cfg["filters"][k] = d[k]
        for k in ("shortlist_size", "min_shortlist_size", "listing_shortlist_size"):
            cfg["run"][k] = d[k]
        for k in cfg["selection"]:
            if k in d:
                cfg["selection"][k] = d[k]
        cfg["escalation"]["steps"] = d["escalation"]
        cfg["ranking"]["hierarchy"] = d["hierarchy"]
        cfg["status"]["sold"] = _words(d["status_sold"])
        cfg["status"]["listing"] = _words(d["status_listing"])
        return cfg


class ConfigForm(RulesForm):
    """Complete pipeline configuration editor covering settings.yaml, column_mapping.yaml,
    and subdivision_aliases.yaml."""

    output_dir = forms.CharField(label="Run output directory", max_length=260)
    gla_bracket_inclusive = forms.BooleanField(
        label="Include comps exactly on the living area % edge", required=False
    )
    lot_bracket_inclusive = forms.BooleanField(
        label="Include comps exactly on the lot size % edge", required=False
    )
    required_features = forms.CharField(
        label="Required property features (optional)",
        widget=forms.Textarea(
            attrs={"rows": 3, "spellcheck": "false", "placeholder": "foundation_type = Crawl Space"}
        ),
        required=False,
    )
    # Ranking tolerance bands
    band_distance_miles = forms.FloatField(label="Distance tie band (miles)", min_value=0.0001)
    band_gla_pct = forms.FloatField(label="Living area tie band (%)", min_value=0.0001)
    band_age_years = forms.FloatField(label="Age tie band (years)", min_value=0.0001)
    band_lot_pct = forms.FloatField(label="Lot size tie band (%)", min_value=0.0001)
    band_beds_count = forms.FloatField(label="Bedrooms tie band (count)", min_value=0.0001)
    band_baths_count = forms.FloatField(label="Baths tie band (count)", min_value=0.0001)
    # Matching & Subdivision aliases
    noise_words = forms.CharField(
        label="Ignored subdivision noise words (comma-separated)", required=False
    )
    subdivision_aliases = forms.CharField(
        label="Subdivision aliases (Canonical Name = Variant 1, Variant 2)",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "spellcheck": "false",
                "placeholder": "BRUSHY CREEK PHASE 2 = BC PHASE 2, BRUSHYCREEK PHASE 2",
            }
        ),
        required=False,
    )
    # Ingest date formats
    date_formats = forms.CharField(label="Accepted CSV date formats (comma-separated)")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Dynamically add column mapping fields for all 18 standard fields
        for std_field in STANDARD_FIELDS:
            title, desc = FIELD_LABELS.get(std_field, (std_field, ""))
            self.fields[f"map_{std_field}"] = forms.CharField(
                label=title,
                help_text=desc,
                required=False,
            )
        # Dynamically add flag severity fields for all FlagReasons
        for reason in FlagReason:
            title, desc = FLAG_DESCRIPTIONS.get(reason.value, (reason.value, ""))
            self.fields[f"sev_{reason.value}"] = forms.ChoiceField(
                label=title,
                help_text=desc,
                choices=SEVERITY_CHOICES,
            )

    @classmethod
    def initial_from(cls, cfg: dict[str, Any]) -> dict[str, Any]:
        initial = super().initial_from(cfg)
        f, r = cfg["filters"], cfg["run"]
        bands = cfg["ranking"]["tolerance_bands"]
        initial["output_dir"] = str(r["output_dir"])
        initial["gla_bracket_inclusive"] = bool(f["gla_bracket_inclusive"])
        initial["lot_bracket_inclusive"] = bool(f["lot_bracket_inclusive"])
        initial["required_features"] = kv_dict_to_text(f.get("required_features") or {})
        initial["band_distance_miles"] = bands["distance_miles"]
        initial["band_gla_pct"] = bands["gla_pct"]
        initial["band_age_years"] = bands["age_years"]
        initial["band_lot_pct"] = bands["lot_pct"]
        initial["band_beds_count"] = bands["beds_count"]
        initial["band_baths_count"] = bands["baths_count"]
        initial["noise_words"] = ", ".join(cfg["matching"]["noise_words"])
        initial["subdivision_aliases"] = aliases_to_text(cfg.get("subdivision_aliases") or {})
        initial["date_formats"] = ", ".join(cfg["ingest"]["date_formats"])
        col_map = cfg.get("column_mapping") or {}
        for std_field in STANDARD_FIELDS:
            initial[f"map_{std_field}"] = ", ".join(col_map.get(std_field, []))
        sev = cfg.get("severity") or {}
        for reason in FlagReason:
            initial[f"sev_{reason.value}"] = sev.get(reason.value, "REVIEW")
        return initial

    def clean_required_features(self) -> dict[str, str]:
        return text_to_kv_dict(self.cleaned_data.get("required_features", ""))

    def clean_subdivision_aliases(self) -> dict[str, list[str]]:
        return text_to_aliases(self.cleaned_data.get("subdivision_aliases", ""))

    def clean_date_formats(self) -> list[str]:
        fmts = _words(self.cleaned_data.get("date_formats", ""))
        if not fmts:
            raise forms.ValidationError("Provide at least one date format (e.g. %Y-%m-%d).")
        return fmts

    def mapping_rows(self) -> list[dict[str, Any]]:
        """Helper for rendering column mapping rows in the template."""
        rows = []
        for std_field in STANDARD_FIELDS:
            title, desc = FIELD_LABELS.get(std_field, (std_field, ""))
            rows.append(
                {
                    "code": std_field,
                    "title": title,
                    "desc": desc,
                    "field": self[f"map_{std_field}"],
                }
            )
        return rows

    def severity_rows(self) -> list[dict[str, Any]]:
        """Helper for rendering flag severity rows in the template."""
        rows = []
        for reason in FlagReason:
            title, desc = FLAG_DESCRIPTIONS.get(reason.value, (reason.value, ""))
            rows.append(
                {
                    "code": reason.value,
                    "title": title,
                    "desc": desc,
                    "field": self[f"sev_{reason.value}"],
                }
            )
        return rows

    def apply_to(self, cfg: dict[str, Any]) -> dict[str, Any]:
        cfg = super().apply_to(cfg)
        d = self.cleaned_data
        cfg["run"]["output_dir"] = d["output_dir"].strip()
        cfg["filters"]["gla_bracket_inclusive"] = bool(d["gla_bracket_inclusive"])
        cfg["filters"]["lot_bracket_inclusive"] = bool(d["lot_bracket_inclusive"])
        cfg["filters"]["required_features"] = d["required_features"]
        cfg["ranking"]["tolerance_bands"] = {
            "distance_miles": d["band_distance_miles"],
            "gla_pct": d["band_gla_pct"],
            "age_years": d["band_age_years"],
            "lot_pct": d["band_lot_pct"],
            "beds_count": d["band_beds_count"],
            "baths_count": d["band_baths_count"],
        }
        cfg["matching"]["noise_words"] = _words(d.get("noise_words", ""))
        cfg["subdivision_aliases"] = d["subdivision_aliases"]
        cfg["ingest"]["date_formats"] = d["date_formats"]
        col_map: dict[str, list[str]] = {}
        for std_field in STANDARD_FIELDS:
            col_map[std_field] = _words(d.get(f"map_{std_field}", ""))
        cfg["column_mapping"] = col_map
        sev: dict[str, str] = {}
        for reason in FlagReason:
            sev[reason.value] = d[f"sev_{reason.value}"]
        cfg["severity"] = sev
        return cfg
