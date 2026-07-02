# wg-agent Unix Socket Contract

状态：M7 已实现。wg-agent 提供 HTTP over Unix socket API，执行 `wg`、`nft` 和健康探测命令；它不读取数据库，只执行 API/Worker 传入的目标状态。

## Transport

- Protocol: HTTP over Unix domain socket.
- Default socket path: `/run/yourvpn/wg-agent.sock`.
- Socket exposure: local filesystem only, never through Nginx or public TCP.
- Database access: forbidden. wg-agent only executes target state supplied by API/Worker.

## Endpoints

### `GET /health`

Response:

```json
{
  "service": "wg-agent",
  "status": "ok",
  "version": "0.1.0",
  "environment": "production",
  "checked_at": "2026-06-28T00:00:00Z",
  "details": {
    "transport": "unix-socket",
    "database_access": false,
    "socket_path": "/run/yourvpn/wg-agent.sock",
    "user": "root",
    "dry_run": false,
    "commands": {
      "wg": "available",
      "nft": "available",
      "sysctl": "available"
    }
  }
}
```

### `GET /wg/status`

Response:

```json
{
  "interface": "wg0",
  "peers": [
    {
      "public_key": "base64-public-key",
      "endpoint": "198.51.100.20:53000",
      "allowed_ips": ["10.77.0.2/32"],
      "latest_handshake_epoch": 1780000000,
      "transfer_rx_bytes": 1024,
      "transfer_tx_bytes": 2048
    }
  ]
}
```

M7 uses `wg show all dump` as the source format because it is safer for automated parsing than human-readable `wg show`.

### `POST /peers/apply`

Request:

```json
{
  "interface": "wg0",
  "public_key": "base64-public-key",
  "vpn_ip": "10.77.0.2",
  "allowed_ips": ["10.77.0.2/32"]
}
```

Response:

```json
{
  "ok": true,
  "operation": "apply_peer",
  "commands": [
    {
      "argv": ["wg", "set", "wg0", "peer", "base64-public-key", "allowed-ips", "10.77.0.2/32"],
      "exit_code": 0,
      "stdout": "",
      "stderr": ""
    }
  ]
}
```

### `POST /peers/remove`

Request:

```json
{
  "interface": "wg0",
  "public_key": "base64-public-key"
}
```

### `POST /firewall/apply`

Request:

```json
{
  "table_name": "yourvpn",
  "family": "ip",
  "ruleset": "table ip yourvpn { ... }"
}
```

Rules:

- The payload must contain a complete replacement for the dedicated `yourvpn` table.
- wg-agent must not modify unrelated nftables tables.
- `table_name` must match `YOURVPN_NFT_TABLE_NAME`, default `yourvpn`.
- The ruleset must contain exactly one `table ip yourvpn { ... }` table.
- The command executed is `nft -f -` with the ruleset passed through stdin.

### `POST /reconcile`

Request:

```json
{
  "interface": "wg0",
  "peers": [
    {
      "public_key": "base64-public-key",
      "vpn_ip": "10.77.0.2",
      "allowed_ips": ["10.77.0.2/32"]
    }
  ],
  "firewall": {
    "table_name": "yourvpn",
    "family": "ip",
    "ruleset": "table ip yourvpn { ... }"
  }
}
```

Response:

```json
{
  "ok": true,
  "operation": "reconcile",
  "commands": [
    {
      "argv": ["wg", "show", "all", "dump"],
      "exit_code": 0,
      "stdout": "...",
      "stderr": ""
    },
    {
      "argv": ["wg", "set", "wg0", "peer", "old-public-key", "remove"],
      "exit_code": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "argv": ["wg", "set", "wg0", "peer", "base64-public-key", "allowed-ips", "10.77.0.2/32"],
      "exit_code": 0,
      "stdout": "",
      "stderr": ""
    },
    {
      "argv": ["nft", "-f", "-"],
      "exit_code": 0,
      "stdout": "",
      "stderr": ""
    }
  ]
}
```

## Error Semantics

- Missing system command returns HTTP `503`.
- Command non-zero exit returns HTTP `500` with command `argv` and `stderr`.
- Firewall table mismatch returns HTTP `403`.
- Invalid payload shape or invalid nftables table ownership returns HTTP `422`.

## Process Entrypoint

Development TCP listener:

```bash
python -m yourvpn_wg_agent.main --http --host 127.0.0.1 --port 8009
```

Unix socket listener:

```bash
python -m yourvpn_wg_agent.main --socket /run/yourvpn/wg-agent.sock
```
