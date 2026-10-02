"""Prepare the project's Poly Haven CC0 material maps and indoor HDRIs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scale_bench.config.models.appearance import AppearanceConfig

USER_AGENT = "SCALE-Bench/0.1 (https://github.com/CrysGate/SCALE-Bench)"
API_ROOT = "https://api.polyhaven.com"
LICENSE_URL = "https://polyhaven.com/license"


def _get_json(url: str) -> dict:
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
        return json.load(response)


def _download(file_info: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if digest == file_info["md5"]:
            print(f"Cached: {destination.relative_to(PROJECT_ROOT)}", flush=True)
            return
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        request = Request(file_info["url"], headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
            while chunk := response.read(1024 * 1024):
                stream.write(chunk)
        with temporary.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if temporary.stat().st_size != file_info["size"] or digest != file_info["md5"]:
            raise ValueError(f"Poly Haven checksum/size mismatch: {destination}")
        temporary.replace(destination)
        print(f"Downloaded: {destination.relative_to(PROJECT_ROOT)}", flush=True)
    finally:
        temporary.unlink(missing_ok=True)


def _write_material(asset_id: str, destination: Path) -> None:
    """Generate an OmniPBR MDL beside its downloaded maps for a fresh asset checkout."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f'''// Poly Haven CC0 maps: https://polyhaven.com/a/{asset_id}
mdl 1.4;
import ::OmniPBR::OmniPBR;
import ::tex::gamma_mode;
export material {asset_id}(*) = ::OmniPBR::OmniPBR(
    diffuse_texture: texture_2d("./base_color.jpg", ::tex::gamma_srgb),
    diffuse_tint: color(1.0),
    albedo_brightness: 1.0,
    reflection_roughness_texture_influence: 1.0,
    reflectionroughness_texture: texture_2d("./roughness.jpg", ::tex::gamma_linear),
    metallic_constant: 0.0,
    normalmap_texture: texture_2d("./normal.jpg", ::tex::gamma_linear),
    bump_factor: 1.0,
    project_uvw: false,
    uv_space_index: 0
);
''')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--appearance-config", type=Path,
        default=PROJECT_ROOT / "configs/appearance/polyhaven.yml",
        help="Poly Haven pool; preset names must match Poly Haven asset IDs.",
    )
    args = parser.parse_args()
    # Parse without resolving/checking assets: this command prepares missing files.
    pool = AppearanceConfig.model_validate(yaml.safe_load(args.appearance_config.read_text()))
    assets_root = PROJECT_ROOT / "Assets"
    jobs = []
    manifest = {"provider": "Poly Haven", "license": "CC0-1.0",
                "license_url": LICENSE_URL, "assets": []}
    materials = {preset.name: preset for preset in (*pool.table_materials, *pool.ground_materials)}
    print("Preparing Poly Haven CC0 assets (https://polyhaven.com)", flush=True)
    for asset_id in (*materials, *(preset.name for preset in pool.lighting)):
        info = _get_json(f"{API_ROOT}/info/{asset_id}")
        files = _get_json(f"{API_ROOT}/files/{asset_id}")
        downloaded_files = []
        if asset_id in materials:
            for map_name, filename in (("Diffuse", "base_color.jpg"),
                                       ("nor_gl", "normal.jpg"), ("Rough", "roughness.jpg")):
                file_info = files[map_name]["2k"]["jpg"]
                destination = (PROJECT_ROOT / materials[asset_id].material_path).parent / filename
                jobs.append((file_info, destination))
                downloaded_files.append({**file_info, "path": str(destination.relative_to(assets_root))})
        else:
            preset = next(light for light in pool.lighting if light.name == asset_id)
            destination = PROJECT_ROOT / preset.texture_path
            file_info = files["hdri"]["4k"]["hdr"]
            jobs.append((file_info, destination))
            downloaded_files.append({**file_info, "path": str(destination.relative_to(assets_root))})
        manifest["assets"].append({
            "id": asset_id, "source_url": f"https://polyhaven.com/a/{asset_id}",
            "authors": info["authors"], "files": downloaded_files,
        })
    with ThreadPoolExecutor(max_workers=3) as executor:
        tuple(executor.map(lambda job: _download(*job), jobs))
    for asset_id, preset in materials.items():
        _write_material(asset_id, PROJECT_ROOT / preset.material_path)
    manifest_path = assets_root / "PolyHaven_appearance_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared {len(materials)} materials and {len(pool.lighting)} HDRIs. "
          f"Provenance: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
