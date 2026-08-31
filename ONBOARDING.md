# Joining Synth Ultra

Four steps. Your **subnet 50 hotkey is your identity** throughout — there is no account, no
password, and no email round-trip. Everything you send is signed with that hotkey, and the
server verifies the signature rather than trusting the request.

**Before you start:** your hotkey must already hold a registered uid on subnet 50. That is
what bounds participation, and applications from unregistered hotkeys are refused.

All commands use `client/submit.py`. It needs `bittensor`; the simplest way to get it, with
nothing to install, is `uv`.

---

## 1. Ask us to register you

Send Synth your **subnet 50 hotkey**, a short handle (`[a-z0-9-]`, up to 20 characters — it
becomes the name of your registry repo) and an email we can reach you on.

Your hotkey must already hold a registered uid on subnet 50. That is what bounds
participation, so register it first if you have not.

We create your registry repo, a push service account and a push key for you. A limited number
of participants are set up per day, in the order requests arrive.

You will hear from us when it is ready — then come back for step 2.

## 2. Collect your push key

```bash
uv run --no-project --with "bittensor>=11,<12" python client/submit.py credentials \
  --wallet my_coldkey --hotkey my_hotkey
```

This writes the key to a file and prints your registry repo and the login command.

> **You get two retrievals in total, then the key can no longer be fetched.** The second one
> exists so that a dropped connection does not cost you the key — it is not a spare. Save the
> file somewhere safe the first time. If you lose it, ask Synth to re-issue.

Then log in:

```bash
cat vhft-push-<your-handle>.json \
  | docker login -u _json_key --password-stdin https://asia-northeast1-docker.pkg.dev
```

That key grants push to **your own repo and nothing else**. It gives no access to the
evaluation machine or to any other participant.

## 3. Build, push, submit

Build for **`linux/amd64`** — the evaluation host is amd64, and an arm64 image built on an
Apple Silicon machine will not run:

```bash
docker build --platform linux/amd64 -t <your-registry-repo>/miner:v1 .
docker push <your-registry-repo>/miner:v1
```

`docker push` prints a `sha256:...` digest. Submit **that digest** — deployment pins the exact
digest, not the tag, so pushing a new image does not change what runs until you submit again:

```bash
uv run --no-project --with "bittensor>=11,<12" python client/submit.py submit \
  --wallet my_coldkey --hotkey my_hotkey \
  --image-uri <your-registry-repo>/miner \
  --image-digest sha256:<digest-from-docker-push> --version 1
```

Check where it got to at any time:

```bash
uv run --no-project --with "bittensor>=11,<12" python client/submit.py status \
  --wallet my_coldkey --hotkey my_hotkey
```

`deploy_state` tells you why you are or are not running: `live`, `queued` (no free slot),
`not_registered` (no subnet 50 uid), `pending_review`, or `disabled`.

---

## Updating your model later

Repeat step 3 with a **higher `--version`**. You do not need a new
key. Submissions are rate-limited to one accepted submission per hotkey every 4 hours.

## What to build

See [SPECIFICATION.md](SPECIFICATION.md) for the model contract and [FAQ.md](FAQ.md) for the
base image, the 5 ms budget, and payload semantics.
