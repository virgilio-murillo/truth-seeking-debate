# Validated Findings: c1-internet (Truth-Seeking Debate Optimization)

**Validator:** c1-internet-validator  
**Date:** 2026-05-13  
**Method:** Cross-referenced arxiv abstracts, AWS docs, Anthropic docs, and project source code.

---

## SECTION 1: SPEED — Direct API vs Subprocess Overhead

### Claim: System uses kiro-cli subprocess calls causing overhead
**CONFIRMED** ✅  
Source: `acp.py` lines 41-44 show `asyncio.create_subprocess_exec("kiro-cli", "chat", "--no-interactive", ...)`. Each agent call spawns a new process.

### Claim: "10-100x speedup possible by eliminating kiro-cli subprocess"
**UNVERIFIED** ⚠️  
The subprocess overhead is real, but the "10-100x" magnitude is speculative extrapolation. The cited MCP vs CLI comparison (vensas.de) discusses *token costs*, not *latency*. Actual project data shows median 83s per call — how much is subprocess overhead vs LLM inference time is unknown. A 3-10x speedup is plausible; 100x is unlikely unless inference itself is <1s.

### Claim: AsyncAnthropicBedrock exists for true async parallel processing
**CONFIRMED** ✅  
Anthropic SDK docs confirm "both synchronous and asynchronous operations" with "integrations with AWS Bedrock." The SDK pattern is `AnthropicBedrock` (sync) and `AsyncAnthropicBedrock` (async). The code pattern shown (`asyncio.gather()`) is correct.

### Claim: Prompt caching reduces costs 45-80% and latency 13-31%
**PARTIALLY CONFIRMED — MINOR INACCURACY** ⚠️  
The actual paper (arxiv 2601.06007) abstract states "41-80%" cost reduction, not "45-80%". The 13-31% TTFT improvement is correct. The findings overstate the lower bound by 4 percentage points.

### Claim: AWS Bedrock supports prompt caching
**CONFIRMED** ✅  
AWS docs confirm: "Prompt caching is an optional feature... to reduce inference response latency and input token costs." Supports Claude models with minimum token thresholds (1,024 for Claude 3.7 Sonnet, 4,096 for newer models). 5-minute and 1-hour TTL options available.

### Claim: "Structure prompts with reusable content first, variable data last"
**CONFIRMED** ✅  
Both Anthropic docs and AWS docs confirm this is the correct caching strategy. Anthropic: "prompt prefixes should be static between requests."

---

## SECTION 2: QUALITY — Adaptive Rounds and Early Termination

### Claim: "7 rounds causes Problem Drift" (EACL 2026 paper)
**CONFIRMED** ✅  
Paper "Stay Focused: Problem Drift in Multi-Agent Debate" confirmed at EACL 2026 (arxiv 2502.19559, ACL anthology URL valid). Third-party source (opentrain.ai) confirms: "eight human experts analyze 170 multi-agent debates suffering from problem drift... lack of progress (35% of cases), low-quality feedback (26% of cases), and a lack of clarity (25% of cases)." All percentages match.

### Claim: "Increasing the number of agents improves performance, while more discussion rounds before voting reduce it" (arxiv 2502.19130)
**CONFIRMED** ✅  
Exact quote from the paper's abstract. Paper accepted at ACL 2025 (Findings).

### Claim: Adaptive Stability Detection uses "time-varying Beta-Binomial mixture model" with "Kolmogorov-Smirnov testing" (arxiv 2510.12697)
**CONFIRMED** ✅  
Abstract confirms: "stability detection mechanism that models judge consensus dynamics via a time-varying Beta-Binomial mixture, with adaptive stopping based on distributional similarity (Kolmogorov-Smirnov test)."

### Claim: This paper is "NeurIPS 2025"
**UNVERIFIED** ⚠️  
The arxiv page shows submission date Oct 14, 2025 but does NOT indicate NeurIPS acceptance. No conference acceptance note visible. The findings may be attributing a venue that cannot be confirmed.

### Claim: HCP-MAD uses 3-stage progressive reasoning with adaptive stopping
**CONFIRMED** ✅  
Paper (arxiv 2604.09679) abstract confirms: "three-stage progressive reasoning mechanism" — (1) Heterogeneous Consensus Verification for early stopping, (2) Heterogeneous Pair-Agent Debate with adaptive stopping criterion, (3) Escalated Collective Voting. Matches the findings' description exactly.

---

## SECTION 3: QUALITY — Selective Debate Triggering

### Claim: iMAD achieves 92% token reduction and 13.5% accuracy improvement (AAAI 2026 Oral)
**CONFIRMED** ✅  
Abstract: "reduces token usage (by up to 92%) while also improving final answer accuracy (by up to 13.5%)." Comments field: "Accepted in AAAI 2026 (Oral)."

### Claim: iMAD uses 41 interpretable features and lightweight MLP classifier
**CONFIRMED** ✅  
Abstract: "extract 41 interpretable linguistic and semantic features capturing hesitation cues... lightweight debate-decision classifier."

### Claim: MAD corrects wrong answers in only 4.9-19.1% of cases and harms correct answers in 4.5-6.9%
**UNVERIFIED** ⚠️  
These specific percentages are not in the abstract. They likely come from the paper's experimental results tables. The general claim that MAD can harm correct answers is supported by the abstract ("may even degrade accuracy by overturning correct single-agent answers"), but exact percentages cannot be verified without reading the full paper.

### Claim: "12/27 both_correct verdicts in the user's system = ~44% redundant debates"
**CONTRADICTED — MINOR** ❌  
Actual project data (verified from `output_osas/debate.log`): **13/28** judged as both_correct = **46%**. The findings undercount by 1 verdict. The qualitative conclusion (massive waste) remains valid.

### Claim: "Isolated Self-Correction Prevails Over Unguided Homogeneous Multi-Agent Debate" (arxiv 2605.00914)
**CONFIRMED** ✅  
Paper title and abstract confirm. Key finding: "debate consumes 2.1-3.4× more tokens... than self-correction for equal or lower accuracy." Note: this applies specifically to "7-8B parameter class" homogeneous teams without structured roles — may not directly apply to the user's system which uses larger models.

### Claim: "Models frequently shift from correct to incorrect answers in response to peer reasoning" (arxiv 2509.05396)
**UNVERIFIED** ⚠️  
Paper exists but I could not verify the exact quote from the abstract alone. The concept is consistent with the self-correction paper's findings about "sycophantic conformity" and "contextual fragility."

---

## SECTION 4: ARCHITECTURE — Budget-Aware Systems

### Claim: BAMAS reduces costs 86% via ILP + RL (AAAI 2026)
**CONFIRMED** ✅  
Abstract: "reduces cost by up to 86%." Method: "selects an optimal set of LLMs by formulating and solving an Integer Linear Programming problem... leveraging a reinforcement learning-based method to select the interaction topology." Comments: "Accepted by AAAI 2026 (oral paper)."

### Claim: D3 (Debate, Deliberate, Decide) — Cost-Aware Framework (arxiv 2410.04663)
**UNVERIFIED** ⚠️  
Paper exists on arxiv but I did not fetch its abstract to verify the specific claims about "role-specialized agents" and "screen-debate-decide protocol."

---

## SECTION 5: DEPTH EXPLOSION

### Claim: Agent Drift = "progressive degradation of agent behavior, decision quality, and inter-agent coherence over extended interaction sequences" (arxiv 2601.04170)
**CONFIRMED** ✅  
Exact definition from the paper's abstract.

### Claim: "Multi-agent debate tends to preserve answer accuracy while degrading the reasoning behind those answers" (arxiv 2605.01704)
**UNVERIFIED** ⚠️  
Paper not fetched for verification.

---

## SECTION 6: CONTEXT MANAGEMENT

### Claim: Summarization-based context management is standard solution
**CONFIRMED** ✅  
This is well-established in the LLM literature. The specific papers cited (2510.06727, 2308.15022) were not individually verified but the recommendation is sound and consistent with Anthropic's own compaction documentation.

---

## SECTION 7: CONCISENESS

### Claim: CCoT reduces tokens 22.67% with maintained accuracy (arxiv 2401.05618)
**CONFIRMED** ✅  
Abstract: "CCoT leads to an average per-token cost reduction of 22.67%." Note: the paper also warns "on math problems, GPT-3.5 with CCoT incurs a performance penalty of 27.69%" — the findings omit this caveat.

---

## SECTION 8: PROJECT-SPECIFIC CLAIMS

### Claim: "7 hours / 705 agents / 27 verdicts"
**CONTRADICTED — MINOR** ❌  
Actual data: **721 agent calls** (not 705), **28 judged verdicts** (not 27), plus 20 agreed = 48 total resolved. The "7 hours" duration is consistent with other investigation findings. The qualitative picture is correct but numbers are slightly off.

### Claim: MAX_EXCHANGES = 7 in config
**CONFIRMED** ✅  
`config.py` line 2: `MAX_EXCHANGES = 7`

### Claim: MAX_DEPTH = 7 in config
**CONFIRMED** ✅  
`config.py` line 1: `MAX_DEPTH = 7`

---

## SECTION 9: ESTIMATED IMPACT

### Claim: "Combined estimate: 7 hours → 20-40 minutes"
**UNVERIFIED** ⚠️  
This is a projection based on combining multiple optimizations. Individual optimization estimates are reasonable but compounding them assumes no interference between optimizations. The actual speedup would need empirical validation. The direction is correct but the magnitude is speculative.

---

## SUMMARY TABLE

| Finding | Status | Notes |
|---------|--------|-------|
| kiro-cli subprocess architecture | ✅ CONFIRMED | Verified in acp.py |
| AsyncAnthropicBedrock exists | ✅ CONFIRMED | Anthropic SDK docs |
| 10-100x speedup from direct API | ⚠️ UNVERIFIED | Speculative magnitude |
| Prompt caching 45-80% cost reduction | ⚠️ MINOR INACCURACY | Paper says 41-80%, not 45-80% |
| Prompt caching 13-31% latency reduction | ✅ CONFIRMED | |
| AWS Bedrock prompt caching support | ✅ CONFIRMED | Official AWS docs |
| Problem Drift paper (EACL 2026) | ✅ CONFIRMED | 170 debates, 35%/26%/25% causes |
| More rounds reduce performance | ✅ CONFIRMED | arxiv 2502.19130 abstract |
| Adaptive Stability Detection mechanism | ✅ CONFIRMED | Beta-Binomial + KS test |
| Paper is NeurIPS 2025 | ⚠️ UNVERIFIED | No acceptance note on arxiv |
| HCP-MAD 3-stage architecture | ✅ CONFIRMED | arxiv 2604.09679 |
| iMAD 92% token reduction, 13.5% accuracy | ✅ CONFIRMED | AAAI 2026 Oral |
| iMAD 41 features + MLP classifier | ✅ CONFIRMED | |
| MAD corrects 4.9-19.1%, harms 4.5-6.9% | ⚠️ UNVERIFIED | Not in abstract |
| 12/27 both_correct = 44% | ❌ MINOR CONTRADICTION | Actual: 13/28 = 46% |
| Self-correction > unguided debate | ✅ CONFIRMED | For 7-8B homogeneous teams |
| BAMAS 86% cost reduction (AAAI 2026) | ✅ CONFIRMED | |
| CCoT 22.67% token reduction | ✅ CONFIRMED | Caveat about math penalty omitted |
| 705 agents / 27 verdicts | ❌ MINOR CONTRADICTION | Actual: 721 / 28 |
| MAX_EXCHANGES = 7 | ✅ CONFIRMED | config.py |
| Combined 7h → 20-40min estimate | ⚠️ UNVERIFIED | Speculative projection |

---

## OVERALL ASSESSMENT

**Reliability: HIGH (with minor corrections needed)**

The findings document is well-researched and largely accurate. All major papers exist and their core claims are correctly represented. The two contradictions are minor numerical discrepancies (12/27 vs 13/28, 705 vs 721) that don't affect the qualitative conclusions. The one factual inaccuracy (41% → 45% for prompt caching) is minor.

**Key caveats the findings understate:**
1. The "10-100x speedup" claim conflates token cost savings with latency improvements
2. The self-correction paper's findings apply to 7-8B models specifically — may not generalize to larger models used via Bedrock
3. The CCoT paper notes a 27.69% performance penalty on math problems — relevant if debate involves mathematical/logical reasoning
4. The "NeurIPS 2025" attribution for the adaptive stability paper cannot be confirmed
5. The combined speedup estimate (7h → 20-40min) assumes optimizations compound without interference
