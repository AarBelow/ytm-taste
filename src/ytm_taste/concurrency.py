# src/ytm_taste/concurrency.py
from concurrent.futures import ThreadPoolExecutor


def run_concurrently(func, items, max_workers=5):
    items = list(items)
    if not items:
        return []
    workers = min(max_workers, len(items))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(func, items))
