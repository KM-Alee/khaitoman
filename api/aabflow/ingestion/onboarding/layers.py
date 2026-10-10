"""Layer reads for one intake. Paths stay inside that intake's workdir."""

from __future__ import annotations

from pathlib import Path

from ..common import read_json

LAYER_IDS = (
    "aoi",
    "imagery",
    "canals",
    "fields-raw",
    "fields-proposed",
    "terrain",
    "weather",
)

_VECTORS = {
    "canals": "processed/canals.geojson",
    "fields-raw": "processed/fields_raw.geojson",
    "fields-proposed": "processed/fields_proposed.geojson",
}


class LayerError(ValueError):
    def __init__(self, detail: str, fields: dict[str, str] | None = None, *, missing: bool = False):
        super().__init__(detail)
        self.detail = detail
        self.fields = fields or {}
        self.missing = missing


def reject_layer_id(layer_id: str) -> None:
    if (
        not layer_id
        or "/" in layer_id
        or "\\" in layer_id
        or ".." in layer_id
        or layer_id.startswith(".")
    ):
        raise LayerError("layer path traversal is rejected", {"layer_id": "path traversal"})
    if layer_id not in LAYER_IDS:
        raise LayerError(f"unknown layer {layer_id!r}", {"layer_id": layer_id})


def _inside(workdir: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(workdir.resolve())
    except ValueError:
        return False
    return path.resolve().is_file() and not path.is_symlink()


def _present(workdir: Path, layer_id: str) -> bool:
    if layer_id == "imagery":
        folder = workdir / "processed" / "imagery"
        return folder.is_dir() and any(
            _inside(workdir, path)
            for path in folder.glob("*.json")
            if path.name != "delineate_input.json"
        )
    if layer_id == "weather":
        return _inside(workdir, workdir / "processed" / "process_result.json")
    if layer_id == "terrain":
        return _inside(workdir, workdir / "processed" / "terrain" / "dem.json")
    rel = _VECTORS.get(layer_id)
    return rel is not None and _inside(workdir, workdir / rel)


def list_layers(workdir: Path, intake: dict) -> dict:
    available = ["aoi"]
    unavailable: list[dict[str, str]] = []
    for layer_id in LAYER_IDS:
        if layer_id == "aoi":
            continue
        if _present(workdir, layer_id):
            available.append(layer_id)
        else:
            unavailable.append(
                {"id": layer_id, "reason": "not available until processing writes it"}
            )
    return {
        "onboarding_id": intake.get("intake_id"),
        "state": intake.get("state"),
        "available": available,
        "unavailable": unavailable,
    }


def read_layer(workdir: Path, intake: dict, layer_id: str) -> dict:
    reject_layer_id(layer_id)
    workdir = Path(workdir)
    if layer_id == "aoi":
        return {"layer_id": "aoi", "geojson": intake.get("aoi"), "source": "intake"}
    if not _present(workdir, layer_id):
        raise LayerError(
            f"{layer_id} is not available yet",
            {"layer_id": layer_id},
            missing=True,
        )
    if layer_id == "imagery":
        scenes = []
        for path in sorted((workdir / "processed" / "imagery").glob("*.json")):
            if path.name == "delineate_input.json" or not _inside(workdir, path):
                continue
            scenes.append(read_json(path))
        return {"layer_id": "imagery", "scenes": scenes}
    if layer_id == "weather":
        weather = read_json(workdir / "processed" / "process_result.json").get("weather")
        if not weather:
            raise LayerError("weather is not available yet", {"layer_id": "weather"}, missing=True)
        return {"layer_id": "weather", "weather": weather}
    if layer_id == "terrain":
        return {
            "layer_id": "terrain",
            "metadata": read_json(workdir / "processed" / "terrain" / "dem.json"),
        }
    return {"layer_id": layer_id, "geojson": read_json(workdir / _VECTORS[layer_id])}
