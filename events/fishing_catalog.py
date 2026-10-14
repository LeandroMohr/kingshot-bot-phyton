"""Fishing reference data and account-specific collection planning."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import config

HANDBOOK_URL = "https://kingshotmastery.com/tools/fishing-handbook"
CATEGORIES = {"Catches", "Memorabilia", "Mermaids", "Ocean Chests"}
SEASONS = {"spring": 2, "summer": 3, "autumn": 4, "winter": 1}


def parse_catalog(source: str) -> list[dict]:
    if source.lstrip().startswith("["):
        entries = json.loads(source)
    else:
        entries = None
        for match in re.finditer(r"JSON\.parse\('((?:\\.|[^'\\])*)'\)", source):
            literal = re.sub(r"\\([\\'])", r"\1", match.group(1))
            candidate = json.loads(literal)
            if (isinstance(candidate, list) and candidate
                    and isinstance(candidate[0], dict)
                    and candidate[0].get("category") in CATEGORIES):
                entries = candidate
                break
        if entries is None:
            raise ValueError("No fishing dataset found in the supplied source.")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Fishing dataset must be a nonempty list.")
    identifiers = set()
    for entry in entries:
        if entry["category"] not in CATEGORIES:
            raise ValueError("Unknown fishing category.")
        for field in ("id", "star", "points", "sellPrice", "depth"):
            if (field in ("star", "points", "sellPrice") and entry[field] is None
                    and entry["category"] in ("Mermaids", "Ocean Chests")):
                continue
            if type(entry[field]) is not int or entry[field] < 0:
                raise ValueError(f"Invalid fishing field: {field}")
        if entry["id"] in identifiers:
            raise ValueError("Duplicate fishing entry ID.")
        identifiers.add(entry["id"])
        if not entry["name"] or not entry["image"] or not entry["seasons"]:
            raise ValueError("Missing name, image or seasons.")
        if any(season not in SEASONS.values() for season in entry["seasons"]):
            raise ValueError("Unknown fishing season.")
    return entries


def download_catalog(source_url: str) -> list[dict]:
    request = Request(source_url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        return parse_catalog(response.read().decode("utf-8"))


def plan_collection(entries: list[dict], collection: dict, season: str,
                    max_depth: int, include_unavailable: bool = False) -> list[dict]:
    if max_depth <= 0:
        raise ValueError("Line depth must be positive.")
    season_id = SEASONS[season.lower()]
    result = []
    for entry in entries:
        available_now = season_id in entry["seasons"]
        if not available_now and not include_unavailable:
            continue
        captured = collection.get(str(entry["id"]), {}).get("captured")
        if captured is not None and type(captured) is not bool:
            raise ValueError("Captured state must be true, false or null.")
        result.append({
            **entry,
            "image_url": urljoin(HANDBOOK_URL, entry["image"]),
            "available_seasons": [name for name, identifier in SEASONS.items()
                                  if identifier in entry["seasons"]],
            "event_season": season.lower(),
            "available_now": available_now,
            "awaiting_seasons": ([] if available_now else
                                 [name for name, identifier in SEASONS.items()
                                  if identifier in entry["seasons"]]),
            "capture_status": ("captured" if captured is True else
                               "missing" if captured is False else "unknown"),
            "reachable": entry["depth"] <= max_depth,
            "eligible_now": available_now and entry["depth"] <= max_depth,
        })
    return sorted(result, key=lambda entry: (
        not entry["available_now"],
        not entry["reachable"],
        {"missing": 0, "unknown": 1, "captured": 2}[entry["capture_status"]],
        -(entry["points"] or 0), entry["depth"], entry["name"],
    ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", help="Handbook JavaScript dataset URL")
    parser.add_argument("--source", type=Path, help="Exported JSON or JavaScript dataset")
    parser.add_argument("--catalog", type=Path, default=config.BASE_DIR / "knowledge/fishing_catalog.json")
    parser.add_argument("--collection", type=Path, help="Account collection JSON with an entries mapping")
    parser.add_argument("--season", choices=SEASONS, required=True,
                        help="Season shown when the current event starts; no calendar is assumed")
    parser.add_argument("--max-depth", type=int, default=250)
    parser.add_argument("--current-season-only", action="store_true",
                        help="Exclude entries that must wait for another season")
    parser.add_argument("--output", type=Path, help="Write the planned collection as JSON")
    args = parser.parse_args()
    if args.source and args.source_url:
        parser.error("Choose --source or --source-url, not both.")
    if args.source or args.source_url:
        entries = (parse_catalog(args.source.read_text(encoding="utf-8"))
                   if args.source else download_catalog(args.source_url))
        catalog = {"source": HANDBOOK_URL, "season_ids": SEASONS, "entries": entries}
        args.catalog.parent.mkdir(parents=True, exist_ok=True)
        args.catalog.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    else:
        entries = json.loads(args.catalog.read_text(encoding="utf-8"))["entries"]
    collection = (json.loads(args.collection.read_text(encoding="utf-8"))["entries"]
                  if args.collection else {})
    planned = plan_collection(entries, collection, args.season, args.max_depth,
                              include_unavailable=not args.current_season_only)
    for category in sorted(CATEGORIES):
        subset = [entry for entry in planned if entry["category"] == category
                  and entry["available_now"]]
        print(f"{category}: {len(subset)} seasonal entries; "
              f"{sum(entry['reachable'] for entry in subset)} within line depth")
    waiting = [entry for entry in planned if not entry["available_now"]
               and entry["capture_status"] != "captured"]
    print(f"Awaiting another season: {len(waiting)} missing or unverified entries")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(planned, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()