"""
Prepare a pull request against notepad-plus-plus/nppPluginList for FingerText2.

Fetches the latest stable GitHub release, downloads both ZIPs, computes SHA-256,
and generates JSON entries for pl.x86.json and pl.x64.json.

With --open-pr it also clones a fork, inserts the entries alphabetically, runs
validator.py, commits, and pushes a branch ready for a PR.

Usage:
    python scripts/prepare-plugin-list-pr.py
    python scripts/prepare-plugin-list-pr.py --open-pr
    python scripts/prepare-plugin-list-pr.py --open-pr --fork-owner someone
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections import OrderedDict
from pathlib import Path


DEFAULT_FORK_OWNER = "ultimatejimmy"
DEFAULT_REPO       = "ultimatejimmy/FingerText2"
DESCRIPTION        = ("Tab-triggered snippet plugin with hotspot navigation, "
                      "dynamic hotspots, and a snippet dock.")
AUTHOR             = "Jimmy Pautz"
FOLDER_NAME        = "FingerText2"


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def find_gh():
    """Resolve gh.exe via PATH, falling back to standard install locations."""
    found = shutil.which("gh")
    if found:
        return found
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", ""), "GitHub CLI", "gh.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "GitHub CLI", "gh.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "GitHub CLI", "gh.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    die("gh CLI not found. Install from https://cli.github.com and run 'gh auth login'.")


def run(cmd, **kw):
    """Run a command, raising on non-zero exit."""
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        die(f"command failed: {' '.join(str(c) for c in cmd)}")
    return result


def run_capture(cmd, **kw):
    result = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if result.returncode != 0:
        die(f"command failed: {' '.join(str(c) for c in cmd)}\n{result.stderr}")
    return result.stdout


def gh_release_view(gh, repo):
    out = run_capture([gh, "release", "view", "--repo", repo,
                       "--json", "tagName,assets,isPrerelease"])
    return json.loads(out)


def download(url, dest):
    print(f"Downloading {os.path.basename(dest)}...")
    with urllib.request.urlopen(url) as response, open(dest, "wb") as f:
        shutil.copyfileobj(response, f)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_entry(version, hash_value, download_url, homepage):
    # OrderedDict preserves the schema's expected key order
    return OrderedDict([
        ("folder-name",  FOLDER_NAME),
        ("display-name", FOLDER_NAME),
        ("version",      version),
        ("id",           hash_value),
        ("repository",   download_url),
        ("description",  DESCRIPTION),
        ("author",       AUTHOR),
        ("homepage",     homepage),
    ])


def insert_into_plugin_list(json_path, entry):
    """Insert/replace entry in pl.x{86,64}.json, keeping alphabetical order."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    plugins_key = "npp-plugins"
    if plugins_key not in data:
        die(f"{json_path} does not have a top-level '{plugins_key}' array.")

    plugins = [p for p in data[plugins_key] if p.get("folder-name") != FOLDER_NAME]
    plugins.append(entry)
    plugins.sort(key=lambda p: p.get("display-name", "").lower())
    data[plugins_key] = plugins

    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def parse_args():
    p = argparse.ArgumentParser(description="Prepare nppPluginList PR for FingerText2.")
    p.add_argument("--open-pr", action="store_true",
                   help="Clone fork, insert entries, validate, and push a branch.")
    p.add_argument("--fork-owner", default=DEFAULT_FORK_OWNER,
                   help=f"Owner of the nppPluginList fork (default: {DEFAULT_FORK_OWNER})")
    p.add_argument("--repo", default=DEFAULT_REPO,
                   help=f"Plugin repo slug owner/name (default: {DEFAULT_REPO})")
    return p.parse_args()


def main():
    args = parse_args()
    gh = find_gh()

    print(f"Fetching latest stable release from {args.repo}...")
    release = gh_release_view(gh, args.repo)

    if release.get("isPrerelease"):
        die(f"Latest release ({release['tagName']}) is a pre-release. "
            "Publish a stable release first.")

    tag_name = release["tagName"]
    version  = tag_name[1:] if tag_name.startswith("v") else tag_name
    print(f"Release: {tag_name}  (version {version})")

    assets = release.get("assets", [])
    zip32 = next((a for a in assets if a["name"].endswith("_32bit.zip")), None)
    zip64 = next((a for a in assets if a["name"].endswith("_64bit.zip")), None)
    if not zip32: die(f"No _32bit.zip asset in release {tag_name}.")
    if not zip64: die(f"No _64bit.zip asset in release {tag_name}.")

    tmp_dir = Path(tempfile.gettempdir()) / f"ft2_pr_{version}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    local32 = tmp_dir / zip32["name"]
    local64 = tmp_dir / zip64["name"]
    download(zip32["url"], local32)
    download(zip64["url"], local64)

    hash32 = sha256(local32)
    hash64 = sha256(local64)

    print()
    print(f"32-bit ZIP: {zip32['name']}")
    print(f"  URL:    {zip32['url']}")
    print(f"  SHA256: {hash32}")
    print()
    print(f"64-bit ZIP: {zip64['name']}")
    print(f"  URL:    {zip64['url']}")
    print(f"  SHA256: {hash64}")
    print()

    homepage = f"https://github.com/{args.repo}"
    entry32  = build_entry(version, hash32, zip32["url"], homepage)
    entry64  = build_entry(version, hash64, zip64["url"], homepage)

    snippet32 = tmp_dir / "entry_x86.json"
    snippet64 = tmp_dir / "entry_x64.json"
    snippet32.write_text(json.dumps(entry32, indent=4) + "\n", encoding="utf-8")
    snippet64.write_text(json.dumps(entry64, indent=4) + "\n", encoding="utf-8")

    print(f"JSON entries written to:")
    print(f"  {snippet32}")
    print(f"  {snippet64}")
    print()

    if not args.open_pr:
        print("Done. To insert these into nppPluginList and open a PR, "
              "re-run with --open-pr.")
        return

    # Clone fork and prepare branch
    fork_repo   = f"{args.fork_owner}/nppPluginList"
    fork_dir    = tmp_dir / "nppPluginList"
    branch_name = f"add-fingertext2-{version}"

    if fork_dir.exists():
        shutil.rmtree(fork_dir)

    print(f"Cloning fork {fork_repo}...")
    run(["git", "clone", f"https://github.com/{fork_repo}.git", str(fork_dir)])
    run(["git", "remote", "add", "upstream",
         "https://github.com/notepad-plus-plus/nppPluginList.git"], cwd=fork_dir)
    run(["git", "fetch", "upstream"], cwd=fork_dir)
    run(["git", "checkout", "-b", branch_name, "upstream/master"], cwd=fork_dir)

    print("Inserting x86 entry...")
    insert_into_plugin_list(fork_dir / "src" / "pl.x86.json", entry32)
    print("Inserting x64 entry...")
    insert_into_plugin_list(fork_dir / "src" / "pl.x64.json", entry64)

    print("Running validator.py...")
    validator_result = subprocess.run([sys.executable, "validator.py"], cwd=fork_dir)
    if validator_result.returncode != 0:
        die("validator.py failed. Fix the schema error before submitting the PR.")
    print("  Validator passed.")

    run(["git", "add", "src/pl.x86.json", "src/pl.x64.json"], cwd=fork_dir)
    run(["git", "commit", "-m", f"Add FingerText2 {version}"], cwd=fork_dir)
    run(["git", "push", "origin", branch_name], cwd=fork_dir)

    print()
    print(f"Branch '{branch_name}' pushed to https://github.com/{fork_repo}")
    print(f"Open a PR at: https://github.com/notepad-plus-plus/nppPluginList/"
          f"compare/master...{args.fork_owner}:{branch_name}")
    print()
    print("Suggested PR title: Add FingerText2 plugin")
    print("Suggested PR body:")
    print(f"  - Adds FingerText2 {version} (32-bit and 64-bit)")
    print(f"  - Homepage: {homepage}")
    print(f"  - Release: https://github.com/{args.repo}/releases/tag/{version}")
    print(f"  - Automated tests pass (link to green workflow run)")


if __name__ == "__main__":
    main()
