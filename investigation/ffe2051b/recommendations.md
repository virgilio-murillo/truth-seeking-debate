# Truth-Seeking Debate System — Improvement Recommendations
**HEAD AGENT** | Investigation ID: ffe2051b | 2026-05-13T20:31

---

## CRITICAL NUMBERS (from debate.log analysis)

| Metric | Value |
|--------|-------|
| Total agent calls | 721 |
| Debate round calls | 586 (81%) |
| Relevance gate calls | 83 (12%) |
| Judge calls | 28 (4%) |
| Median call time | **83s** |
| Mean call time | **145s** |
| Max call time | **5614s** |
| Total serial time | 29h |
| Actual wall time | 7.2h |
| Children spawned | 56 (depths 1–7) |
| Relevance gate pass rate | 67% (56/83) |
| "both_correct" verdicts | 13/28 = **46%** |

---

## TOP 3 ACTIONS (do these first)

### 1. Replace kiro-cli with direct Bedrock API
**Impact: ~1.6x per-call speedup + enables all other improvements**

```python
# acp.py — replace call_agent() entirely
import boto3, json

_bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")
_PROC_SEM = asyncio.Semaphore(20)  # raise from 10 to 20

async def call_agent(task: str, work_dir: str, agent: str = None) -> str:
    async with _PROC_SEM:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _invoke_bedrock, task)
        return resp

def _invoke_bedrock(task: str) -> str:
    resp = _bedrock.invoke_model(
        modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": task}]
        })
    )
    return json.loads(resp["body"].read())["content"][0]["text"]
```

**CLI to verify Bedrock access:**
```bash
aws bedrock-runtime invoke-model --model-id us.anthropic.claude-sonnet-4-5-20251001-v1:0 --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":100,"messages":[{"role":"user","content":"ping"}]}' --region us-east-1 /tmp/test_out.json && cat /tmp/test_out.json
```

### 2. Reduce MAX_DEPTH 7→3 and MAX_EXCHANGES 7→4
**Impact: 79% reduction in total agent calls (721 → ~149)**

```python
# config.py
MAX_DEPTH = 3       # was 7 — eliminates 41% of children
MAX_EXCHANGES = 4   # was 7 — eliminates 43% of debate calls
RELEVANCE_THRESHOLD = 0.80      # was 0.60
RELEVANCE_THRESHOLD_DEEP = 0.90 # was 0.80
MAX_CHILDREN_PER_NODE = 2       # NEW — hard cap on children per contention
MAX_INITIAL_CONTENTIONS = 5     # NEW — limit opening contentions
```

### 3. Parallel Team A + Team B
**Impact: ~1.7x speedup on debate rounds (81% of all calls)**

```python
# orchestrator.py — _run_contention()
# Replace sequential A→B with parallel using previous round's response
async def _run_contention(self, node: ContentionNode, wid: int):
    node.status = Status.ACTIVE
    prev_a, prev_b = "", ""
    while node.current_round < MAX_EXCHANGES:
        node.current_round += 1
        truths = self._truths_ctx()
        # Run A and B in parallel — each gets the OTHER's PREVIOUS response
        a_resp, b_resp = await asyncio.gather(
            call_agent(debate_round_prompt(node, "a", truths, prev_b), self.work_dir),
            call_agent(debate_round_prompt(node, "b", truths, prev_a), self.work_dir),
        )
        prev_a, prev_b = a_resp, b_resp
        node.exchanges.append(Exchange(round=node.current_round, team="a", content=a_resp))
        node.exchanges.append(Exchange(round=node.current_round, team="b", content=b_resp))
        # Check signals on both
        if await self._check_signals(node, a_resp, "a", wid): return
        if await self._check_signals(node, b_resp, "b", wid): return
    await self._judge(node, wid)
```

---

## SPEED IMPROVEMENTS (ordered by impact)

### S1. Prompt Caching for Established Truths
**Impact: 45–80% cost reduction, 13–31% latency reduction (arxiv 2601.06007)**

The `ESTABLISHED TRUTHS` section is identical across all concurrent calls. Cache it.

```python
# In _invoke_bedrock(), use cache_control on the system prompt
body = {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 1500,
    "system": [
        {"type": "text", "text": "You are a truth-seeking debate agent."},
        {"type": "text", "text": f"ESTABLISHED TRUTHS:\n{truths_ctx}",
         "cache_control": {"type": "ephemeral"}}  # 5-min TTL, resets on hit
    ],
    "messages": [{"role": "user", "content": task_without_truths}]
}
```

Minimum 1024 tokens for Claude 3.7 Sonnet to qualify for caching.

### S2. Early Termination (Convergence Detection)
**Impact: Eliminates rounds 5–7 when both sides agree on substance**

```python
# After round 3, check convergence
async def _check_convergence(self, node, wid) -> bool:
    if node.current_round < 3:
        return False
    last_a = next((e.content for e in reversed(node.exchanges) if e.team == "a"), "")
    last_b = next((e.content for e in reversed(node.exchanges) if e.team == "b"), "")
    # Simple heuristic: if both sides use "agree", "concede", "correct" → force judge
    convergence_words = {"agree", "concede", "correct", "acknowledge", "grant"}
    a_words = set(last_a.lower().split())
    b_words = set(last_b.lower().split())
    if len(convergence_words & a_words) >= 2 and len(convergence_words & b_words) >= 2:
        print(f"    [{_ts()}] [W{wid}] 🔀 CONVERGENCE DETECTED at round {node.current_round}")
        await self._judge(node, wid)
        return True
    return False
```

### S3. Context Summarization
**Impact: Prevents unbounded prompt growth; later calls are faster**

```python
# orchestrator.py
MAX_TRUTHS_INLINE = 10  # after this, summarize

def _truths_ctx(self) -> str:
    truths = self.state.found_truths
    if not truths:
        return "None yet."
    if len(truths) <= MAX_TRUTHS_INLINE:
        return "\n".join(f"- [{t.confidence:.1f}] {t.statement}" for t in truths)
    # Summarize older truths, keep recent 5 inline
    summary = f"[{len(truths)-5} earlier truths established — key themes: faith, grace, perseverance]"
    recent = "\n".join(f"- [{t.confidence:.1f}] {t.statement}" for t in truths[-5:])
    return f"{summary}\nRecent:\n{recent}"
```

### S4. Increase Workers + Semaphore
```python
# config.py
AGENT_SLOTS = 20  # was 10 (safe with direct API, no subprocess overhead)
# orchestrator.py
workers = [asyncio.create_task(self._worker(i)) for i in range(8)]  # was 4
```

### S5. Limit Initial Contentions
```python
# orchestrator.py — _parse_contentions()
nodes = nodes[:MAX_INITIAL_CONTENTIONS]  # add this line; was unlimited (got 10)
```

---

## QUALITY IMPROVEMENTS (ordered by impact)

### Q1. Selective Debate Triggering (iMAD approach)
**Impact: 92% token reduction with 13.5% accuracy improvement (arxiv 2511.11306)**

The key insight from iMAD (AAAI 2026 Oral): **don't debate things that don't need debating**.
46% of judged contentions were "both_correct" — these wasted 14+ agent calls each.

```python
# Before starting a contention, run a quick self-assessment
async def _should_debate(self, node: ContentionNode) -> bool:
    """Returns False if both positions are clearly compatible."""
    prompt = (
        f"Are these positions genuinely contradictory, or are they compatible?\n"
        f"Position A: {node.team_a_position}\nPosition B: {node.team_b_position}\n"
        f"Output ONLY JSON: {{\"contradictory\": true/false, \"confidence\": 0.0-1.0}}"
    )
    resp = await call_agent(prompt, self.work_dir)
    result = _parse_json(resp)
    return result.get("contradictory", True) and result.get("confidence", 0) > 0.7
```

Add to `_run_contention()` at the start:
```python
if not await self._should_debate(node):
    node.status = Status.RESOLVED
    node.winner = "both_correct"
    node.truth = f"Both positions are compatible: {node.claim}"
    self._notify_parent(node)
    return
```

### Q2. Hard Cap on Children Per Contention
```python
# orchestrator.py — _handle_child()
if len(parent.children) >= MAX_CHILDREN_PER_NODE:  # add this check
    return False
```

### Q3. Steelman Requirement
**Impact: Reduces sycophantic agreements, improves argument quality**

```python
# prompts.py — debate_round_prompt() — add to RULES section
"- In round 1 ONLY: begin with a 1-sentence steelman of the opponent's strongest point.\n"
```

### Q4. Truth Deduplication
```python
# orchestrator.py — before appending to found_truths
def _is_duplicate_truth(self, new_truth: str) -> bool:
    for t in self.state.found_truths:
        # Simple word overlap check
        new_words = set(new_truth.lower().split())
        old_words = set(t.statement.lower().split())
        overlap = len(new_words & old_words) / max(len(new_words), 1)
        if overlap > 0.6:
            return True
    return False
```

### Q5. Conciseness Enforcement
```python
# prompts.py — add to all debate prompts
"- CRITICAL: Your response MUST be under 400 words. No preamble. Evidence only.\n"
```

### Q6. Judge Sees Only Final Positions (not full history)
```python
# prompts.py — judge_prompt() — replace full history with summaries
def judge_prompt(node: ContentionNode) -> str:
    # Only last 2 rounds per team, not all 7
    recent = [e for e in node.exchanges if e.round >= node.current_round - 1]
    history = "\n".join(f"[R{e.round} {e.team.upper()}]: {e.content[:300]}..." for e in recent)
    ...
```

---

## ARCHITECTURE IMPROVEMENTS

### A1. Debate Budget
```python
# config.py
MAX_TOTAL_CALLS = 200  # hard stop

# orchestrator.py
self._call_count = 0

# In call_agent wrapper:
if self._call_count >= MAX_TOTAL_CALLS:
    raise DebateBudgetExceeded()
self._call_count += 1
```

### A2. Persistent State (Resume Interrupted Debates)
```python
# orchestrator.py — _save() already exists; add _load()
@classmethod
def from_checkpoint(cls, work_dir: str) -> "Orchestrator":
    state_file = Path(work_dir) / "debate_state.json"
    if state_file.exists():
        # Restore state and re-enqueue PENDING/ACTIVE nodes
        ...
```

### A3. AWS Architecture for Scale
If running multiple debates in parallel:
- **SQS** for contention queue (replaces asyncio.PriorityQueue)
- **DynamoDB** for shared state (replaces in-memory DebateState)
- **Step Functions** for orchestration with built-in retry/timeout
- **Lambda** for individual agent calls (parallel execution, no semaphore needed)

```bash
# Deploy contention queue
aws sqs create-queue --queue-name debate-contentions --attributes '{"FifoQueue":"true","ContentBasedDeduplication":"true"}' --region us-east-1
```

---

## PROJECTED IMPACT

| Change | Call Reduction | Speedup |
|--------|---------------|---------|
| Direct Bedrock API | 0% | 1.6x per call |
| Parallel A+B | 0% | 1.7x on debate rounds |
| MAX_EXCHANGES 7→4 | 43% | — |
| MAX_DEPTH 7→3 | 41% | — |
| Stricter gate (0.6→0.85) | 56% of children | — |
| Selective debate trigger | ~46% of contentions | — |
| **Combined** | **~79%** | **~20–55x wall time** |

**Estimated: 7.2h → 15–20 minutes for equivalent debate depth**

---

## IMPLEMENTATION ORDER

1. `config.py`: Set `MAX_DEPTH=3`, `MAX_EXCHANGES=4`, `RELEVANCE_THRESHOLD=0.80`, add `MAX_CHILDREN_PER_NODE=2`, `MAX_INITIAL_CONTENTIONS=5`
2. `acp.py`: Replace `call_agent()` with direct Bedrock API
3. `orchestrator.py`: Add parallel A+B, selective debate trigger, truth dedup
4. `prompts.py`: Add conciseness constraint (400 words), steelman in round 1
5. Test with `MAX_TOTAL_CALLS=50` budget to validate before full run

---

*Updated: 2026-05-13T20:31 | Sources: debate.log analysis, c1-internet (MAD literature), c2-kb (prompt caching), c3-context (source code), c4-docs (Bedrock API), c5-internal (frameworks)*
