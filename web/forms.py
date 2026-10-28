"""Forms for one run: the MLS export, the subject property, and the shortlisting rules."""

from typing import Any

import yaml
from django import forms

from comps_pipeline.config.schema import BRACKET_ATTRIBUTES, RANKING_KEYS

MISSING = [("exclude", "Exclude the comp"), ("keep_and_flag", "Keep it and flag it")]
ATTRIBUTE_LABELS = {
    "gla": "Living area",
    "lot": "Lot size",
    "age": "Year built",
    "beds": "Bedrooms",
    "baths": "Baths",
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
            step[key] = yaml.safe_load(value)
        steps.append(step)
    return steps


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
    save_default = forms.BooleanField(label="Save these rules as the default", required=False)

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
        cfg = yaml.safe_load(yaml.safe_dump(cfg))  # deep copy of plain data
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
