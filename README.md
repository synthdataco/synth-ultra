# Synth Ultra

An ultra-low-latency forecasting competition: predict the distribution of the
**BTC price 10 seconds ahead**, from live Binance order-book and trade data, with
a model that runs in **under 5 ms**.

Synth builds predictive models and applies them to financial markets. Synth Ultra
targets the shortest horizons — short-term dynamics such as autocorrelation and
order flow, and extracting the best estimate of the current price from deep,
fast-moving crypto order books — with models that feed directly into Synth's
trading systems.

## What you build

A model that:

- predicts **100 percentiles** of the BTC price **10 seconds** into the future,
- runs in **under 5 ms** per prediction (strictly enforced), and
- meets the technical specification so it runs directly in Synth's evaluation
  environment.

Models are evaluated continuously on live market data; scores are visible to all
participants.

## Data available to the model

Each prediction, the model receives — for Binance **spot** and **USDT-M
futures** (BTCUSDT):

- the last **1 hour** of 1-second candles (OHLCV),
- an order-book snapshot to a set depth from ~**60 s** prior, every subsequent
  order-book update, and the latest snapshot,
- **60 s** of aggregate trades, and
- **60 s** of book-ticker updates (best bid/ask price and size).

Full schema: [`input.md`](input.md). Full competition spec:
[`SPECIFICATION.md`](SPECIFICATION.md).

## Rewards & participation

- **25%** of total subnet miner rewards are allocated to Synth Ultra.
- Initially limited to **10 participants**. All participants must be onboarded and
  complete the participation form before submitting a model.

## Objective

Build market-beating, ultra-low-latency predictive models that can generalize
across assets and feed directly into Synth's trading systems — competing at the
shortest market horizons, where HFT firms operate.
