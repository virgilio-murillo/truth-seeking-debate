# Early Recommendations — Elastic Agent Pool for Debate System
**HEAD AGENT | Investigation dddfdb0e | Updated: 21:15**

## TL;DR
Replace kiro-cli subprocess calls with a **Bedrock Converse API + asyncio elastic pool**.
A "persistent agent" is a Python object holding `messages: list`. The API is stateless — you pass full history each call. Prompt caching makes this cheap. MCP tools connect via `mcp-use` library.

---

## Immediate Actions

### 1. Verify Bedrock Access (5 min)
```bash
aws bedrock-runtime invoke-model --model-id us.anthropic.claude-sonnet-4-5-20251001-v1:0 --body '{"anthropic_version":"bedrock-2023-05-31","max_tokens":50,"messages":[{"role":"user","content":"ping"}]}' --region us-east-1 /tmp/ping.json && cat /tmp/ping.json
```

### 2. Install Dependencies (2 min)
```bash
pip install boto3 mcp-use anthropic
```

### 3. Check System Process Count (macOS)
```bash
pgrep -c kiro-cli 2>/dev/null || echo 0
```
Hard cap: if count >= 15, block new agent spawns.

---

## Architecture Decision

**Use Phil Schmid Pattern 3 (Agent Pool):**
- Persistent agents with `messages: list` (client-managed history)
- Bedrock Converse API (stateless — pass full history each call)
- Prompt caching for system prompt + established truths (1-hour TTL on Sonnet 4.5)
- MCP tools via `mcp-use` AnthropicMCPAdapter (supports local stdio servers)
- Elastic scaling via asyncio.Queue + worker coroutines

**Do NOT use:**
- Bedrock Sessions API (preview, not GA, adds complexity)
- Bedrock AgentCore (overkill for this use case)
- kiro-cli subprocess (15-20s overhead floor, cannot be reduced)

---

## Key Findings Summary

| Question | Answer | Source |
|---|---|---|
| Bedrock Converse API stateful? | NO — caller manages history | c3-context, c2-kb, milvus.io |
| MCP tools for local stdio? | mcp-use AnthropicMCPAdapter | c1-internet, mcpuse.mintlify.app |
| Context window limit? | 200k (Claude 3.7), 1M (Sonnet 4.6) | c2-kb |
| When to summarize? | 50 msgs OR 150k tokens | c5-internal (StoreGen pattern) |
| Prompt caching TTL? | 1-hour (Sonnet 4.5), 5-min (Claude 3.7) | c4-docs |
| Best framework? | Strands Agents SDK OR pure asyncio | c5-internal, c2-kb |
| macOS process cap check? | `pgrep -c kiro-cli` | head agent |
| Elastic pool pattern? | asyncio.Queue + worker coroutines | c3-context |
| Role flexibility? | Yes — assign role per work item | head agent |
| Affinity routing? | Yes — track agent_id per contention | head agent |
