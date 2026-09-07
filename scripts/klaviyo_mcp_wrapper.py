#!/usr/bin/env python3
"""
Wrapper for klaviyo-mcp-server that patches serverInfo.name in the initialize
response so multiple instances (TI, TE) can coexist in Claude Code without
being deduplicated.

Usage:
    PRIVATE_API_KEY=... SERVER_NAME=klaviyo-te python3 klaviyo_mcp_wrapper.py uvx klaviyo-mcp-server@latest
"""
import json
import os
import subprocess
import sys
import threading


def pipe_with_patch(src, dst, patch_name=None):
    """Copy lines from src to dst, optionally patching the serverInfo.name."""
    patched = False
    for line in src:
        if patch_name and not patched:
            try:
                msg = json.loads(line)
                result = msg.get("result", {})
                server_info = result.get("serverInfo", {})
                if server_info.get("name"):
                    server_info["name"] = patch_name
                    result["serverInfo"] = server_info
                    msg["result"] = result
                    line = (json.dumps(msg) + "\n").encode()
                    patched = True
            except (json.JSONDecodeError, AttributeError):
                pass
        dst.write(line)
        dst.flush()


def main():
    server_name = os.environ.get("SERVER_NAME")
    cmd = sys.argv[1:]

    if not cmd:
        print("Usage: klaviyo_mcp_wrapper.py <command> [args...]", file=sys.stderr)
        sys.exit(1)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
    )

    # stdin → proc.stdin (no patching needed)
    def forward_stdin():
        try:
            for line in sys.stdin.buffer:
                proc.stdin.write(line)
                proc.stdin.flush()
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    t = threading.Thread(target=forward_stdin, daemon=True)
    t.start()

    # proc.stdout → stdout (patch serverInfo.name on first initialize response)
    pipe_with_patch(proc.stdout, sys.stdout.buffer, patch_name=server_name)

    proc.wait()
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
