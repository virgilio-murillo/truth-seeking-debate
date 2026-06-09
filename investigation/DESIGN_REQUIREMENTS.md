# Design Requirements for v2

## Core Constraint: Elastic Pool of Persistent Agents

The next version must use **persistent agents** — like people sitting at a table, not ephemeral processes.

### Model
- **4–10 long-lived agent sessions** that scale elastically based on workload
- Each agent pulls work from a **shared queue**
- Agents maintain conversational memory across the entire debate
- No re-sending full history every turn — they remember
- **Hard cap: never more than 15 total agents on the machine** (check `pgrep` before spawning)

### Elastic Scaling Rules
- Start with 4 agents (minimum)
- Scale up when queue depth > 2× current agent count
- Scale down when agents idle for >60s
- Before spawning: `pgrep -c kiro-cli` must be < 15 (system-wide, not just this debate)
- Max 10 agents for the debate system itself (leave headroom for other work)

### Why
- Current system spawns 700+ processes, each starting from zero
- Massive token waste re-sending established truths + exchange history
- No coherence between turns (agent doesn't "remember" its own arguments)

### Implementation Ideas
1. **Bedrock Converse API** — stateful multi-turn conversations, N sessions
2. **Anthropic Messages API with conversation history** — append messages, don't restart
3. **kiro-cli with `--session`** — if available, persistent chat sessions
4. **Queue pattern**: asyncio.Queue feeds work items to each agent's session
5. **Pool manager**: monitors queue depth + system load, spawns/kills agents

### Behavior
- Agent pool starts at 4
- Orchestrator fills queue with contention work items
- Each agent pulls next item: "Argue contention X, round 3"
- Agent already has context from prior rounds in its conversation history
- Responds, result goes back to orchestrator → routed to opponent's queue
- If queue backs up → pool manager spawns another agent (up to 10, if system < 15)
- If agents idle → pool manager retires them back to minimum 4

### Open Questions
- How to handle context window limits for very long debates? (summarize older exchanges)
- Should each agent specialize (always Team A) or be flexible (any role)?
- Can we use prompt caching to keep the "persona" system prompt cached?
- How to hand off contention context when a new agent joins mid-debate?
