# Persistent kiro-cli Agents: Internal Investigation Findings

## Executive Summary

**The answer is `kiro-cli acp` (Agent Client Protocol).** This is a JSON-RPC 2.0 interface over stdin/stdout that keeps kiro-cli alive as a persistent subprocess. Multiple production systems at Amazon already use this pattern for exactly what you need: persistent agent workers that process multiple prompts without restarting.

---

## 1. The ACP Protocol (Agent Client Protocol)

### What It Is
- JSON-RPC 2.0 over stdin/stdout
- Originated by the Zed team, adopted by Kiro
- Same protocol JetBrains IDEs use to talk to kiro
- Available since kiro-cli 1.25.0

### How to Start
```bash
kiro-cli acp                          # default agent
kiro-cli acp --agent bible-expert     # specific agent
kiro-cli acp --trust-all-tools        # auto-approve all tools
```

### Protocol Flow
```
initialize → session/new → session/prompt (loop forever) → session/cancel (optional)
```

### Key Protocol Methods
| Method | Direction | Purpose |
|--------|-----------|---------|
| `initialize` | Client→Agent | Capability negotiation |
| `session/new` | Client→Agent | Create session (accepts cwd, mcpServers) |
| `session/prompt` | Client→Agent | Send user message |
| `session/update` | Agent→Client | Streams all activity (text chunks, tool calls) |
| `session/cancel` | Client→Agent | Cancel in-progress turn |
| `session/load` | Client→Agent | Resume previous session |
| `session/request_permission` | Agent→Client | Tool approval request |
| `session/set_mode` | Client→Agent | Switch agent |
| `session/set_model` | Client→Agent | Switch model |

### Critical Limitations
- **Multi-session per process NOT supported** — MCP servers initialize once; concurrent users need separate processes
- **No service-account auth** — requires human SSO identity (IAM Identity Center)
- **No dynamic system prompt injection** — system prompt is static at process start
- **Context auto-compacts at ~90%** — older messages summarized, tools still work

Sources: [Kiro ACP wiki](https://w.amazon.com/bin/view/Users/yanliag/kb/wiki/entities/kiro-acp/), [KiroClaw docs](code.amazon.com/packages/KiroClaw), [Botctl](code.amazon.com/packages/Botctl)

---

## 2. Python ACP Client Implementation (Copy-Paste Ready)

Based on patterns from AGIArsenalMesh, AISlackBot, ATXKiroPowerPythonEvalScenarioFramework, Agent-Orchestrator, and 10+ other repos:

```python
"""ACP client for persistent kiro-cli connection — JSON-RPC 2.0 over stdio."""

import asyncio
import json
from pathlib import Path

class AcpClient:
    """Single ACP connection to a kiro-cli acp child process."""

    def __init__(self, agent: str, cwd: str = None):
        self._agent = agent
        self._cwd = cwd or str(Path.home())
        self._proc = None
        self._request_id = 0
        self._session_id = None

    async def start(self):
        """Spawn kiro-cli acp, initialize, create session."""
        self._proc = await asyncio.create_subprocess_exec(
            "kiro-cli", "acp", "--agent", self._agent, "--trust-all-tools",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=self._cwd,
            start_new_session=True,  # own process group for clean kill
        )
        # Initialize
        await self._request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "debate-worker", "version": "1.0.0"},
        })
        # Create session
        result = await self._request("session/new", {
            "cwd": self._cwd,
            "mcpServers": [],
        })
        self._session_id = result["sessionId"]

    async def prompt(self, text: str, timeout: float = 900) -> str:
        """Send prompt, collect streaming response, auto-approve permissions."""
        req_id = self._next_id()
        msg = {
            "jsonrpc": "2.0", "id": req_id,
            "method": "session/prompt",
            "params": {
                "sessionId": self._session_id,
                "content": [{"type": "text", "text": text}],
            },
        }
        self._write(msg)

        chunks = []
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            line = await asyncio.wait_for(
                self._proc.stdout.readline(), timeout=30
            )
            if not line:
                raise ConnectionError("ACP process died")
            data = json.loads(line.decode())

            # Auto-approve tool permissions
            if data.get("method") == "session/request_permission":
                perm_id = data.get("id")
                options = data.get("params", {}).get("options", [])
                option_id = options[0]["optionId"] if options else "allow_once"
                await self._send_response(perm_id, {
                    "outcome": {"outcome": "selected", "optionId": option_id}
                })
                continue

            # Collect text chunks from session/update
            if data.get("method") == "session/update":
                update = data.get("params", {}).get("update", {})
                utype = update.get("sessionUpdate", "")
                if utype == "agent_message_chunk":
                    text_content = update.get("content", {}).get("text", "")
                    if text_content:
                        chunks.append(text_content)
                continue

            # Final response (has result with stopReason)
            if "id" in data and data["id"] == req_id and "result" in data:
                break

        return "".join(chunks)

    async def new_session(self):
        """Create a fresh session (resets context window)."""
        result = await self._request("session/new", {
            "cwd": self._cwd, "mcpServers": [],
        })
        self._session_id = result["sessionId"]

    async def ensure_alive(self):
        """Restart if process died."""
        if self._proc is None or self._proc.returncode is not None:
            await self.start()

    async def stop(self):
        """Kill the process."""
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _write(self, msg: dict):
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())

    async def _request(self, method: str, params: dict) -> dict:
        req_id = self._next_id()
        self._write({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        await self._proc.stdin.drain()
        # Read until we get our response
        while True:
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30)
            if not line:
                raise ConnectionError("ACP process died during request")
            data = json.loads(line.decode())
            if data.get("id") == req_id:
                if "error" in data:
                    raise RuntimeError(f"ACP error: {data['error']}")
                return data.get("result", {})
            # Skip notifications during handshake

    async def _send_response(self, request_id, result: dict):
        msg = {"jsonrpc": "2.0", "id": request_id, "result": result}
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()
```

Sources: AGIArsenalMesh/arsenal/acp/client.py, AISlackBot/acp_client.py, Agent-Orchestrator/skills/agent-orchestrator/scripts/agent_orchestrator.py, AlfredAgentBridge/src/alfred_agent_bridge/acp_client.py

---

## 3. Worker Pool Architecture (from Botctl)

Botctl (code.amazon.com/packages/Botctl) implements a production-grade worker pool:

### Architecture
```
Orchestrator → acp-proxy (pool manager) → kiro-cli acp (workers)
```

### Config (TOML)
```toml
[agent]
command = "kiro-cli acp"
max_workers = 5
idle_timeout_secs = 300
mcp_wait_ms = 2000

[agent.pool]
strategy = "worker"
max_workers = 5
```

### Key Features
- **Worker pool with max_workers** — caps concurrent kiro-cli processes
- **Idle timeout reaping** — kills workers idle > N seconds (60s reap interval)
- **Auto-respawn on crash** — if kiro-cli dies, next prompt triggers respawn
- **Session routing** — maps conversation→worker, routes prompts to correct process
- **Warm pool** — pre-spawns workers for instant availability
- **Process group management** — SIGKILL entire process group on cleanup

### Pool Capacity Model
```rust
pub struct PoolCapacity {
    pub active: usize,   // workers with assigned conversations
    pub warm: usize,     // pre-spawned, waiting for assignment
    pub spawning: usize, // currently starting up
    pub max: usize,      // hard cap
}
```

Source: code.amazon.com/packages/Botctl/crates/acp-proxy/src/lib.rs

---

## 4. The "Never Stop" Pattern — Proven Approaches

### Approach A: ACP + External Queue (RECOMMENDED)

Your Python orchestrator manages the queue. kiro-cli stays alive via ACP. Each prompt is a debate turn.

```python
class DebateWorker:
    """Persistent kiro-cli worker that processes debate turns via ACP."""

    def __init__(self, agent: str, worker_id: int):
        self.client = AcpClient(agent=agent, cwd="/path/to/debate")
        self.worker_id = worker_id
        self.busy = False

    async def start(self):
        await self.client.start()
        # Wait for MCP servers to initialize (~3-5 seconds)
        await asyncio.sleep(5)

    async def process_turn(self, work_item: dict) -> str:
        """Process a single debate turn."""
        self.busy = True
        try:
            await self.client.ensure_alive()
            response = await self.client.prompt(work_item["prompt"])
            return response
        finally:
            self.busy = False

    async def reset_context(self):
        """Create fresh session when context fills up."""
        await self.client.new_session()
```

### Approach B: Instruct Agent to Poll (NOT RECOMMENDED)

From Hanami and KiroClaw learnings: **Don't make the LLM poll.** The LLM will:
- Decide it's "done" and stop
- Hallucinate queue items
- Waste tokens on polling logic
- Hit context limits faster

Instead: **Keep the LLM passive. Your orchestrator sends prompts when work arrives.**

### Approach C: tmux + kb bridge (Alternative)

From the Multi-Agent Orchestration wiki (SCP/ContributionCatalog):
- 16+ persistent kiro-cli sessions in tmux panes
- Python bridge (`kb`) dispatches tasks via `kb send PANE "prompt"`
- Workers stay alive for follow-ups
- Leader monitors with `kb status` and `kb watch`

This works but is heavier than ACP for your use case.

---

## 5. Context Window Management

### Auto-Compaction
- kiro-cli auto-compacts when context reaches ~90%
- Older messages are summarized (destructive, irreversible)
- Tool access is preserved after compaction
- MCP servers remain connected

### Strategy for Debate System
1. **One session per debate** — create session at debate start
2. **Monitor context usage** — `_kiro.dev/metadata` notification reports `contextUsagePercentage`
3. **Fresh session per turn** — if context > 80%, call `session/new` and inject minimal context
4. **Or: fresh session every N turns** — simpler, predictable

### Session Persistence
- Sessions stored in `~/.kiro/sessions/cli/{session_id}.json` + `.jsonl`
- Can resume with `session/load` (sends session_id)
- Survives process restart (KiroClaw pattern: restart process, reload session)

---

## 6. Concrete Implementation Plan for Truth-Seeking Debate

### Architecture
```
Python Orchestrator (asyncio)
    │
    ├── WorkerPool (4-10 workers)
    │   ├── DebateWorker[0] → kiro-cli acp --agent bible-expert
    │   ├── DebateWorker[1] → kiro-cli acp --agent bible-expert
    │   ├── DebateWorker[2] → kiro-cli acp --agent bible-expert
    │   └── DebateWorker[3] → kiro-cli acp --agent bible-expert
    │
    ├── WorkQueue (asyncio.Queue)
    │   └── {turn_id, prompt, debate_id, role}
    │
    └── ResultCollector
        └── results/{turn_id}.json
```

### Queue Implementation (Filesystem — simplest)
```
queue/
├── pending/     # orchestrator writes here
│   ├── 001.json
│   └── 002.json
├── processing/  # worker moves here while working
│   └── 003.json
└── done/        # worker writes result here
    └── 003.json
```

But since your orchestrator is Python asyncio, **use `asyncio.Queue` directly** — no filesystem queue needed. The orchestrator already knows what work to dispatch.

### Elastic Scaling
```python
class WorkerPool:
    def __init__(self, agent: str, min_workers=4, max_workers=10):
        self.workers = []
        self.agent = agent
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.queue = asyncio.Queue()

    async def scale_up(self):
        if len(self.workers) < self.max_workers:
            worker = DebateWorker(self.agent, len(self.workers))
            await worker.start()
            self.workers.append(worker)

    async def scale_down(self):
        idle = [w for w in self.workers if not w.busy]
        if len(idle) > self.min_workers:
            victim = idle[-1]
            await victim.client.stop()
            self.workers.remove(victim)

    def get_idle_worker(self) -> DebateWorker | None:
        for w in self.workers:
            if not w.busy:
                return w
        return None
```

### Crash Recovery
- Check `proc.returncode is not None` before each prompt
- If dead: `await client.start()` (respawns process)
- Work item stays in queue until result confirmed
- KiroClaw pattern: "If kiro-cli crashes mid-turn, restart process, reload session, identify suspect tool call, retry with hint"

### Process Counting
```bash
pgrep -c "kiro-cli"  # count all kiro-cli processes
```

### Stopping Workers
```python
await worker.client.stop()  # SIGTERM → wait 5s → SIGKILL
# Or: os.killpg(os.getpgid(proc.pid), signal.SIGTERM)  # kill process group
```

---

## 7. Custom Agent Definition

Create `~/.kiro/agents/debate-worker.json`:
```json
{
  "$schema": "https://raw.githubusercontent.com/aws/amazon-q-developer-cli/refs/heads/main/schemas/agent-v1.json",
  "name": "debate-worker",
  "description": "Persistent debate worker with bible research tools",
  "prompt": "You are a biblical scholar participating in a truth-seeking debate...",
  "tools": ["bible_tools", "web_search", "patristic_commentary", "morphology_analysis"],
  "allowedTools": ["bible_tools", "web_search", "patristic_commentary", "morphology_analysis"],
  "mcpServers": {},
  "includeMcpJson": true
}
```

---

## 8. Key Differences from Current `--no-interactive` Approach

| Aspect | Current (--no-interactive) | ACP (persistent) |
|--------|---------------------------|-------------------|
| Startup time | 15-20s per turn (MCP init) | 15-20s once, then instant |
| Process count | 700+ over a debate | 4-10 total |
| Context | Lost between turns | Preserved across turns |
| MCP tools | Re-initialized each time | Initialized once |
| Crash recovery | Start from scratch | Respawn + resume session |
| Cost | High (repeated init) | Low (amortized) |

---

## 9. Related Projects to Study

| Project | What It Does | Relevance |
|---------|-------------|-----------|
| **Botctl** | Rust worker pool for kiro-cli ACP | Production pool implementation |
| **KiroClaw** | Python async ACP runner with crash recovery | Closest to your needs |
| **Hanami** | Rust orchestrator with DAG task scheduling | Task queue + worker pattern |
| **AMek** | HTTP task queue for AI agents with MCP | Pull-based queue design |
| **KiroGateway** | Express + React managing ACP sessions | Session registry pattern |
| **Agent-Orchestrator** | Python daemon managing persistent ACP agents | Daemon + prompt dispatch |
| **PersonalKiroSlackAgent** | Python ACP client with auto-approve | Simple Python reference |

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Context window fills up | Create new session every N turns or when >80% |
| kiro-cli crashes | Auto-respawn (check returncode before each prompt) |
| MCP server disconnects | `--require-mcp-startup` flag; restart process |
| Auth token expires | kiro-cli handles refresh; if fails, restart |
| Too many processes | Hard cap at 15; `pgrep -c kiro-cli` check |
| Prompt timeout | 900s timeout per prompt; cancel + retry |

---

## Sources

1. Wiki: [KiroCLI](https://w.amazon.com/bin/view/DCCS/DAGenAI/Tools/KiroCLI/) — DA GenAI team's comprehensive guide
2. Wiki: [Kiro ACP](https://w.amazon.com/bin/view/Users/yanliag/kb/wiki/entities/kiro-acp/) — Protocol reference
3. Wiki: [Kiro ACP Testing](https://w.amazon.com/bin/view/Users/swinyted/kiro-acp-testing/) — Python PoC
4. Wiki: [PersonalKiroSlackAgent](https://w.amazon.com/bin/view/Users/jiangyan/poc/PersonalKiroSlackAgent/) — ACP client pattern
5. Wiki: [Hanami AI Factory](https://w.amazon.com/bin/view/CloudWatchLogs/AIWins/2026/04/21/HanamiAIFactory/) — Worker orchestration
6. Wiki: [Multi-Agent Orchestration with tmux](https://w.amazon.com/bin/view/SCP/ContributionCatalog/Blog/2026-03-09-Multi-Agent-Orchestration-with-Kiro-and-tmux/) — Persistent workers
7. Wiki: [KiroClaw](https://w.amazon.com/bin/view/Users/ningsong/2026/kiroclaw_intro/) — ACP runner with crash recovery
8. Wiki: [AMek Task Queue](https://w.amazon.com/bin/view/Users/anhho/amek-A-task-queue-for-AI-agents-in-your-team/) — Pull-based queue
9. Wiki: [Resuming Kiro CLI Sessions](https://w.amazon.com/bin/view/AmazonFCNetworking/Runbooks/AI/Resuming-Kiro-CLI-Sessions/) — Session management
10. Wiki: [Kiro CLI Persistence Guide](https://w.amazon.com/bin/view/Users/reetheo/tips/kiro-cli-persistence/) — Storage details
11. Code: Botctl/crates/acp-proxy/src/lib.rs — Worker pool implementation
12. Code: AGIArsenalMesh/arsenal/acp/client.py — Async Python ACP client
13. Code: AISlackBot/acp_client.py — Sync Python ACP client
14. Code: Agent-Orchestrator/skills/agent-orchestrator/scripts/agent_orchestrator.py — Daemon pattern
15. BuilderHub: [Getting started with Kiro CLI](https://docs.hub.amazon.dev/docs/kiro/user-guide/getting-started-cli/) — Official docs
