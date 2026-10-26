"""Generate a synthetic Texas-style MLS export around one subject property.

Usage: uv run python scripts/generate_synthetic.py --rows 300 --seed 42 --out data/samples
Same seed -> byte-identical files. Edge cases are planted on purpose (see SPECIALS).
"""

import argparse
import csv
import datetime as dt
import math
import random
from pathlib import Path

EFFECTIVE_DATE = dt.date(2026, 10, 1)
SUBJECT = {
    "address": "1708 Hidden Glen Dr, Round Rock, TX 78681",
    "latitude": 30.508300,
    "longitude": -97.678900,
    "living_area": 2000,
    "year_built": 2005,
    "lot_size_sqft": 7800,
    "subdivision": "Brushy Creek Phase 2",
    "foundation_type": "Slab",
    "bedrooms": 3,
    "baths_full": 2,
    "baths_half": 1,
}
HEADERS = [
    "MLS #", "Status", "Address", "List Price", "Close Price", "Close Date", "SqFt Living",
    "Year Built", "Lot SqFt", "Subdivision", "Latitude", "Longitude", "Foundation",
    "Public Remarks", "Beds", "Baths Full", "Baths Half", "Pool",
]  # fmt: skip
# Share of generated rows that are current listings, and that are expired (excluded).
LISTING_STATUSES = ["Active", "Pending", "Option Pending"]
LISTING_SHARE, EXPIRED_SHARE = 0.06, 0.02
SUBJECT_VARIANTS = [
    "Brushy Creek Phase 2", "BRUSHY CREEK PHASE 2", "Brushy Creek Ph 2", "Brushy Creek Ph. 2",
    "Brushy Creek Phase II",
]  # fmt: skip
NEIGHBOR_PHASES = ["Brushy Creek Phase 1", "Brushy Creek Phase 3"]
OTHER_SUBDIVISIONS = [
    "Forest Creek",
    "Teravista",
    "Behrens Ranch",
    "Vista Oaks",
    "Highland Horizon",
]
STREETS = [
    "Hidden Glen Dr", "Creek Bend Blvd", "Live Oak Ln", "Pecan Hollow", "Bluebonnet Trl",
    "Mesquite Ridge", "Cypress Cove", "Limestone Way", "Prairie Clover Dr", "Cedar Elm Ct",
]  # fmt: skip
ORDINARY_REMARKS = [
    "Well maintained single story home on a quiet street. Open floor plan, granite counters.",
    "Two story home with game room upstairs. Covered patio and mature shade trees.",
    "Move-in ready. New HVAC in 2021, fresh interior paint, wood-look tile throughout.",
    "Corner lot with oversized backyard. Walk to neighborhood park and elementary school.",
    "Light and bright living room with fireplace. Primary suite down, three beds up.",
    "Original owner home, carefully kept. Roof replaced 2020. Close to shopping and 45 toll.",
    "Spacious kitchen with island and breakfast nook. Sprinkler system, privacy fence.",
    "",
]


def offset(lat: float, lon: float, miles: float, bearing_deg: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    dlat = miles / 69.0 * math.cos(b)
    dlon = miles / (69.0 * math.cos(math.radians(lat))) * math.sin(b)
    return round(lat + dlat, 6), round(lon + dlon, 6)


def money(rng: random.Random, value: int) -> str:
    style = rng.random()
    if style < 0.8:
        return f"${value:,}"
    if style < 0.9:
        return f"${value:,}.00"
    return str(value)


def base_row(rng: random.Random, mls: str) -> dict[str, str]:
    roll = rng.random()
    if roll < 0.55:
        subdivision, miles = rng.choice(SUBJECT_VARIANTS), rng.uniform(0.05, 0.95)
        year = rng.randint(1998, 2014)
    elif roll < 0.65:
        subdivision, miles = rng.choice(NEIGHBOR_PHASES), rng.uniform(0.2, 1.2)
        year = rng.randint(1996, 2012)
    else:
        subdivision, miles = rng.choice(OTHER_SUBDIVISIONS), rng.uniform(0.4, 2.8)
        year = rng.randint(1985, 2022)
    gla = rng.randint(1500, 2500) if rng.random() < 0.85 else rng.randint(1000, 3400)
    days_ago = rng.randint(5, 335) if rng.random() < 0.92 else rng.randint(380, 720)
    lat, lon = offset(SUBJECT["latitude"], SUBJECT["longitude"], miles, rng.uniform(0, 360))
    price = round(gla * rng.uniform(165, 215) / 500) * 500
    return {
        "MLS #": mls,
        "Status": "Closed",
        "Address": f"{rng.randint(100, 4999)} {rng.choice(STREETS)}, Round Rock, TX 78681",
        "List Price": money(rng, round(price * 1.02 / 500) * 500),
        "Close Price": money(rng, price),
        "Close Date": (EFFECTIVE_DATE - dt.timedelta(days=days_ago)).strftime("%m/%d/%Y"),
        "SqFt Living": f"{gla:,}" if rng.random() < 0.3 else str(gla),
        "Year Built": str(year),
        "Lot SqFt": str(rng.randint(5800, 11500)),
        "Subdivision": subdivision,
        "Latitude": f"{lat:.6f}",
        "Longitude": f"{lon:.6f}",
        "Foundation": "Slab" if rng.random() < 0.85 else "Pier & Beam",
        "Public Remarks": rng.choice(ORDINARY_REMARKS),
        "Beds": str(rng.randint(2, 5)),
        "Baths Full": str(rng.randint(2, 3)),
        "Baths Half": str(rng.randint(0, 1)),
        "Pool": "Y" if rng.random() < 0.2 else "N",
    }


# Each special overrides fields of a "near twin of the subject" row.
SPECIALS: list[dict[str, str]] = [
    {"SqFt Living": "1500", "Public Remarks": "GLA exactly 25% below subject."},
    {"SqFt Living": "1499", "Public Remarks": "GLA 1 sqft beyond the lower 25% boundary."},
    {"SqFt Living": "2500", "Public Remarks": "GLA exactly 25% above subject."},
    {"SqFt Living": "2,501", "Public Remarks": "GLA 1 sqft beyond the upper 25% boundary."},
    {"Subdivision": "brushy creek phase 2"},
    {"Subdivision": "Brushy Creek Ph 2"},
    {"Subdivision": "Brushy Creek Phase II"},
    {"Subdivision": "Brushy Crek Phase 2"},  # typo
    {"Subdivision": "Brushy Creek Phase 3"},  # different phase number
    {"SqFt Living": ""},  # missing GLA
    {"SqFt Living": "0"},  # zero GLA
    {"Latitude": "", "Longitude": ""},  # missing coordinates
    {"Close Date": (EFFECTIVE_DATE + dt.timedelta(days=20)).strftime("%m/%d/%Y")},  # future
    {"Close Date": (EFFECTIVE_DATE - dt.timedelta(days=500)).strftime("%m/%d/%Y")},  # old
    {"Public Remarks": "Estate sale, sold as-is. Bring your contractor and your ideas."},
    {"Public Remarks": "Sold to family member prior to marketing. Updated baths in 2019."},
    {"Public Remarks": "Investor special! Needs paint, carpet and some TLC. Cash or conventional."},
    {"Public Remarks": "Fully renovated 2023: new kitchen, quartz counters, new roof and windows."},
    {"Close Price": "$389,900", "Public Remarks": "Seller paid closing costs. Clean and bright."},
    {"Status": "Active", "Close Price": "", "Close Date": ""},  # listing, near twin
    {"Status": "Pending", "Close Price": "", "Close Date": ""},
    {"Status": "Expired", "Close Price": "", "Close Date": ""},  # excluded by status
    {"Status": "", "Public Remarks": "Status left blank."},  # excluded by status
]
DUPLICATE_OF = [4, 14]  # indexes into SPECIALS whose MLS number is reused later


def near_twin(rng: random.Random, mls: str) -> dict[str, str]:
    row = base_row(rng, mls)
    lat, lon = offset(
        SUBJECT["latitude"], SUBJECT["longitude"], rng.uniform(0.04, 0.2), rng.uniform(0, 360)
    )
    row.update(
        {
            "Subdivision": "Brushy Creek Phase 2",
            "SqFt Living": str(rng.randint(1960, 2040)),
            "Year Built": str(rng.randint(2004, 2006)),
            "Lot SqFt": str(rng.randint(7500, 8100)),
            "Latitude": f"{lat:.6f}",
            "Longitude": f"{lon:.6f}",
            "Close Date": (EFFECTIVE_DATE - dt.timedelta(days=rng.randint(10, 200))).strftime(
                "%m/%d/%Y"
            ),
        }
    )
    return row


def generate(rows: int, seed: int) -> list[dict[str, str]]:
    if rows < len(SPECIALS) + len(DUPLICATE_OF):
        raise ValueError(f"--rows must be at least {len(SPECIALS) + len(DUPLICATE_OF)}")
    rng = random.Random(seed)
    mls_numbers = [str(n) for n in rng.sample(range(1_000_000, 9_999_999), rows)]
    out = []
    for i, special in enumerate(SPECIALS):
        row = near_twin(rng, mls_numbers[i])
        row.update(special)
        out.append(row)
    for i in range(len(SPECIALS), rows - len(DUPLICATE_OF)):
        row, roll = base_row(rng, mls_numbers[i]), rng.random()
        if roll < LISTING_SHARE + EXPIRED_SHARE:
            status = rng.choice(LISTING_STATUSES) if roll < LISTING_SHARE else "Expired"
            row.update({"Status": status, "Close Price": "", "Close Date": ""})
        out.append(row)
    rng.shuffle(out)
    for idx in DUPLICATE_OF:  # appended last so the original is always the first occurrence
        dup = base_row(rng, mls_numbers[idx])
        dup["Public Remarks"] = "Duplicate listing entry."
        out.append(dup)
    return out


def subject_yaml() -> str:
    s = SUBJECT
    return (
        "# Subject property for the synthetic sample (scripts/generate_synthetic.py).\n"
        f'address: "{s["address"]}"\n'
        f"latitude: {s['latitude']:.6f}\n"
        f"longitude: {s['longitude']:.6f}\n"
        f"living_area: {s['living_area']}\n"
        f"year_built: {s['year_built']}\n"
        f"lot_size_sqft: {s['lot_size_sqft']}\n"
        f'subdivision: "{s["subdivision"]}"\n'
        f'foundation_type: "{s["foundation_type"]}"\n'
        f"bedrooms: {s['bedrooms']}\n"
        f"baths_full: {s['baths_full']}\n"
        f"baths_half: {s['baths_half']}\n"
        f"effective_date: {EFFECTIVE_DATE.isoformat()}\n"
        "extras: {}\n"
    )


def write(rows: int, seed: int, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    csv_path, subject_path = out / "mls_sample.csv", out / "subject.yaml"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(generate(rows, seed))
    subject_path.write_text(subject_yaml(), encoding="utf-8", newline="\n")
    return csv_path, subject_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/samples"))
    args = parser.parse_args()
    for path in write(args.rows, args.seed, args.out):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
