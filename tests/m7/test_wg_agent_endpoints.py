from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from yourvpn_core.config import AppSettings
from yourvpn_wg_agent.main import CommandExecution, create_app


WG_DUMP = "\n".join(
    [
        "wg0\tprivate\tserverpub\t51820\toff",
        "wg0\told-peer\t(none)\t198.51.100.10:53000\t10.77.0.9/32\t1780000000\t10\t20\toff",
        "",
    ]
)


@dataclass
class RecordingRunner:
    commands: list[tuple[list[str], str | None]]

    def run(self, argv: list[str], *, stdin: str | None = None) -> CommandExecution:
        self.commands.append((argv, stdin))
        stdout = WG_DUMP if argv == ["wg", "show", "all", "dump"] else ""
        return CommandExecution(argv=argv, exit_code=0, stdout=stdout, stderr="")


def test_wg_agent_apply_and_remove_peer_commands() -> None:
    runner = RecordingRunner(commands=[])
    app = create_app(AppSettings(environment="test"), command_runner=runner)
    client = TestClient(app)

    apply = client.post(
        "/peers/apply",
        json={
            "interface": "wg0",
            "public_key": "new-peer",
            "vpn_ip": "10.77.0.2",
            "allowed_ips": ["10.77.0.2/32"],
        },
    )
    remove = client.post("/peers/remove", json={"interface": "wg0", "public_key": "old-peer"})

    assert apply.status_code == 200
    assert remove.status_code == 200
    assert runner.commands == [
        (["wg", "set", "wg0", "peer", "new-peer", "allowed-ips", "10.77.0.2/32"], None),
        (["wg", "set", "wg0", "peer", "old-peer", "remove"], None),
    ]


def test_wg_agent_reconcile_removes_drift_and_replaces_owned_firewall_table() -> None:
    runner = RecordingRunner(commands=[])
    app = create_app(AppSettings(environment="test", nft_table_name="yourvpn"), command_runner=runner)
    client = TestClient(app)
    ruleset = 'table ip yourvpn {\n  chain forward {\n    type filter hook forward priority filter; policy accept;\n  }\n}\n'

    response = client.post(
        "/reconcile",
        json={
            "interface": "wg0",
            "peers": [
                {
                    "public_key": "new-peer",
                    "vpn_ip": "10.77.0.2",
                    "allowed_ips": ["10.77.0.2/32"],
                }
            ],
            "firewall": {
                "table_name": "yourvpn",
                "family": "ip",
                "ruleset": ruleset,
            },
        },
    )

    assert response.status_code == 200
    assert [command for command, _stdin in runner.commands] == [
        ["wg", "show", "all", "dump"],
        ["wg", "set", "wg0", "peer", "old-peer", "remove"],
        ["wg", "set", "wg0", "peer", "new-peer", "allowed-ips", "10.77.0.2/32"],
        ["nft", "-f", "-"],
    ]
    assert runner.commands[-1][1] == ruleset


def test_wg_agent_rejects_unowned_firewall_table() -> None:
    runner = RecordingRunner(commands=[])
    app = create_app(AppSettings(environment="test", nft_table_name="yourvpn"), command_runner=runner)
    client = TestClient(app)

    response = client.post(
        "/firewall/apply",
        json={
            "table_name": "other",
            "family": "ip",
            "ruleset": "table ip other {\n}\n",
        },
    )

    assert response.status_code == 403
    assert runner.commands == []
