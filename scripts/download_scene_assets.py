"""Download the representative asset catalog, retaining sources and licenses."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
import zipfile

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LICENSE_URLS = {
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/legalcode.txt",
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt",
    "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/legalcode.txt",
}


def checksum(path: Path, algorithm: str) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def download(session: requests.Session, url: str, target: Path) -> None:
    """Reuse local downloads; the caller validates provider checksums."""
    if target.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".part")
    print(f"Download {target}", flush=True)
    with session.get(url, stream=True, timeout=(20, 120)) as response:
        response.raise_for_status()
        with temporary.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                stream.write(chunk)
    temporary.replace(target)


def verify(path: Path, algorithm: str, expected: str) -> None:
    if checksum(path, algorithm) != expected:
        raise ValueError(f"{algorithm} mismatch: {path}; remove this file and retry")


def get_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def complete_polyhaven_dependencies(session: requests.Session, entry: Path) -> None:
    """Resolve textures referenced by USD even when absent from API 'include'."""
    from pxr import UsdUtils

    files = json.loads((entry.parent / "files.json").read_text())
    downloads: dict[str, dict] = {}
    pending = [files]
    while pending:
        item = pending.pop()
        if "url" in item and "md5" in item:
            downloads[Path(urlparse(item["url"]).path).name] = item
        pending.extend(value for value in item.values() if isinstance(value, dict))
    _, _, unresolved = UsdUtils.ComputeAllDependencies(str(entry))
    for missing in unresolved:
        target = Path(missing)
        if not target.resolve().is_relative_to(entry.parent.resolve()):
            raise ValueError(f"Dependency escapes asset directory: {missing}")
        item = downloads[target.name]
        download(session, item["url"], target)
        verify(target, "md5", item["md5"])


def download_polyhaven(session: requests.Session, spec: dict, source: Path) -> Path:
    name = spec["id"]
    info = get_json(session, f"https://api.polyhaven.com/info/{name}")
    if info["files_hash"] != spec["revision"]:
        raise ValueError(f"{name}: upstream changed; review the catalog revision first")
    files = get_json(session, f"https://api.polyhaven.com/files/{name}")
    for label, document in (("info", info), ("files", files)):
        (source / f"{label}.json").write_text(json.dumps(document, indent=2) + "\n")
    usd = files["usd"][spec["resolution"]]["usd"]
    entry = source / Path(urlparse(usd["url"]).path).name
    for relative, item in {entry.name: usd, **usd["include"]}.items():
        target = source / relative
        download(session, item["url"], target)
        verify(target, "md5", item["md5"])
    return entry


def download_huggingface(session: requests.Session, spec: dict, source: Path) -> Path:
    repo, revision = spec["repo"], spec["revision"]
    base = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/"
    download(session, base + "README.md", source / "DATASET_CARD.md")
    remote_path = Path(spec["path"])
    if spec["provider"] == "huggingface_zip":
        archive = source / remote_path.name
        download(session, base + spec["path"], archive)
        verify(archive, "sha256", spec["sha256"])
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                target = (source / member.filename).resolve()
                if not target.is_relative_to(source.resolve()):
                    raise ValueError(f"Archive path escapes source directory: {member.filename}")
            package.extractall(source)
        return archive
    url = f"https://huggingface.co/api/datasets/{repo}/tree/{revision}/{remote_path.parent}?recursive=true&limit=1000"
    while url:
        response = session.get(url, timeout=60)
        response.raise_for_status()
        for item in response.json():
            if item["type"] != "file" or ".thumbs/" in item["path"]:
                continue
            relative = Path(item["path"]).relative_to(remote_path.parent)
            target = source / relative
            download(session, base + item["path"], target)
            if "lfs" in item:
                verify(target, "sha256", item["lfs"]["oid"])
            elif target.stat().st_size != item["size"]:
                raise ValueError(f"Size mismatch: {target}")
        url = response.links.get("next", {}).get("url", "")
    return source / remote_path.name


def download_github_archive(session: requests.Session, spec: dict, source: Path) -> Path:
    """Extract selected modular backgrounds and their shared texture directory."""
    base = f"https://raw.githubusercontent.com/{spec['repo']}/{spec['revision']}"
    download(session, base + "/README.md", source / "README.md")
    download(session, base + "/LICENSE.txt", source / "LICENSE.txt")
    archive = source / Path(spec["path"]).name
    download(session, f"https://media.githubusercontent.com/media/{spec['repo']}/{spec['revision']}/{spec['path']}", archive)
    verify(archive, "sha256", spec["sha256"])
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not any(member.filename.startswith(prefix) for prefix in spec["include"]):
                continue
            if not (source / member.filename).resolve().is_relative_to(source.resolve()):
                raise ValueError(f"Archive path escapes source directory: {member.filename}")
            package.extract(member, source)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=PROJECT_ROOT / "configs/assets/representatives.yml")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "Assets/Imported")
    args = parser.parse_args()
    session = requests.Session()
    session.headers["User-Agent"] = "SCALE-Bench asset integration (https://github.com/CrysGate/SCALE-Bench)"
    session.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))))
    for spec in yaml.safe_load(args.catalog.read_text())["assets"]:
        directory = args.output_dir / spec["id"]
        source = directory / "source"
        source.mkdir(parents=True, exist_ok=True)
        # A previous manifest protects reused downloads, including non-LFS files.
        manifest_path = directory / "source_manifest.json"
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text())
            if previous["asset"] != spec:
                raise ValueError(f"Catalog changed for {directory}; choose a new output directory")
            for item in previous["files"]:
                verify(directory / item["path"], "sha256", item["sha256"])
            print(f"Verified {spec['id']}", flush=True)
            entry = directory / previous["entry"]
        else:
            provider = {
                "polyhaven": download_polyhaven,
                "huggingface_zip": download_huggingface,
                "huggingface_usd": download_huggingface,
                "github_zip": download_github_archive,
            }[spec["provider"]]
            entry = provider(session, spec, source)
        if spec["provider"] == "polyhaven":
            complete_polyhaven_dependencies(session, entry)
        license_url = LICENSE_URLS[spec["license"]]
        download(session, license_url, directory / "LICENSE.txt")
        (directory / "ATTRIBUTION.txt").write_text(
            f"{spec['id']}\n{spec['attribution']}\n{spec['source_url']}\n"
            f"Version: {spec['revision']}\nLicense: {spec['license']} ({license_url})\n"
            "Changes: normalized USD in model.usdc; original files in source/.\n"
        )
        files = [
            {"path": str(path.relative_to(directory)), "bytes": path.stat().st_size, "sha256": checksum(path, "sha256")}
            for path in sorted([*source.rglob("*"), directory / "LICENSE.txt", directory / "ATTRIBUTION.txt"])
            if path.is_file()
        ]
        manifest_path.write_text(json.dumps({"asset": spec, "entry": str(entry.relative_to(directory)), "files": files}, indent=2) + "\n")
        print(f"Ready: {spec['id']} ({sum(item['bytes'] for item in files) / 1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
