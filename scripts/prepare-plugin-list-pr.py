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
import stat
import subprocess
import sys
import tempfile
import urllib.request
from collections import OrderedDict
from pathlib import Path


def _rm_readonly(func, path, exc):
    """rmtree error handler: clear the read-only bit and retry.

    Git marks files inside .git/objects/ read-only, which Windows refuses to
    delete without this dance.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


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


def latest_successful_test_run_url(gh, repo):
    """Return the HTML URL of the most recent successful Test workflow run on master."""
    result = subprocess.run(
        [gh, "run", "list", "--repo", repo, "--workflow", "Test",
         "--branch", "master", "--status", "success", "--limit", "1",
         "--json", "url"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        runs = json.loads(result.stdout)
        return runs[0]["url"] if runs else None
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


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


def check_ft2_validation(output):
    """Inspect validator.py output and report FingerText2's status.

    Returns:
        "ok"      — FingerText2 listed, no error block follows it.
        "error"   — an error block follows the FingerText2 line.
        "missing" — FingerText2 not found in the output.
    """
    lines = output.splitlines()
    for i, line in enumerate(lines):
        # validator prints display-name on its own line, optionally followed
        # by an annotation like "*** REQUIRES Npp >= ... ***"
        stripped = line.strip()
        if stripped == FOLDER_NAME or stripped.startswith(FOLDER_NAME + " "):
            # Look at the next non-blank line. If it starts an error dict,
            # this entry errored; otherwise it passed.
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    continue
                if nxt.lstrip().startswith("{'category': 'error'"):
                    return "error"
                return "ok"
            return "ok"
    return "missing"


def insert_into_plugin_list(json_path, entry):
    """Insert/replace entry in pl.x{86,64}.json, keeping alphabetical order."""
    # Read raw bytes first so we can detect the line ending convention.
    # pl.x86.json uses LF, pl.x64.json uses CRLF; mixing them up produces
    # a massive diff where every line appears changed.
    raw_bytes = open(json_path, "rb").read()
    newline = "\r\n" if b"\r\n" in raw_bytes else "\n"

    data = json.loads(raw_bytes.decode("utf-8"))

    plugins_key = "npp-plugins"
    if plugins_key not in data:
        die(f"{json_path} does not have a top-level '{plugins_key}' array.")

    plugins = [p for p in data[plugins_key] if p.get("folder-name") != FOLDER_NAME]
    plugins.append(entry)
    plugins.sort(key=lambda p: p.get("display-name", "").lower())
    data[plugins_key] = plugins

    # nppPluginList uses tab indentation. Use the same line ending as the
    # original file so git sees only the actual entry change.
    with open(json_path, "w", encoding="utf-8", newline=newline) as f:
        json.dump(data, f, indent="\t", ensure_ascii=False)
        if raw_bytes.endswith(b"\n"):
            f.write(newline)


def parse_args():
    p = argparse.ArgumentParser(description="Prepare nppPluginList PR for FingerText2.")
    p.add_argument("--open-pr", action="store_true",
                   help="Clone fork, insert entries, validate, and push a branch.")
    p.add_argument("--fork-owner", default=DEFAULT_FORK_OWNER,
                   help=f"Owner of the nppPluginList fork (default: {DEFAULT_FORK_OWNER})")
    p.add_argument("--repo", default=DEFAULT_REPO,
                   help=f"Plugin repo slug owner/name (default: {DEFAULT_REPO})")
    p.add_argument("--validate", action="store_true",
                   help="Run nppPluginList's validator.py against the inserted entry.")
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
        shutil.rmtree(fork_dir, onexc=_rm_readonly)

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

    if not args.validate:
        print("Skipping validator (use --validate to enable).")
    else:
        # Install validator dependencies. nppPluginList ships a requirements.txt;
        # if it doesn't, fall back to installing jsonschema directly.
        print("Installing validator dependencies...")
        req_file = fork_dir / "requirements.txt"
        if req_file.exists():
            run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "--quiet"])
        else:
            run([sys.executable, "-m", "pip", "install", "jsonschema", "--quiet"])

        # validator.py walks the whole plugin list, downloading every plugin's
        # ZIP to verify its SHA-256. Many entries fail with unrelated network
        # errors (especially on corporate networks that do TLS interception).
        # We only care whether FingerText2 itself validated.
        for arch in ("x86", "x64"):
            print(f"Running validator.py for {arch}...")
            result = subprocess.run(
                [sys.executable, "validator.py"],
                cwd=fork_dir,
                input=arch + "\n",
                capture_output=True,
                text=True,
            )
            output = result.stdout + result.stderr
            ft2_status = check_ft2_validation(output)
            if ft2_status == "missing":
                die(f"FingerText2 entry not found in validator output for {arch}. "
                    "Did the insertion fail?")
            if ft2_status == "error":
                print(output)
                die(f"FingerText2 validation failed for {arch}. See above.")
            other_errors = output.count("{'category': 'error'")
            print(f"  FingerText2 passed validation for {arch}. "
                  f"({other_errors} unrelated errors on other plugins ignored.)")

    run(["git", "add", "src/pl.x86.json", "src/pl.x64.json"], cwd=fork_dir)
    run(["git", "commit", "-m", f"Add FingerText2 {version}"], cwd=fork_dir)
    # Force-with-lease: the branch on the fork is owned by us and may have
    # earlier (now-obsolete) commits from a previous script run.
    run(["git", "push", "--force-with-lease", "origin", branch_name], cwd=fork_dir)

    print()
    print(f"Branch '{branch_name}' pushed to https://github.com/{fork_repo}")
    print(f"Open a PR at: https://github.com/notepad-plus-plus/nppPluginList/"
          f"compare/master...{args.fork_owner}:{branch_name}")
    print()
    test_run_url = latest_successful_test_run_url(gh, args.repo)
    test_line = (f"  - Automated tests pass: {test_run_url}"
                 if test_run_url
                 else "  - Automated tests pass (paste a green workflow run URL here)")

    print("Suggested PR title: Add FingerText2 plugin")
    print("Suggested PR body:")
    print(f"  - Adds FingerText2 {version} (32-bit and 64-bit)")
    print(f"  - Homepage: {homepage}")
    print(f"  - Release: https://github.com/{args.repo}/releases/tag/{version}")
    print(test_line)


if __name__ == "__main__":
    main()
