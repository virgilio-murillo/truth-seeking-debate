#!/usr/bin/env python3
import asyncio
import sys
from config import AGENT_MAP, DEFAULT_AGENT
from orchestrator import Orchestrator


def detect_agent(topic: str) -> str:
    topic_lower = topic.lower()
    for agent, keywords in AGENT_MAP.items():
        if any(kw in topic_lower for kw in keywords):
            return agent
    return DEFAULT_AGENT


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py '<debate topic>' [work_dir] [--agent NAME]")
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    topic = args[0]
    work_dir = args[1] if len(args) > 1 else "."

    # --agent flag overrides auto-detection
    agent = None
    for i, a in enumerate(sys.argv):
        if a == "--agent" and i + 1 < len(sys.argv):
            agent = sys.argv[i + 1]
    if not agent:
        agent = detect_agent(topic)

    print(f"🤖 Agent: {agent}")
    orch = Orchestrator(topic=topic, work_dir=work_dir, agent=agent)
    asyncio.run(orch.run())


if __name__ == "__main__":
    main()
