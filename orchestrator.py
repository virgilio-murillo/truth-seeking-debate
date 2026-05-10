import asyncio
import json
import time
from pathlib import Path
from acp import call_agent, status_ticker, _ts
from models import ContentionNode, DebateState, Exchange, Status, Truth
from prompts import (
    opening_prompt, contention_identification_prompt,
    debate_round_prompt, judge_prompt, relevance_gate_prompt,
    agreement_validation_prompt,
)
from config import MAX_DEPTH, MAX_EXCHANGES, RELEVANCE_THRESHOLD, RELEVANCE_THRESHOLD_DEEP


class Orchestrator:
    def __init__(self, topic: str, work_dir: str):
        self.state = DebateState(topic=topic)
        self.work_dir = work_dir
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._counter = 0

    async def run(self) -> DebateState:
        print(f"[{_ts()}] [DEBATE] Topic: {self.state.topic}\n", flush=True)

        # Phase 1: Opening statements (parallel)
        print(f"[{_ts()}] [PHASE 1] Opening statements...", flush=True)
        self.state.opening_a, self.state.opening_b = await asyncio.gather(
            call_agent(opening_prompt(self.state.topic, "a"), self.work_dir),
            call_agent(opening_prompt(self.state.topic, "b"), self.work_dir),
        )
        print(f"[{_ts()}] Team A: {self.state.opening_a[:100]}...", flush=True)
        print(f"[{_ts()}] Team B: {self.state.opening_b[:100]}...\n", flush=True)

        # Phase 2: Identify contentions
        print(f"[{_ts()}] [PHASE 2] Identifying contentions...", flush=True)
        raw = await call_agent(
            contention_identification_prompt(self.state.opening_a, self.state.opening_b),
            self.work_dir,
        )
        contentions = self._parse_contentions(raw)
        print(f"[{_ts()}] Found {len(contentions)} contention points\n", flush=True)
        for c in contentions:
            self._enqueue(c)

        # Phase 3: Debate + Judge
        print(f"[{_ts()}] [PHASE 3] Debating...", flush=True)
        ticker = asyncio.create_task(status_ticker(30))
        workers = [asyncio.create_task(self._worker(i)) for i in range(4)]
        await self.queue.join()
        ticker.cancel()
        for _ in workers:
            await self.queue.put((999999, 999999, None))
        await asyncio.gather(*workers)

        self._save()
        print(f"\n[{_ts()}] [DONE] {len(self.state.found_truths)} truths found:", flush=True)
        for t in self.state.found_truths:
            print(f"  ✓ [{t.confidence:.1f}] {t.statement}", flush=True)
        return self.state

    def _parse_contentions(self, raw: str) -> list[ContentionNode]:
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            s, e = raw.find("["), raw.rfind("]") + 1
            items = json.loads(raw[s:e]) if s >= 0 else []
        nodes = []
        for item in items:
            node = ContentionNode(
                claim=item.get("claim", ""),
                team_a_position=item.get("team_a_position", ""),
                team_b_position=item.get("team_b_position", ""),
            )
            self.state.tree[node.id] = node
            nodes.append(node)
        return nodes

    def _enqueue(self, node: ContentionNode):
        self._counter += 1
        self.queue.put_nowait((node.priority, self._counter, node))

    async def _worker(self, wid: int):
        while True:
            _, _, node = await self.queue.get()
            if node is None:
                self.queue.task_done()
                break
            print(f"  [{_ts()}] [W{wid}] → {node.claim[:50]}... (d={node.depth}, r={node.current_round})", flush=True)
            await self._run_contention(node, wid)
            self.queue.task_done()

    async def _run_contention(self, node: ContentionNode, wid: int):
        node.status = Status.ACTIVE
        while node.current_round < MAX_EXCHANGES:
            node.current_round += 1
            truths = self._truths_ctx()

            # Team A
            a_resp = await call_agent(debate_round_prompt(node, "a", truths), self.work_dir)
            node.exchanges.append(Exchange(round=node.current_round, team="a", content=a_resp))
            print(f"    [{_ts()}] [W{wid}] R{node.current_round}A: {a_resp[:60]}...", flush=True)

            if await self._check_signals(node, a_resp, "a", wid):
                return

            # Team B (gets A's argument via full history in prompt)
            b_resp = await call_agent(debate_round_prompt(node, "b", truths), self.work_dir)
            node.exchanges.append(Exchange(round=node.current_round, team="b", content=b_resp))
            print(f"    [{_ts()}] [W{wid}] R{node.current_round}B: {b_resp[:60]}...", flush=True)

            if await self._check_signals(node, b_resp, "b", wid):
                return

        # 7 rounds done → judge
        await self._judge(node, wid)

    async def _check_signals(self, node, resp, team, wid) -> bool:
        if "AGREEMENT:" in resp:
            if await self._handle_agreement(node, resp, team, wid):
                return True
        if "CHILD_CONTENTION:" in resp and node.depth < MAX_DEPTH:
            if await self._handle_child(node, resp, wid):
                return True
        return False

    async def _handle_agreement(self, node, resp, team, wid) -> bool:
        try:
            raw = resp[resp.index("AGREEMENT:") + 10:].strip()
            agreement = _parse_json(raw)
        except (ValueError, json.JSONDecodeError):
            return False
        if not agreement.get("reason"):
            return False
        # Validate
        val_resp = await call_agent(agreement_validation_prompt(node, agreement, team), self.work_dir)
        val = _parse_json(val_resp)
        if val.get("valid"):
            node.status = Status.AGREED
            node.truth = val.get("truth", agreement.get("revised_position", ""))
            node.winner = f"team_{'b' if team == 'a' else 'a'}"
            if node.truth:
                self.state.found_truths.append(Truth(node.truth, node.id, val.get("confidence", 0.7)))
            print(f"    [{_ts()}] [W{wid}] ✅ AGREED: {node.truth}", flush=True)
            self._notify_parent(node)
            return True
        return False

    async def _handle_child(self, parent, resp, wid) -> bool:
        try:
            raw = resp[resp.index("CHILD_CONTENTION:") + 17:].strip()
            data = _parse_json(raw)
        except (ValueError, json.JSONDecodeError):
            return False
        if not data.get("claim"):
            return False
        # Relevance gate
        threshold = RELEVANCE_THRESHOLD_DEEP if parent.depth > 3 else RELEVANCE_THRESHOLD
        gate_resp = await call_agent(relevance_gate_prompt(parent, data["claim"]), self.work_dir)
        gate = _parse_json(gate_resp)
        if not gate.get("relevant") or gate.get("score", 0) < threshold:
            return False
        # Spawn
        child = ContentionNode(
            parent_id=parent.id, claim=data["claim"],
            team_a_position=data.get("your_position", ""),
            team_b_position=data.get("opponent_position", ""),
            depth=parent.depth + 1,
        )
        self.state.tree[child.id] = child
        parent.children.append(child.id)
        parent.status = Status.PAUSED
        parent.was_paused = True
        self._enqueue(child)
        print(f"    [{_ts()}] [W{wid}] 🌱 CHILD {child.id} (d={child.depth})", flush=True)
        return True

    async def _judge(self, node, wid):
        resp = await call_agent(judge_prompt(node), self.work_dir)
        result = _parse_json(resp)
        node.winner = result.get("winner", "both_correct")
        node.truth = result.get("truth")
        node.status = Status.RESOLVED
        if node.truth:
            self.state.found_truths.append(Truth(node.truth, node.id, result.get("confidence", 0.5)))
        print(f"    [{_ts()}] [W{wid}] ⚖️ JUDGED: {node.winner} | {node.truth}", flush=True)
        self._notify_parent(node)

    def _notify_parent(self, child: ContentionNode):
        if not child.parent_id:
            return
        parent = self.state.tree.get(child.parent_id)
        if not parent or parent.status != Status.PAUSED:
            return
        if all(self.state.tree[c].status in (Status.RESOLVED, Status.AGREED)
               for c in parent.children if c in self.state.tree):
            parent.status = Status.PENDING
            parent.was_paused = True
            self._enqueue(parent)
            print(f"    [{_ts()}] 🔄 RESUME {parent.id}", flush=True)

    def _truths_ctx(self) -> str:
        if not self.state.found_truths:
            return "None yet."
        return "\n".join(f"- {t.statement}" for t in self.state.found_truths)

    def _save(self):
        p = Path(self.work_dir)
        # State
        (p / "debate_state.json").write_text(json.dumps({
            "topic": self.state.topic,
            "truths": [{"s": t.statement, "c": t.confidence} for t in self.state.found_truths],
            "tree": {nid: {"claim": n.claim, "status": n.status.value, "winner": n.winner,
                           "truth": n.truth, "depth": n.depth, "rounds": n.current_round}
                     for nid, n in self.state.tree.items()},
        }, indent=2))
        # Truths
        with open(p / "found_truths.jsonl", "w") as f:
            for t in self.state.found_truths:
                f.write(json.dumps({"truth": t.statement, "confidence": t.confidence}) + "\n")


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s = text.find("{")
    e = text.rfind("}") + 1
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e])
        except json.JSONDecodeError:
            pass
    return {}
