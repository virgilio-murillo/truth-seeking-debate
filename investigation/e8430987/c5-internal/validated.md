# Validated Findings: Persistent kiro-cli Agents via ACP

## Validation Summary

| Category | Count |
|----------|-------|
| CONFIRMED | 20 |
| CONTRADICTED | 2 |
| UNVERIFIED | 8 |

---

## Section 1: The ACP Protocol (Agent Client Protocol)

### Claim: `kiro-cli acp` exists as a subcommand
**CONFIRMED** — Ran `kiro-cli acp --help` locally. Output confirms: "Start Agent Client Protocol (ACP) agent" with options `--agent`, `--model`, `-a/--trust-all-tools`, `--trust-tools`, `--agent-engine`.

### Claim: JSON-RPC 2.0 over stdin/stdout
**CONFIRMED** — Multiple production codebases (AISlackBot, Agent-Orchestrator, Botctl, AGIArsenalConsole, AIVirtuosoTUI) all implement NDJSON over stdio. Official docs (kiro.dev/docs/cli/acp/) confirm this.

### Claim: Originated by the Zed team
**CONFIRMED** — Web search confirms github.com/zed-industries/agent-client-protocol. Multiple sources describe ACP as "an open effort by Zed Industries to standardize how code editors talk to AI coding agents."

### Claim: Same protocol JetBrains IDEs use to talk to kiro
**CONFIRMED** — Official Kiro docs (from kiro.dev/docs/cli/acp/, cached in multiple repos): "This means you can use Kiro's agentic capabilities in JetBrains IDEs, Zed, and other ACP-compatible editors." CousidAIMAgents repo shows JetBrains config at `~/.jetbrains/acp.json`.

### Claim: Available since kiro-cli 1.25.0
**UNVERIFIED** — Current installed version is 2.3.0. Official docs show `agentInfo.version: "1.5.0"` in examples. Cannot determine when ACP was first introduced. The "1.25.0" version number appears fabricated — kiro-cli versioning appears to use semver (current: 2.3.0, docs show 1.5.0), not 1.25.0.

### Claim: `kiro-cli acp --trust-all-tools` auto-approves all tools
**CONFIRMED** — Help output shows: `-a, --trust-all-tools  Auto-approve all tool permission requests`. Multiple repos (AIM-AgentForge, AISlackBot) confirm this flag.

### Claim: Protocol methods table (initialize, session/new, session/prompt, session/update, session/cancel, session/load, session/request_permission, session/set_mode, session/set_model)
**CONFIRMED** — All methods verified across multiple sources:
- Official docs (ASTDE-AgentProfiles, AB-SSR-Finance-workspace)
- Production code (AIVirtuosoTUI client.ts tests, AGIArsenalConsole, AIpiary, AcpPool)
- AIM-AgentForge server implementation
- AIVirtuosoCLI Rust server (server.rs dispatch table)

### Claim: Multi-session per process NOT supported
**CONFIRMED** — AIM-AgentForge code comment: "the ACP server is single-session (one process per agent session)." Botctl implements a worker pool specifically because each kiro-cli process handles one session.

### Claim: No service-account auth — requires human SSO identity
**UNVERIFIED** — Docs mention IAM Identity Center and social login (Google, GitHub). Cannot confirm there is no service account path. The AWSLogsAutonomousAgent testing showed auth may be needed (`authMethods` in initialize response).

### Claim: No dynamic system prompt injection — system prompt is static at process start
**UNVERIFIED** — AIM-AgentForge (third-party ACP server) supports `systemPrompt` override via session/new params. For kiro-cli specifically, AgentHub docs list this as "Still Untested." The agent's prompt is set via the agent JSON config file, but whether session/new accepts a systemPrompt override in kiro-cli is unconfirmed.

### Claim: Context auto-compacts at ~90%
**UNVERIFIED** — Context compaction exists (confirmed via `_kiro.dev/compaction/status` notification in docs). The specific 90% threshold is not documented in any source found. AIEverywhere uses 50% as a client-side restart threshold, but that's a different mechanism.

---

## Section 2: Python ACP Client Implementation

### Claim: The Python code is copy-paste ready and functional
**CONTRADICTED** — The Python code contains a critical bug in the `prompt()` method. It uses `"content"` as the field name:
```python
"content": [{"type": "text", "text": text}]
```
However, working production implementations (AISlackBot, Agent-Orchestrator) use `"prompt"`:
```python
"prompt": [{"type": "text", "text": text}]
```
The AWSLogsAutonomousAgent eval explicitly discovered this: "Found the issue. The field is `prompt`, not `content`." Note: The official kiro.dev docs show `content` in examples, creating confusion, but actual testing against kiro-cli confirms `prompt` is the working field name.

**Additional discrepancy:** The official ACP protocol reference (AIVirtuosoContext acp-protocol-reference.md) states: `session/prompt | { sessionId, prompt: ContentBlock[] }` — confirming `prompt` is the correct field per the protocol spec.

### Claim: Code patterns from AGIArsenalMesh, AISlackBot, Agent-Orchestrator, AlfredAgentBridge
**PARTIALLY CONFIRMED** —
- AISlackBot/acp_client.py: **CONFIRMED** (found via code search, matches described pattern)
- Agent-Orchestrator/skills/agent-orchestrator/scripts/agent_orchestrator.py: **CONFIRMED** (found via code search)
- AGIArsenalMesh/arsenal/acp/client.py: **UNVERIFIED** (code search returned 0 results)
- AlfredAgentBridge: **UNVERIFIED** (not searched)

---

## Section 3: Worker Pool Architecture (Botctl)

### Claim: Botctl implements a production-grade worker pool at code.amazon.com/packages/Botctl
**CONFIRMED** — Code search found Botctl with active repository status. Architecture matches: `Bot Core → acp-proxy (pool) → kiro-cli (pool)`.

### Claim: TOML config with `command = "kiro-cli acp"`, `max_workers = 5`, `idle_timeout_secs = 300`
**CONFIRMED** — README.md at line 172 shows exact config format with these fields. Code shows `ACP_MAX_WORKERS` env var defaulting to 10.

### Claim: PoolCapacity struct with active, warm, spawning, max fields
**CONFIRMED** — Exact match in `crates/acp-proxy/src/lib.rs` line 141:
```rust
pub struct PoolCapacity {
    pub active: usize,
    pub warm: usize,
    pub spawning: usize,
    pub max: usize,
}
```

### Claim: Idle timeout reaping, auto-respawn, session routing, warm pool, process group management
**CONFIRMED** — All features found in code:
- `reap_idle()` method with timeout-based expiration
- `get_or_spawn()` for auto-respawn
- `conversation_sessions: HashMap<String, String>` for routing
- `warm_pool: RefCell<Vec<Rc<dyn Worker>>>` with `replenish()`
- `shutdown()` kills all workers

---

## Section 4: The "Never Stop" Pattern

### Claim: Approach A (ACP + External Queue) is recommended
**CONFIRMED** — This matches the architecture used by Botctl, AISlackBot, and Agent-Orchestrator. All use external orchestration sending prompts to persistent ACP processes.

### Claim: Approach B (instruct agent to poll) is not recommended
**CONFIRMED** — The debate-worker.json on this system uses the polling approach (agent polls filesystem queue). This is the less reliable pattern — the ACP approach where the orchestrator sends prompts is architecturally superior.

### Claim: tmux + kb bridge approach exists (from SCP/ContributionCatalog)
**UNVERIFIED** — Not verified via code search. The wiki reference exists in the findings but was not cross-checked.

---

## Section 5: Context Window Management

### Claim: Sessions stored in `~/.kiro/sessions/cli/{session_id}.json` + `.jsonl`
**CONFIRMED** — Verified on disk: 584 files in `~/.kiro/sessions/cli/`, format is `{uuid}.json` + `{uuid}.jsonl` (+ optional `.lock`). Official docs confirm: "Each session creates two files: `<session-id>.json` - Session metadata and state, `<session-id>.jsonl` - Event log (conversation history)."

### Claim: Can resume with `session/load`
**CONFIRMED** — Multiple implementations (AGIArsenalConsole, AIpiary, AcpPool, AIVirtuosoTUI) implement `session/load`. Official docs confirm `loadSession: true` capability. ASBXGenAIBenchmarking testing confirms it works with kiro-cli.

### Claim: `_kiro.dev/metadata` notification reports contextUsagePercentage
**CONFIRMED** — AGIArsenalConsole code (line 648): `contextUsagePercentage: p.contextUsagePercentage as number | undefined`. AIEverywhere docs confirm the same.

---

## Section 6: Implementation Plan

### Claim: Architecture with WorkerPool, asyncio.Queue, ResultCollector
**CONFIRMED as viable** — Matches proven patterns from Botctl (Rust) and Agent-Orchestrator (Python). The asyncio approach is sound.

### Claim: Crash recovery via checking `proc.returncode`
**CONFIRMED** — Agent-Orchestrator code (line 230): `if self.proc.poll() is not None: return "FAILED"`. AISlackBot also checks process liveness.

---

## Section 7: Custom Agent Definition

### Claim: Create agent at `~/.kiro/agents/debate-worker.json`
**CONFIRMED** — File exists at that path (verified on disk). Contains valid agent definition with name, description, mcpServers, prompt, and tools fields.

### Claim: Agent JSON schema at `https://raw.githubusercontent.com/aws/amazon-q-developer-cli/refs/heads/main/schemas/agent-v1.json`
**UNVERIFIED** — Not fetched/verified. The actual debate-worker.json on disk does not include a `$schema` field.

---

## Section 8: Key Differences Table

### Claim: --no-interactive startup time is 15-20s per turn (MCP init)
**UNVERIFIED** — `--no-interactive` flag confirmed to exist on `kiro-cli chat`. The 15-20s timing is plausible for MCP server initialization but not measured.

### Claim: ACP startup is 15-20s once, then instant
**UNVERIFIED** — Plausible based on architecture (MCP servers initialize once per process), but not measured. AIVirtuosoContext mentions "Runs in ~4 seconds for a simple prompt round-trip" after initialization.

---

## Section 9: Related Projects

### Claim: Botctl exists
**CONFIRMED** — Found via code search, active repository.

### Claim: KiroClaw exists
**UNVERIFIED** — Code search for "KiroClaw" returned 0 results. Wiki reference exists in findings but repo not found. May be a private/renamed repo.

### Claim: Hanami, AMek, KiroGateway, Agent-Orchestrator, PersonalKiroSlackAgent exist
**PARTIALLY CONFIRMED** — Agent-Orchestrator confirmed via code search. Others not verified.

---

## Section 10: Risks and Mitigations

### Claim: `--require-mcp-startup` flag exists
**CONTRADICTED** — Not found in `kiro-cli acp --help` output. The flag does not exist on the current version (2.3.0). Botctl uses `mcp_wait_ms` (a time-based wait) instead.

### Claim: Auth token refresh is handled by kiro-cli
**UNVERIFIED** — Plausible but not confirmed via code or docs.

---

## Critical Issues Found

1. **Python code bug (Section 2):** The `session/prompt` params use `"content"` but should use `"prompt"` based on working implementations and protocol spec. This will cause silent failures.

2. **Non-existent flag (Section 10):** `--require-mcp-startup` does not exist. Use Botctl's `mcp_wait_ms` pattern (time-based wait after session/new) instead.

3. **Version claim (Section 1):** "Available since kiro-cli 1.25.0" appears fabricated. Version numbering doesn't match observed semver pattern (current: 2.3.0).

---

## Validation Methodology

- **Local CLI testing:** Ran `kiro-cli acp --help`, `kiro-cli --version`, `kiro-cli chat --help`
- **Filesystem verification:** Checked `~/.kiro/sessions/cli/`, `~/.kiro/agents/`
- **Internal code search:** Searched Botctl, AISlackBot, Agent-Orchestrator, AGIArsenalMesh, AIVirtuosoCLI, AIM-AgentForge, AGIArsenalConsole, AIpiary, AIVirtuosoTUI, and others
- **Web search:** Verified ACP origin (Zed Industries)
- **Cross-referencing:** Compared findings against official kiro.dev docs cached in multiple repos
