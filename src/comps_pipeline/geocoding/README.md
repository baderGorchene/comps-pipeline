# geocoding

## Purpose
Provide coordinates when the MLS CSV has addresses but no latitude/longitude.

## Status
PLACEHOLDER. Only `base.py` exists (interface, no implementation).

## Waiting on
Sam's real CSV, to confirm whether coordinates are included.

## Planned design
County GIS data first if available, otherwise a geocoding API (track cost and accuracy). Cache every result locally. Confidence below a configured threshold -> `NO_COORDINATES` flag, never a guess.

## Interface
`Geocoder.geocode(address: str) -> GeoResult(lat, lon, confidence) | None`
