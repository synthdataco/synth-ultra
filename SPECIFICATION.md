# Synth Ultra — competition specification

Each prediction, a model outputs the distribution of the BTC price 10 seconds
ahead and is scored on live market data. This document defines the task, the
runtime environment, the scoring, and the submission format.

## Context

Synth Ultra targets ultra-low-latency, short-horizon price prediction —
autocorrelation, order flow, and estimating the current price from deep,
fast-moving order books. Models run inside Synth's evaluation environment under a
hard latency budget so they can feed directly into live trading systems.

## The task

For asset **BTC**, predict the **100 percentiles** of the price **10 seconds**
after the prediction time (`current_time_ms + 10_000`).

The output is a length-100 array on the centered quantile grid
`q_i = (2i − 1) / 200`, `i = 1..100` (0.005, 0.015, …, 0.995). It must be:

- shape `(100,)`, dtype `float64`,
- **finite**, **strictly positive**, and **non-decreasing**.

Model interface:

```python
def predict_percentiles(payload: dict) -> np.ndarray:  # shape (100,)
    ...
```

`payload` is the market-data snapshot specified in [`input.md`](input.md); it is
the model's only input.

## Environment

The model runs inside Synth's evaluation environment, under these constraints:

- **Latency** — under **5 ms** per call, strictly enforced. A prediction that
  exceeds the budget does not count.
- **No network access** during inference — the payload is the only input.
- **Deterministic** — the same payload must produce the same output.
- **Isolated and resource-limited** — the model runs in a sandboxed container with
  a fixed CPU and memory allocation and no persistent writable storage. It cannot
  observe or affect other participants.
- **CPU only** for the initial competition (no GPU).

## Input data

Each prediction, the model receives a snapshot of Binance **spot** and **USDT-M
futures** data for BTCUSDT: 1 hour of 1-second candles, an order-book snapshot to
a set depth from ~60 s prior plus every subsequent update and the latest
snapshot, and 60 s of aggregate trades and book-ticker updates. Full schema,
field reference, and timestamp semantics: [`input.md`](input.md).

## Scoring

Predictions are graded by **pinball-loss CRPS** against the realized price —
lower is better, in price units:

```
CRPS = (2/N) · Σ_i  ρ_τ_i( y − x_i ),   τ_i = (2i−1)/200,   ρ_τ(u) = u·(τ − 1{u<0})
```

where `x_i` are the predicted percentiles, `y` is the realized price, and
`N = 100`.

**Realized price.** The target `y` is the spot **microprice**

```
microprice = (bid_price·ask_qty + ask_price·bid_qty) / (bid_qty + ask_qty)
```

computed from the **last spot book-ticker update at or before**
`current_time_ms + 10_000` — the best bid/ask prevailing at the target instant. A
prediction is not scored (dropped, no penalty) if the spot feed is not live
around that instant.

Models are evaluated **continuously on live market data**; scores accumulate over
time and are visible to all participants. Lower average CRPS ranks higher.

## Submission

> Submissions are not open yet; the base image and submission client will be
> published before they open. See the [FAQ](FAQ.md) for the current details.

You submit a **Docker image** that exposes the model behind the
`predict_percentiles` interface, built `FROM` a Synth-provided base image. You
push the image to a per-hotkey registry repository Synth provisions for you and
submit a **signed reference to it by digest** — Synth runs the image as-is and
does not build it for you. It must run under the environment constraints above
(CPU-only, no network at inference, deterministic, under the 5 ms budget).
