from __future__ import annotations

import base64
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from yourvpn_core.config import AppSettings
from yourvpn_core.modules.errors import InstallerBuildError, ValidationError


PACKAGE_FORMAT = "wireportal-self-pack-v1"
CONFIG_ZIP_FORMAT = "wireportal-config-zip-v1"
MANIFEST_NAME = "wireportal-package.json"
RUNNER_NAME = "runner/install-wireportal.ps1"
README_NAME = "README.txt"
DEVICE_INI_NAME = "payload/device.ini"
WIREGUARD_MSI_NAME = "payload/wireguard-amd64.msi"


@dataclass(frozen=True)
class BuildInstallerRequest:
    settings: AppSettings
    device_id: str
    device_name: str
    vpn_ip: str
    package_id: str
    allowed_group_ids: list[str]
    allowed_ips: list[str]
    now: datetime


@dataclass(frozen=True)
class BuildInstallerResult:
    public_key: str
    file_name: str
    artifact_path: Path
    sha256: str
    file_size: int
    signed_status: str
    config_format: str
    wireguard_installer_version: str
    manifest: dict[str, Any]
    temp_ini_deleted: bool


class InstallerBuilder(Protocol):
    job_type: str

    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult:
        ...


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _b64_key(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _clamp_private_key(raw: bytes) -> bytes:
    if len(raw) != 32:
        raise ValueError("WireGuard private key material must be 32 bytes")
    key = bytearray(raw)
    key[0] &= 248
    key[31] &= 127
    key[31] |= 64
    return bytes(key)


def _cswap(swap: int, x2: int, x3: int) -> tuple[int, int]:
    if swap:
        return x3, x2
    return x2, x3


def _x25519_public_key(private_key: bytes) -> bytes:
    p = 2**255 - 19
    scalar = _clamp_private_key(private_key)
    scalar_int = int.from_bytes(scalar, "little")
    x1 = 9
    x2 = 1
    z2 = 0
    x3 = x1
    z3 = 1
    swap = 0

    for bit_index in range(254, -1, -1):
        bit = (scalar_int >> bit_index) & 1
        swap ^= bit
        x2, x3 = _cswap(swap, x2, x3)
        z2, z3 = _cswap(swap, z2, z3)
        swap = bit

        a = (x2 + z2) % p
        aa = (a * a) % p
        b = (x2 - z2) % p
        bb = (b * b) % p
        e = (aa - bb) % p
        c = (x3 + z3) % p
        d = (x3 - z3) % p
        da = (d * a) % p
        cb = (c * b) % p
        x3 = ((da + cb) ** 2) % p
        z3 = (x1 * ((da - cb) ** 2)) % p
        x2 = (aa * bb) % p
        z2 = (e * (aa + 121665 * e)) % p

    x2, x3 = _cswap(swap, x2, x3)
    z2, z3 = _cswap(swap, z2, z3)
    public = (x2 * pow(z2, p - 2, p)) % p
    return public.to_bytes(32, "little")


def generate_wireguard_keypair() -> tuple[str, str]:
    private_key = _clamp_private_key(os.urandom(32))
    public_key = _x25519_public_key(private_key)
    return _b64_key(private_key), _b64_key(public_key)


def render_wireguard_ini(
    *,
    private_key: str,
    vpn_ip: str,
    server_public_key: str,
    endpoint: str,
    allowed_ips: list[str],
    persistent_keepalive_seconds: int,
) -> str:
    if not server_public_key.strip():
        raise ValidationError("WireGuard server public key is required")
    if not endpoint.strip():
        raise ValidationError("WireGuard endpoint is required")
    if not allowed_ips:
        raise ValidationError("At least one WireGuard AllowedIPs route is required")
    rendered_allowed_ips = ", ".join(allowed_ips)
    return "\n".join(
        [
            "[Interface]",
            f"PrivateKey = {private_key}",
            f"Address = {vpn_ip}/32",
            "",
            "[Peer]",
            f"PublicKey = {server_public_key.strip()}",
            f"Endpoint = {endpoint.strip()}",
            f"AllowedIPs = {rendered_allowed_ips}",
            f"PersistentKeepalive = {persistent_keepalive_seconds}",
            "",
        ]
    )


def render_windows_runner(*, tunnel_name: str) -> str:
    return r"""
$ErrorActionPreference = "Stop"
$PayloadDir = Join-Path $PSScriptRoot "..\payload"
$MsiPath = Join-Path $PayloadDir "wireguard-amd64.msi"
$IniPath = Join-Path $PayloadDir "device.ini"
$TunnelIniPath = Join-Path $env:TEMP "__TUNNEL_NAME__.ini"
$WireGuardExe = Join-Path $env:ProgramFiles "WireGuard\wireguard.exe"

try {
  if (-not (Test-Path -LiteralPath $WireGuardExe)) {
    Start-Process -FilePath "msiexec.exe" -ArgumentList @("/i", $MsiPath, "/qn", "/norestart") -Wait -Verb RunAs
  }

  if (-not (Test-Path -LiteralPath $WireGuardExe)) {
    throw "WireGuard executable was not found after installer completed."
  }

  Copy-Item -LiteralPath $IniPath -Destination $TunnelIniPath -Force
  Start-Process -FilePath $WireGuardExe -ArgumentList @("/installtunnelservice", $TunnelIniPath) -Wait -Verb RunAs
} finally {
  if (Test-Path -LiteralPath $TunnelIniPath) {
    Remove-Item -LiteralPath $TunnelIniPath -Force
  }
  if (Test-Path -LiteralPath $IniPath) {
    Remove-Item -LiteralPath $IniPath -Force
  }
}
""".replace("__TUNNEL_NAME__", tunnel_name)


def render_config_zip_runner(*, tunnel_name: str) -> str:
    return r"""
$ErrorActionPreference = "Stop"
$PayloadDir = Join-Path $PSScriptRoot "..\payload"
$IniPath = Join-Path $PayloadDir "device.ini"
$TunnelIniPath = Join-Path $env:TEMP "__TUNNEL_NAME__.ini"
$WireGuardExe = Join-Path $env:ProgramFiles "WireGuard\wireguard.exe"

try {
  if (-not (Test-Path -LiteralPath $WireGuardExe)) {
    throw "WireGuard for Windows is not installed. Install it first, then run this script again."
  }

  Copy-Item -LiteralPath $IniPath -Destination $TunnelIniPath -Force
  Start-Process -FilePath $WireGuardExe -ArgumentList @("/installtunnelservice", $TunnelIniPath) -Wait -Verb RunAs
} finally {
  if (Test-Path -LiteralPath $TunnelIniPath) {
    Remove-Item -LiteralPath $TunnelIniPath -Force
  }
}
""".replace("__TUNNEL_NAME__", tunnel_name)


def render_config_zip_readme(*, tunnel_name: str) -> str:
    return "\n".join(
        [
            "WirePortal tunnel package",
            "",
            "This package does not install WireGuard.",
            "1. Install the official WireGuard for Windows client first.",
            "2. Extract this ZIP to a local folder.",
            "3. Right-click runner\\install-wireportal.ps1 and choose Run with PowerShell.",
            "4. Approve the Windows UAC prompt to add the tunnel.",
            "",
            f"Tunnel name: {tunnel_name}",
            "",
            "Keep this ZIP private. It contains the device WireGuard private key.",
            "",
        ]
    )


def _asset_metadata(name: str, archive_path: str, source_path: Path) -> dict[str, Any]:
    return {
        "name": name,
        "path": archive_path,
        "sha256": sha256_file(source_path),
        "size_bytes": source_path.stat().st_size,
    }


class FakeInstallerBuilder:
    job_type = "build_installer_fake"

    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult:
        artifacts_dir = Path(request.settings.artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        public_key = f"fake-pub-{request.device_id}"[:88]
        file_name = f"wireportal-{request.device_id}.fake-installer.txt"
        artifact_path = artifacts_dir / file_name
        content = "\n".join(
            [
                "WirePortal fake installer",
                f"device_id={request.device_id}",
                f"device_name={request.device_name}",
                f"vpn_ip={request.vpn_ip}",
                f"public_key={public_key}",
                f"access_group_ids={','.join(request.allowed_group_ids)}",
                "config_format=ini",
                "",
            ]
        )
        artifact_path.write_text(content, encoding="utf-8")
        digest = sha256_file(artifact_path).lower()
        manifest = {
            "format": "wireportal-fake-installer-v1",
            "package_id": request.package_id,
            "device_id": request.device_id,
            "config_format": "ini",
        }
        return BuildInstallerResult(
            public_key=public_key,
            file_name=file_name,
            artifact_path=artifact_path,
            sha256=digest,
            file_size=artifact_path.stat().st_size,
            signed_status="fake-unsigned",
            config_format="ini",
            wireguard_installer_version="fake",
            manifest=manifest,
            temp_ini_deleted=True,
        )


class SelfPackInstallerBuilder:
    job_type = "build_installer"

    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult:
        settings = request.settings
        if not settings.wireguard_msi_path:
            raise InstallerBuildError("WireGuard MSI path is required for self-pack builder")
        if not settings.wireguard_server_public_key.strip():
            raise InstallerBuildError("WireGuard server public key is required for self-pack builder")
        if not settings.wireguard_endpoint.strip():
            raise InstallerBuildError("WireGuard endpoint is required for self-pack builder")

        wireguard_msi = Path(settings.wireguard_msi_path)
        if not wireguard_msi.is_file():
            raise InstallerBuildError(f"WireGuard MSI not found: {wireguard_msi}")

        actual_msi_sha = sha256_file(wireguard_msi)
        expected_msi_sha = settings.wireguard_msi_sha256.upper()
        if actual_msi_sha != expected_msi_sha:
            raise InstallerBuildError(
                f"WireGuard MSI SHA256 mismatch: expected {expected_msi_sha}, got {actual_msi_sha}"
            )

        artifacts_dir = Path(settings.artifacts_dir)
        build_tmp_dir = Path(settings.build_tmp_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        build_tmp_dir.mkdir(parents=True, exist_ok=True)

        private_key, public_key = generate_wireguard_keypair()
        file_name = f"wireportal-{request.device_id}.exe"
        output_path = artifacts_dir / file_name
        tunnel_name = _tunnel_name(settings.wireguard_tunnel_name_prefix, request.device_name)

        temp_ini_deleted = False
        with tempfile.TemporaryDirectory(prefix="wireportal-build-", dir=build_tmp_dir) as tmp:
            tmp_dir = Path(tmp)
            device_ini = tmp_dir / "device.ini"
            runner = tmp_dir / "install-wireportal.ps1"
            device_ini.write_text(
                render_wireguard_ini(
                    private_key=private_key,
                    vpn_ip=request.vpn_ip,
                    server_public_key=settings.wireguard_server_public_key,
                    endpoint=settings.wireguard_endpoint,
                    allowed_ips=request.allowed_ips,
                    persistent_keepalive_seconds=settings.wireguard_persistent_keepalive_seconds,
                ),
                encoding="utf-8",
            )
            runner.write_text(render_windows_runner(tunnel_name=tunnel_name), encoding="utf-8")

            manifest = self._manifest(
                request=request,
                tunnel_name=tunnel_name,
                wireguard_msi=wireguard_msi,
                device_ini=device_ini,
                runner=runner,
                public_key=public_key,
                wireguard_installer_sha256=actual_msi_sha,
            )
            self._write_package(
                output_path=output_path,
                manifest=manifest,
                wireguard_msi=wireguard_msi,
                device_ini=device_ini,
                runner=runner,
            )
            temp_ini_path = device_ini

        temp_ini_deleted = not temp_ini_path.exists()
        if not temp_ini_deleted:
            raise InstallerBuildError("Temporary device INI was not deleted after build")

        return BuildInstallerResult(
            public_key=public_key,
            file_name=file_name,
            artifact_path=output_path,
            sha256=sha256_file(output_path).lower(),
            file_size=output_path.stat().st_size,
            signed_status="unsigned",
            config_format="ini",
            wireguard_installer_version=settings.wireguard_installer_version,
            manifest=manifest,
            temp_ini_deleted=temp_ini_deleted,
        )

    def _manifest(
        self,
        *,
        request: BuildInstallerRequest,
        tunnel_name: str,
        wireguard_msi: Path,
        device_ini: Path,
        runner: Path,
        public_key: str,
        wireguard_installer_sha256: str,
    ) -> dict[str, Any]:
        return {
            "format": PACKAGE_FORMAT,
            "package_id": request.package_id,
            "device_id": request.device_id,
            "device_name": request.device_name,
            "tunnel_name": tunnel_name,
            "created_at": request.now.replace(microsecond=0).astimezone(UTC).isoformat(),
            "config_format": "ini",
            "wireguard_installer_version": request.settings.wireguard_installer_version,
            "wireguard_installer_sha256": wireguard_installer_sha256,
            "wireguard_endpoint": request.settings.wireguard_endpoint,
            "device": {
                "vpn_ip": request.vpn_ip,
                "public_key": public_key,
                "allowed_ips": request.allowed_ips,
                "access_group_ids": request.allowed_group_ids,
            },
            "install_plan": [
                "extract_payload",
                "install_or_detect_wireguard",
                "set_wireguard_tunnel_from_ini",
                "remove_intermediate_ini",
            ],
            "cleanup": {
                "build_temp_ini_deleted": True,
                "runtime_remove_released_ini": True,
            },
            "runner": {
                "entrypoint": RUNNER_NAME,
                "requires_admin": True,
            },
            "assets": [
                _asset_metadata("wireguard_installer", WIREGUARD_MSI_NAME, wireguard_msi),
                _asset_metadata("device_ini", DEVICE_INI_NAME, device_ini),
                _asset_metadata("windows_runner", RUNNER_NAME, runner),
            ],
        }

    def _write_package(
        self,
        *,
        output_path: Path,
        manifest: dict[str, Any],
        wireguard_msi: Path,
        device_ini: Path,
        runner: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, dir=output_path.parent, suffix=".tmp") as tmp:
            tmp_path = Path(tmp.name)
        try:
            with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as package:
                package.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
                package.write(wireguard_msi, WIREGUARD_MSI_NAME)
                package.write(device_ini, DEVICE_INI_NAME)
                package.write(runner, RUNNER_NAME)
            os.replace(tmp_path, output_path)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


class ConfigZipInstallerBuilder:
    job_type = "build_config_zip"

    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult:
        settings = request.settings
        if not settings.wireguard_server_public_key.strip():
            raise InstallerBuildError("WireGuard server public key is required for config ZIP builder")
        if not settings.wireguard_endpoint.strip():
            raise InstallerBuildError("WireGuard endpoint is required for config ZIP builder")

        artifacts_dir = Path(settings.artifacts_dir)
        build_tmp_dir = Path(settings.build_tmp_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        build_tmp_dir.mkdir(parents=True, exist_ok=True)

        private_key, public_key = generate_wireguard_keypair()
        file_name = f"wireportal-{request.device_id}.zip"
        output_path = artifacts_dir / file_name
        tunnel_name = _tunnel_name(settings.wireguard_tunnel_name_prefix, request.device_name)

        with tempfile.TemporaryDirectory(prefix="wireportal-build-", dir=build_tmp_dir) as tmp:
            tmp_dir = Path(tmp)
            device_ini = tmp_dir / "device.ini"
            runner = tmp_dir / "install-wireportal.ps1"
            readme = tmp_dir / "README.txt"
            device_ini.write_text(
                render_wireguard_ini(
                    private_key=private_key,
                    vpn_ip=request.vpn_ip,
                    server_public_key=settings.wireguard_server_public_key,
                    endpoint=settings.wireguard_endpoint,
                    allowed_ips=request.allowed_ips,
                    persistent_keepalive_seconds=settings.wireguard_persistent_keepalive_seconds,
                ),
                encoding="utf-8",
            )
            runner.write_text(render_config_zip_runner(tunnel_name=tunnel_name), encoding="utf-8")
            readme.write_text(render_config_zip_readme(tunnel_name=tunnel_name), encoding="utf-8")

            manifest = self._manifest(
                request=request,
                tunnel_name=tunnel_name,
                device_ini=device_ini,
                runner=runner,
                readme=readme,
                public_key=public_key,
            )
            self._write_package(
                output_path=output_path,
                manifest=manifest,
                device_ini=device_ini,
                runner=runner,
                readme=readme,
            )
            temp_ini_path = device_ini

        temp_ini_deleted = not temp_ini_path.exists()
        if not temp_ini_deleted:
            raise InstallerBuildError("Temporary device INI was not deleted after build")

        return BuildInstallerResult(
            public_key=public_key,
            file_name=file_name,
            artifact_path=output_path,
            sha256=sha256_file(output_path).lower(),
            file_size=output_path.stat().st_size,
            signed_status="zip-unsigned",
            config_format="ini",
            wireguard_installer_version="external",
            manifest=manifest,
            temp_ini_deleted=temp_ini_deleted,
        )

    def _manifest(
        self,
        *,
        request: BuildInstallerRequest,
        tunnel_name: str,
        device_ini: Path,
        runner: Path,
        readme: Path,
        public_key: str,
    ) -> dict[str, Any]:
        return {
            "format": CONFIG_ZIP_FORMAT,
            "package_id": request.package_id,
            "device_id": request.device_id,
            "device_name": request.device_name,
            "tunnel_name": tunnel_name,
            "created_at": request.now.replace(microsecond=0).astimezone(UTC).isoformat(),
            "config_format": "ini",
            "wireguard_endpoint": request.settings.wireguard_endpoint,
            "device": {
                "vpn_ip": request.vpn_ip,
                "public_key": public_key,
                "allowed_ips": request.allowed_ips,
                "access_group_ids": request.allowed_group_ids,
            },
            "install_plan": [
                "install_wireguard_manually",
                "extract_zip",
                "run_windows_runner",
                "set_wireguard_tunnel_from_ini",
                "remove_intermediate_ini",
            ],
            "cleanup": {
                "build_temp_ini_deleted": True,
                "runtime_remove_released_ini": True,
            },
            "runner": {
                "entrypoint": RUNNER_NAME,
                "requires_admin": True,
            },
            "assets": [
                _asset_metadata("device_ini", DEVICE_INI_NAME, device_ini),
                _asset_metadata("windows_runner", RUNNER_NAME, runner),
                _asset_metadata("readme", README_NAME, readme),
            ],
        }

    def _write_package(
        self,
        *,
        output_path: Path,
        manifest: dict[str, Any],
        device_ini: Path,
        runner: Path,
        readme: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, dir=output_path.parent, suffix=".tmp") as tmp:
            tmp_path = Path(tmp.name)
        try:
            with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as package:
                package.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
                package.write(device_ini, DEVICE_INI_NAME)
                package.write(runner, RUNNER_NAME)
                package.write(readme, README_NAME)
            os.replace(tmp_path, output_path)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def _tunnel_name(prefix: str, device_name: str) -> str:
    safe = "".join(character if character.isalnum() else "-" for character in device_name).strip("-")
    safe = "-".join(part for part in safe.split("-") if part)
    return f"{prefix}-{safe or 'device'}"[:64]
