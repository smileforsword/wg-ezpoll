from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


if hasattr(socketserver, "UnixStreamServer"):

    class UnixHTTPServer(socketserver.UnixStreamServer):  # type: ignore[attr-defined]
        allow_reuse_address = True

else:

    class UnixHTTPServer(socketserver.BaseServer):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("socketserver.UnixStreamServer is not available on this platform")


class WgAgentPocHandler(BaseHTTPRequestHandler):
    server_version = "WirePortalM0WgAgent/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "socket": "unix",
                    "database_access": False,
                    "capabilities": {
                        "wg": "not_checked_in_poc",
                        "nft": "not_checked_in_poc",
                    },
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        body = self._read_json_body()
        if self.path == "/peers/apply":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "operation": "apply_peer",
                    "would_execute": [
                        "wg",
                        "set",
                        body["interface"],
                        "peer",
                        body["public_key"],
                        "allowed-ips",
                        body["vpn_ip"] + "/32",
                    ],
                },
            )
            return
        if self.path == "/peers/remove":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "operation": "remove_peer",
                    "would_execute": [
                        "wg",
                        "set",
                        body["interface"],
                        "peer",
                        body["public_key"],
                        "remove",
                    ],
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})


def request_unix_http(
    socket_path: Path,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")
    request_lines = [
        f"{method} {path} HTTP/1.1",
        "Host: wg-agent.local",
        "Connection: close",
        "Accept: application/json",
        f"Content-Length: {len(body)}",
        "",
        "",
    ]
    raw_request = "\r\n".join(request_lines).encode("ascii") + body

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(raw_request)
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    raw_response = b"".join(chunks)
    header_bytes, _, body_bytes = raw_response.partition(b"\r\n\r\n")
    status_line = header_bytes.splitlines()[0].decode("ascii")
    status_code = int(status_line.split(" ")[1])
    return status_code, json.loads(body_bytes.decode("utf-8"))


def run_server(socket_path: Path) -> None:
    if socket_path.exists():
        socket_path.unlink()
    with UnixHTTPServer(str(socket_path), WgAgentPocHandler) as server:
        server.serve_forever()


def run_smoke(socket_path: Path) -> dict[str, Any]:
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("AF_UNIX is not available on this platform")

    thread = threading.Thread(target=run_server, args=(socket_path,), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if socket_path.exists():
            break
        time.sleep(0.05)

    health_status, health = request_unix_http(socket_path, "GET", "/health")
    apply_status, apply_result = request_unix_http(
        socket_path,
        "POST",
        "/peers/apply",
        {
            "interface": "wg0",
            "public_key": "m0samplepublickey000000000000000000000000000=",
            "vpn_ip": "10.77.0.2",
        },
    )
    return {
        "health_status": health_status,
        "health": health,
        "apply_status": apply_status,
        "apply": apply_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M0 wg-agent Unix socket PoC.")
    parser.add_argument("--socket", type=Path, default=Path(tempfile.gettempdir()) / "wireportal-m0-wg-agent.sock")
    parser.add_argument("--server", action="store_true", help="Run the PoC wg-agent server.")
    parser.add_argument("--smoke", action="store_true", help="Run an in-process server/client smoke test.")
    args = parser.parse_args()

    if args.server:
        run_server(args.socket)
        return 0

    if args.smoke:
        try:
            result = run_smoke(args.socket)
        except RuntimeError as exc:
            print(
                json.dumps(
                    {
                        "skipped": True,
                        "reason": str(exc),
                        "required_for_acceptance": "Run this smoke test on the Ubuntu/Debian validation host.",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(json.dumps(result, indent=2, sort_keys=True))
        try:
            os.unlink(args.socket)
        except FileNotFoundError:
            pass
        return 0

    parser.error("choose --server or --smoke")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
