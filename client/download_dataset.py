#!/usr/bin/env python3
"""Download a day of the Synth Ultra prompt dataset.

Each day holds 500 real prompts per asset, picked at random: the payload miners received, the price
that followed, how the field scored, plus YOUR OWN answers to them. See input.md, "Prompt dataset".

The request is signed with your hotkey, like submit.py, with its own message:

  dataset      vhft-dataset|v1|{hotkey}|{unix_ts}|{day}

You must be an active participant. Each successful request counts as one of your 2 downloads per
UTC day, and returns links that work for 15 minutes; this script downloads everything you asked for
right away, from that one request. Running it again for a day you already have in full is free: it
sees the day's build is complete in your folder and makes no request. An interrupted run keeps the
files it finished and fetches only the rest next time.

  # which days are available (no signature needed):
  uv run --no-project --with "bittensor>=11,<12" python download_dataset.py --list

  # the newest day, every asset, into ./prompt-dataset/<day>/<build>/:
  uv run --no-project --with "bittensor>=11,<12" python download_dataset.py \\
    --wallet my_coldkey --hotkey my_hotkey

  # one day, only the assets you compete in:
  uv run --no-project --with "bittensor>=11,<12" python download_dataset.py \\
    --wallet my_coldkey --hotkey my_hotkey --day 2026-10-29 --assets BTC,ETH

Files, under <out>/<day>/<build>/ — a day can be rebuilt, and each build keeps its own folder, so
files of two builds never mix (a build's files never change, so re-downloading one is safe):

  <ASSET>/prompts.jsonl.gz     one line per prompt: kind, times, the realized price, the field's scores
  <ASSET>/payloads.jsonl.gz    the payload of each prompt, exactly as miners received it
  own/<hotkey>/<ASSET>.jsonl.gz   your answers to those prompts (none if you did not answer that asset)

Several hotkeys can share one output folder: shared files are kept once per build, answers and the
"already complete" record per hotkey.

Identity options:
  --wallet <name> --hotkey <hk>   reads ~/.bittensor/wallets/<name>/hotkeys/<hk>
  --mnemonic "word word ..."      a raw mnemonic
  --uri //Alice                   a dev throwaway (testing only)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request

API_DEFAULT = "https://vhft-submit.synthdata.co"
DATASET_PREFIX = "vhft-dataset|v1"


def load_keypair(args):
    from bittensor import sp_core

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


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {"detail": e.reason}


def _download(url: str, path: pathlib.Path) -> int:
    """Stream one signed link to `path`; returns its size in bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with urllib.request.urlopen(url, timeout=120) as r, partial.open("wb") as out:
        shutil.copyfileobj(r, out, length=1 << 20)
    partial.replace(path)
    return path.stat().st_size


def _asset_of(rel: str) -> str:
    """The asset a file is for: `.../BTC/prompts.jsonl.gz` and `.../own/<hotkey>/BTC.jsonl.gz` -> BTC."""
    parts = pathlib.PurePosixPath(rel).parts
    return parts[-1].split(".")[0] if "own" in parts[:-1] else parts[-2]


def _marker(build_dir: pathlib.Path, hotkey: str) -> pathlib.Path:
    """Per hotkey: two hotkeys downloading into one folder share the build's shared files, never
    each other's answers or "complete" record."""
    return build_dir / f".complete-{hotkey}.json"


def list_days(api: str) -> tuple[list[str], dict[str, str]]:
    """The available days, newest first, and each one's current build ({} from an older API)."""
    code, body = _get_json(f"{api}/v1/dataset")
    if code != 200:
        raise SystemExit(f"-> {code} {body.get('detail', body)}")
    return body["days"], body.get("builds", {})


def _covered(build_dir: pathlib.Path, hotkey: str, wanted: set[str] | None) -> bool:
    """True when an earlier run FOR THIS HOTKEY downloaded every file of this build for the wanted
    assets (None = every asset). A build's files never change, so that copy is still current."""
    try:
        done = json.loads(_marker(build_dir, hotkey).read_text())
    except (OSError, ValueError):
        return False
    return bool(done.get("all")) or (wanted is not None and wanted <= set(done.get("assets", [])))


def _mark_complete(build_dir: pathlib.Path, hotkey: str, assets: set[str], all_assets: bool) -> None:
    marker = _marker(build_dir, hotkey)
    try:
        done = json.loads(marker.read_text())
    except (OSError, ValueError):
        done = {}
    done = {
        "all": bool(done.get("all")) or all_assets,
        "assets": sorted(set(done.get("assets", [])) | assets),
    }
    marker.write_text(json.dumps(done))


def main() -> None:
    ap = argparse.ArgumentParser(description="Download a day of the Synth Ultra prompt dataset")
    ap.add_argument("--api", default=API_DEFAULT, help=f"submission API base (default {API_DEFAULT})")
    ap.add_argument("--list", action="store_true", help="list the available days and exit (no signature)")
    ap.add_argument("--day", help="YYYY-MM-DD (default: the newest available)")
    ap.add_argument("--assets", help="comma-separated, e.g. BTC,ETH (default: all)")
    ap.add_argument("--out", default="prompt-dataset", help="output directory (default ./prompt-dataset)")
    ap.add_argument("--force", action="store_true", help="download again even if this build is already complete")
    ap.add_argument("--wallet", help="bittensor coldkey wallet name")
    ap.add_argument("--hotkey", help="bittensor hotkey name under that wallet")
    ap.add_argument("--mnemonic", help="raw hotkey mnemonic (alternative to --wallet/--hotkey)")
    ap.add_argument("--uri", help="dev throwaway URI, e.g. //Alice (testing only)")
    args = ap.parse_args()

    days, builds = list_days(args.api)
    if args.list:
        print("\n".join(f"{d}  (build {builds[d]})" if d in builds else d for d in days) or "no day is available yet")
        return
    if not days:
        raise SystemExit("no day is available yet")
    day = args.day or days[0]
    if day not in days:
        raise SystemExit(f"{day} is not available; available: {', '.join(days)}")

    out = pathlib.Path(args.out)
    wanted = {a.strip().upper() for a in args.assets.split(",")} if args.assets else None
    kp = load_keypair(args)  # local: the cache check below needs to know WHOSE download this is
    hotkey = kp.ss58_address
    # Before spending a download: is the current build of that day already here in full, for this hotkey?
    if day in builds and not args.force and _covered(out / day / builds[day], hotkey, wanted):
        print(f"{day} (build {builds[day]}) is already complete in {out / day / builds[day]}; nothing to download")
        print("(use --force to download it again)")
        return

    ts = int(time.time())
    signature = "0x" + kp.sign(f"{DATASET_PREFIX}|{kp.ss58_address}|{ts}|{day}".encode()).hex()
    query = urllib.parse.urlencode({"day": day, "timestamp": ts, "signature": signature})
    code, body = _get_json(f"{args.api}/v1/dataset/{kp.ss58_address}?{query}")
    if code != 200:
        raise SystemExit(f"-> {code} {body.get('detail', body)}")

    build = f"{day}/{body['build']}"
    files = [(f"{build}/{name}", url) for name, url in body["shared"].items()]
    files += [(f"{build}/own/{hotkey}/{name}", url) for name, url in body["own"].items()]
    if wanted is not None:
        files = [(p, u) for p, u in files if _asset_of(p) in wanted]

    print(f"hotkey : {kp.ss58_address}")
    print(f"day    : {day} (build {body['build']}); {body['downloads_left_today']} download(s) left today")
    total = skipped = 0
    for rel, url in files:
        path = out / rel
        # A file is only ever in place complete (written to .partial, then renamed), and a build's
        # files never change: one already here from an interrupted run is kept, not fetched again.
        if path.exists() and not args.force:
            skipped += 1
            continue
        try:
            size = _download(url, path)
        except (OSError, urllib.error.URLError) as exc:
            raise SystemExit(
                f"download of {rel} failed ({exc}). The files already in {out / build} are complete; "
                "run again to fetch the rest (it uses another of today's downloads, but skips those files)."
            ) from None
        total += size
        print(f"  {rel}  {size / 1e6:.1f} MB")
    _mark_complete(out / build, hotkey, {_asset_of(rel) for rel, _ in files}, wanted is None)
    kept = f", {skipped} already here" if skipped else ""
    print(f"done: {len(files) - skipped} files, {total / 1e6:.0f} MB in {out / build}{kept}")
    if not body["own"]:
        print("no answers of yours on that day (you were not running, or answered no prompt)")


if __name__ == "__main__":
    main()
