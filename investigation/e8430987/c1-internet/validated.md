# Validation Report: Persistent kiro-cli Agents as Queue Workers

**Validator**: c1-internet validator  
**Date**: 2026-05-13T21:28 MDT  
**Method**: Cross-referenced official kiro.dev documentation, verified CLI flags locally, checked external source URLs via web search/fetch.

---

## Section 1: kiro-cli Capabilities

### Headless Mode (`--no-interactive`)

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Requires `KIRO_API_KEY` environment variable | **CONFIRMED** | Official docs at kiro.dev/docs/cli/headless/ explicitly state this |
| Syntax: `kiro-cli chat --no-interactive --trust-all-tools "prompt here"` | **CONFIRMED** | Verified in official docs AND local `kiro-cli chat --help` output |
| Prints response to stdout and exits | **CONFIRMED** | Official docs: "pass a prompt, and Kiro executes it end-to-end" |
| "No mid-session user input is possible" | **CONFIRMED** | Exact quote from official docs Limitations section |
| Can pipe context: `cat file.txt \| kiro-cli chat --no-interactive "process this"` | **CONFIRMED** | Official docs CI/CD examples section shows this exact pattern |
| Supports `--agent` flag | **CONFIRMED** | Verified locally via `kiro-cli chat --help`: `--agent <AGENT>` present |
| Supports `--trust-all-tools` or `--trust-tools=read,grep,write` | **CONFIRMED** | Both flags confirmed in local help output and official docs |

### Session Management

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Sessions auto-save per-directory | **CONFIRMED** | Official docs: "Kiro CLI automatically saves all chat sessions on every conversation turn. Sessions are stored per-directory" |
| Stored in SQLite in `~/.kiro/` | **CONFIRMED** | Official docs Technical Details: "Storage: SQLite database in ~/.kiro/" |
| Can resume: `kiro-cli chat --resume-id <SESSION_ID>` | **CONFIRMED** | Verified in local CLI help AND official docs |
| `--resume-id` could maintain conversation history across calls | **CONFIRMED** | Docs confirm full conversation history is restored on resume |

### Context Compaction

| Claim | Verdict | Evidence |
|-------|---------|----------|
| `/compact` command summarizes conversation history | **CONFIRMED** | Changelog 1-24: "Free up context space with the /compact command" |
| Auto-triggers when context window overflows | **CONFIRMED** | Changelog 1-24: "Compaction also triggers automatically when your context window overflows" |
| Configurable: `compaction.excludeMessages` and `compaction.excludeContextWindowPercent` | **CONFIRMED** | Changelog 1-24 explicitly names both settings |

### Custom Agent Configuration

| Claim | Verdict | Evidence |
|-------|---------|----------|
| JSON format stored in `~/.kiro/agents/` (global) or `.kiro/agents/` (project) | **CONFIRMED** | Official docs + verified locally: `ls ~/.kiro/agents/` shows 20+ agent JSON files |
| Key fields: `name`, `prompt`, `tools`, `mcpServers`, `allowedTools`, `hooks`, `resources` | **CONFIRMED** | All fields documented in official configuration reference |
| `prompt` supports `file://` URIs for external prompt files | **CONFIRMED** | Official docs with examples |
| Hooks: `agentSpawn`, `userPromptSubmit`, `preToolUse`, `postToolUse`, `stop` | **CONFIRMED** | All five hooks documented in official reference |
| `stop` hook fires when assistant finishes responding — could be used for "never stop" but only in interactive mode | **UNVERIFIED** | The docs confirm `stop` fires "when the assistant finishes responding" but do NOT explicitly state it's interactive-only. In `--no-interactive` mode the process exits after responding regardless of hooks. The inference is reasonable but not explicitly documented. |

### Subagents

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Up to 4 parallel subagents | **CONFIRMED** | Official docs: "Run up to four subagents at once" |
| DAG-based task dependencies | **CONFIRMED** | Official docs: "directed acyclic graph (DAG) where tasks can depend on each other" |
| Each subagent gets its own isolated context | **CONFIRMED** | Official docs: "Subagents run independently with their own context" |
| `trustedAgents` config allows unattended spawning | **CONFIRMED** | Official docs show `trustedAgents` in `toolsSettings.subagent` |
| Not suitable for persistent workers — ephemeral within parent session | **CONFIRMED** | Docs describe subagents as task-scoped; they call `summary` tool and return results to parent |

### Stdin Piping

| Claim | Verdict | Evidence |
|-------|---------|----------|
| `cat build-error.log \| kiro-cli chat --no-interactive "Explain this"` works | **CONFIRMED** | Official docs CI/CD examples section |
| GitHub issue #4497 mentions "Bad file descriptor" on Linux for interactive mode without TTY | **CONFIRMED** | Issue exists at github.com/kirodotdev/Kiro/issues/4497 with exact title "kiro-cli interactive mode fails with 'Bad file descriptor (os error 9)' on Linux" |

---

## Section 2: The Ralph Loop Pattern

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Ralph Loop is a recursive AI agent pattern using infinite shell loop + filesystem as memory | **CONFIRMED** | Multiple authoritative sources (thomas-wiegold.com, medium.com, linearb.io, zerosync.co, dreamhost.com) all describe this pattern consistently |
| Source: thomas-wiegold.com/blog/ralph-loop-how-recursive-ai-agents-work/ | **CONFIRMED** | URL exists, snippet matches description |
| Source: blakecrosley.com/blog/ralph-agent-architecture | **CONFIRMED** | URL exists, describes stop-hook loops and fresh context per iteration |
| Source: github.com/snarktank/ralph | **CONFIRMED** | Repo exists: "Ralph is an autonomous AI agent loop that runs repeatedly until all PRD items are complete" |
| Source: github.com/vercel-labs/ralph-loop-agent | **CONFIRMED** | Repo exists with 652 stars, Apache-2.0 license, "Continuous Autonomy for the AI SDK" |
| Each iteration starts with fresh context window | **CONFIRMED** | Core principle of the pattern per all sources |
| LLMs degrade past ~100K tokens | **UNVERIFIED** | This is a commonly cited claim in the AI community but the specific threshold varies. The Ralph Loop sources reference "context degradation" generally without citing a specific 100K number. Reasonable claim but not precisely sourced. |

---

## Section 3-8: Implementation Plan (Architecture, Worker Script, Orchestrator, Performance)

These sections are **design proposals/recommendations**, not factual claims. They cannot be "confirmed" or "contradicted" in the traditional sense. However, I can validate the technical assumptions underlying them:

| Technical Assumption | Verdict | Evidence |
|---------------------|---------|----------|
| `mv` is atomic on same filesystem (macOS) | **CONFIRMED** | macOS `man 2 rename`: "cause the source and target to be atomically" — POSIX guarantee |
| `--require-mcp-startup` flag exists | **CONFIRMED** | Verified in local `kiro-cli chat --help` output |
| 15-20 seconds per `--no-interactive` call | **UNVERIFIED** | Stated as "current observed" from user's system. Cannot independently verify without running timed tests. Plausible given MCP startup + auth + LLM response time. |
| 10x improvement from parallelism (700 sequential → 10 workers) | **UNVERIFIED** | Math is correct (700/10 × 20s ≈ 23min vs 700 × 20s ≈ 4hr). Assumes no API rate limiting, no resource contention, and linear scaling — all unverified assumptions. |
| `pgrep -c kiro-cli` counts active processes | **CONFIRMED** | Standard Unix command, works on macOS |
| Filesystem queue with atomic `mv` prevents race conditions | **CONFIRMED** | Well-established pattern; `rename(2)` atomicity guarantees this on same partition |

---

## Section 9: The "Work Loop" Skill Pattern

| Claim | Verdict | Evidence |
|-------|---------|----------|
| eliteai.tools work-loop skill exists | **CONFIRMED** | URL confirmed: eliteai.tools/index.php/agent-skills/work-loop-2 — "Queue-driven work orchestrator. Processes requests from do-work/requests/ using isolated sub-agents" |
| 163 GitHub stars | **UNVERIFIED** | Cannot verify this specific number. eliteai.tools is a website, not a GitHub repo. The star count may refer to a related GitHub repo but no source is cited for this specific number. |
| Core principle: "The Orchestrator never performs task work. Every request spawns a fresh sub-agent." | **UNVERIFIED** | The search snippet confirms queue-driven orchestration with isolated sub-agents, but the exact quote cannot be verified without fetching the full page. Pattern matches the description. |

---

## Section 10-11: Decisions, Trade-offs, and Risks

These are **analytical recommendations**, not factual claims. The reasoning is sound and consistent with the confirmed technical facts above.

One notable claim to validate:

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Interactive mode requires TTY; fails with "Bad file descriptor" in non-TTY | **CONFIRMED** | GitHub issue #4497 confirms this exact behavior |
| `launch_agent` (kiro-agents MCP tool) agents are ephemeral | **CONFIRMED** | From my own tool list, `launch_agent` description says "Returns immediately with a job_id" — designed for single tasks |

---

## Source URL Validation

| # | Cited URL | Verdict | Notes |
|---|-----------|---------|-------|
| 1 | kiro.dev/docs/cli/headless/ | **CONFIRMED** | Fetched and verified |
| 2 | kiro.dev/docs/cli/chat/ | **CONFIRMED** | Found in search results |
| 3 | kiro.dev/docs/cli/chat/session-management/ | **CONFIRMED** | Fetched and verified |
| 4 | kiro.dev/docs/cli/custom-agents/configuration-reference/ | **CONFIRMED** | Fetched and verified |
| 5 | kiro.dev/docs/cli/chat/subagents/ | **CONFIRMED** | Fetched and verified |
| 6 | kiro.dev/blog/cli-2-0/ | **CONTRADICTED** | The correct URL is `kiro.dev/changelog/cli/2-0/` (not /blog/). Content exists at the changelog URL with title "Windows Support, Headless Mode, and Terminal UI" |
| 7 | kiro.dev/blog/introducing-headless-mode/ | **CONFIRMED** | Found in search results |
| 8 | kiro.dev/changelog/cli/1-24/ | **CONFIRMED** | Fetched and verified |
| 9 | thomas-wiegold.com/blog/ralph-loop-how-recursive-ai-agents-work/ | **CONFIRMED** | Found in search results |
| 10 | blakecrosley.com/blog/ralph-agent-architecture | **CONFIRMED** | Found in search results |
| 11 | eliteai.tools/index.php/agent-skills/work-loop-2 | **CONFIRMED** | Found in search results |
| 12 | github.com/kirodotdev/Kiro/issues/4497 | **CONFIRMED** | Found in search results with matching title |

---

## Summary Statistics

- **CONFIRMED**: 38 claims
- **UNVERIFIED**: 6 claims (mostly performance projections and one unverifiable star count)
- **CONTRADICTED**: 1 claim (Source URL #6 path is wrong: `/blog/cli-2-0/` should be `/changelog/cli/2-0/`)

## Overall Assessment

**HIGH CONFIDENCE** — The findings document is well-researched and overwhelmingly accurate. All core technical claims about kiro-cli capabilities are confirmed against official documentation and local CLI verification. The Ralph Loop pattern is well-established with multiple independent sources. The single contradiction is a minor URL path error. The unverified claims are reasonable projections that cannot be independently confirmed without runtime testing.

The implementation plan is architecturally sound and based on confirmed primitives (atomic mv, --no-interactive mode, custom agents, filesystem I/O). The main risk not addressed is potential API rate limiting from the kiro.dev backend when running 10 parallel workers.
