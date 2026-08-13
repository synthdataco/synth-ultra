# Synth Ultra — model input

What your model receives on each prediction: a snapshot of Binance market data
for BTCUSDT, as a plain dict of NumPy arrays. Read this alongside
[`SPECIFICATION.md`](SPECIFICATION.md) (the task and how the output is scored).

## Payload shape

```
{
  "schema_version": 3,
  "prompt": {
    "asset": "BTC",
    "horizon_seconds": 10,
    "num_percentiles": 100,
    "quantile_grid": "centered-100",     # q_i = (2i-1)/200
    "current_time_ms": int,              # the "now" the forecast is anchored to (ms)
    "trigger": {"kind": "interval"|"trade"|"book", "venue": str|None}
  },
  "venues": { "spot": VenueData, "futures": VenueData }
}

VenueData = {
  "symbol": "BTCUSDT",
  "candles_1s":   {"open_time_ms": i64 (n,), "ohlcv": f64 (n,5), "complete_history": bool},
  "trades":       {"ts_ms","event_ts_ms","recv_ts_ms": i64 (m,), "price","qty": f64 (m,), "buyer_is_maker": bool_ (m,)},
  "book_ticker":  {"recv_ts_ms": i64 (k,), "bid_price","bid_qty","ask_price","ask_qty": f64 (k,),
                   "event_ts_ms","transaction_ts_ms": i64 (k,)},   # futures only — keys absent on spot
  "depth_start":   {"recv_ts_ms": i64, "update_id": int, "bids","asks": f64 (levels,2),
                    "event_ts_ms","transaction_ts_ms": int|None},   # futures only; None on spot
  "depth_updates": [{"recv_ts_ms","event_ts_ms","transaction_ts_ms": i64, "first_id","final_id","prev_final_id": int,
                     "bids","asks": f64 (·,2)}, ...],   # transaction_ts_ms futures only
  "depth_latest":  same shape as depth_start,
  "last_event_times": {stream_name: recv_ts_ms}
}
```

Both `spot` and `futures` are present with the identical shape. Arrays are ordered
oldest-first. Depth snapshots carry a set number of levels per side (20 in the
initial competition).

## Field reference

- **`candles_1s`** — 1-second OHLCV over the trailing hour. `open_time_ms[j]` is
  the candle's open time; `ohlcv[j] = [open, high, low, close, volume]`.
  `complete_history` — see [candle completeness](#candle-completeness).
- **`trades`** — aggregate trades in the trailing **60 s**. `ts_ms` is the
  exchange **trade/execution time** (Binance `T`), `event_ts_ms` the exchange
  **event/push time** (`E`), and `recv_ts_ms` the local receive time; `price`,
  `qty`, and `buyer_is_maker` (`True` ⇒ the aggressor was a seller).
- **`book_ticker`** — best bid/ask stream in the trailing **60 s**: `bid_price`,
  `bid_qty`, `ask_price`, `ask_qty`, each stamped with `recv_ts_ms`. Futures
  book-ticker also carries `event_ts_ms` (`E`) and `transaction_ts_ms` (`T`);
  **spot book-ticker carries neither**, so those keys are absent on the `spot`
  venue.
- **`depth_start` / `depth_latest`** — order-book snapshots. `bids`/`asks` are
  `(levels, 2)` arrays of `[price, qty]`, sorted best-first. `depth_start` is a
  snapshot ~60 s before `current_time_ms`; `depth_latest` is the most recent.
  `event_ts_ms`/`transaction_ts_ms` are the exchange `E`/`T` on futures, `None` on
  spot.
- **`depth_updates`** — the incremental diff messages between `depth_start` and
  now. `first_id`/`final_id`/`prev_final_id` are the exchange update-id chain for
  gap-free application. `event_ts_ms` (`E`) is present on both venues;
  `transaction_ts_ms` (`T`) on futures only. You can replay `depth_start` +
  `depth_updates` to reconstruct the book to full depth, or use `depth_latest`
  directly.
- **`last_event_times`** — the most recent `recv_ts_ms` per stream (staleness
  check).

## Timestamps

The canonical clock is **`recv_ts_ms`** — the local wall-clock time (ms) each
message was received. It orders both venues on one timeline and is what
`current_time_ms`, the 60 s windows, and scoring use. It has to be the local
clock because it is the only timestamp present on **every** stream — spot
book-ticker carries no exchange time at all.

**Exchange timestamps ride along where the stream provides them** — useful for
aligning to Binance's public/historical data, not for cross-stream ordering:

- **trades**: `ts_ms` = `T` (trade/execution time), `event_ts_ms` = `E` (event/push time).
- **depth diffs**: `event_ts_ms` = `E` (both venues), `transaction_ts_ms` = `T` (futures).
- **futures book-ticker / depth snapshots**: `event_ts_ms` = `E`, `transaction_ts_ms` = `T`; **spot book-ticker has neither**.

## Candle completeness

`candles_1s.complete_history` indicates whether the full 1-hour window is
populated:

- **Spot** candles come from Binance's 1-second kline feed and span a full hour,
  so `spot.candles_1s.complete_history` is `True`.
- **Futures** has no 1-second kline feed, so `futures.candles_1s` is built from the
  aggregate-trade stream and may still be filling; while it is,
  `futures.candles_1s.complete_history` is `False` and the array holds only the
  seconds available so far.

**Your model must handle `futures.candles_1s.complete_history == False`** — e.g.
fall back to spot candles or a trade-derived volatility estimate for the futures
venue while its candle history is short. Spot candles are always complete.

## Sample payload

A shape-faithful sample payload and a local validation harness — to check that
your model loads the schema and returns a valid `(100,)` response within the
latency budget — will be provided in this repository before submissions open.
