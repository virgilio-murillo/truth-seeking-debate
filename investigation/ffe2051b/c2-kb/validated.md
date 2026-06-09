# VALIDATION SKIPPED

# Truth-Seeking Debate System: Speed & Quality Improvement Analysis

**Agent:** c2-kb (Knowledge Base + Web Research)  
**Date:** 2026-05-13  
**Sources:** Internal KB lessons, arxiv papers (2510.12697, 2511.11306, 2410.04663v2), Bedrock documentation

---

## Executive Summary

The current system's 7+ hour runtime for 27 verdicts (705 agents) is caused by three compounding factors: (1) subprocess overhead per agent call, (2) unbounded recursive depth explosion, and (3) no early termination. Academic research on Multi-Agent Debate (MAD) systems confirms these are solved problems with well-established solutions that can reduce runtime by 80-95%.

---

## 1. SPEED IMPROVEMENTS

### 1.1 Replace kiro-cli with Direct Bedrock API (HIGHEST IMPACT)

**Evidence from KB:**
- Bedrock `converse_stream` API is the recommended approach for agentic workloads (KB lesson: "Bedrock large-context tab processing pipeline")
- Critical config: `Config(read_timeout=3600, tcp_keepalive=True)` in boto3
- Use `us.anthropic.claude-sonnet-4-6` which has 1M context natively (GA since March 2026), no beta header needed
- Cross-region inference profiles (`us.`, `eu.`, `global.` prefixes) required for 1M context

**Expected speedup:** 10-50x per call. Current kiro-cli spawns a full process with MCP tool initialization (30-1500s). Direct API call with streaming: 3-30s for equivalent output.

**Implementation:**
```python
import boto3
from botocore.config import Config

config = Config(read_timeout=3600, tcp_keepalive=True)
client = boto3.client('bedrock-runtime', config=config, region_name='us-east-1')

response = client.converse_stream(
    modelId='us.anthropic.claude-sonnet-4-6-20260313-v1:0',
    messages=[...],
    system=[{"text": system_prompt}],
    inferenceConfig={"maxTokens": 1000}  # Keep low! 5x burndown on Claude 4+
)
```

### 1.2 Prompt Caching for Growing Context (HIGH IMPACT)

**Evidence from KB (CRITICAL):**
- Bedrock Explicit Prompt Caching (EPC) requires **exact byte-for-byte match** of the prompt prefix
- Cache TTL is 1 hour — sufficient for a single debate run
- EPC is **region-specific** — CRIS routing across regions reduces cache hit rate
- Cache read tokens cost 10x less than standard input tokens ($0.55/MTok vs $5.50/MTok)
- The "ESTABLISHED TRUTHS" section that grows with every verdict is a PERFECT candidate for caching — it's a static prefix that gets prepended to every subsequent prompt

**Implementation strategy:**
1. Place `cache_control: {"type": "ephemeral"}` marker after the system prompt + established truths block
2. Use a **single region** (not CRIS) to maximize cache hits
3. Keep the truths section byte-stable (don't reformat between calls)
4. Monitor `CacheReadInputTokenCount` vs `CacheWriteInputTokenCount` in API responses

**Pitfall (from KB lesson on Zuora incident):** Any mutation of content before the cache marker causes a miss. Ensure no dynamic content (timestamps, random IDs) appears before the cache breakpoint.

### 1.3 Adaptive Round Count with Early Stopping (HIGH IMPACT)

**Evidence from research (arxiv 2510.12697, NeurIPS 2025):**
- **Kolmogorov-Smirnov (KS) statistic** on Beta-Binomial mixture model detects when debate has converged
- Threshold of 0.05 for 2 consecutive rounds is optimal
- Reduces 10 rounds to 4-6 rounds with **<1% accuracy loss**
- Most debates converge by round 4-5

**Simpler implementation for this system:**
- After each round, check if Team B's response contains >80% agreement with Team A
- If judge scores agree in same direction for 2 consecutive rounds, stop (from SAMRE paper)
- Parse for explicit AGREEMENT signals already in the system

**Expected savings:** 30-50% of rounds eliminated (from 7 → 3-4 average)

### 1.4 Selective Debate Triggering (HIGH IMPACT)

**Evidence from iMAD paper (arxiv 2511.11306):**
- MAD uses 3-5x more tokens than single-agent with only 1.5-5.3% accuracy gain
- **Only 5-19% of cases** actually benefit from debate (✗→✓ corrections)
- 71-82% of cases are already correct without debate (✓→✓)
- Selective triggering via self-critique + classifier reduces tokens by **92%** while improving accuracy by 13.5%

**Application to this system:**
- Before spawning a child contention debate, have the judge do a quick single-call assessment
- If confidence is high (both sides would likely agree), skip the full 7-round debate
- The 12/27 "both_correct" verdicts (44%) confirm massive waste on non-contentious items

### 1.5 Reduce maxTokens (QUICK WIN)

**Evidence from KB:**
- Claude 4+ family has **5x output token burndown rate** for quota
- Setting `maxTokens=500` instead of 4000 reduces quota reservation 8x
- Current responses are 2000+ words — force conciseness with `maxTokens=800` and explicit prompt instruction
- This directly reduces TPM throttling risk when running 10 concurrent calls

### 1.6 Streaming for Early Signal Detection

**Confirmed approach:**
- Use `converse_stream` to detect AGREEMENT or CHILD_CONTENTION signals in the first 200 tokens
- If AGREEMENT detected early, can abort the stream and skip remaining generation
- If CHILD_CONTENTION detected, can begin spawning the child immediately while the current response completes

---

## 2. QUALITY IMPROVEMENTS

### 2.1 Structured Self-Critique Before Debate (from iMAD)

**Evidence:** The iMAD framework shows that having each agent produce:
1. Initial CoT justification
2. Required self-critique (counterargument)
3. Final reflection with confidence scores

...exposes internal hesitation that predicts whether debate will be useful. Apply this as a pre-filter.

### 2.2 Collaborative vs Adversarial Structure

**Evidence from D3/SAMRE paper (arxiv 2410.04663v2):**
- **Adversarial debate (MAD-style) underperforms collaborative debate** on judgment tasks
- "MAD's balanced exposure to both correct and incorrect arguments gives the incorrect side equal opportunity to persuade the judge"
- Collaborative belief-refinement (where agents see each other's reasoning and update) outperforms adversarial by 3-8%

**Recommendation:** Shift from pure adversarial (Team A vs Team B) to a hybrid:
- Round 1-2: Adversarial (surface disagreements)
- Round 3+: Collaborative (refine toward truth together)

### 2.3 Multi-Advocate Parallel (MORE Architecture)

**Evidence (arxiv 2410.04663v2):**
- Multiple advocates per position in ONE round achieves comparable quality to iterative single-advocate in 4 rounds
- Iteration complexity theorem: `I_ma(ε) < I_id(ε)` — multi-advocate needs fewer rounds
- 3 advocates per answer + 1 judge in a single round = equivalent to 4 iterative rounds

**Application:** Instead of 7 sequential rounds, use 3 parallel advocates per side + judge = 7 calls total (parallelizable) vs 14 sequential calls.

### 2.4 Steelman Requirement

**Evidence from legal/argumentation theory (D3 paper):**
- Requiring each side to steelman the other before arguing forces genuine engagement
- Reduces "talking past each other" which wastes rounds
- Judge can verify steelman accuracy before scoring

### 2.5 Truth Deduplication and Summarization

**Problem:** Growing ESTABLISHED TRUTHS section makes later calls slower and noisier.

**Solution:**
- After every 10 verdicts, run a summarization pass to consolidate redundant truths
- Use semantic similarity (embeddings) to detect near-duplicate truths
- Present truths in categories rather than flat list

---

## 3. ARCHITECTURE IMPROVEMENTS

### 3.1 Depth Budget System (CRITICAL)

**Evidence from scalable oversight research:**
- Recursive debates need explicit depth limits AND budget allocation per branch
- "Prover-Estimator-Debate" protocol (Alignment Forum 2025) decomposes problems but with bounded recursion
- Current system: depth=7 with 7 rounds each = 7^7 potential calls in worst case (823,543!)

**Proposed budget system:**
```
TOTAL_BUDGET = 200 agent calls
Per-contention cost = 2 * rounds_used + sum(child_costs)
Before spawning child: check remaining_budget > estimated_child_cost
If budget exhausted: force judge to decide with available evidence
```

### 3.2 Relevance Gating Tightening

**Current:** RELEVANCE_THRESHOLD = 0.6 (0.8 for deep)

**Proposed:**
- Depth 0-1: threshold 0.6 (allow exploration)
- Depth 2-3: threshold 0.85 (only material disagreements)
- Depth 4+: threshold 0.95 (only if fundamentally contradictory)
- Depth 6+: NEVER spawn children (hard cap)

### 3.3 Parallel Architecture Redesign

**Current:** 4 workers, semaphore(10), sequential Team A → Team B

**Proposed:**
- Give Team B the PREVIOUS round's Team A response (not current) — enables parallel execution
- Increase workers to 8 for shallow contentions (depth 0-2)
- Reduce workers to 2 for deep contentions (depth 3+) to limit explosion
- Priority: breadth-first (shallow first) instead of depth-first

### 3.4 Persistent State for Resume

- Serialize debate state to JSON after each round
- On crash/timeout, resume from last completed round
- Critical for 7+ hour runs

### 3.5 Tool Access via API

**Instead of MCP tools via kiro-cli subprocess:**
- For bible-tools: pre-load reference data into the prompt or use RAG
- For web_search: call a search API directly from Python
- Eliminates the entire MCP initialization overhead per call

---

## 4. QUANTIFIED IMPACT ESTIMATES

| Improvement | Speed Gain | Quality Impact | Effort |
|---|---|---|---|
| Direct Bedrock API | 10-50x per call | Neutral | Medium |
| Prompt caching | 2-3x for later calls | Neutral | Low |
| Adaptive rounds (3-4 avg) | 2x | <1% loss | Low |
| Selective debate triggering | 2-3x (skip 44% of debates) | +5-13% | Medium |
| Reduce maxTokens | 1.5x (less throttling) | Neutral if prompted well | Trivial |
| Depth budget (cap at 3) | 5-10x (prevent explosion) | Slight loss on edge cases | Low |
| Parallel Team A/B | 1.5x | Neutral | Low |
| Multi-advocate (MORE) | 2x (fewer rounds needed) | +2-4% | Medium |

**Combined realistic estimate:** From 7 hours → 20-40 minutes for equivalent quality.

---

## 5. RECOMMENDED IMPLEMENTATION ORDER

1. **Week 1:** Replace kiro-cli with Bedrock `converse_stream` (biggest single win)
2. **Week 1:** Add depth budget (cap=3) and tighten relevance gating
3. **Week 2:** Implement prompt caching with static truths prefix
4. **Week 2:** Add early stopping (agreement detection after round 2)
5. **Week 3:** Selective debate triggering (self-critique pre-filter)
6. **Week 3:** Parallel Team A/B execution
7. **Week 4:** Multi-advocate architecture for remaining contentions

---

## Sources

1. KB Lesson: "Bedrock large-context tab processing pipeline" — converse_stream config
2. KB Lesson: "AWS Bedrock Claude Sonnet 4.5 EU latency optimization" — prompt caching, maxTokens
3. KB Lesson: "Bedrock Prompt Caching — Client-Side Bug" — byte-for-byte prefix requirement
4. KB Lesson: "Multi-stream investigation overhead for trivial questions" — skip trivial debates
5. KB Lesson: "Bedrock TPM throttling with cross-region inference" — maxTokens burndown
6. arxiv 2510.12697 — "Multi-Agent Debate for LLM Judges with Adaptive Stability Detection" (NeurIPS 2025)
7. arxiv 2511.11306 — "Intelligent Multi-Agent Debate (iMAD)" — selective triggering, 92% token reduction
8. arxiv 2410.04663v2 — "Adversarial Multi-Agent Evaluation (D3/SAMRE)" — MORE vs iterative, early stopping
9. Alignment Forum — "Prover-Estimator-Debate: A New Scalable Oversight Protocol" — recursive depth budgets
10. arxiv 2506.03541 — "Debate & Reflect (D&R)" — tree-structured preference optimization
