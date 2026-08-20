#!/usr/bin/env python3
"""Synth Ultra submission client.

Signs the sr25519 submission envelope with your subnet hotkey and posts your
pre-pushed image reference to the submission API. The server verifies the exact
message `vhft-submission|v1|{hotkey}|{unix_ts}|{payload_hash}`, where
payload_hash = sha256 over the canonical JSON of {image_uri, image_digest, version}.

You need `bittensor` available. The simplest way, with no install, is uv:

  # submit (use YOUR wallet + hotkey, YOUR registry repo from onboarding, and the
  # digest that `docker push` printed):
  uv run --no-project --with "bittensor>=11,<12" python submit.py submit \
    --wallet my_coldkey --hotkey my_hotkey \
    --image-uri <your-registry-repo>/miner \
    --image-digest sha256:<digest-from-docker-push> --version 1

  # check status (signature-gated):
  uv run --no-project --with "bittensor>=11,<12" python submit.py status \
    --wallet my_coldkey --hotkey my_hotkey

Identity options:
  --wallet <name> --hotkey <hk>   reads ~/.bittensor/wallets/<name>/hotkeys/<hk>
  --mnemonic "word word ..."      a raw mnemonic
  --uri //Alice                   a dev throwaway (testing only)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import time
import urllib.error
import urllib.request

from bittensor import sp_core

API_DEFAULT = "https://vhft-submit.synthdata.co"
SUBMIT_PREFIX = "vhft-submission|v1"
STATUS_PREFIX = "vhft-status|v1"


def canonical_payload_json(payload: dict) -> bytes:
    fields = {k: v for k, v in payload.items() if v not in ("", None)}
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_payload_json(payload)).hexdigest()


def load_keypair(args):
    if args.wallet and args.hotkey:
        p = pathlib.Path.home() / ".bittensor" / "wallets" / args.wallet / "hotkeys" / args.hotkey
        data = json.loads(p.read_text())
        if data.get("secretPhrase"):
            return sp_core.Keypair.create_from_mnemonic(data["secretPhrase"])
        if data.get("secretSeed"):
            seed = str(data["secretSeed"])
            return sp_core.Keypair.create_from_seed(seed if seed.startswith("0x") else "0x" + seed)
        raise SystemExit(f"no secretPhrase/secretSeed in {p}")
    if args.mnemonic:
        return sp_core.Keypair.create_from_mnemonic(args.mnemonic)
    if args.uri:
        return sp_core.Keypair.create_from_uri(args.uri)
    raise SystemExit("provide one of: --wallet + --hotkey, --mnemonic, or --uri")


def _request(method: str, url: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def cmd_submit(args, kp) -> None:
    ts = int(time.time())
    payload = {"image_uri": args.image_uri, "image_digest": args.image_digest, "version": args.version}
    message = f"{SUBMIT_PREFIX}|{kp.ss58_address}|{ts}|{payload_hash(payload)}"
    body = {
        "hotkey_ss58": kp.ss58_address,
        "timestamp": ts,
        "signature": "0x" + kp.sign(message.encode()).hex(),
        "payload": payload,
    }
    print(f"hotkey : {kp.ss58_address}")
    print(f"POST   : {args.api}/v1/submissions")
    code, resp = _request("POST", f"{args.api}/v1/submissions", body)
    print(f"-> {code} {resp}")


def cmd_status(args, kp) -> None:
    ts = int(time.time())
    message = f"{STATUS_PREFIX}|{kp.ss58_address}|{ts}"
    sig = "0x" + kp.sign(message.encode()).hex()
    url = f"{args.api}/v1/submissions/{kp.ss58_address}?timestamp={ts}&signature={sig}"
    print(f"GET    : {url}")
    code, resp = _request("GET", url)
    print(f"-> {code} {resp}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Synth Ultra submission client")
    ap.add_argument("command", choices=["submit", "status"])
    ap.add_argument("--api", default=API_DEFAULT, help=f"submission API base (default {API_DEFAULT})")
    ap.add_argument("--wallet", help="bittensor coldkey wallet name")
    ap.add_argument("--hotkey", help="bittensor hotkey name under that wallet")
    ap.add_argument("--mnemonic", help="raw hotkey mnemonic (alternative to --wallet/--hotkey)")
    ap.add_argument("--uri", help="dev throwaway URI, e.g. //Alice (testing only)")
    ap.add_argument("--image-uri", help="registry image reference (without the digest)")
    ap.add_argument("--image-digest", help="the sha256:... digest from `docker push`")
    ap.add_argument("--version", type=int, default=1, help="your submission version (>= 1)")
    args = ap.parse_args()
    if args.command == "submit" and not (args.image_uri and args.image_digest):
        raise SystemExit("submit requires --image-uri and --image-digest")
    kp = load_keypair(args)
    (cmd_submit if args.command == "submit" else cmd_status)(args, kp)


if __name__ == "__main__":
    main()
