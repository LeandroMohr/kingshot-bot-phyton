"""Export labeled handbook crops, separate from calibrated gameplay templates."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import cv2
import numpy as np

import config
from events.fishing_catalog import SEASONS


CATEGORY_FOLDERS = {
    "Catches": "fish",
    "Memorabilia": "objects",
    "Mermaids": "mermaids",
    "Ocean Chests": "chests",
}
CDN_URL = "https://cdn.kingshotmastery.com/"


def crop_card(image: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    if image is None or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("Expected a color handbook card.")
    height, width = image.shape[:2]
    if height < 100 or width < 80:
        raise ValueError("Handbook card is too small for a reference crop.")
    left, top = round(width * .02), round(height * .20)
    right, bottom = round(width * .98), round(height * .73)
    return image[top:bottom, left:right].copy(), (left, top, right, bottom)


def export_reference(entry: dict, image: np.ndarray, output: Path,
                     collection: dict) -> dict:
    crop, bounds = crop_card(image)
    relative = Path(CATEGORY_FOLDERS[entry["category"]]) / f'{entry["id"]}_{entry["slug"]}.png'
    destination = output / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), crop):
        raise OSError(f"Could not write reference: {destination}")
    captured = collection.get(str(entry["id"]), {}).get("captured")
    if captured is not None and type(captured) is not bool:
        raise ValueError("Captured state must be true, false or null.")
    return {
        "id": entry["id"],
        "name": entry["name"],
        "category": entry["category"],
        "file": relative.as_posix(),
        "points": entry["points"],
        "depth": entry["depth"],
        "available_seasons": [name for name, identifier in SEASONS.items()
                              if identifier in entry["seasons"]],
        "capture_status": ("captured" if captured is True else
                           "missing" if captured is False else "unknown"),
        "source_url": urljoin(CDN_URL, entry["image"]),
        "source_size": [image.shape[1], image.shape[0]],
        "crop_bounds": list(bounds),
        "calibrated_for_gameplay": False,
        "background_removed": False,
    }


def download_card(entry: dict, cache: Path) -> np.ndarray:
    destination = cache / f'{entry["id"]}_{entry["slug"]}.webp'
    if not destination.exists():
        request = Request(urljoin(CDN_URL, entry["image"]),
                          headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            content = response.read()
        image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_UNCHANGED)
        crop_card(image)
        cache.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return image
    image = cv2.imread(str(destination), cv2.IMREAD_UNCHANGED)
    crop_card(image)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path,
                        default=config.BASE_DIR / "knowledge/fishing_catalog.json")
    parser.add_argument("--collection", type=Path,
                        default=config.BASE_DIR / "memory/fishing_collection_5555.json")
    parser.add_argument("--output", type=Path,
                        default=config.BASE_DIR / "templates/fishing_references")
    parser.add_argument("--names", nargs="+", help="Export only these exact specimen names")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    collection = json.loads(args.collection.read_text(encoding="utf-8"))["entries"]
    entries = catalog["entries"]
    if args.names:
        requested = set(args.names)
        entries = [entry for entry in entries if entry["name"] in requested]
        missing = requested - {entry["name"] for entry in entries}
        if missing:
            parser.error(f"Unknown specimen names: {sorted(missing)}")
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "cards"

    def export(entry: dict) -> dict:
        return export_reference(entry, download_card(entry, cache), args.output, collection)

    with ThreadPoolExecutor(max_workers=4) as pool:
        references = list(pool.map(export, entries))
    manifest = {
        "source": catalog["source"],
        "reference_type": "handbook_artwork",
        "calibrated_for_gameplay": False,
        "background_removed": False,
        "entries": references,
    }
    (args.output / "index.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(references)} labeled references to {args.output}")


if __name__ == "__main__":
    main()