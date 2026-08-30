#!/usr/bin/env python3
"""Synth Ultra onboarding + submission client.

Everything is signed with your subnet hotkey (sr25519). Your hotkey IS your identity —
there is no account, no password, and no email round-trip. Each action signs a different
message, so a signature for one can never be replayed as another:

  apply        vhft-onboard|v1|{hotkey}|{unix_ts}|{payload_hash}
  credentials  vhft-onboard-status|v1|{hotkey}|{unix_ts}
  submit       vhft-submission|v1|{hotkey}|{unix_ts}|{payload_hash}
  status       vhft-status|v1|{hotkey}|{unix_ts}

where payload_hash = sha256 over the canonical JSON of the payload.

You need `bittensor` available. The simplest way, with no install, is uv.

THE ORDER, once end to end:

  # 1. apply. Your hotkey must already hold a registered uid on subnet 50.
  uv run --no-project --with "bittensor>=11,<12" python submit.py apply \
    --wallet my_coldkey --hotkey my_hotkey --handle acme --email me@example.com

  # 2. wait for a human to approve you, then collect your push key. This writes
  #    the key to a file and prints the docker login line. You get TWO retrievals
  #    in total, so keep the file.
  uv run --no-project --with "bittensor>=11,<12" python submit.py credentials \
    --wallet my_coldkey --hotkey my_hotkey

  # 3. build + push your image to the repo the previous step printed, then submit
  #    the digest that `docker push` gave you:
  uv run --no-project --with "bittensor>=11,<12" python submit.py submit \
    --wallet my_coldkey --hotkey my_hotkey \
    --image-uri <your-registry-repo>/miner \
    --image-digest sha256:<digest-from-docker-push> --version 1

  # check submission status any time (signature-gated):
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
ONBOARD_PREFIX = "vhft-onboard|v1"
ONBOARD_STATUS_PREFIX = "vhft-onboard-status|v1"
REGISTRY_HOST = "asia-northeast1-docker.pkg.dev"


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


def cmd_apply(args, kp) -> None:
    """Apply to join. Creates (or updates) your application; it does not admit you."""
    ts = int(time.time())
    # Every field is optional, but give us at least one way to reach you: the API will
    # otherwise fall back to labelling you by your hotkey.
    payload = {
        k: v
        for k, v in (
            ("handle", args.handle),
            ("email", args.email),
            ("discord", args.discord),
            ("contact", args.contact),
        )
        if v
    }
    message = f"{ONBOARD_PREFIX}|{kp.ss58_address}|{ts}|{payload_hash(payload)}"
    body = {
        "hotkey_ss58": kp.ss58_address,
        "timestamp": ts,
        "signature": "0x" + kp.sign(message.encode()).hex(),
        "payload": payload,
    }
    print(f"hotkey : {kp.ss58_address}")
    print(f"POST   : {args.api}/v1/onboard")
    code, resp = _request("POST", f"{args.api}/v1/onboard", body)
    print(f"-> {code} {resp}")
    if code == 202:
        print("\nApplication recorded. A human reviews it before anything is created for you.")
        print("Re-running `apply` updates your contact details; it never creates a second entry.")
        print("Then run `credentials` to collect your push key once you're approved.")
    elif code == 403:
        print("\nYour hotkey holds no registered uid on subnet 50. Register it first, then re-apply.")


def cmd_credentials(args, kp) -> None:
    """Collect the push key. Limited retrievals — save the file."""
    ts = int(time.time())
    message = f"{ONBOARD_STATUS_PREFIX}|{kp.ss58_address}|{ts}"
    sig = "0x" + kp.sign(message.encode()).hex()
    url = f"{args.api}/v1/onboard/credentials?hotkey={kp.ss58_address}&timestamp={ts}&signature={sig}"
    print(f"GET    : {args.api}/v1/onboard/credentials")
    code, resp = _request("GET", url)
    if code != 200:
        print(f"-> {code} {resp}")
        if code == 404:
            print("\nNo application found for this hotkey. Run `apply` first.")
        elif code == 410:
            print("\nYour retrievals are used up. Ask Synth to re-issue a key.")
        return

    data = json.loads(resp)
    status = data.get("status")
    if status != "provisioned":
        # pending_review = waiting on a human; provisioning = approved, being set up
        print(f"-> 200 {resp}")
        print("\nNot ready yet. Try again later." if status else "")
        return

    key, slug = data.get("push_key"), data.get("slug")
    out = pathlib.Path(args.out or f"vhft-push-{slug}.json")
    out.write_text(key)
    out.chmod(0o600)
    remaining = data.get("retrievals_remaining")
    print(f"-> 200 key written to {out} (retrievals remaining: {remaining})")
    print(f"\nKEEP THIS FILE. You have {remaining} retrieval(s) left, then it cannot be fetched again.\n")
    print("Log in to the registry:")
    print(f"  cat {out} | docker login -u _json_key --password-stdin https://{REGISTRY_HOST}")
    print("\nBuild for linux/amd64, push, then submit the digest docker prints:")
    print(f"  docker push {data.get('image_uri')}:v1")


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
    ap = argparse.ArgumentParser(description="Synth Ultra onboarding + submission client")
    ap.add_argument("command", choices=["apply", "credentials", "submit", "status"])
    ap.add_argument("--api", default=API_DEFAULT, help=f"submission API base (default {API_DEFAULT})")
    ap.add_argument("--wallet", help="bittensor coldkey wallet name")
    ap.add_argument("--hotkey", help="bittensor hotkey name under that wallet")
    ap.add_argument("--mnemonic", help="raw hotkey mnemonic (alternative to --wallet/--hotkey)")
    ap.add_argument("--uri", help="dev throwaway URI, e.g. //Alice (testing only)")
    # apply
    ap.add_argument("--handle", help="short name for your registry repo, e.g. acme (apply)")
    ap.add_argument("--email", help="contact email (apply)")
    ap.add_argument("--discord", help="discord handle (apply)")
    ap.add_argument("--contact", help="any other contact, e.g. a telegram handle (apply)")
    # credentials
    ap.add_argument("--out", help="where to write the push key (credentials)")
    # submit
    ap.add_argument("--image-uri", help="registry image reference (without the digest)")
    ap.add_argument("--image-digest", help="the sha256:... digest from `docker push`")
    ap.add_argument("--version", type=int, default=1, help="your submission version (>= 1)")
    args = ap.parse_args()
    if args.command == "submit" and not (args.image_uri and args.image_digest):
        raise SystemExit("submit requires --image-uri and --image-digest")
    kp = load_keypair(args)
    {"apply": cmd_apply, "credentials": cmd_credentials, "submit": cmd_submit, "status": cmd_status}[args.command](
        args, kp
    )


if __name__ == "__main__":
    main()
