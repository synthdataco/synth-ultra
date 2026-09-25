# Frequently Asked Questions

> Submissions are not open yet. This page describes the current design; the
> submission client and the exact pinned base-image digest will be published
> before submissions open.

## Compute and the 5 ms budget

**What is actually enforced, and how should I size my model?**

- The target is **< 5 ms per call**, **measured inside the container around your
  `predict_percentiles` call only** — transport and scheduling are measured
  separately and are **not** charged to you. It is **not enforced yet**; see
  [the latency budget](#the-latency-budget-what-is-enforced-today) for what is in
  force today and where it is heading.
- **CPU-only** (no GPU) and **no network** at inference, in a locked-down sandbox:
  read-only filesystem, all Linux capabilities dropped, a small in-memory `/tmp`.
  The payload is your only input.
- **Sizing:** benchmark conservatively against a **single CPU core** and a couple
  of GB of RAM. Design to that floor and you'll fit — the evaluation environment
  may give you more, never less. Because absolute timings vary by hardware, track
  algorithmic cost (allocations, vectorization) rather than only wall-clock on
  your dev machine.

## Base image and entrypoint

**Which base image and entrypoint do I use? Is there a warm-up allowance before
the first call?**

- You build **`FROM` the Synth Ultra base image**, published on GitHub Container
  Registry (free, anonymous pull) at
  **`ghcr.io/synthdataco/vhft-miner-base`** — Python 3.12 (slim) carrying the
  serving loop, with `numpy` and `msgpack` available. **Pin it by digest** for a
  reproducible build and target **`linux/amd64`** (the evaluation platform); copy
  your model package in and set `VHFT_MINER_ENTRYPOINT` to your module:

  ```dockerfile
  FROM ghcr.io/synthdataco/vhft-miner-base:v2   # stable, frozen tag for this round
  # for a fully reproducible build, pin the digest instead:
  # FROM ghcr.io/synthdataco/vhft-miner-base@sha256:66dbeb6f64cab66383333b1499b0fe45a186e5d7bf2f1ade2ddacc3342e1d6ca
  COPY my_model/ /app/my_model/
  ENV VHFT_MINER_ENTRYPOINT=my_model.model
  ```

  `v2` is current, and `v2`'s serving loop recovers from a dropped connection by
  waiting for the reconnect. `v1` remains published and works; if you built on it,
  rebuilding on `v2` is worth doing whenever convenient. Nothing else changed — same
  Python, same `numpy`/`msgpack`, same interface — so a rebuild is the only step.
- Your entrypoint is an importable `package.module` (or `package.module:function`)
  exposing:

  ```python
  def predict_percentiles(payload: dict) -> np.ndarray:  # shape (100,), float64
      ...
  ```

  The result must be **100 finite, positive, non-decreasing** values — the
  percentile grid described in the specification.
- **Warm-up:** your model is loaded **once at container start**. The runtime
  **imports your entrypoint before it starts accepting prompts**, so import and
  model-load time are **never** counted against the 5 ms budget. In addition, you
  receive **one warm-up prediction that is discarded** — not scored, not timed —
  so numpy/allocation warm-up does not land on your first scored prompt.

Practical implication: do all heavy setup (loading weights, allocating buffers,
priming any lazy code paths) at **import / module load**, and keep
`predict_percentiles` itself lean.

## Joining

**How do I get in?** Ask Synth to register you — send your subnet 50 hotkey, a short handle
and an email. See [`ONBOARDING.md`](ONBOARDING.md). Your hotkey is your identity; there is no
form and no account. It must already hold a registered uid on subnet 50, which is what bounds
participation.

**Is registration automatic?** No. We set participants up by hand, a limited number per day,
in the order requests arrive. Nothing is created for you until then.

**Where does my registry repo come from?** It is created for you on approval, along with a
push service account and a key you collect yourself. That key grants push to your own repo
only — no access to the evaluation machine or to anyone else's repo.

**I lost my push key.** You get two retrievals in total, so check whether you have one left
(`client/submit.py credentials`). The second exists so a dropped download does not cost you
the key — it is not a spare. If both are used, ask Synth to re-issue.

## Submitting and updating a model

**How are images submitted, how many resubmissions are allowed, and how fast does
a new version go live?**

- **Flow:** build your image `FROM` the base → **push it to the dedicated registry
  repository Synth provisions for your hotkey** → take the image **digest**
  (`sha256:…`) → **sign** a small submission envelope with your **subnet hotkey** →
  **POST** it to the submission API. You submit a reference to a **pre-pushed image
  (by digest)**; Synth does not build the image for you. Synth grants you push
  access to that repository at onboarding — it is **private, not public** — and
  Synth's evaluation runtime is granted read access to pull your image.
- The signed envelope binds `{image_uri, image_digest, version}` to your hotkey
  and a timestamp, so only the holder of the hotkey can submit on its behalf. You
  poll a signed status endpoint to see when it is accepted and approved.
- After submission, Synth runs a **security review** and approves the version.
  Once approved, it goes **live within about 2 minutes** (one reconcile cycle),
  provided your hotkey holds a registered slot on the Synth subnet.

**Limits and rules:**

- your hotkey must be **registered on the Synth subnet** and on the participant
  **allow-list**;
- **one submission per hotkey every 4 hours**;
- each new submission must be **strictly newer** (by timestamp) than your previous
  one;
- submit **by digest** (`sha256:` + 64 hex characters), with a non-empty image
  reference and `version ≥ 1`.

There is no cap on how many versions you ship over time — you are bounded only by
the 4-hour cadence and the strictly-newer rule.

**Submitting with the client.** Use [`client/submit.py`](client/submit.py) — it
signs the envelope with your hotkey and posts it (no install needed via `uv`):

```bash
# push to the registry repo you collected in ONBOARDING.md step 2, then take
# the digest that `docker push` printed:
docker push <your-registry-repo>/miner:v1

uv run --no-project --with "bittensor>=11,<12" python client/submit.py submit \
  --wallet my_coldkey --hotkey my_hotkey \
  --image-uri <your-registry-repo>/miner \
  --image-digest sha256:<digest-from-docker-push> --version 1

# check status any time (signature-gated):
uv run --no-project --with "bittensor>=11,<12" python client/submit.py status \
  --wallet my_coldkey --hotkey my_hotkey
```

Your `<your-registry-repo>` URL, push credentials, and `docker login` command are
provided by Synth at onboarding.

**Reading your status.** The `status` command tells you both whether we accepted
your image and whether it's actually running:

- **`status`** — your latest submission: `pending` (awaiting review), `approved`,
  or `rejected` (reason in `error`).
- **`deploy_state`** — *why* it is or isn't live:
  - `live` — deployed and scoring;
  - `queued` — approved, waiting for a free slot;
  - `not_registered` — approved, but your hotkey isn't registered on the Synth
    subnet; register it and you'll deploy automatically;
  - `pending_review` / `rejected` — mirrors the submission status.
- **`live_digest`** — the image digest actually running for you (set only when `live`).

So `approved` + `not_registered` means we accepted your image, but you still need a
**registered subnet hotkey** before it can run.

## The latency budget: what is enforced today

**Is the 5 ms budget enforced, and what happens if I exceed it?**

- **Not yet.** The threshold in force is a **1-second timeout on the round trip**
  (as of 2026-09-21). A response slower than 5 ms is currently scored like any
  other, and the competition standings reflect that. This line is updated as the
  threshold moves — check it rather than assuming.
- **It is going to tighten.** We will reduce the threshold toward **5 ms
  progressively**, so build to 5 ms — it is the target the competition is designed
  around, and the reduction will be gradual rather than a cliff.
- **If a call exceeds the threshold** the round trip is abandoned, the connection
  is re-established, and that prompt counts as a non-answer for you.

**How is a non-answer scored?**

A non-answer is not dropped — it is charged the **95th percentile of the CRPS
scored by the models that did answer that prompt**. Each prompt's best score is
then subtracted, so the prompt's winner scores 0 and everyone is measured against
the field.

The effect is that a miss costs you rather than shortening your series: every
model is averaged over the *same* prompts. Output that fails validation — wrong
shape or dtype, non-finite, non-positive, or not non-decreasing — is treated the
same as a non-answer.

## How often am I called, and why

**How many prompts per hour, and what triggers them?**

- Roughly **4.5–5 calls per minute** — about **270–300 per hour**. Every
  participant receives every prompt; there is no per-model sampling.
- Mix, on a recent sample: about **two thirds clock-driven** (`time`) and **one
  third triggered by a real price move** (`event` / `event_delayed`).

**What is the clock interval, and is it aligned?**

**20 seconds, aligned to wall-clock multiples** — `:00`, `:20`, `:40`. A `time` prompt
fires on each boundary, and `current_time_ms` is that boundary.

**I see far more qualifying price moves than event prompts. How is one chosen?**

Neither a minimum gap nor random sampling — a **window**, and the **first** qualifying
move inside it wins:

```
:00   time prompt fires
:10   event window OPENS, 10 s after the boundary
      · any move already queued from before the window is discarded as stale
      · the first qualifying move from here on fires the event prompt
:15   window CLOSES if nothing qualified — 5 s maximum wait
:20   next boundary, and it starts again
```

So at most **one** event prompt per 20-second interval, and only from a 5-second slice of
it. Every other qualifying move is ignored: those outside the window entirely, and any
that arrive after the first one within it. That is why qualifying moves vastly outnumber
event prompts.

If no move qualifies inside those 5 seconds the window is **abandoned** and only the clock
prompt fires for that interval — which is why the mix is about ⅔ time and ⅓ event rather
than an even split. Quiet markets produce proportionally fewer event prompts.

**What counts as a qualifying move?** A trade group that shifts the price by **more than
one tick** against the previous group. Trades sharing an exchange timestamp are grouped
first, so one order sweeping several levels counts once, as a single move rather than
several one-tick steps.

**Is the delay on `event_delayed` uniform between 0 and 500 ms?**

Not quite, and the difference matters if you are modelling it. There is a **coin flip
first**:

- **50%** of move-triggered prompts fire with **zero delay** — these arrive as `event`;
- **50%** are delayed by `uniform(0, 500 ms)` — these arrive as `event_delayed`.

So across all move-triggered prompts the delay is a mixture, not a uniform: half the mass
sits at exactly 0 ms, and the rest is spread evenly up to 500 ms. Median 0, mean ~125 ms.

The delayed branch exists so a model cannot assume its data is perfectly fresh. The coin
decides *when* you are asked, never *whether* — and `current_time_ms` stays the move's own
receive time either way, so only the staleness of your inputs changes, not the question or
the horizon it is scored over.

## Feed completeness

**Are book-ticker updates coalesced or sampled?**

No. **Every update we receive is in the payload** — the array is every tick in the
trailing 60 s, in receive order, with nothing dropped or merged.

Size your parsing for the busy end: spot book-ticker runs from a few hundred
messages per second when quiet into the low thousands when active, so a 60 s
window is on the order of **10k–60k entries**, and futures is heavier still. A
model that is fast on a quiet window can miss the budget on a busy one.

## Compute environment

**What does my container actually run on?**

- **CPU only**, no GPU. Your container gets a **pinned set of 2 cores** — a real
  CPU set, not a scheduler quota — and a couple of GB of RAM.
- The **host is shared** with other participants' containers. They cannot observe
  or affect your model, but they do share the machine.
- Models run inside a **gVisor sandbox**, which services syscalls in userspace.
  This is the single most common reason a model that is fast locally is slower
  here: **pure computation runs close to native, but syscall-heavy work does not**
  — file access, memory mapping, thread creation, and allocation churn that
  reaches `brk`/`mmap` all cost far more than on a normal host.

Practical advice: allocate buffers and load everything at **module import**, keep
`predict_percentiles` free of allocation and I/O, and do not spawn threads. If you
want to reproduce the environment locally, run your image under `runsc`.

**Can I ship a compiled extension?**

Yes. A C++ or Cython extension built during the Docker build, with source included
in the image, is acceptable — and under the sandbox it often helps, since it
removes interpreter overhead and syscalls.

The constraints that do apply: build `FROM` the published base image, do not
override the serving command, keep the image under 2 GB, target `linux/amd64`, no
network at inference, and produce deterministic output.

One trap worth stating: **compile for a conservative baseline instruction set.**
If you build with `-march=native` on a machine newer than the evaluation host, you
get an illegal-instruction crash on the first call rather than a slow model.

## Testing before you submit

**Is there a sample payload?**

Yes — two, in [`samples/`](samples/). A 200 KB one for checking shape, and a full-size
real capture (0.7 MB gzipped) for checking that your model still fits the budget at
production row counts. Both are real captures from the same code path that builds live
prompts.

Run your model against them with [`client/validate.py`](client/validate.py), which calls
your entrypoint the way the runtime does and checks the response contract. See
[`input.md`](input.md#sample-payloads).

## The two slow fields

**Why do `liquidations` and `depth_bands` behave differently from everything else?**

Every other field in the payload is a live stream, current to the tick. These two are not,
and each is deliberately slow for its own reason.

**`liquidations`** covers a **1-hour** window rather than the 60 s the other streams use.
They are simply too sparse for a short one: about 0.7 per minute, with roughly 80% of any
given 60 s window completely empty. Over an hour the field reads as a volatility-regime
signal; over a minute it would be blank four prompts out of five.

The trap is the side. **`is_buy` is the liquidation order's side, not the trapped
position's** — `True` is the exchange buying to close a short, which pushes price *up*.

**`depth_bands`** is refreshed every **~30 seconds** and is **anchored to an absolute
price**, not to the current mid. Re-anchor it against the live top of book from
`book_ticker`, and read its `recv_ts_ms` rather than assuming it is current.

That combination is what makes a slow refresh workable: resting size in the book barely
changes over 30 seconds when measured on a fixed price frame, even while the mid moves.
A mid-relative view of the same book would be stale within seconds.

Neither field replaces anything. `depth_start` / `depth_latest` are still live and still
precise — they just cover about $20 either side, where the bands cover about $1,000.

## Payload semantics at an event-triggered call

**At an event-triggered call, does `book_ticker` already reflect that trade, and
what is `current_time_ms` relative to the triggering event?**

- **`current_time_ms`** is the **local receive timestamp (ms) of the triggering
  event** — for an `event` or `event_delayed` trigger, the instant the triggering
  trade message was received; for a `time` trigger, the wall-clock boundary. Your forecast target is
  `current_time_ms + 10 s`, and **every window in the payload is relative to
  `current_time_ms`.**
- The **triggering trade is included** in the payload's trades array
  (`venues.spot.trades`) — it is recorded before the call is triggered, so a
  event-triggered call always contains its own trade.
- **`book_ticker` is a separate best-bid/ask stream** and does **not** contain the
  trade itself. Whether it already reflects that trade's price impact is
  **timing-dependent**: the payload includes the best-bid/ask updates received up
  to the moment it is assembled, but a fresh **post-trade** book-ticker tick is
  **not guaranteed** to be present at an event-triggered call. Treat `trades` as
  the authoritative signal that the trade happened, and `book_ticker` as the
  best-bid/ask state as of the call.
