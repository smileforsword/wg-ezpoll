from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PACKAGE_FORMAT = "wireportal-self-pack-v1"
MANIFEST_NAME = "wireportal-package.json"


@dataclass(frozen=True)
class Asset:
    logical_name: str
    archive_path: str
    source_path: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _manifest_for_assets(
    *,
    package_id: str,
    tunnel_name: str,
    assets: list[Asset],
    wireguard_installer_version: str,
) -> dict[str, Any]:
    return {
        "format": PACKAGE_FORMAT,
        "package_id": package_id,
        "tunnel_name": tunnel_name,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "wireguard_installer_version": wireguard_installer_version,
        "install_plan": [
            "extract_payload",
            "install_or_detect_wireguard",
            "set_wireguard_tunnel_from_ini",
            "remove_intermediate_ini",
        ],
        "assets": [
            {
                "name": asset.logical_name,
                "path": asset.archive_path,
                "sha256": sha256_file(asset.source_path),
                "size_bytes": asset.source_path.stat().st_size,
            }
            for asset in assets
        ],
    }


def build_package(
    *,
    wireguard_msi: Path,
    device_ini: Path,
    output: Path,
    package_id: str,
    tunnel_name: str,
    wireguard_installer_version: str = "1.1",
    expected_msi_sha256: str | None = None,
) -> dict[str, Any]:
    if not wireguard_msi.is_file():
        raise FileNotFoundError(f"WireGuard MSI not found: {wireguard_msi}")
    if not device_ini.is_file():
        raise FileNotFoundError(f"Device INI not found: {device_ini}")

    actual_msi_sha256 = sha256_file(wireguard_msi)
    if expected_msi_sha256 and actual_msi_sha256 != expected_msi_sha256.upper():
        raise ValueError(
            f"WireGuard MSI SHA256 mismatch: expected {expected_msi_sha256.upper()}, got {actual_msi_sha256}"
        )

    assets = [
        Asset("wireguard_installer", "payload/wireguard-amd64.msi", wireguard_msi),
        Asset("device_ini", "payload/device.ini", device_ini),
    ]
    manifest = _manifest_for_assets(
        package_id=package_id,
        tunnel_name=tunnel_name,
        assets=assets,
        wireguard_installer_version=wireguard_installer_version,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=output.parent, suffix=".tmp") as tmp:
        tmp_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
            for asset in assets:
                package.write(asset.source_path, asset.archive_path)
        os.replace(tmp_path, output)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

    return manifest


def inspect_package(package_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(package_path, mode="r") as package:
        return json.loads(package.read(MANIFEST_NAME).decode("utf-8"))


def extract_package(package_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, mode="r") as package:
        package.extractall(output_dir)
    return json.loads((output_dir / MANIFEST_NAME).read_text(encoding="utf-8"))


def _default_sample_ini() -> Path:
    return Path(__file__).with_name("installer-assets") / "sample-wireguard.ini"


def main() -> int:
    parser = argparse.ArgumentParser(description="M0 self-packager PoC for WirePortal installer payloads.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build a self-packaged installer payload.")
    build.add_argument("--wireguard-msi", type=Path, required=True)
    build.add_argument("--device-ini", type=Path, default=_default_sample_ini())
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--package-id", default="m0-probe")
    build.add_argument("--tunnel-name", default="WirePortal-M0")
    build.add_argument("--wireguard-installer-version", default="1.1")
    build.add_argument("--expected-msi-sha256")

    inspect = subparsers.add_parser("inspect", help="Print package manifest.")
    inspect.add_argument("package", type=Path)

    extract = subparsers.add_parser("extract", help="Extract package to a directory.")
    extract.add_argument("package", type=Path)
    extract.add_argument("output_dir", type=Path)

    args = parser.parse_args()

    if args.command == "build":
        manifest = build_package(
            wireguard_msi=args.wireguard_msi,
            device_ini=args.device_ini,
            output=args.output,
            package_id=args.package_id,
            tunnel_name=args.tunnel_name,
            wireguard_installer_version=args.wireguard_installer_version,
            expected_msi_sha256=args.expected_msi_sha256,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    if args.command == "inspect":
        print(json.dumps(inspect_package(args.package), indent=2, sort_keys=True))
        return 0

    if args.command == "extract":
        manifest = extract_package(args.package, args.output_dir)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
