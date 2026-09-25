#!/usr/bin/env python3
"""Check your model against a real payload, before you submit.

Loads a payload, calls your entrypoint the way the evaluation runtime does, and checks
the response against the contract — shape, dtype, finiteness, positivity, monotonicity —
then times it against the 5 ms target.

    uv run --no-project --with numpy python client/validate.py \\
        --entrypoint my_model.model --payload samples/sample_payload.json

Point it at samples/real_payload.json.gz for production-sized input: that is where a model
that looks fast on the small sample discovers it scales with row count.

This checks the CONTRACT, not your accuracy. Passing here means the runtime will accept
your output, nothing more.
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

GRID = (2 * np.arange(1, 101) - 1) / 200.0


def load_payload(path: Path) -> dict:
    raw = gzip.open(path, "rt") if path.suffix == ".gz" else path.open("rt")
    with raw as handle:
        payload = json.load(handle)
    # The runtime hands you numpy arrays, not lists. Converting here means a model that
    # only works on lists fails HERE rather than in production.
    return _arrays(payload)


def _arrays(value):
    """JSON lists back to numpy, including NESTED ones.

    `ohlcv` is (n, 5) and `bids`/`asks` are (levels, 2) — a converter that only handles
    flat lists hands a model a list-of-arrays, and `ohlcv[:, 3]` raises. The runtime gives
    you real 2-D arrays, so this has to as well or the harness passes what production
    rejects.
    """
    if isinstance(value, dict):
        return {k: _arrays(v) for k, v in value.items()}
    if isinstance(value, list):
        if value:
            candidate = np.asarray(value)
            if candidate.dtype.kind in "ifb":  # numeric or bool, any dimensionality
                return candidate
        return [_arrays(v) for v in value]
    return value


def resolve(entrypoint: str):
    module_name, _, attr = entrypoint.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr or "predict_percentiles")


def check(out) -> list[str]:
    problems = []
    if not isinstance(out, np.ndarray):
        return [f"returned {type(out).__name__}, expected numpy.ndarray"]
    if out.dtype.kind not in "if":
        problems.append(f"dtype is {out.dtype}, expected a float or int dtype")
    if out.shape != (100,):
        return problems + [f"shape is {out.shape}, expected (100,)"]
    arr = out.astype(np.float64, copy=False)
    if not np.isfinite(arr).all():
        problems.append(f"{int((~np.isfinite(arr)).sum())} value(s) are NaN or infinite")
    if not (arr > 0).all():
        problems.append(f"{int((arr <= 0).sum())} value(s) are not strictly positive")
    if not (np.diff(arr) >= 0).all():
        bad = int((np.diff(arr) < 0).sum())
        problems.append(f"values decrease at {bad} position(s) — they must be non-decreasing")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrypoint", required=True, help="module, or module:function")
    ap.add_argument("--payload", required=True, type=Path)
    ap.add_argument("--runs", type=int, default=200, help="timed calls after a warm-up")
    args = ap.parse_args()

    payload = load_payload(args.payload)
    venue = payload["venues"]["spot"]
    print(f"payload: schema_version {payload['schema_version']}, trigger {payload['prompt']['trigger']['kind']}")
    print(
        f"         spot {len(venue['candles_1s']['open_time_ms']):,} candles, "
        f"{len(venue['book_ticker']['recv_ts_ms']):,} book_ticker, "
        f"{len(venue['trades']['recv_ts_ms']):,} trades"
    )

    predict = resolve(args.entrypoint)
    predict(payload)  # warm-up, exactly as the runtime gives you one
    out = predict(payload)

    problems = check(out)
    if problems:
        print("\nFAILED the response contract:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nresponse contract: OK  (100 finite, positive, non-decreasing values)")

    times = []
    for _ in range(args.runs):
        start = time.perf_counter()
        predict(payload)
        times.append((time.perf_counter() - start) * 1000)
    times.sort()
    p50, p99, worst = statistics.median(times), times[int(0.99 * len(times)) - 1], times[-1]
    print(f"latency over {args.runs} calls: p50 {p50:.3f} ms, p99 {p99:.3f} ms, max {worst:.3f} ms")
    if p99 >= 5.0:
        print("  p99 is over the 5 ms target — see the FAQ on what is enforced today.")
    print("\nThis checks the contract, not your accuracy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
