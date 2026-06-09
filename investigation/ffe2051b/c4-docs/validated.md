# VALIDATION SKIPPED

# AWS Documentation Findings: Truth-Seeking Debate System Optimization

## Executive Summary

Based on official AWS documentation, the current architecture (kiro-cli subprocess per debate turn) can be replaced with direct Bedrock API calls using the **Converse/ConverseStream API** with **prompt caching**, **structured outputs**, and **cross-region inference profiles**. This combination addresses all three problem areas: speed, quality, and architecture.

---

## 1. SPEED IMPROVEMENTS (AWS-Documented Solutions)

### 1.1 Replace kiro-cli with Direct Bedrock Converse API (PRIMARY RECOMMENDATION)

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html

The Converse API provides:
- **Direct boto3 calls** — eliminates subprocess spawn overhead (process creation, MCP tool initialization, ANSI cleanup)
- **Multi-turn conversation support** — maintains message history natively via `messages` array
- **Consistent interface** across all Bedrock models (Claude, Nova, etc.)
- **Tool use built-in** — can give debate agents access to bible-tools/web_search via `toolConfig` without spawning separate processes

**Key API details:**
- Endpoint: `bedrock-runtime` 
- Permission needed: `bedrock:InvokeModel` (Converse) or `bedrock:InvokeModelWithResponseStream` (ConverseStream)
- Supports `system` prompts, `messages`, `inferenceConfig`, `toolConfig`

**Estimated speed gain:** Eliminates 10-30s subprocess overhead per call. For 705 agent calls, that's 2-6 hours saved on overhead alone.

### 1.2 ConverseStream for Early Signal Detection

**Source:** https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html

ConverseStream returns responses as a stream of events. This enables:
- **Early AGREEMENT detection** — parse streaming tokens for "AGREEMENT:" signal without waiting for full response
- **Early CHILD_CONTENTION detection** — detect spawning signals mid-stream
- **Abort on convergence** — if streaming response shows both sides agreeing, cancel remaining generation

**Implementation:** Use `ConverseStream` with event processing loop. Check accumulated text every N tokens for signal patterns.

### 1.3 Prompt Caching (CRITICAL for Growing Context)

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html

**Problem addressed:** The "ESTABLISHED TRUTHS" section grows with every verdict and is included in every prompt, making later calls slower.

**Solution:** Cache the system prompt + established truths as a prompt prefix:
- **Claude 3.7 Sonnet:** 1,024 token minimum per cache checkpoint, up to 4 checkpoints
- **Claude Sonnet 4.5 / Haiku 4.5:** 4,096 token minimum, supports **1-hour TTL** (ideal for 7-hour debates)
- **Cache hits are NOT counted against TPM quota** — directly increases effective concurrency
- Supported in both `Converse` and `ConverseStream` APIs
- Cache fields: `system`, `messages`, and `tools`

**Strategy for debate system:**
1. Cache checkpoint 1: System prompt + debate rules (static, 1-hour TTL)
2. Cache checkpoint 2: Established truths (updates per verdict, 5-min TTL refreshed by frequent hits)
3. Cache checkpoint 3: Current contention context + exchange history (per-contention)

**Simplified Cache Management for Claude:** Place a single cache checkpoint at end of static content; system automatically finds longest matching prefix looking back ~20 content blocks.

### 1.4 Token Quota Optimization (max_tokens)

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html

**CRITICAL FINDING:** Claude 3.7+ has a **5x burndown rate for output tokens**. Each output token consumes 5 tokens from TPM quota.

**Current problem:** With 2000+ word responses (~2500 tokens output), each debate turn burns:
- Initial deduction: `input_tokens + max_tokens` (if max_tokens=4096, that's input + 4096 reserved)
- Final: `input_tokens + cache_write + (output_tokens × 5)` = e.g., 3000 + 0 + 2500×5 = **15,500 tokens**

**Optimization:**
- Set `max_tokens` to 800 (enforce concise 500-word responses via prompt engineering)
- This reduces initial quota reservation from ~7000 to ~3800 per request
- Allows **2x more concurrent requests** within same TPM quota
- Use CloudWatch `OutputTokenCount` metric to calibrate

### 1.5 Cross-Region Inference for Higher Throughput

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html

- Routes requests across multiple AWS regions automatically
- Manages traffic bursts (exactly what 10 concurrent debate agents create)
- **Compatible with prompt caching**
- Two options: Geographic (data stays in geography) or Global (maximum throughput)
- Use inference profile ID instead of model ID in API calls

---

## 2. QUALITY IMPROVEMENTS (AWS-Documented Solutions)

### 2.1 Structured Outputs for Reliable Parsing

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html

**Problem addressed:** Current system parses free-form text for signals (AGREEMENT, CHILD_CONTENTION). This is fragile and produces verbose responses.

**Solution:** Use Bedrock Structured Outputs to enforce JSON schema on debate responses:

```json
{
  "outputConfig": {
    "textFormat": {
      "type": "json_schema",
      "structure": {
        "jsonSchema": {
          "schema": "{\"type\":\"object\",\"properties\":{\"argument\":{\"type\":\"string\",\"description\":\"Core argument in under 300 words\"},\"signal\":{\"type\":\"string\",\"enum\":[\"CONTINUE\",\"AGREEMENT\",\"CHILD_CONTENTION\"]},\"child_contention\":{\"type\":\"string\",\"description\":\"If signal is CHILD_CONTENTION, the sub-question\"},\"confidence\":{\"type\":\"number\",\"description\":\"0-1 confidence in position\"},\"concessions\":{\"type\":\"array\",\"items\":{\"type\":\"string\"}}},\"required\":[\"argument\",\"signal\",\"confidence\"],\"additionalProperties\":false}",
          "name": "debate_turn",
          "description": "Structured debate response"
        }
      }
    }
  }
}
```

**Benefits:**
- Eliminates parsing failures
- Forces conciseness (schema constrains argument length)
- Enables programmatic convergence detection (compare `confidence` scores)
- Grammar cached for 24 hours — no compilation overhead after first use
- Works with Converse, ConverseStream, batch inference

### 2.2 Tool Use for Research Phase

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html

Instead of giving each agent full MCP tool access via subprocess, use Bedrock's native tool use:
- Define tools (bible lookup, web search) as `toolConfig` in Converse API
- Model requests tool calls → your code executes them → returns results
- **Client-side tool calling** gives you full control over which tools are available per debate phase
- Can restrict tools during argumentation phase (no research, just argue from established facts)
- Allow tools only during initial research phase

**Pattern for debate:**
1. Research phase: Agent gets tool access, gathers evidence (1-2 tool calls)
2. Argumentation phase: No tools, just structured argument based on gathered evidence
3. This separates research latency from debate latency

### 2.3 Guardrails for Quality Control

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-use-converse-api.html

Can apply Bedrock Guardrails to:
- Prevent off-topic responses (content filters)
- Enforce relevance to the contention being debated
- Block repetitive/circular arguments

---

## 3. ARCHITECTURE IMPROVEMENTS (AWS-Documented Patterns)

### 3.1 Multi-Agent Collaboration Pattern (AWS Prescriptive Guidance)

**Source:** https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/multi-agent-collaboration.html

AWS recommends this architecture for multi-agent debate systems:

| Component | AWS Service | Purpose |
|-----------|-------------|---------|
| Agent hosting | Amazon Bedrock (Converse API) | Host individual LLM-driven debate agents |
| Communication | Amazon SQS or EventBridge | Messaging between debate agents |
| Shared memory | DynamoDB or S3 | Store established truths (blackboard pattern) |
| Orchestration | Step Functions or Lambda | Timeout, retry, budget enforcement |
| Agent roles | Bedrock Converse with role-specific system prompts | Team A, Team B, Judge |

**Key insight from docs:** "Multi-agent collaboration emphasizes peer-to-peer or emergent coordination by enabling adaptivity, parallelism, and division of cognition."

The current system already implements this pattern but with subprocess overhead. Migration to direct API calls preserves the pattern while eliminating overhead.

### 3.2 Step Functions for Orchestration (Optional, for Durability)

**Source:** https://docs.aws.amazon.com/step-functions/latest/dg/state-map.html

- **Distributed Map state:** Up to 10,000 parallel child workflow executions
- **Inline Map state:** 40 concurrent iterations (sufficient for debate system)
- Built-in error handling, retry, timeout
- **Standard workflows:** Up to 1 year execution (handles 7+ hour debates)
- Provides automatic state persistence (resume interrupted debates)

**Relevance:** Could replace the Python asyncio orchestrator for production deployment, providing durability and observability. However, for the immediate speed fix, staying with Python asyncio + direct Bedrock API is simpler.

### 3.3 Batch Inference for Non-Interactive Phases

**Source:** https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html

For phases that don't need real-time interaction (e.g., judging multiple completed contentions):
- Submit JSONL file to S3 with multiple judge prompts
- Bedrock processes them asynchronously
- Results written to S3
- Supports Converse API format

**Use case:** After accumulating 5-10 completed debates, batch-submit all judge evaluations simultaneously.

---

## 4. IMPLEMENTATION PRIORITY (Speed Impact Ranking)

| Priority | Change | Estimated Speed Gain | Effort |
|----------|--------|---------------------|--------|
| 1 | Replace kiro-cli with boto3 Converse API | 10-30s per call × 705 calls = 2-6 hours | Medium |
| 2 | Add prompt caching for established truths | 30-50% latency reduction on later calls | Low |
| 3 | Structured outputs (shorter responses) | 50-70% fewer output tokens = faster + cheaper | Low |
| 4 | Reduce max_tokens from 4096 to 800 | 2x effective concurrency within quota | Trivial |
| 5 | ConverseStream + early termination | Skip 3-4 rounds when convergence detected | Medium |
| 6 | Cross-region inference profile | Higher burst throughput for parallel calls | Low |
| 7 | Separate research phase from debate phase | Fewer tool calls during debate = faster turns | Medium |

### Combined Impact Estimate

- Current: 7+ hours for 27 verdicts (705 agent calls)
- After priorities 1-4: ~45-90 minutes for same workload
- After all 7: ~20-40 minutes for same workload (with depth limiting)

---

## 5. KEY LIMITATIONS & CONSTRAINTS (from AWS Docs)

1. **Prompt caching minimum tokens:** Claude 3.7 needs 1024 tokens minimum per checkpoint. Established truths must exceed this to benefit from caching.
2. **Cache TTL:** 5 minutes default (resets on hit). For gaps >5 min between calls to same contention, cache expires. Use 1-hour TTL with Claude Sonnet 4.5/Haiku 4.5.
3. **5x output burndown:** Claude 3.7+ output tokens cost 5x against TPM quota. Long responses severely limit concurrency.
4. **Structured output first-time compilation:** New JSON schemas take "up to a few minutes" to compile. Cache lasts 24h. Use consistent schemas.
5. **RPM limits:** Requests per minute quota exists independently of TPM. With 10 concurrent workers, may hit RPM before TPM.
6. **Cross-region + caching interaction:** "At times of high demand, cross-region optimizations may lead to increased cache writes" (potential cache misses when routed to different region).
7. **Batch inference is async:** Not suitable for interactive debate rounds, only for post-hoc judging.

---

## 6. RECOMMENDED ARCHITECTURE (Minimal Viable Change)

```python
# Replace acp.py call_agent() with:
import boto3

client = boto3.client('bedrock-runtime', region_name='us-east-1')

async def call_bedrock(messages, system_prompt, tools=None):
    """Direct Bedrock call replacing kiro-cli subprocess."""
    request = {
        'modelId': 'us.anthropic.claude-sonnet-4-5-20250929-v1:0',  # Cross-region profile
        'messages': messages,
        'system': [
            {'text': system_prompt},
            {'cachePoint': {'type': 'default', 'ttl': '1h'}}  # Cache system prompt
        ],
        'inferenceConfig': {'maxTokens': 800, 'temperature': 0.7},
        'outputConfig': {
            'textFormat': {
                'type': 'json_schema',
                'structure': {'jsonSchema': {...}}  # Structured debate response
            }
        }
    }
    if tools:
        request['toolConfig'] = {'tools': tools}
    
    response = client.converse(**request)
    return json.loads(response['output']['message']['content'][0]['text'])
```

---

## Sources

All findings from official AWS documentation:
- https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html
- https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-token-burndown.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html
- https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/multi-agent-collaboration.html
- https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference.html
- https://docs.aws.amazon.com/step-functions/latest/dg/state-map.html
