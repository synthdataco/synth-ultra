# Synth Ultra

An ultra-low-latency forecasting competition: predict the distribution of the
**BTC, ETH, SOL and XRP prices 10 seconds ahead**, from live Binance order-book and
trade data, with a model that runs in **under 5 ms**. Each asset is its own
competition.

Synth builds predictive models and applies them to financial markets. Synth Ultra
targets the shortest horizons — short-term dynamics such as autocorrelation and
order flow, and extracting the best estimate of the current price from deep,
fast-moving crypto order books — with models that feed directly into Synth's
trading systems.

## What you build

A model that:

- predicts **100 percentiles** of the asset's price **10 seconds** into the future
  (the asset is named in each prompt; one model answers every asset it handles),
- runs in **under 5 ms** per prediction (strictly enforced), and
- meets the technical specification so it runs directly in Synth's evaluation
  environment.

Models are evaluated continuously on live market data; scores are visible to all
participants.

## Data available to the model

Each prediction, the model receives — for the prompted asset, on Binance **spot** and
**USDT-M futures** (`BTCUSDT`, `ETHUSDT`, `SOLUSDT` or `XRPUSDT`):

- the last **1 hour** of 1-second candles (OHLCV),
- an order-book snapshot to a set depth from ~**60 s** prior, every subsequent
  order-book update, and the latest snapshot,
- **60 s** of aggregate trades, and
- **60 s** of book-ticker updates (best bid/ask price and size),
- **1 h** of futures liquidations (forced position closures), and
- a coarse **banded view of the whole spot book** (100 bands per side; $10 wide on BTC,
  sized to each asset's volatility on the others), refreshed every ~30 s alongside the
  live 20-level snapshot, and
- **60 s of Bybit perpetual-futures trades** for the same symbol — as received in Tokyo, so
  typically ~40 ms behind Bybit's own clock.

Full schema: [`input.md`](input.md). Full competition spec:
[`SPECIFICATION.md`](SPECIFICATION.md). Answers to the questions participants
actually ask — the latency budget, call rate, the compute environment:
[`FAQ.md`](FAQ.md).

## Rewards & participation

- **25%** of total subnet miner rewards are allocated to Synth Ultra, split equally
  between its assets: each asset is a separate competition with its own ranking.
- **Rollout:** ETH, SOL and XRP are prompted from 2026-10-16 (a shadow period: scored and
  shown, not yet paid) and paid from 2026-10-20. Until then BTC takes the whole 25%.
- **To join, apply with `client/submit.py apply`** — see [`ONBOARDING.md`](ONBOARDING.md). The
  application is signed with your hotkey; we approve it, create your registry repo and push key,
  and you collect the key yourself over a signed request — we never email you a credential.
- Your hotkey must already hold a **registered uid on subnet 50** before you can apply.
- **Prompt dataset:** real prompts from each of the last 7 days, with the price that followed, how
  the field scored, and your own answers — `client/download_dataset.py`, see
  [`input.md`](input.md#prompt-dataset).

## Objective

Build market-beating, ultra-low-latency predictive models that can generalize
across assets and feed directly into Synth's trading systems — competing at the
shortest market horizons, where HFT firms operate.
