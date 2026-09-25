# Synth Ultra — model input

What your model receives on each prediction: a snapshot of Binance market data
for BTCUSDT, as a plain dict of NumPy arrays. Read this alongside
[`SPECIFICATION.md`](SPECIFICATION.md) (the task and how the output is scored).

## Payload shape

```
{
  "schema_version": 5,
  "prompt": {
    "asset": "BTC",
    "horizon_seconds": 10,
    "num_percentiles": 100,
    "quantile_grid": "centered-100",     # q_i = (2i-1)/200
    "current_time_ms": int,              # the "now" the forecast is anchored to (ms)
    "trigger": {"kind": "time"|"event"|"event_delayed", "venue": str|None}
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
  "liquidations": {"ts_ms","recv_ts_ms": i64 (j,), "price","qty": f64 (j,), "is_buy": bool_ (j,)},
                  # 1 hour; futures only — present but always EMPTY on spot
  "depth_bands":  {"anchor_price","bucket_usd": f64, "bids","asks": f64 (bands,), "recv_ts_ms": int},
                  # spot only — present but empty on futures; refreshed every ~30 s
  "last_event_times": {stream_name: recv_ts_ms}
}
```

Both `spot` and `futures` are present with the identical shape — `liquidations` and
`depth_bands` appear on both, but each is only populated on the venue it applies to, so
you never have to check whether a key exists. Arrays are ordered oldest-first. Depth
snapshots carry a set number of levels per side (20 in the initial competition).

## Field reference

- **`prompt.trigger`** — why this call fired. `kind` is one of:
  - **`time`** — the clock, on a **20-second wall-clock boundary** (`:00`, `:20`,
    `:40`). `current_time_ms` is that boundary; `venue` is `None`.
  - **`event`** — a trade that moved the price more than one tick, fired at the
    instant of the move. `current_time_ms` is that trade's local receive time.
  - **`event_delayed`** — the same move, but asked after `uniform(0, 500 ms)`.
    `current_time_ms` is still the move's own receive time, so only the staleness
    of your inputs changes — not the question or the horizon it is scored over.

  **At most one event prompt per 20-second interval**, and only from a 5-second
  window opening 10 s after each boundary. The **first** qualifying move in that
  window wins; every other move is ignored, including any that follow it inside
  the window. If none qualifies, the window is abandoned and only the `time`
  prompt fires for that interval. This is why qualifying moves vastly outnumber
  event prompts — see [the FAQ](FAQ.md#how-often-am-i-called-and-why).

  Of the move-triggered prompts, a coin flip sends about half down each branch,
  so **half arrive with zero delay** (`event`) and half delayed
  (`event_delayed`).

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
- **`liquidations`** — forced closures of leveraged futures positions, over the trailing
  **1 hour**. When a leveraged position moves far enough against its holder, the exchange
  force-closes it; that trade hits the market regardless of anyone's intent, which is why
  liquidations often arrive in clusters just before or during a fast move.

  `ts_ms` is the exchange trade time, `recv_ts_ms` the local receive time, `price` the
  **average fill price** (what it actually traded at, not the order's limit), `qty` the
  size in base units.

  **`is_buy` is the liquidation ORDER's side, not the trapped position's.** `True` means
  the engine is *buying* to close someone's short, which pushes price **up**; `False`
  closes a long and pushes price **down**. Read it the other way round and any signal you
  build from it points backwards.

  The window is an hour rather than the 60 s the other streams use because these are far
  sparser: roughly 0.7 per minute, with about 80% of any given 60 s window empty. Over an
  hour it reads as a volatility-regime signal instead of a field that is usually blank.
  **Futures only** — spot has no liquidations, so `spot.liquidations` is always empty.

- **`depth_bands`** — a coarse, wide view of the spot order book: resting size folded into
  fixed-width price bands. `bids[i]` is the size resting in
  `[anchor_price - (i+1)*bucket_usd, anchor_price - i*bucket_usd)`, and `asks[i]` mirrors
  it above. Currently 100 bands of $10 per side, so about $1,000 of reach.

  This complements `depth_start`/`depth_latest` rather than replacing them. Those 20
  levels are precise and live but span only around $20 in total, while most 10-second
  moves travel further than that — so the snapshot tells you the terrain underfoot and
  the bands tell you what is further out.

  Two things to know before using it:

  **It is anchored to an absolute price, not to the current mid.** `anchor_price` is the
  mid at the moment the snapshot was taken. Re-anchor the bands against the live top of
  book you already have from `book_ticker`; do not assume band 0 is adjacent to the
  current price.

  **It is seconds old, unlike everything else in the payload.** `recv_ts_ms` says when it
  was taken — read it. A `recv_ts_ms` of `0` with zero-length arrays means no snapshot has
  landed yet, which you should handle the same way you handle
  `futures.candles_1s.complete_history == False`.

  The staleness is affordable precisely because of the absolute anchoring: resting size
  measured essentially unchanged over 30 seconds on a fixed price frame, while a
  mid-relative view of the same book degrades within seconds as the price moves.
  **Spot only** — the realized price and the scoring target are both spot, so
  `futures.depth_bands` is always empty.

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

## Sample payloads

Two real captures, both produced by the same code path that builds live prompts — so
neither can drift from the contract the way a hand-written fixture would.

| file | size | what it is for |
|---|---|---|
| [`samples/sample_payload.json`](samples/sample_payload.json) | 200 KB | shape. Every field present, long arrays truncated, readable by eye. |
| [`samples/real_payload.json.gz`](samples/real_payload.json.gz) | 0.7 MB gz | statistics. Full production sizes — 3,600 candles, thousands of book-ticker rows. |

Start with the small one, then run against the real one before you submit: that is where a
model that looks fast on the sample discovers it scales with row count.

**Validate your model against them** with
[`client/validate.py`](client/validate.py) — it calls your entrypoint the way the
evaluation runtime does, checks the response contract (100 finite, positive,
non-decreasing values), and times it:

```bash
uv run --no-project --with numpy python client/validate.py \
    --entrypoint my_model.model --payload samples/real_payload.json.gz
```

It checks the contract, not your accuracy — passing means the runtime will accept your
output, nothing more.

Note both captures were taken in a live market, so they show one moment rather than a
typical one. `futures.candles_1s.complete_history` is `False` in them, which is realistic:
futures candles build from the trade stream and take an hour to fill.
