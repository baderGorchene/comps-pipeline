import math

from comps_pipeline.config.schema import Settings
from comps_pipeline.models import (
    AuditEntry,
    Cell,
    Decision,
    FlagReason,
    Source,
    StageOutput,
    Subject,
)
from comps_pipeline.models.comp import Comp

STAGE = "geo"
EARTH_RADIUS_MILES = 3958.8  # mean Earth radius, a physical constant


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def compute_distances(comps: list[Comp], subject: Subject, settings: Settings) -> StageOutput:
    """Distance to the subject: haversine when both sides have coordinates, else the MLS
    export's own Distance column, else null + NO_COORDINATES (never a guess).
    Whether unknown-distance comps are dropped is decided by filters.missing_distance."""
    out = StageOutput()
    subject_coords = subject.latitude is not None and subject.longitude is not None
    for comp in comps:
        lat, lon = comp.latitude.value, comp.longitude.value
        reported = comp.reported_distance_miles.value
        if subject_coords and lat is not None and lon is not None:
            miles = haversine_miles(subject.latitude, subject.longitude, lat, lon)
            cell = Cell(value=miles, source=Source.COMPUTED)
        elif reported is not None:
            cell = Cell(value=reported, source=Source.MLS, note="distance reported by the MLS")
        else:
            msg = "no coordinates and no reported distance; distance unknown"
            out.flags.append(
                settings.flag(FlagReason.NO_COORDINATES, comp.mls_number, msg, "distance_miles")
            )
            out.audit.append(
                AuditEntry(
                    mls_number=comp.mls_number,
                    stage=STAGE,
                    decision=Decision.FLAGGED,
                    rule=FlagReason.NO_COORDINATES.value,
                    detail={"message": msg},
                )
            )
            cell = Cell(source=Source.NONE, flag=FlagReason.NO_COORDINATES, note=msg)
        out.comps.append(comp.model_copy(update={"distance_miles": cell}))
    return out
