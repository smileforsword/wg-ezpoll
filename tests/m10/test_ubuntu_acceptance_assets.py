from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_root_pyproject_is_dependency_metapackage() -> None:
    data = tomllib.loads(read("pyproject.toml"))

    assert data["build-system"]["build-backend"] == "setuptools.build_meta"
    assert data["tool"]["setuptools"]["packages"] == []


def test_m10_ubuntu_acceptance_doc_covers_release_gates() -> None:
    doc = read("docs/m10-ubuntu-acceptance.md")

    required_phrases = [
        "Ubuntu 24.04",
        "Node.js 18+",
        "install.sh",
        "wireportal-wg-agent",
        "wg-agent is not exposed",
        "YOURVPN_SESSION_COOKIE_SECURE=true",
        "backup.sh",
        "restore.sh",
        "reconcile.sh",
        "Release Decision",
    ]

    for phrase in required_phrases:
        assert phrase in doc
