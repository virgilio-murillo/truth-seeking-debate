#!/usr/bin/env python3
import asyncio
import sys
from orchestrator import Orchestrator


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py '<debate topic>' [work_dir]")
        sys.exit(1)
    topic = sys.argv[1]
    work_dir = sys.argv[2] if len(sys.argv) > 2 else "."
    orch = Orchestrator(topic=topic, work_dir=work_dir)
    asyncio.run(orch.run())


if __name__ == "__main__":
    main()
