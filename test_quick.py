#!/usr/bin/env python3
"""Quick test: simple factual debate to validate the ACP-based system."""
import asyncio
import sys
sys.path.insert(0, ".")

import config
config.MAX_EXCHANGES = 3  # runtime override for quick test only
config.MAX_DEPTH = 2

from orchestrator import Orchestrator


async def main():
    topic = "Is water wet, or does it only make other things wet?"
    print(f"=== QUICK DEBATE TEST ===")
    print(f"Topic: {topic}")
    print(f"Max rounds: {config.MAX_EXCHANGES} (test override)")
    print()
    orch = Orchestrator(topic=topic, work_dir=".")
    state = await orch.run()
    print(f"\n=== FINAL RESULTS ===")
    print(f"Contentions: {len(state.tree)}")
    print(f"Truths: {len(state.found_truths)}")


if __name__ == "__main__":
    asyncio.run(main())
