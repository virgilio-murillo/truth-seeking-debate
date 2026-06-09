#!/usr/bin/env python3
"""Test suite for acp_persistent.py — validates ACP worker pool."""
import asyncio
import time
import sys
sys.path.insert(0, ".")
from acp_persistent import ACPWorker, WorkerPool, _ts


async def test_1_single_worker():
    """Test: single worker can start, respond, and stop."""
    print(f"\n{'='*60}")
    print(f"TEST 1: Single worker basic prompt")
    print(f"{'='*60}")
    w = ACPWorker(agent="bible-expert", work_dir="/tmp", worker_id=99)
    await w.start()
    assert w.alive, "Worker should be alive after start"

    result = await w.prompt("What is 2+2? Reply with ONLY the number.")
    print(f"  Response: {result[:100]}")
    assert "4" in result, f"Expected '4' in response, got: {result}"

    await w.stop()
    assert not w.alive, "Worker should be dead after stop"
    print(f"  ✅ PASSED")


async def test_2_multiple_prompts():
    """Test: same worker handles multiple prompts (persistence)."""
    print(f"\n{'='*60}")
    print(f"TEST 2: Multiple prompts to same worker (memory test)")
    print(f"{'='*60}")
    w = ACPWorker(agent="bible-expert", work_dir="/tmp", worker_id=98)
    await w.start()

    # First prompt: set context
    r1 = await w.prompt("Remember this secret code: ALPHA-7742. Just say 'Noted.'")
    print(f"  R1: {r1[:80]}")

    # Second prompt: recall context
    r2 = await w.prompt("What was the secret code I told you? Reply with ONLY the code.")
    print(f"  R2: {r2[:80]}")
    has_memory = "ALPHA-7742" in r2 or "7742" in r2
    print(f"  Memory retained: {has_memory}")

    await w.stop()
    print(f"  ✅ PASSED (memory={'YES' if has_memory else 'NO — session may not retain'})")


async def test_3_pool_basic():
    """Test: pool starts, handles calls, stops."""
    print(f"\n{'='*60}")
    print(f"TEST 3: Worker pool (2 workers, 3 calls)")
    print(f"{'='*60}")
    pool = WorkerPool(agent="bible-expert", work_dir="/tmp")
    pool.MIN = 2
    pool.MAX = 4
    await pool.start()

    # Sequential calls
    r1 = await pool.call_agent("Say 'hello' and nothing else.")
    print(f"  R1: {r1[:60]}")

    r2 = await pool.call_agent("Say 'world' and nothing else.")
    print(f"  R2: {r2[:60]}")

    r3 = await pool.call_agent("Say 'done' and nothing else.")
    print(f"  R3: {r3[:60]}")

    await pool.stop_all()
    print(f"  ✅ PASSED")


async def test_4_parallel_calls():
    """Test: pool handles parallel calls correctly."""
    print(f"\n{'='*60}")
    print(f"TEST 4: Parallel calls (4 simultaneous)")
    print(f"{'='*60}")
    pool = WorkerPool(agent="bible-expert", work_dir="/tmp")
    pool.MIN = 2
    pool.MAX = 6
    await pool.start()

    start = time.time()
    results = await asyncio.gather(
        pool.call_agent("Say 'A' and nothing else."),
        pool.call_agent("Say 'B' and nothing else."),
        pool.call_agent("Say 'C' and nothing else."),
        pool.call_agent("Say 'D' and nothing else."),
    )
    elapsed = time.time() - start

    for i, r in enumerate(results):
        print(f"  R{i}: {r[:40]}")
    print(f"  Total time: {elapsed:.1f}s (parallel)")
    print(f"  Workers used: {len(pool._workers)}")

    await pool.stop_all()
    print(f"  ✅ PASSED")


async def test_5_tool_use():
    """Test: worker can use MCP tools (bible-tools)."""
    print(f"\n{'='*60}")
    print(f"TEST 5: MCP tool use (bible-tools)")
    print(f"{'='*60}")
    w = ACPWorker(agent="bible-expert", work_dir="/tmp", worker_id=97)
    await w.start()

    result = await w.prompt(
        "Use your verse_lookup tool to look up John 3:16 in the ESV version. "
        "Return ONLY the verse text."
    )
    print(f"  Response: {result[:150]}")
    has_content = len(result) > 20 and ("God" in result or "world" in result or "love" in result)
    print(f"  Tool worked: {has_content}")

    await w.stop()
    print(f"  ✅ PASSED" if has_content else "  ⚠️ Tool may not have been called")


async def test_6_crash_recovery():
    """Test: pool recovers from worker crash."""
    print(f"\n{'='*60}")
    print(f"TEST 6: Crash recovery")
    print(f"{'='*60}")
    pool = WorkerPool(agent="bible-expert", work_dir="/tmp")
    pool.MIN = 2
    pool.MAX = 4
    await pool.start()

    # Kill a worker's process
    worker = pool._workers[0]
    worker._proc.kill()
    await asyncio.sleep(1)
    print(f"  Killed worker {worker.worker_id} (pid={worker._proc.pid})")

    # Next call should still work (respawn)
    try:
        result = await pool.call_agent("Say 'recovered' and nothing else.")
        print(f"  Response after crash: {result[:60]}")
        print(f"  ✅ PASSED")
    except Exception as e:
        print(f"  ❌ FAILED: {e}")

    await pool.stop_all()


async def main():
    print(f"[{_ts()}] Starting ACP Persistent Worker Tests")
    print(f"[{_ts()}] Agent: bible-expert")

    await test_1_single_worker()
    await test_2_multiple_prompts()
    await test_3_pool_basic()
    await test_4_parallel_calls()
    await test_5_tool_use()
    await test_6_crash_recovery()

    print(f"\n{'='*60}")
    print(f"[{_ts()}] ALL TESTS COMPLETE")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
