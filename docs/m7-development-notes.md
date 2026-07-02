# M7 Development Notes

状态：完成。M7 目标是接入真实 WireGuard/nftables 执行边界，并保持 wg-agent 单独验收。

## Checklist

| Task | Status | Evidence |
|---|---|---|
| M7-01 wg-agent Unix socket service | Done | `python -m yourvpn_wg_agent.main --socket ...` |
| M7-02 `/health` | Done | wg-agent health includes command availability |
| M7-03 `/wg/status` | Done | parses `wg show all dump` |
| M7-04 `/peers/apply` | Done | renders `wg set ... allowed-ips` |
| M7-05 `/peers/remove` | Done | renders `wg set ... remove` |
| M7-06 `/firewall/apply` | Done | validates one configured nftables table, then `nft -f -` |
| M7-07 `/reconcile` | Done | removes drift peers, applies targets, applies firewall |
| M7-08 API/Worker wg-agent client | Done | `UnixSocketWgAgentClient`, worker `--job-once` |
| M7-09 active device target state | Done | `WgRuntimeModule.build_target_state()` |
| M7-10 access-group nft rules | Done | routes rendered into dedicated nftables table |
| M7-11 default SNAT/MASQUERADE | Done | `enable_masquerade=true` renders postrouting masquerade |
| M7-12 traffic sample job | Done | `sample_wg_status` worker job writes `traffic_snapshots` |
| M7-13 health data aggregation | Done | `GET /api/admin/runtime/health` |

## Runtime Flow

1. User confirms package download.
2. API enqueues `apply_peer`.
3. Worker claims `apply_peer`.
4. Core validates the device is `download_confirmed` or `active`.
5. Worker calls wg-agent `/peers/apply`.
6. Device moves to `active` after wg-agent success.

## Safety Boundary

- wg-agent does not read the database.
- wg-agent validates interface/table identifiers.
- wg-agent only accepts firewall rulesets for `YOURVPN_NFT_TABLE_NAME`.
- Server peer `AllowedIPs` is device VPN IP `/32`.
- Access-group routes are enforced by nftables.

## 2026-06-28 Validation Run

- `python -m pytest` passed: 42 tests.
- `npm.cmd run lint` passed.
- `npm.cmd run build` passed after cleaning stale `dist`.

## Manual Linux Acceptance Still Required

The Windows development machine validates command shape, target-state generation, API contracts, and worker dispatch. A Linux host must still verify real `wg`, `nft`, sysctl/capabilities, Unix socket filesystem permissions, and recovery after runtime drift.

## Documentation Updated

- `docs/wg-agent-contract.md`: M7 final socket API and error semantics.
- `docs/api-contract.md`: admin runtime health endpoint.
- `docs/database-schema.md`: M7 runtime/job/traffic semantics.
- `docs/deployment.md`: wg-agent and runtime environment variables.
- `docs/security-model.md`: runtime execution boundary.
