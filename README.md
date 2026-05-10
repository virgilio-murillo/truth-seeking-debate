# Truth-Seeking Agentic Debate System

A multi-agent debate framework that finds truth through structured adversarial debate with recursive contention resolution.

## How It Works

Two teams (A and B) debate contention points to find truth. A judge resolves each contention and extracts verified truths.

```
Topic → Opening Statements → Contention Identification → Parallel Debate → Judge → Found Truths
                                                              ↓
                                                    Child Contentions (recursive)
```

### Key Features

- **7 exchanges max per contention** — but can finish early via honest agreement
- **Unlimited child contentions** — sub-disputes spawn recursively (max depth 7)
- **4 parallel workers** — split work across contentions, faster ones free up agents
- **Priority queue** — children resolved first (depth-first), parents resume after
- **Sycophancy detection** — agreements require evidence, judge validates
- **Relevance gating** — child contentions only spawn if material to parent
- **Found truths accumulate** — all agents see established truths in real-time

### Architecture

```
Orchestrator (Python asyncio)
├── 4 debate workers (grab contentions from priority queue)
├── Semaphore(10) — max concurrent agent calls
├── Priority Queue — children > resumed parents > new roots
└── Found Truths — append-only, shared across all rounds

Each agent call: kiro-cli chat --no-interactive (full contention history in prompt)
```

## Usage

```bash
python main.py "Is consciousness computable?" ./output
```

Or with the test script (reduced rounds for quick validation):

```bash
python test_quick.py
```

## Configuration

Edit `config.py`:

```python
MAX_DEPTH = 7        # max recursive contention depth
MAX_EXCHANGES = 7    # max rounds per contention (can finish early)
AGENT_SLOTS = 10     # max concurrent agent calls
```

## Requirements

- Python 3.12+
- [kiro-cli](https://kiro.dev) installed and authenticated
- Agent `investigator-child` available

## File Structure

```
├── main.py           # CLI entry point
├── orchestrator.py   # Asyncio event loop, workers, queue, coordination
├── acp.py            # Agent wrapper (kiro-cli --no-interactive)
├── prompts.py        # All prompt templates
├── models.py         # Dataclasses (ContentionNode, DebateState, Truth)
├── config.py         # Constants
└── test_quick.py     # Quick test (3 rounds)
```

## Output

- `debate_state.json` — full debate tree with all exchanges
- `found_truths.jsonl` — append-only list of established truths

## Design Decisions

Based on research from: ReDel (EMNLP 2024), MACI, iMAD (AAAI 2025), D3 framework, and multi-agent debate literature.

- **No max children** — tree grows organically, backpressure from semaphore only
- **Parent pause/resume** — parent releases slots when child spawns, re-queued when child resolves (prevents deadlock)
- **Work-splitting** — agents that finish fast grab next contention from queue
- **Full history per call** — each agent gets complete contention exchange history + found truths (no lost context)

## License

MIT
