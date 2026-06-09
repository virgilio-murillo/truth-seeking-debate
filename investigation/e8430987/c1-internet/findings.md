# Investigation: Persistent kiro-cli Agents as Queue Workers

## Executive Summary

**The Ralph Loop pattern adapted for kiro-cli is the recommended approach.** Instead of keeping a single kiro-cli process alive forever (which is not natively supported), use a bash `while` loop that repeatedly invokes `kiro-cli chat --no-interactive` with fresh context per iteration. Each iteration reads from a filesystem queue, processes one work item, and writes results back. This gives you fresh context every turn (no degradation), crash resilience, and full MCP tool access.

---

## 1. kiro-cli Capabilities (Confirmed from Official Docs)

### Headless Mode (`--no-interactive`)
- **Source**: https://kiro.dev/docs/cli/headless/
- Requires `KIRO_API_KEY` environment variable
- Syntax: `kiro-cli chat --no-interactive --trust-all-tools "prompt here"`
- Prints response to stdout and exits
- **Limitation**: "No mid-session user input is possible" — single prompt in, single response out
- Can pipe context: `cat file.txt | kiro-cli chat --no-interactive "process this"`
- Supports `--agent` flag to use custom agent configurations
- Supports `--trust-all-tools` or `--trust-tools=read,grep,write` for unattended execution

### Session Management
- **Source**: https://kiro.dev/docs/cli/chat/session-management/
- Sessions auto-save per-directory to SQLite in `~/.kiro/`
- Can resume: `kiro-cli chat --resume-id <SESSION_ID>`
- **Key insight**: `--resume-id` could theoretically maintain conversation history across calls
- However, for the Ralph Loop pattern, fresh context per iteration is BETTER (avoids degradation)

### Context Compaction
- **Source**: https://kiro.dev/changelog/cli/1-24/
- `/compact` command summarizes conversation history
- Auto-triggers when context window overflows
- Configurable: `compaction.excludeMessages` and `compaction.excludeContextWindowPercent`
- **Implication**: Even if you kept a session alive, compaction is lossy — fresh context is superior

### Custom Agent Configuration
- **Source**: https://kiro.dev/docs/cli/custom-agents/configuration-reference/
- JSON format stored in `~/.kiro/agents/` (global) or `.kiro/agents/` (project)
- Key fields: `name`, `prompt`, `tools`, `mcpServers`, `allowedTools`, `hooks`, `resources`
- `prompt` supports `file://` URIs for external prompt files
- **Hooks** available: `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop`
- The `stop` hook fires when the assistant finishes responding — could theoretically be used for "never stop" but only in interactive mode

### Subagents
- **Source**: https://kiro.dev/docs/cli/chat/subagents/
- Up to 4 parallel subagents
- DAG-based task dependencies
- Each subagent gets its own isolated context
- `trustedAgents` config allows unattended spawning
- **Not suitable for persistent workers** — subagents are ephemeral within a parent session

### Stdin Piping
- **Confirmed**: `cat build-error.log | kiro-cli chat --no-interactive "Explain this"` works
- **Confirmed**: Blog post says "You can pipe inputs, script outputs"
- **NOT confirmed**: Interactive mode reading from stdin pipe in non-TTY (likely fails — GitHub issue #4497 mentions "Bad file descriptor" on Linux for interactive mode without TTY)

---

## 2. The Ralph Loop Pattern (Adapted for kiro-cli)

### What Is It?
The Ralph Loop is a recursive AI agent pattern where a coding agent runs in an infinite shell loop, reading a prompt file each iteration, using the filesystem as memory instead of conversation history. Each iteration starts with a fresh context window.

**Sources**:
- https://thomas-wiegold.com/blog/ralph-loop-how-recursive-ai-agents-work/
- https://blakecrosley.com/blog/ralph-agent-architecture
- https://github.com/snarktank/ralph
- https://github.com/vercel-labs/ralph-loop-agent

### Core Principle
```bash
while :; do cat PROMPT.md | kiro-cli chat --no-interactive --agent debate-worker --trust-all-tools; done
```

### Why Fresh Context Per Iteration Is BETTER Than Persistent Sessions

1. **LLMs degrade past ~100K tokens** — quality measurably drops in the "Dumb Zone"
2. **Compaction is lossy** — specs get summarized into vagueness
3. **Each iteration gets full cognitive resources** applied to current state
4. **Crash resilience** — if the process dies, the loop restarts cleanly
5. **No state corruption** — filesystem IS the memory

### Adaptation for Debate System

Instead of the generic Ralph pattern (one task from a TODO file), adapt it to:
1. Read the OLDEST pending work item from `queue/pending/`
2. Process it using MCP tools (bible-tools, web_search, etc.)
3. Write result to `queue/results/`
4. Move work item to `queue/done/`
5. Loop

---

## 3. Concrete Implementation Plan

### Architecture

```
┌─────────────────────────────────────────────────────┐
│  Python Orchestrator (asyncio)                       │
│  - Writes work items to queue/pending/               │
│  - Polls queue/results/ for completed work           │
│  - Manages worker processes (4-10)                   │
│  - Elastic scaling based on queue depth              │
└─────────────────────────────────────────────────────┘
         │ writes                    │ reads
         ▼                          ▼
┌─────────────────────────────────────────────────────┐
│  Filesystem Queue                                    │
│  queue/pending/001.json  002.json  003.json          │
│  queue/in-progress/                                  │
│  queue/results/001.json                              │
│  queue/done/001.json                                 │
│  queue/errors/001.json                               │
└─────────────────────────────────────────────────────┘
         ▲ reads                    ▲ writes
         │                          │
┌─────────────────────────────────────────────────────┐
│  Worker Bash Loops (4-10 processes)                   │
│  while :; do                                         │
│    ITEM=$(pick_oldest queue/pending/)                 │
│    mv $ITEM queue/in-progress/                       │
│    RESULT=$(kiro-cli chat --no-interactive ...)       │
│    write_result queue/results/                        │
│    mv in-progress/$ITEM queue/done/                  │
│  done                                                │
└─────────────────────────────────────────────────────┘
```

### Worker Script (`worker.sh`)

```bash
#!/bin/bash
set -euo pipefail

WORKER_ID="${1:-worker-$$}"
AGENT="${2:-bible-expert}"
QUEUE_DIR="${3:-./queue}"
PENDING="$QUEUE_DIR/pending"
IN_PROGRESS="$QUEUE_DIR/in-progress"
RESULTS="$QUEUE_DIR/results"
DONE="$QUEUE_DIR/done"
ERRORS="$QUEUE_DIR/errors"

mkdir -p "$PENDING" "$IN_PROGRESS" "$RESULTS" "$DONE" "$ERRORS"

echo "[${WORKER_ID}] Starting worker loop with agent: $AGENT"

while :; do
    # Atomically claim the oldest pending item
    ITEM=$(ls -1t "$PENDING"/*.json 2>/dev/null | tail -1)
    
    if [ -z "$ITEM" ]; then
        # No work available, sleep and retry
        sleep 2
        continue
    fi
    
    BASENAME=$(basename "$ITEM")
    
    # Atomic claim via mv (filesystem-level atomicity on same partition)
    if ! mv "$ITEM" "$IN_PROGRESS/$BASENAME" 2>/dev/null; then
        # Another worker claimed it
        continue
    fi
    
    echo "[${WORKER_ID}] Processing: $BASENAME"
    
    # Read the work item and construct the prompt
    TASK_CONTENT=$(cat "$IN_PROGRESS/$BASENAME")
    PROMPT="You are processing a debate work item. Read the task below and execute it using your available tools. Write ONLY the result content, nothing else.

TASK:
$TASK_CONTENT"
    
    # Execute with kiro-cli
    RESULT=$(echo "$PROMPT" | KIRO_API_KEY="${KIRO_API_KEY}" kiro-cli chat \
        --no-interactive \
        --agent "$AGENT" \
        --trust-all-tools 2>/dev/null) || {
        # On failure, move to errors
        echo "[${WORKER_ID}] FAILED: $BASENAME"
        mv "$IN_PROGRESS/$BASENAME" "$ERRORS/$BASENAME"
        continue
    }
    
    # Write result
    echo "$RESULT" > "$RESULTS/$BASENAME"
    
    # Move to done
    mv "$IN_PROGRESS/$BASENAME" "$DONE/$BASENAME"
    
    echo "[${WORKER_ID}] Completed: $BASENAME"
done
```

### Custom Agent Definition (`~/.kiro/agents/debate-worker.json`)

```json
{
  "name": "debate-worker",
  "description": "Debate system worker that processes argumentation tasks",
  "prompt": "file://./prompts/debate-worker-prompt.md",
  "tools": ["*"],
  "allowedTools": ["*"],
  "mcpServers": {
    "bible-tools": {
      "command": "node",
      "args": ["/path/to/bible-tools-mcp/index.js"]
    }
  },
  "includeMcpJson": true,
  "model": "claude-sonnet-4"
}
```

### Python Orchestrator Integration

```python
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

class WorkerPool:
    def __init__(self, queue_dir: Path, min_workers=4, max_workers=10, system_cap=15):
        self.queue_dir = queue_dir
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.system_cap = system_cap
        self.workers: dict[str, subprocess.Popen] = {}
        
        # Ensure queue dirs exist
        for d in ['pending', 'in-progress', 'results', 'done', 'errors']:
            (queue_dir / d).mkdir(parents=True, exist_ok=True)
    
    def submit_work(self, task_id: str, task_data: dict):
        """Submit a work item to the queue."""
        path = self.queue_dir / 'pending' / f'{task_id}.json'
        path.write_text(json.dumps(task_data))
    
    def get_result(self, task_id: str) -> dict | None:
        """Poll for a completed result."""
        path = self.queue_dir / 'results' / f'{task_id}.json'
        if path.exists():
            return json.loads(path.read_text())
        return None
    
    async def wait_for_result(self, task_id: str, timeout=300) -> dict:
        """Wait for a result with timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.get_result(task_id)
            if result is not None:
                return result
            await asyncio.sleep(1)
        raise TimeoutError(f"Task {task_id} timed out after {timeout}s")
    
    def count_pending(self) -> int:
        return len(list((self.queue_dir / 'pending').glob('*.json')))
    
    def count_system_kiro(self) -> int:
        """Count total kiro-cli processes system-wide."""
        result = subprocess.run(['pgrep', '-c', 'kiro-cli'], 
                              capture_output=True, text=True)
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    
    def start_worker(self, agent: str = 'debate-worker'):
        """Start a new worker process."""
        if self.count_system_kiro() >= self.system_cap:
            return  # System cap reached
        
        worker_id = f"worker-{len(self.workers)+1}"
        proc = subprocess.Popen(
            ['bash', 'worker.sh', worker_id, agent, str(self.queue_dir)],
            env={**os.environ, 'KIRO_API_KEY': os.environ['KIRO_API_KEY']}
        )
        self.workers[worker_id] = proc
    
    def scale(self):
        """Elastic scaling based on queue depth."""
        # Remove dead workers
        self.workers = {k: v for k, v in self.workers.items() if v.poll() is None}
        
        pending = self.count_pending()
        active = len(self.workers)
        
        if pending > active * 2 and active < self.max_workers:
            # Scale up
            self.start_worker()
        elif pending == 0 and active > self.min_workers:
            # Scale down (graceful — worker will exit after current task)
            pass  # Workers naturally idle; can send SIGTERM
    
    def stop_all(self):
        """Gracefully stop all workers."""
        for worker_id, proc in self.workers.items():
            proc.terminate()
        for proc in self.workers.values():
            proc.wait(timeout=30)
```

---

## 4. Why NOT a Persistent Interactive Session

### Investigated and Rejected Approaches

| Approach | Why It Fails |
|----------|-------------|
| Pipe to interactive stdin | kiro-cli interactive mode requires TTY; fails with "Bad file descriptor" in non-TTY (GitHub issue #4497) |
| `stop` hook to prevent exit | Only works in interactive mode; `--no-interactive` exits after response regardless |
| Single long session with compaction | Context degrades; compaction is lossy; no crash resilience |
| `--resume-id` for continuity | Adds accumulated context weight; defeats fresh-context advantage |
| `launch_agent` for "forever agent" | kiro-agents MCP tool agents are ephemeral; designed for single tasks |

### The "Never Stop" Prompt Pattern — Not Needed

The original question asked about instructing an LLM to "never stop." With the Ralph Loop pattern, this is unnecessary because:
- The **bash loop** is what never stops, not the LLM
- Each LLM invocation is a single, focused task
- The LLM doesn't need to know it's in a loop
- No prompt engineering needed to prevent "I'm done" behavior

---

## 5. Queue Implementation Recommendation

### Filesystem Queue (Recommended)

**Why filesystem over Redis/SQLite:**
- kiro-cli agents can read/write files natively (built-in `read`/`write` tools)
- No external dependencies
- Atomic `mv` on same partition provides locking
- Human-debuggable (just `ls` the directories)
- Works with the existing `execute_bash` tool

**Directory structure:**
```
queue/
├── pending/          # Orchestrator writes here
│   ├── turn-001.json
│   └── turn-002.json
├── in-progress/      # Worker claims by mv here
├── results/          # Worker writes output here
├── done/             # Completed work items
└── errors/           # Failed items with error info
```

**Work item format:**
```json
{
  "id": "turn-001",
  "type": "debate_turn",
  "agent_role": "advocate",
  "topic": "Was the Comma Johanneum original?",
  "context": "Previous arguments...",
  "instructions": "Present your strongest argument using biblical scholarship...",
  "created_at": "2026-05-13T21:00:00Z",
  "timeout_seconds": 120
}
```

### Atomic Claiming (Race Condition Prevention)

```bash
# mv is atomic on same filesystem — first worker to mv wins
if ! mv "$PENDING/$FILE" "$IN_PROGRESS/$FILE" 2>/dev/null; then
    continue  # Another worker got it
fi
```

---

## 6. Handling Failures and Recovery

### Worker Crash Recovery
- On startup, check `in-progress/` for orphaned items
- If item has been in-progress > timeout, move back to `pending/` or `errors/`
- Python orchestrator monitors worker PIDs

### Context Window Exhaustion
- **Not a problem** with Ralph Loop — each invocation is fresh
- Single debate turn should be well under 200K tokens
- If a single task is too large, split it in the orchestrator

### Agent Restart
- Worker bash loop auto-restarts on kiro-cli exit (that's what `while :; do ... done` does)
- If the worker script itself dies, Python orchestrator detects via `proc.poll()` and restarts

### Stuck Detection
```python
# In orchestrator
for item in (queue_dir / 'in-progress').glob('*.json'):
    data = json.loads(item.read_text())
    age = time.time() - data.get('claimed_at', 0)
    if age > data.get('timeout_seconds', 120):
        item.rename(queue_dir / 'errors' / item.name)
```

---

## 7. Elastic Scaling Strategy

```
Queue Depth → Worker Count
0-3 items   → 4 workers (minimum)
4-8 items   → 6 workers
9-15 items  → 8 workers
16+ items   → 10 workers (maximum)
System cap  → 15 kiro-cli processes total (including non-debate)
```

**Monitoring:**
```bash
# Count active kiro-cli processes
pgrep -c kiro-cli

# Count pending work
ls queue/pending/*.json 2>/dev/null | wc -l
```

**Graceful scale-down:** Don't kill workers mid-task. Set a flag file that workers check between iterations:
```bash
# In worker loop, after completing a task:
if [ -f "$QUEUE_DIR/.scale-down-$WORKER_ID" ]; then
    rm "$QUEUE_DIR/.scale-down-$WORKER_ID"
    echo "[${WORKER_ID}] Scaling down gracefully"
    exit 0
fi
```

---

## 8. Performance Characteristics

### Per-Invocation Overhead
- **Current observed**: 15-20 seconds per `--no-interactive` call (from user's existing system)
- **Breakdown**: ~3-5s MCP server startup, ~2-3s auth/handshake, ~10-15s LLM response
- **Optimization**: The `--require-mcp-startup` flag ensures fast-fail if MCP is broken

### Throughput Estimate
- With 4 workers at 20s/turn: ~12 turns/minute
- With 10 workers at 20s/turn: ~30 turns/minute
- A 10-round debate with 4 participants = 40 turns ≈ 3-4 minutes with 4 workers

### vs. Current System (700+ sequential calls)
- Current: 700 × 20s = ~4 hours sequential
- Ralph Loop with 10 workers: 700 / 10 × 20s = ~23 minutes
- **~10x improvement** from parallelism alone

---

## 9. The "Work Loop" Skill Pattern (Community Validation)

The `work-loop` skill from eliteai.tools (163 GitHub stars) validates this exact pattern:
- **Source**: https://eliteai.tools/index.php/agent-skills/work-loop-2
- Queue-driven orchestrator that processes `do-work/requests/` using isolated sub-agents
- Core principle: "The Orchestrator never performs task work. Every request spawns a fresh sub-agent."
- Guarantees: Context isolation, atomic execution, crash resilience, audit trail

This is essentially the same architecture proposed here, confirming it's a proven community pattern.

---

## 10. Key Decisions and Trade-offs

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Session persistence | Fresh per iteration | Avoids context degradation; crash resilient |
| Queue mechanism | Filesystem | No dependencies; kiro-cli native file access |
| Worker lifecycle | Bash while loop | Simple; auto-restarts; no framework needed |
| Scaling | Python orchestrator | Already asyncio-based; monitors PIDs |
| Agent config | Custom JSON agent | Full MCP tool access; custom prompt per role |
| Locking | Atomic `mv` | Race-condition safe on same partition |
| Error handling | Move to errors/ dir | Preserves failed items for debugging |

---

## 11. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| API rate limiting | Respect kiro-cli rate limits; add exponential backoff between retries |
| MCP server startup overhead | Consider if MCP servers can be shared (likely not — each kiro-cli process starts its own) |
| Token costs | Each turn is bounded; monitor with `KIRO_LOG_LEVEL=info` |
| Filesystem queue race conditions | Atomic `mv`; single-item claim pattern |
| Worker zombies | Orchestrator monitors PIDs; timeout detection |
| Context too large for single turn | Pre-split in orchestrator; summarize debate history |

---

## Sources

1. kiro.dev/docs/cli/headless/ — Official headless mode documentation
2. kiro.dev/docs/cli/chat/ — Interactive chat documentation
3. kiro.dev/docs/cli/chat/session-management/ — Session persistence
4. kiro.dev/docs/cli/custom-agents/configuration-reference/ — Agent JSON format
5. kiro.dev/docs/cli/chat/subagents/ — Subagent architecture
6. kiro.dev/blog/cli-2-0/ — CLI 2.0 headless announcement
7. kiro.dev/blog/introducing-headless-mode/ — Headless mode walkthrough
8. kiro.dev/changelog/cli/1-24/ — Compaction feature
9. thomas-wiegold.com/blog/ralph-loop-how-recursive-ai-agents-work/ — Ralph Loop deep dive
10. blakecrosley.com/blog/ralph-agent-architecture — Ralph implementation with stop hooks
11. eliteai.tools/index.php/agent-skills/work-loop-2 — Work Loop skill (community pattern)
12. github.com/kirodotdev/Kiro/issues/4497 — Interactive mode stdin issue
