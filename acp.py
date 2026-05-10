"""Agent wrapper using kiro-cli chat --no-interactive.
One call per exchange, but full contention history passed each time for context."""
import asyncio
import os
import re
import time

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b\[\?[0-9]*[hl]|\x1b\[[0-9]*G')
_PROC_SEM = asyncio.Semaphore(10)
_active: dict[int, dict] = {}
_counter = 0


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _clean(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    lines = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("> "):
            line = line[2:]
        if line.startswith("▸ Credits:") or not line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


async def call_agent(task: str, work_dir: str, agent: str = "investigator-child") -> str:
    """Single kiro-cli call. Full context must be in the task prompt."""
    global _counter
    _counter += 1
    cid = _counter
    preview = task[:50].replace("\n", " ")
    _active[cid] = {"start": time.time(), "task": preview}
    print(f"  [{_ts()}] 🚀 #{cid}: {preview}...", flush=True)

    async with _PROC_SEM:
        proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "chat", "--no-interactive",
            "--agent", agent, "--trust-all-tools", task,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
            env={**os.environ, "NO_COLOR": "1"},
        )
        stdout, _ = await proc.communicate()

    elapsed = time.time() - _active[cid]["start"]
    del _active[cid]
    result = _clean(stdout.decode())
    print(f"  [{_ts()}] ✅ #{cid} done ({elapsed:.0f}s)", flush=True)
    return result


async def status_ticker(interval: int = 30):
    while True:
        await asyncio.sleep(interval)
        if _active:
            now = time.time()
            print(f"\n  [{_ts()}] 📊 {len(_active)} agents running:", flush=True)
            for cid, info in sorted(_active.items()):
                print(f"    #{cid} ({now - info['start']:.0f}s) {info['task']}", flush=True)
            print(flush=True)
