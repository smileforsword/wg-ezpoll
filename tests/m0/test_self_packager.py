from __future__ import annotations

import zipfile

from poc.m0.self_packager import PACKAGE_FORMAT, build_package, extract_package, inspect_package, sha256_file


def test_self_packager_bundles_msi_ini_and_manifest(tmp_path) -> None:
    msi = tmp_path / "wireguard.msi"
    ini = tmp_path / "device.ini"
    package = tmp_path / "wireportal-m0.package"
    extract_dir = tmp_path / "extract"

    msi.write_bytes(b"fake-msi")
    ini.write_text("[Interface]\nPrivateKey = fake\n", encoding="utf-8")

    manifest = build_package(
        wireguard_msi=msi,
        device_ini=ini,
        output=package,
        package_id="test-package",
        tunnel_name="WirePortal-Test",
        expected_msi_sha256=sha256_file(msi),
    )

    assert manifest["format"] == PACKAGE_FORMAT
    assert manifest["install_plan"] == [
        "extract_payload",
        "install_or_detect_wireguard",
        "set_wireguard_tunnel_from_ini",
        "remove_intermediate_ini",
    ]
    assert {asset["name"] for asset in manifest["assets"]} == {"wireguard_installer", "device_ini"}

    inspected = inspect_package(package)
    assert inspected["package_id"] == "test-package"

    with zipfile.ZipFile(package) as archive:
        assert sorted(archive.namelist()) == [
            "payload/device.ini",
            "payload/wireguard-amd64.msi",
            "wireportal-package.json",
        ]

    extracted = extract_package(package, extract_dir)
    assert extracted["format"] == PACKAGE_FORMAT
    assert (extract_dir / "payload" / "device.ini").read_text(encoding="utf-8").startswith("[Interface]")


def test_self_packager_rejects_msi_sha_mismatch(tmp_path) -> None:
    msi = tmp_path / "wireguard.msi"
    ini = tmp_path / "device.ini"
    msi.write_bytes(b"fake-msi")
    ini.write_text("[Interface]\nPrivateKey = fake\n", encoding="utf-8")

    try:
        build_package(
            wireguard_msi=msi,
            device_ini=ini,
            output=tmp_path / "out.package",
            package_id="bad-sha",
            tunnel_name="WirePortal-Test",
            expected_msi_sha256="0" * 64,
        )
    except ValueError as exc:
        assert "SHA256 mismatch" in str(exc)
    else:
        raise AssertionError("expected SHA256 mismatch")
