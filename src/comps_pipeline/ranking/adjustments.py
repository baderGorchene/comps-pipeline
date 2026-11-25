"""Deterministic UAD 3.6 component adjustments for closing vs. adjusted price analysis."""

import re
import statistics

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import Cell, Comp, Source, StageOutput, Subject

STAGE = "valuation_adjustments"


def _parse_money(raw: str) -> int:
    if not raw:
        return 0
    cleaned = re.sub(r"[^0-9.-]", "", raw)
    if not cleaned:
        return 0
    try:
        return max(0, round(float(cleaned)))
    except ValueError:
        return 0


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _round_to(val: float, step: int) -> int:
    return round(val / step) * step


def resolve_benchmark_price(comps: list[Comp], subject: Subject) -> int | None:
    """Return subject benchmark valuation, or peer-median $/sqft * GLA when omitted."""
    if subject.benchmark_price is not None:
        return subject.benchmark_price
    candidates = [
        c
        for c in comps
        if c.pool == "sold"
        and c.close_price.value is not None
        and c.living_area.value is not None
        and c.living_area.value > 0
        and abs(c.living_area.value - subject.living_area) <= 0.30 * subject.living_area
        and (
            subject.year_built is None
            or c.year_built.value is None
            or abs(c.year_built.value - subject.year_built) <= 15
        )
    ]
    near = [
        c
        for c in candidates
        if c.distance_miles.value is not None and c.distance_miles.value <= 3.0
    ]
    peers = near if len(near) >= 5 else candidates
    if len(peers) < 5:
        return None
    med_ppsf = statistics.median(c.close_price.value / c.living_area.value for c in peers)
    return round(med_ppsf * subject.living_area)


def _comp_base_price(c: Comp) -> int | None:
    if c.pool == "sold" and c.close_price.value is not None:
        return c.close_price.value
    return c.close_price.value or c.list_price.value


def compute_adjustments(
    comps: list[Comp],
    subject: Subject,
    settings: Settings,
    benchmark: int | None = None,
) -> StageOutput:
    """Compute UAD 3.6 component adjustments, adjusted_price, net_adjustment, and gross_adj_%."""
    out = StageOutput()
    v = settings.valuation
    if not v.enabled:
        out.comps = list(comps)
        return out

    bench = benchmark if benchmark is not None else resolve_benchmark_price(comps, subject)
    for c in comps:
        price = _comp_base_price(c)
        gla = c.living_area.value
        if price is None or gla is None or gla <= 0:
            out.comps.append(c)
            continue

        scale = bench or price
        subj_ppsf = scale / subject.living_area
        adjs: list[tuple[str, int]] = []

        if c.pool == "sold":
            raw_conc = c.extra_str("Seller Concession Amount", "Concessions", "Seller Concessions")
            conc = min(round(price * 0.15), _parse_money(raw_conc))
            if conc > 0:
                adjs.append(("Concessions", -conc))

        gla_diff = subject.living_area - gla
        if abs(gla_diff) >= v.gla_deadband_sqft:
            gla_rate = _clamp(subj_ppsf * v.gla_adj_factor, v.min_gla_rate, v.max_gla_rate)
            gla_adj = _round_to(gla_diff * gla_rate, 100)
            if gla_adj:
                adjs.append(("GLA", gla_adj))

        if subject.lot_size_sqft and c.lot_size_sqft.value:
            lot_diff = subject.lot_size_sqft - c.lot_size_sqft.value
            if abs(lot_diff) / subject.lot_size_sqft * 100 > v.lot_deadband_pct:
                lot_rate = _clamp(scale / max(subject.lot_size_sqft, 5000) * 0.12, 1.5, 4.5)
                lot_cap = round(scale * (v.max_lot_adj_pct / 100))
                lot_adj = max(-lot_cap, min(lot_cap, _round_to(lot_diff * lot_rate, 250)))
                if lot_adj:
                    adjs.append(("Lot", lot_adj))

        if subject.bedrooms is not None and c.bedrooms.value is not None:
            bd_diff = subject.bedrooms - c.bedrooms.value
            if bd_diff != 0:
                bed_rate = _round_to(max(v.min_bedroom_adj, scale * v.bedroom_adj_pct), 500)
                adjs.append(("Beds", bd_diff * bed_rate))

        subj_baths = subject.total_baths()
        comp_baths = c.total_baths()
        if subj_baths is not None and comp_baths is not None:
            ba_diff = float(subj_baths - comp_baths)
            if abs(ba_diff) >= 0.5:
                bath_rate = _round_to(max(v.min_full_bath_adj, scale * v.full_bath_adj_pct), 500)
                ba_adj = round(ba_diff * bath_rate)
                if ba_adj:
                    adjs.append(("Baths", ba_adj))

        if subject.garage_spaces is not None:
            g_raw = c.extra_str("Garage Spaces", "Garage", "GarageSpaces", "# Garage Spaces")
            if g_raw:
                try:
                    cg = int(float(g_raw.split()[0]))
                    if cg != subject.garage_spaces:
                        gar_rate = _round_to(max(v.min_garage_adj, scale * v.garage_adj_pct), 500)
                        adjs.append(("Garage", (subject.garage_spaces - cg) * gar_rate))
                except (ValueError, IndexError):
                    pass

        if subject.pool is not None:
            p_raw = c.extra_str("Poolyn", "Pool", "Pool Y/N", "Pool Private YN", "Private Pool")
            if p_raw:
                comp_pool = p_raw.strip().casefold() in {"yes", "y", "true", "1"}
                if comp_pool != subject.pool:
                    pool_amt = _round_to(
                        _clamp(scale * v.pool_adj_pct, v.min_pool_adj, v.max_pool_adj), 500
                    )
                    adjs.append(("Pool", pool_amt if subject.pool else -pool_amt))

        if subject.has_adu is not None:
            comp_adu = bool(c.remarks_signals.get("_has_adu") or c.extras.get("_has_adu"))
            if comp_adu != subject.has_adu:
                adu_amt = _round_to(
                    _clamp(scale * v.adu_adj_pct, v.min_adu_adj, v.max_adu_adj), 500
                )
                adjs.append(("ADU", adu_amt if subject.has_adu else -adu_amt))

        net_adj = sum(amt for _, amt in adjs)
        gross_abs = sum(abs(amt) for _, amt in adjs)
        gross_pct = round(gross_abs / price * 100, 2)
        adj_price = max(1, price + net_adj)
        summary = "; ".join(f"{name} {amt:+,}" for name, amt in adjs) if adjs else "No net adj"
        out.comps.append(
            c.model_copy(
                update={
                    "adjusted_price": Cell(value=adj_price, source=Source.COMPUTED),
                    "net_adjustment": Cell(value=net_adj, source=Source.COMPUTED),
                    "gross_adjustment_pct": Cell(value=gross_pct, source=Source.COMPUTED),
                    "adjustment_summary": summary,
                }
            )
        )
    return out
