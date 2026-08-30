"""Entry point of the local background service.

Startup contract with the host process:

1. The host generates a token and passes it on standard input (first line)
   or via --token. It is never written to a file.
2. The service binds a random free port on 127.0.0.1.
3. The service prints one JSON handshake line to standard output:
   {"event": "ready", "port": <int>, "pid": <int>, "version": "..."}
4. The service keeps running even after the host process disappears.
   Standard input is read exactly once and then ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from . import __version__
from .api.server import create_app
from .storage import paths


def _read_token(cli_token: str | None) -> str:
    if cli_token:
        return cli_token
    line = sys.stdin.readline().strip() if not sys.stdin.closed else ""
    if not line:
        print(json.dumps({"event": "error", "reason": "no_token"}), flush=True)
        raise SystemExit(2)
    return line


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _service_already_running() -> int | None:
    """Return the port of a live instance, if the runtime file points at one."""
    runtime = paths.runtime_file()
    if not runtime.exists():
        return None
    try:
        data = json.loads(runtime.read_text(encoding="utf-8"))
        port = int(data["port"])
    except (OSError, ValueError, KeyError):
        return None
    request = urllib.request.Request(f"http://127.0.0.1:{port}/health")
    try:
        urllib.request.urlopen(request, timeout=1.0)
    except urllib.error.HTTPError as exc:
        # 401 means: something is listening and it speaks our protocol.
        return port if exc.code == 401 else None
    except OSError:
        return None
    return port


def _publish_runtime(port: int) -> Path:
    runtime = paths.runtime_file()
    runtime.write_text(
        json.dumps({"port": port, "pid": os.getpid(), "version": __version__}),
        encoding="utf-8",
    )
    return runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--token", default=None)
    parser.add_argument("--allow-second-instance", action="store_true")
    args = parser.parse_args(argv)

    paths.ensure_layout()

    if not args.allow_second_instance:
        running = _service_already_running()
        if running is not None:
            print(json.dumps({"event": "already_running", "port": running}), flush=True)
            return 3

    token = _read_token(args.token)
    port = _free_port()
    runtime = _publish_runtime(port)

    print(
        json.dumps({"event": "ready", "port": port, "pid": os.getpid(), "version": __version__}),
        flush=True,
    )

    config = uvicorn.Config(
        create_app(token),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    try:
        uvicorn.Server(config).run()
    finally:
        try:
            if runtime.exists():
                runtime.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
