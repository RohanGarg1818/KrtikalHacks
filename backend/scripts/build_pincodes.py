"""Build data/pincodes_ncr.csv: every Delhi pincode plus the NCR city pincodes.

Run from backend/ (takes ~4 minutes: OpenStreetMap allows one request a second):

    python -m scripts.build_pincodes /path/to/geonames/IN.txt

Sources
- Pincode list and area names: GeoNames postal codes for India
  (https://download.geonames.org/export/zip/IN.zip, CC BY 4.0).
- Coordinates: OpenStreetMap Nominatim (© OpenStreetMap contributors, ODbL).
  GeoNames coordinates for Delhi are district centroids (many pincodes share
  one point, up to 16 km off), so they are not used.

Pincodes already in the CSV keep their curated name and position.
"""

from __future__ import annotations

import csv
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "data" / "pincodes_ncr.csv"
LEGACY = Path(__file__).resolve().parents[1] / "data" / "pincodes_delhi.csv"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ShelfSense/1.0 (hackathon pincode catalogue; one-off build)"
# Delhi-NCR bounding box: anything outside is a geocoding miss.
LAT_RANGE, LNG_RANGE = (28.20, 28.95), (76.80, 77.65)
# (state, district, pincode prefix) -> city label
NCR = [
    ("Haryana", "Gurgaon", "1220", "Gurugram"),
    ("Haryana", "Faridabad", "1210", "Faridabad"),
    ("Uttar Pradesh", "Gautam Buddha Nagar", "2013", "Noida"),
    ("Uttar Pradesh", "Ghaziabad", "2010", "Ghaziabad"),
]
GREATER_NOIDA = re.compile(r"greater noida|knowledge park|kasna|surajpur|dadri|alpha|beta|gamma|delta", re.IGNORECASE)
NOT_A_LOCALITY = re.compile(
    r"\b(h\.?o|s\.?o|b\.?o|extn?|extension|counter|postal|sb|court|bhawan|secretariat|"
    r"complex|camp|hospital|university|institute|college|office|police|airport|cantt|"
    r"station|indl|industrial estate|sector-?\s*\d+\s*$)\b",
    re.IGNORECASE,
)


INSTITUTION = re.compile(r"commission|foreign post|parliament|rashtrapati|president|\bibc\b|secretariat", re.IGNORECASE)


# Well-known area names where the post-office name would confuse sellers.
AREA_NAMES = {
    "110002": "Daryaganj", "110006": "Chandni Chowk", "110009": "Model Town", "110010": "Delhi Cantt",
    "110012": "Pusa", "110013": "Nizamuddin", "110027": "Rajouri Garden", "110031": "Gandhi Nagar",
    "110033": "Jahangirpuri", "110034": "Pitampura", "110039": "Bawana", "110040": "Narela",
    "110043": "Najafgarh", "110044": "Badarpur", "110047": "Chhatarpur", "110051": "Krishna Nagar",
    "110052": "Ashok Vihar", "110055": "Paharganj", "110062": "Dakshinpuri", "110067": "JNU",
    "110068": "IGNOU, Maidan Garhi", "110075": "Dwarka", "110076": "Sarita Vihar", "110085": "Rohini Sector 11",
    "110088": "Shalimar Bagh", "110091": "Mayur Vihar Phase 1", "110092": "Laxmi Nagar",
    "110095": "Dilshad Garden", "110096": "Mayur Vihar Phase 3",
    "121001": "NIT Faridabad", "121007": "Escorts Nagar", "121008": "Faridabad Sector 29",
    "121012": "Faridabad Sector 21D", "121013": "Faridabad Sector 91", "121015": "Faridabad Sector 55",
    "201010": "Sahibabad", "201014": "Indirapuram", "201301": "Noida Sector 18",
    "201313": "Noida Sector 125", "201318": "Greater Noida Sector 1",
    "122001": "Gurugram City", "122002": "DLF Qutab Enclave", "122007": "Udyog Vihar",
    "122015": "Palam Vihar", "122016": "Dundahera",
}


def pick_area(names: list[str]) -> str:
    """The most locality-like name among a pincode's post offices."""
    cleaned = [re.sub(r"\s+", " ", n).strip(" .-") for n in names]
    good = [n for n in cleaned if not NOT_A_LOCALITY.search(n)] or cleaned
    # Prefer names shared with other offices of the pincode ("Saket", "Saket Bazar").
    good.sort(key=lambda n: (-sum(n.split()[0].lower() in other.lower() for other in cleaned), len(n)))
    return good[0].title() if good[0].islower() or good[0].isupper() else good[0]


def candidates(geonames: Path) -> dict[str, tuple[str, str]]:
    """code -> (area, city)."""
    names: dict[str, list[str]] = defaultdict(list)
    city_of: dict[str, str] = {}
    with geonames.open(encoding="utf-8") as fh:
        for row in csv.reader(fh, delimiter="\t"):
            state, district, code, place = row[3], row[5], row[1], row[2]
            if state.lower() == "delhi" and code.startswith("110"):
                city = "Delhi"
            else:
                city = next(
                    (label for st, dist, prefix, label in NCR if state == st and district == dist and code.startswith(prefix)),
                    None,
                )
            if city is None:
                continue
            names[code].append(place)
            if city == "Noida" and GREATER_NOIDA.search(place):
                city = "Greater Noida"
            city_of[code] = city_of.get(code) if city_of.get(code) == "Greater Noida" else city
    picked = {code: (pick_area(places), city_of[code]) for code, places in names.items()}
    # Special (non-delivery) pincodes: foreign post, government offices.
    return {
        code: value
        for code, value in picked.items()
        if not (code.startswith("110") and int(code) > 110097) and not INSTITUTION.search(value[0])
    }


def in_ncr(lat: float, lng: float) -> bool:
    return LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LNG_RANGE[0] <= lng <= LNG_RANGE[1]


def geocode(client: httpx.Client, code: str, area: str, city: str) -> tuple[float, float] | None:
    for params in ({"postalcode": code}, {"q": f"{area}, {city}"}):
        time.sleep(1.1)  # Nominatim usage policy: at most one request per second
        try:
            hits = client.get(
                NOMINATIM, params={**params, "format": "jsonv2", "limit": 1, "countrycodes": "in"}
            ).json()
        except (httpx.HTTPError, ValueError):
            continue
        if hits:
            lat, lng = round(float(hits[0]["lat"]), 4), round(float(hits[0]["lon"]), 4)
            if in_ncr(lat, lng):
                return lat, lng
    return None


def main(geonames: Path) -> None:
    curated = {}
    for path in (OUT, LEGACY):
        if path.exists():
            curated.update({row["code"]: row for row in csv.DictReader(path.open(encoding="utf-8"))})
    found = candidates(geonames)
    rows, skipped = [], []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for code in sorted(set(found) | set(curated)):
            if code in curated:
                rows.append(curated[code])
                continue
            area, city = found[code]
            point = geocode(client, code, area, city)
            if point is None:
                skipped.append(code)
                continue
            rows.append({"code": code, "area_name": area, "city": city, "lat": point[0], "lng": point[1]})
            print(f"{code} {area} ({city}) {point}", flush=True)
    for row in rows:
        row["area_name"] = AREA_NAMES.get(row["code"], row["area_name"])
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["code", "area_name", "city", "lat", "lng"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["city"] != "Delhi", r["city"], r["code"])))
    print(f"\nWrote {len(rows)} pincodes to {OUT}; skipped (no location found): {skipped or 'none'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
