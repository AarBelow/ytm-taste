# tests/test_concurrency.py
import time

from ytm_taste import concurrency


def test_run_concurrently_preserves_order_and_applies_func():
    assert concurrency.run_concurrently(lambda x: x * x, [1, 2, 3, 4]) == [1, 4, 9, 16]


def test_run_concurrently_empty_returns_empty_and_does_nothing():
    calls = []
    assert concurrency.run_concurrently(lambda x: calls.append(x), []) == []
    assert calls == []


def test_run_concurrently_actually_runs_in_parallel():
    def slow(x):
        time.sleep(0.1)
        return x

    start = time.monotonic()
    result = concurrency.run_concurrently(slow, [1, 2, 3, 4, 5], max_workers=5)
    elapsed = time.monotonic() - start
    assert result == [1, 2, 3, 4, 5]
    # 5 x 0.1s sequential would be ~0.5s; concurrent with 5 workers ~0.1s
    assert elapsed < 0.35
