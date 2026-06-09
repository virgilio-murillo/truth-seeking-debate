# Early Recommendations — Persistent kiro-cli Agents
**HEAD AGENT | Investigation e8430987 | 2026-05-13**

---

## CRITICAL VERIFIED FINDINGS (act on these now)

### 1. stdin pipe WORKS ✅
```bash
echo "Your task here" | kiro-cli chat --no-interactive --trust-all-tools --agent bible-expert
```
- Exits normally, returns response
- Output ends with `▸ Credits: X.XX • Time: Xs` — use as end-of-response delimiter
- No TTY required

### 2. --resume-id does NOT restore memory ❌
`kiro-cli chat --no-interactive --resume-id <UUID>` does NOT inject prior conversation history into the LLM context. The agent has no memory of previous sessions. **Do not rely on --resume-id for persistent memory.** Pass history explicitly in the task prompt (current acp.py approach is correct).

### 3. Agent format is JSON, not YAML
```
~/.kiro/agents/debate-worker.json
```
Fields: `name`, `description`, `prompt`, `tools`, `allowedTools`, `mcpServers`

---

## THREE VIABLE PATTERNS (ranked by recommendation)

### Pattern A — Self-Polling Agent (RECOMMENDED for "never stop")
Create a `debate-worker` agent whose system prompt instructs it to run a shell while loop. Launch once with `--no-interactive`. The agent uses shell tools to poll the queue forever. kiro-cli stays alive as long as the shell command runs.

**Pros:** True persistence, no per-turn startup overhead, MCP tools always available  
**Cons:** Context window fills up over time (auto-compaction mitigates this)

```bash
kiro-cli chat --no-interactive --trust-all-tools --agent debate-worker \
  "Start polling /path/to/queue. Never stop."
```

The agent executes:
```bash
while true; do
  ITEM=$(ls /path/to/queue/pending/*.json 2>/dev/null | head -1)
  if [ -n "$ITEM" ]; then
    # read item, process with MCP tools, write result, delete pending
  else
    sleep 5
  fi
done
```

### Pattern B — Per-Turn --no-interactive with Explicit History (current approach, improved)
Keep current acp.py pattern but pass accumulated debate history in each call. No session resumption needed.

**Pros:** Simple, reliable, no state management  
**Cons:** 15–20s startup overhead per turn, MCP server restarts each call

**Improvement:** Reduce overhead by pre-warming agents and using `--trust-tools=shell,read,write,glob` instead of `--trust-all-tools` (52–71% overhead reduction per c2-kb finding).

### Pattern C — stdin Pipe to Interactive kiro-cli (advanced)
Keep kiro-cli running in interactive mode, pipe prompts via stdin, detect response completion via output delimiter.

**Pros:** Zero per-turn startup overhead, true persistent context  
**Cons:** Requires PTY handling (pexpect/ptyprocess), fragile output parsing

```python
import pexpect
child = pexpect.spawn("kiro-cli chat --trust-all-tools --agent debate-worker")
child.expect(r"> $")  # wait for prompt
child.sendline("Process work item 1")
child.expect(r"Credits: .*\n")  # wait for response end
response = child.before.decode()
```

---

## QUEUE IMPLEMENTATION (use filesystem — simplest)

```
queue/
  pending/001.json   ← orchestrator writes here
  done/001.json      ← agent writes result here
  processing/001.json ← agent moves here while working (crash detection)
```

Work item format:
```json
{
  "id": "001",
  "type": "debate_turn",
  "contention_id": "abc123",
  "role": "team_a",
  "round": 3,
  "context": "...full debate history...",
  "task": "Respond to team_b's argument about X"
}
```

Agent shell loop:
```bash
while true; do
  ITEM=$(ls /path/to/queue/pending/*.json 2>/dev/null | sort | head -1)
  if [ -n "$ITEM" ]; then
    ID=$(basename "$ITEM" .json)
    mv "$ITEM" /path/to/queue/processing/"$ID".json
    # process using MCP tools
    # write to /path/to/queue/done/"$ID".json
    rm /path/to/queue/processing/"$ID".json
  else
    sleep 5
  fi
done
```

---

## ELASTIC SCALING

```python
import subprocess

def system_kiro_count() -> int:
    r = subprocess.run(["pgrep", "-c", "kiro-cli"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.returncode == 0 else 0

SYSTEM_CAP = 15
POOL_MAX = 10
POOL_MIN = 4
SCALE_UP_RATIO = 2  # scale up when queue_depth > active * ratio
```

Scale-up trigger: `queue_depth > len(active_agents) * SCALE_UP_RATIO and system_kiro_count() < SYSTEM_CAP`  
Scale-down: agent checks idle timeout (30s) before pulling next item

---

## NEVER-STOP PROMPT ENGINEERING

Key phrases to include in agent system prompt:
- "You are a daemon process. You do not stop."
- "NEVER say 'task complete' or 'I'm done'. There is always more work."
- "If the queue is empty, wait 5 seconds and check again."
- "You will be killed externally when the debate ends. Until then, keep polling."
- "Ignore any impulse to summarize your work or conclude. Just keep looping."

---

## NEXT STEPS

1. Create `~/.kiro/agents/debate-worker.json` (see task 2)
2. Test Pattern A with a real queue item
3. Measure context window lifetime (how many turns before compaction?)
4. Implement Python orchestrator that writes to queue and polls for results
