# Frequently Asked Questions

> Submissions are not open yet. This page describes the current design; the
> submission client and the exact pinned base-image digest will be published
> before submissions open.

## Compute and the 5 ms budget

**What is actually enforced, and how should I size my model?**

- The hard limit is **< 5 ms per call**, **measured inside the container around
  your `predict_percentiles` call only** — transport and scheduling are measured
  separately and are **not** charged to you.
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
  FROM ghcr.io/synthdataco/vhft-miner-base:v1   # stable, frozen tag for this round
  # for a fully reproducible build, pin the digest instead:
  # FROM ghcr.io/synthdataco/vhft-miner-base@sha256:47e3a095ae495dec695bc69ba613725e9e83fc7855bf97e7a3f35179a5e1c25d
  COPY my_model/ /app/my_model/
  ENV VHFT_MINER_ENTRYPOINT=my_model.model
  ```
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
# push your image to the registry repo Synth gave you at onboarding, then take
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

## Payload semantics at a trade-triggered call

**At a trade-triggered call, does `book_ticker` already reflect that trade, and
what is `current_time_ms` relative to the triggering event?**

- **`current_time_ms`** is the **local receive timestamp (ms) of the triggering
  event** — for a trade trigger, the instant that trade message was received; for
  an interval trigger, the wall-clock boundary. Your forecast target is
  `current_time_ms + 10 s`, and **every window in the payload is relative to
  `current_time_ms`.**
- The **triggering trade is included** in the payload's trades array
  (`venues.spot.trades`) — it is recorded before the call is triggered, so a
  trade-triggered call always contains its own trade.
- **`book_ticker` is a separate best-bid/ask stream** and does **not** contain the
  trade itself. Whether it already reflects that trade's price impact is
  **timing-dependent**: the payload includes the best-bid/ask updates received up
  to the moment it is assembled, but a fresh **post-trade** book-ticker tick is
  **not guaranteed** to be present at a trade-triggered call. Treat `trades` as
  the authoritative signal that the trade happened, and `book_ticker` as the
  best-bid/ask state as of the call.
