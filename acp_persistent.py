"""Persistent kiro-cli workers via ACP (Agent Client Protocol).
JSON-RPC 2.0 over stdin/stdout. One process per worker, unlimited prompts.
Replaces acp.py as drop-in for the debate system.
"""
import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class ACPWorker:
    """Single persistent kiro-cli acp process."""

    def __init__(self, agent: str, work_dir: str, worker_id: int = 0):
        self.agent = agent
        self.work_dir = work_dir
        self.worker_id = worker_id
        self._proc: asyncio.subprocess.Process | None = None
        self._session_id: str | None = None
        self._req_id = 0
        self._turn_count = 0
        self.SESSION_RESET_EVERY = 40

    async def start(self):
        """Spawn kiro-cli acp and initialize."""
        self._proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "acp", "--agent", self.agent, "--trust-all-tools",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self.work_dir,
            env={**os.environ, "NO_COLOR": "1"},
        )
        await self._rpc("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": f"debate-worker-{self.worker_id}", "version": "1.0.0"},
        })
        await self._new_session()
        print(f"  [{_ts()}] 🟢 Worker {self.worker_id} started (pid={self._proc.pid})", flush=True)

    async def _new_session(self):
        result = await self._rpc("session/new", {"cwd": self.work_dir})
        self._session_id = result.get("sessionId")
        self._turn_count = 0

    async def prompt(self, text: str, timeout: float = 600) -> str:
        """Send a prompt, collect full response. Auto-resets session every N turns."""
        await self.ensure_alive()
        if self._turn_count >= self.SESSION_RESET_EVERY:
            await self._new_session()

        req_id = self._next_id()
        self._write({
            "jsonrpc": "2.0", "id": req_id,
            "method": "session/prompt",
            "params": {"sessionId": self._session_id,
                       "content": [{"type": "text", "text": text}]},
        })
        await self._proc.stdin.drain()

        chunks: list[str] = []
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=60)
            except asyncio.TimeoutError:
                continue  # keep waiting until deadline
            if not line:
                raise ConnectionError(f"Worker {self.worker_id}: ACP process died")
            try:
                data = json.loads(line.decode())
            except json.JSONDecodeError:
                continue  # skip non-JSON lines

            # Auto-approve tool permissions
            if data.get("method") == "session/request_permission":
                options = data.get("params", {}).get("options", [])
                option_id = options[0]["optionId"] if options else "allow_once"
                self._write({"jsonrpc": "2.0", "id": data["id"],
                             "result": {"outcome": {"outcome": "selected", "optionId": option_id}}})
                await self._proc.stdin.drain()
                continue

            # Collect streaming text
            if data.get("method") == "session/update":
                params = data.get("params", {})
                update = params.get("update", params)  # handle both nested and flat
                utype = update.get("sessionUpdate", "")
                if utype == "agent_message_chunk":
                    content = update.get("content", {})
                    if isinstance(content, dict):
                        chunks.append(content.get("text", ""))
                    elif isinstance(content, str):
                        chunks.append(content)
                elif "turn_end" in str(utype).lower() or "turnend" in str(utype).lower():
                    break
                continue

            # Final response (has matching id + result)
            if data.get("id") == req_id and "result" in data:
                # Extract text from result if present
                result = data.get("result", {})
                if isinstance(result, dict) and "content" in result:
                    for block in result["content"]:
                        if block.get("type") == "text":
                            chunks.append(block.get("text", ""))
                break

        self._turn_count += 1
        return "".join(chunks).strip()

    async def ensure_alive(self):
        if self._proc is None or self._proc.returncode is not None:
            await self.start()

    async def stop(self):
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
            print(f"  [{_ts()}] 🔴 Worker {self.worker_id} stopped", flush=True)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _write(self, msg: dict):
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())

    async def _rpc(self, method: str, params: dict) -> dict:
        req_id = self._next_id()
        self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        await self._proc.stdin.drain()
        while True:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=60)
            if not line:
                raise ConnectionError(f"Worker {self.worker_id}: ACP process died during {method}")
            try:
                data = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            if data.get("id") == req_id:
                if "error" in data:
                    raise RuntimeError(f"ACP error in {method}: {data['error']}")
                return data.get("result", {})
            # Skip notifications during handshake
            continue


class WorkerPool:
    """Elastic pool of persistent ACPWorker instances."""

    SYSTEM_CAP = 15
    MIN = 4
    MAX = 10

    def __init__(self, agent: str, work_dir: str):
        self.agent = agent
        self.work_dir = work_dir
        self._workers: list[ACPWorker] = []
        self._idle: asyncio.Queue[ACPWorker] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._counter = 0
        self._call_count = 0

    async def start(self):
        """Initialize pool with MIN workers."""
        print(f"[{_ts()}] [POOL] Starting {self.MIN} workers...", flush=True)
        for i in range(self.MIN):
            await self._spawn()
        print(f"[{_ts()}] [POOL] Ready ({len(self._workers)} workers)", flush=True)

    async def call_agent(self, task: str, work_dir: str = "", agent: str = "") -> str:
        """Drop-in replacement for acp.call_agent(). Gets a worker, sends prompt, returns."""
        self._call_count += 1
        cid = self._call_count
        preview = task[:50].replace("\n", " ")
        print(f"  [{_ts()}] 🚀 #{cid}: {preview}...", flush=True)
        start = time.time()

        # Get an idle worker (or scale up)
        worker = await self._acquire()
        try:
            result = await worker.prompt(task)
        except Exception as e:
            print(f"  [{_ts()}] ❌ #{cid} failed: {e}", flush=True)
            # Worker died — remove and respawn
            async with self._lock:
                if worker in self._workers:
                    self._workers.remove(worker)
            await self._spawn()
            raise
        finally:
            # Return worker to idle pool
            await self._idle.put(worker)

        elapsed = time.time() - start
        print(f"  [{_ts()}] ✅ #{cid} done ({elapsed:.0f}s)", flush=True)
        return result

    async def _acquire(self) -> ACPWorker:
        """Get an idle worker. Scale up if none available and under cap."""
        # Try to get one immediately
        try:
            return self._idle.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Try to scale up
        async with self._lock:
            if len(self._workers) < self.MAX and self._system_count() < self.SYSTEM_CAP:
                await self._spawn()
                return self._idle.get_nowait()

        # Wait for one to become available (backpressure)
        return await self._idle.get()

    async def _spawn(self):
        self._counter += 1
        w = ACPWorker(self.agent, self.work_dir, self._counter)
        await w.start()
        self._workers.append(w)
        await self._idle.put(w)

    def _system_count(self) -> int:
        r = subprocess.run(["pgrep", "-c", "kiro-cli"], capture_output=True, text=True)
        return int(r.stdout.strip()) if r.returncode == 0 else 0

    async def stop_all(self):
        print(f"[{_ts()}] [POOL] Stopping all workers...", flush=True)
        for w in self._workers:
            await w.stop()
        self._workers.clear()
        print(f"[{_ts()}] [POOL] All stopped.", flush=True)


# ── Module-level convenience (matches acp.py interface) ───────────────────────
_pool: WorkerPool | None = None


async def init_pool(agent: str = "bible-expert", work_dir: str = "."):
    global _pool
    _pool = WorkerPool(agent=agent, work_dir=work_dir)
    await _pool.start()


async def call_agent(task: str, work_dir: str = "", agent: str = "") -> str:
    """Drop-in for acp.call_agent()."""
    if _pool is None:
        raise RuntimeError("Pool not initialized. Call init_pool() first.")
    return await _pool.call_agent(task, work_dir, agent)


async def stop_pool():
    if _pool:
        await _pool.stop_all()
