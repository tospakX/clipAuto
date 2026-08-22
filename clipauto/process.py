from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable, Sequence


class ProcessError(RuntimeError):
    def __init__(self, command: Sequence[str], returncode: int, output: str):
        super().__init__(output.strip() or f"Process exited with code {returncode}")
        self.command = list(command)
        self.returncode = returncode
        self.output = output


class ProcessCancelled(RuntimeError):
    pass


async def run_process(
    command: Sequence[str],
    on_line: Callable[[str], None] | None = None,
    cancel_event: asyncio.Event | None = None,
) -> str:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    assert process.stdout is not None
    lines: list[str] = []
    try:
        while True:
            if cancel_event and cancel_event.is_set():
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                raise ProcessCancelled("Processing was cancelled")
            try:
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=0.25)
            except TimeoutError:
                if process.returncode is not None:
                    break
                continue
            if not raw:
                break
            line = raw.decode(errors="replace").rstrip()
            lines.append(line)
            if len(lines) > 250:
                lines.pop(0)
            if on_line:
                on_line(line)
        returncode = await process.wait()
    except asyncio.CancelledError:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGTERM)
            await process.wait()
        raise
    output = "\n".join(lines)
    if returncode:
        raise ProcessError(command, returncode, output)
    return output
