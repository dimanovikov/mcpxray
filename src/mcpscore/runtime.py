"""Runtime capture — spawn an MCP server and read its ``tools/list`` over stdio.

For servers whose tools can't be discovered statically (compiled, 3rd-party, or
built dynamically at runtime), this opt-in path launches the server, performs
the MCP JSON-RPC 2.0 handshake (``initialize`` → ``notifications/initialized``
→ ``tools/list``) over its stdio transport, and returns the declared tools.
The CLI feeds the result to :func:`mcpscore.extract.manifest.from_tools`, so the
rest of the pipeline (rules → score → verdict) is reused unchanged.

.. warning::

   This **executes the server under inspection**, which may be untrusted code.
   It is strictly opt-in (``--runtime --command``) and provides process
   isolation + bounded lifetime only — **there is no OS-level sandbox** (no
   filesystem or network isolation). Only point it at servers you trust, or run
   mcpscore inside a container/VM when inspecting untrusted servers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import signal
from dataclasses import dataclass
from pathlib import Path

from mcpscore import __version__

# --- protocol constants -------------------------------------------------------
_PROTOCOL_VERSION = "2024-11-05"
_INIT_ID = 1
_LIST_ID = 2
_EXIT_TIMEOUT = 3.0  # grace period for the server to exit on EOF before we kill it


class CaptureError(RuntimeError):
    """Raised for any spawn / handshake / timeout / parse failure during capture."""


@dataclass
class CaptureResult:
    """The outcome of a successful ``tools/list`` capture."""

    tools: list[dict]
    server_name: str | None
    server_version: str | None


# --- message builders (pure, unit-tested) ------------------------------------
def _initialize_msg(req_id: int) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "initialize",
        "params": {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "mcpscore", "version": __version__},
        },
    }


def _initialized_notification() -> dict:
    # A notification carries no ``id`` and expects no response.
    return {"jsonrpc": "2.0", "method": "notifications/initialized"}


def _tools_list_msg(req_id: int) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}}


def split_command(command: str) -> list[str]:
    """POSIX-split a ``--command`` string into an argv list (raises if empty)."""
    argv = shlex.split(command)
    if not argv:
        raise CaptureError(f"could not parse a launch command from {command!r}")
    return argv


# --- stdio transport ----------------------------------------------------------
async def _send(proc: asyncio.subprocess.Process, msg: dict) -> None:
    if proc.stdin is None:
        raise CaptureError("server has no stdin to write to")
    proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
    await proc.stdin.drain()


async def _read_response(
    proc: asyncio.subprocess.Process, expected_id: int, timeout: float, label: str
) -> dict:
    """Read newline-delimited JSON until the response with ``expected_id`` arrives."""

    async def _read() -> dict:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                raise CaptureError(f"server closed its output before answering {label}")
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue  # non-JSON line (log noise on stdout) — skip
            if isinstance(obj, dict) and obj.get("id") == expected_id:
                return obj
            # otherwise a notification / unrelated response — keep reading

    try:
        return await asyncio.wait_for(_read(), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise CaptureError(f"timed out waiting for the server's {label} response") from e


async def _drain_stderr(stderr: asyncio.StreamReader, sink: list[str]) -> None:
    """Continuously read stderr so a full pipe buffer can't deadlock the server."""
    try:
        while True:
            chunk = await stderr.read(4096)
            if not chunk:
                break
            sink.append(chunk.decode("utf-8", "replace"))
    except (OSError, asyncio.LimitOverrunError):
        pass


def _kill(proc: asyncio.subprocess.Process) -> None:
    """Force-kill the server (and its process group, where supported)."""
    try:
        if os.name == "nt":
            proc.kill()  # TerminateProcess on the direct child only
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # whole session/group
    except (ProcessLookupError, OSError):
        pass


async def _shutdown(proc: asyncio.subprocess.Process) -> None:
    """Close stdin, wait briefly for exit, then force-kill if still alive."""
    if proc.stdin is not None:
        with contextlib.suppress(BaseException):
            proc.stdin.close()
    try:
        await asyncio.wait_for(proc.wait(), timeout=_EXIT_TIMEOUT)
        return
    except asyncio.TimeoutError:
        pass
    _kill(proc)
    with contextlib.suppress(Exception):
        await proc.wait()


async def _spawn(argv: list[str], cwd: Path | None) -> asyncio.subprocess.Process:
    kwargs: dict = {}
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if os.name != "nt":
        kwargs["start_new_session"] = True  # own process group → killable as a unit
    try:
        return await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
    except FileNotFoundError as e:
        raise CaptureError(f"could not start server: executable not found ({argv[0]!r})") from e
    except OSError as e:
        raise CaptureError(f"could not start server: {e}") from e


async def _handshake(
    proc: asyncio.subprocess.Process, init_timeout: float, list_timeout: float
) -> CaptureResult:
    await _send(proc, _initialize_msg(_INIT_ID))
    init_resp = await _read_response(proc, _INIT_ID, init_timeout, "initialize")
    init_result = init_resp.get("result")
    init_result = init_result if isinstance(init_result, dict) else {}
    info = init_result.get("serverInfo")
    info = info if isinstance(info, dict) else {}
    server_name = info.get("name") if isinstance(info.get("name"), str) else None
    server_version = info.get("version") if isinstance(info.get("version"), str) else None

    await _send(proc, _initialized_notification())
    await _send(proc, _tools_list_msg(_LIST_ID))
    list_resp = await _read_response(proc, _LIST_ID, list_timeout, "tools/list")
    if isinstance(list_resp.get("error"), dict):
        msg = list_resp["error"].get("message", "tools/list returned an error")
        raise CaptureError(f"tools/list failed: {msg}")

    list_result = list_resp.get("result")
    list_result = list_result if isinstance(list_result, dict) else {}
    tools = list_result.get("tools")
    if not isinstance(tools, list):
        raise CaptureError("tools/list did not return a 'tools' list")

    return CaptureResult(tools=tools, server_name=server_name, server_version=server_version)


async def _capture(
    argv: list[str], *, cwd: Path | None, init_timeout: float, list_timeout: float
) -> CaptureResult:
    proc = await _spawn(argv, cwd)
    # Drain stderr in the background: a server that logs heavily to stderr would
    # otherwise fill the OS pipe buffer and deadlock before we read its stdout.
    stderr_sink: list[str] = []
    stderr_task = (
        asyncio.create_task(_drain_stderr(proc.stderr, stderr_sink))
        if proc.stderr is not None
        else None
    )

    err: CaptureError | None = None
    result: CaptureResult | None = None
    try:
        result = await _handshake(proc, init_timeout, list_timeout)
    except CaptureError as e:
        err = e
    except Exception as e:  # noqa: BLE001 — surface any protocol-level surprise
        err = CaptureError(f"unexpected error during capture: {e}")

    # Shut down first: killing the process closes the pipes, letting the drainer finish.
    await _shutdown(proc)
    if stderr_task is not None:
        stderr_task.cancel()
        with contextlib.suppress(BaseException):
            await stderr_task

    if err is not None:
        tail = "".join(stderr_sink).strip()
        if tail:
            msg = f"{err.args[0]}\n  server stderr (tail):\n  {tail[-1200:]}"
            raise CaptureError(msg) from None
        raise err
    assert result is not None
    return result


def capture_tools(
    argv: list[str],
    *,
    cwd: Path | None = None,
    init_timeout: float = 15.0,
    list_timeout: float = 15.0,
) -> CaptureResult:
    """Spawn ``argv``, run the MCP stdio handshake, return the captured tools.

    Raises :class:`CaptureError` on any spawn / handshake / timeout / parse
    failure. Synchronous wrapper over the async implementation.
    """
    if not argv:
        raise CaptureError("no launch command provided")
    return asyncio.run(
        _capture(argv, cwd=cwd, init_timeout=init_timeout, list_timeout=list_timeout)
    )
