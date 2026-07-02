from __future__ import annotations

import argparse
import getpass
import ipaddress
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from yourvpn_core.config import AppSettings, load_settings
from yourvpn_core.health import build_health_status
from yourvpn_core.logging import configure_logging


@dataclass(frozen=True)
class CommandExecution:
    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecution:
        ...


class SubprocessCommandRunner:
    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecution:
        if self.dry_run:
            return CommandExecution(argv=argv, exit_code=0, stdout="", stderr="")
        completed = subprocess.run(
            argv,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
        )
        return CommandExecution(
            argv=argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


@dataclass(frozen=True)
class WgPeerStatus:
    interface: str
    public_key: str
    endpoint: str | None
    allowed_ips: tuple[str, ...]
    latest_handshake_epoch: int | None
    transfer_rx_bytes: int
    transfer_tx_bytes: int
    persistent_keepalive_seconds: int | None


class PeerApplyRequest(BaseModel):
    interface: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=1, max_length=128)
    vpn_ip: str
    allowed_ips: list[str] = Field(min_length=1)

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        return _validate_identifier(value, "interface")

    @field_validator("vpn_ip")
    @classmethod
    def validate_vpn_ip(cls, value: str) -> str:
        return str(ipaddress.ip_address(value))

    @field_validator("allowed_ips")
    @classmethod
    def validate_allowed_ips(cls, values: list[str]) -> list[str]:
        return [str(ipaddress.ip_network(value, strict=False)) for value in values]


class PeerRemoveRequest(BaseModel):
    interface: str = Field(min_length=1, max_length=64)
    public_key: str = Field(min_length=1, max_length=128)

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        return _validate_identifier(value, "interface")


class FirewallApplyRequest(BaseModel):
    table_name: str = Field(min_length=1, max_length=64)
    family: str = "ip"
    ruleset: str = Field(min_length=1)

    @field_validator("table_name")
    @classmethod
    def validate_table_name(cls, value: str) -> str:
        return _validate_identifier(value, "table_name")

    @field_validator("family")
    @classmethod
    def validate_family(cls, value: str) -> str:
        if value != "ip":
            raise ValueError("Only nftables family 'ip' is supported in V1")
        return value


class ReconcilePeer(BaseModel):
    public_key: str = Field(min_length=1, max_length=128)
    vpn_ip: str
    allowed_ips: list[str] = Field(min_length=1)

    @field_validator("vpn_ip")
    @classmethod
    def validate_vpn_ip(cls, value: str) -> str:
        return str(ipaddress.ip_address(value))

    @field_validator("allowed_ips")
    @classmethod
    def validate_allowed_ips(cls, values: list[str]) -> list[str]:
        return [str(ipaddress.ip_network(value, strict=False)) for value in values]


class ReconcileRequest(BaseModel):
    interface: str = Field(min_length=1, max_length=64)
    peers: list[ReconcilePeer] = Field(default_factory=list)
    firewall: FirewallApplyRequest

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        return _validate_identifier(value, "interface")


def build_apply_peer_command(
    *,
    interface: str,
    public_key: str,
    allowed_ips: list[str],
) -> list[str]:
    return ["wg", "set", interface, "peer", public_key, "allowed-ips", ",".join(allowed_ips)]


def build_remove_peer_command(*, interface: str, public_key: str) -> list[str]:
    return ["wg", "set", interface, "peer", public_key, "remove"]


def parse_wg_show_dump(dump_text: str) -> list[WgPeerStatus]:
    peers: list[WgPeerStatus] = []
    for raw_line in dump_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 5:
            continue
        if len(parts) != 9:
            raise ValueError(f"Unsupported wg dump line with {len(parts)} fields")
        (
            interface,
            public_key,
            _preshared_key,
            endpoint,
            allowed_ips,
            latest_handshake,
            transfer_rx,
            transfer_tx,
            persistent_keepalive,
        ) = parts
        peers.append(
            WgPeerStatus(
                interface=interface,
                public_key=public_key,
                endpoint=_none_if_placeholder(endpoint),
                allowed_ips=tuple() if allowed_ips == "(none)" else tuple(allowed_ips.split(",")),
                latest_handshake_epoch=_int_or_none(latest_handshake),
                transfer_rx_bytes=int(transfer_rx),
                transfer_tx_bytes=int(transfer_tx),
                persistent_keepalive_seconds=_int_or_none(persistent_keepalive),
            )
        )
    return peers


def create_app(
    settings: AppSettings | None = None,
    *,
    command_runner: CommandRunner | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings, service="wg-agent")
    runner = command_runner or SubprocessCommandRunner(dry_run=resolved_settings.wg_agent_dry_run)

    agent = FastAPI(
        title="WirePortal wg-agent",
        version="0.1.0",
    )

    @agent.get("/health", tags=["health"])
    def health():
        return build_health_status(
            service="wg-agent",
            settings=resolved_settings,
            details={
                "transport": "unix-socket",
                "database_access": False,
                "socket_path": resolved_settings.wg_agent_socket_path,
                "user": getpass.getuser(),
                "dry_run": resolved_settings.wg_agent_dry_run,
                "commands": _command_availability(),
            },
        )

    @agent.get("/wg/status", tags=["wg"])
    def wg_status():
        result = _run_checked(runner, ["wg", "show", "all", "dump"])
        peers = [
            asdict(peer)
            for peer in parse_wg_show_dump(result.stdout)
            if peer.interface == resolved_settings.wg_interface
        ]
        return {"interface": resolved_settings.wg_interface, "peers": peers}

    @agent.post("/peers/apply", tags=["peers"])
    def apply_peer(payload: PeerApplyRequest):
        argv = build_apply_peer_command(
            interface=payload.interface,
            public_key=payload.public_key,
            allowed_ips=payload.allowed_ips,
        )
        result = _run_checked(runner, argv)
        return {
            "ok": True,
            "operation": "apply_peer",
            "commands": [asdict(result)],
        }

    @agent.post("/peers/remove", tags=["peers"])
    def remove_peer(payload: PeerRemoveRequest):
        result = _run_checked(
            runner,
            build_remove_peer_command(interface=payload.interface, public_key=payload.public_key),
        )
        return {
            "ok": True,
            "operation": "remove_peer",
            "commands": [asdict(result)],
        }

    @agent.post("/firewall/apply", tags=["firewall"])
    def apply_firewall(payload: FirewallApplyRequest):
        _validate_firewall_ruleset(
            payload.ruleset,
            table_name=payload.table_name,
            family=payload.family,
            configured_table_name=resolved_settings.nft_table_name,
        )
        result = _run_checked(runner, ["nft", "-f", "-"], stdin=payload.ruleset)
        return {
            "ok": True,
            "operation": "apply_firewall",
            "commands": [asdict(result)],
        }

    @agent.post("/reconcile", tags=["reconcile"])
    def reconcile(payload: ReconcileRequest):
        _validate_firewall_ruleset(
            payload.firewall.ruleset,
            table_name=payload.firewall.table_name,
            family=payload.firewall.family,
            configured_table_name=resolved_settings.nft_table_name,
        )
        commands: list[CommandExecution] = []
        status = _run_checked(runner, ["wg", "show", "all", "dump"])
        commands.append(status)
        current_keys = {
            peer.public_key
            for peer in parse_wg_show_dump(status.stdout)
            if peer.interface == payload.interface
        }
        target_keys = {peer.public_key for peer in payload.peers}
        for public_key in sorted(current_keys - target_keys):
            commands.append(
                _run_checked(
                    runner,
                    build_remove_peer_command(interface=payload.interface, public_key=public_key),
                )
            )
        for peer in payload.peers:
            commands.append(
                _run_checked(
                    runner,
                    build_apply_peer_command(
                        interface=payload.interface,
                        public_key=peer.public_key,
                        allowed_ips=peer.allowed_ips,
                    ),
                )
            )
        commands.append(_run_checked(runner, ["nft", "-f", "-"], stdin=payload.firewall.ruleset))
        return {
            "ok": True,
            "operation": "reconcile",
            "commands": [asdict(command) for command in commands],
        }

    return agent


def main() -> int:
    parser = argparse.ArgumentParser(description="WirePortal wg-agent.")
    parser.add_argument("--socket", default=None, help="Unix socket path. Defaults to settings.")
    parser.add_argument("--http", action="store_true", help="Run a development TCP listener instead of Unix socket.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8009)
    args = parser.parse_args()

    import uvicorn

    settings = load_settings()
    app = create_app(settings)
    if args.http:
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    socket_path = Path(args.socket or settings.wg_agent_socket_path)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    uvicorn.run(app, uds=str(socket_path))
    return 0


def _run_checked(
    runner: CommandRunner,
    argv: list[str],
    *,
    stdin: str | None = None,
) -> CommandExecution:
    try:
        result = runner.run(argv, stdin=stdin)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Command not found: {argv[0]}") from exc
    if result.exit_code != 0:
        raise HTTPException(status_code=500, detail={"argv": result.argv, "stderr": result.stderr})
    return result


def _validate_firewall_ruleset(
    ruleset: str,
    *,
    table_name: str,
    family: str,
    configured_table_name: str,
) -> None:
    if table_name != configured_table_name:
        raise HTTPException(status_code=403, detail="wg-agent may only manage the configured nftables table")
    table_refs = re.findall(r"(?m)^\s*table\s+([a-zA-Z0-9_.-]+)\s+([a-zA-Z0-9_.-]+)\s*\{", ruleset)
    if table_refs != [(family, table_name)]:
        raise HTTPException(status_code=422, detail="ruleset must contain exactly one configured nftables table")


def _validate_identifier(value: str, field_name: str) -> str:
    if not all(character.isalnum() or character in {"_", "-", "."} for character in value):
        raise ValueError(f"Invalid {field_name}")
    return value


def _none_if_placeholder(value: str) -> str | None:
    return None if value in {"", "(none)", "off"} else value


def _int_or_none(value: str) -> int | None:
    if value in {"", "0", "off"}:
        return None
    return int(value)


def _command_availability() -> dict[str, str]:
    return {
        "wg": "available" if shutil.which("wg") else "missing",
        "nft": "available" if shutil.which("nft") else "missing",
        "sysctl": "available" if shutil.which("sysctl") else "missing",
    }


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
