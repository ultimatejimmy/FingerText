"""
Cut a FingerText2 release with date-based versioning.

Usage:
    python scripts/release.py 26.5.26
    python scripts/release.py 26.5.26-beta
    python scripts/release.py 26.5.26 --dry-run
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path


VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(-beta)?$")
MONTHS = ["", "January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"]


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd, **kw):
    """Run a command, raising on non-zero exit."""
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        die(f"command failed: {' '.join(cmd)}")
    return result


def run_capture(cmd):
    """Run a command and return stdout as a string."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        die(f"command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def parse_args():
    p = argparse.ArgumentParser(description="Cut a FingerText2 release.")
    p.add_argument("version", nargs="?",
                   help="Version: YY.M.D[.N][-beta]. Prompted if omitted.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan; do not edit, commit, tag, or push.")
    return p.parse_args()


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent

    version = args.version
    if not version:
        version = input("Enter version (e.g. 26.5.26 or 26.5.26-beta): ").strip()
    version = version.strip()

    m = VERSION_RE.match(version)
    if not m:
        die(f"Invalid version '{version}'. Expected YY.M.D, YY.M.D.N, "
            "YY.M.D-beta, or YY.M.D.N-beta.")

    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    revision = int(m.group(4)) if m.group(4) else 0
    is_beta = m.group(5) is not None

    version_num = f"{year},{month},{day},{revision}"
    beta_bit = 1 if is_beta else 0
    version_linear = (year * 10_000_000
                      + month * 100_000
                      + day * 1_000
                      + revision * 10
                      + beta_bit)
    tag_name = version

    # Guard: dirty working tree (ignore untracked files)
    porcelain = run_capture(["git", "status", "--porcelain"])
    dirty = [ln for ln in porcelain.splitlines() if not ln.startswith("??")]
    if dirty:
        die("Working tree is dirty. Commit or stash before releasing:\n"
            + "\n".join(dirty))

    # Guard: tag must not already exist locally
    existing = run_capture(["git", "tag", "--list", tag_name]).strip()
    if existing:
        die(f"Tag {tag_name} already exists locally. Use a different version.")

    # Plan
    print()
    print(f"Release plan for {version}")
    print(f'  VERSION_TEXT    = "{version}"')
    print(f"  VERSION_NUM     = {version_num}")
    print(f"  VERSION_LINEAR  = {version_linear}")
    print(f'  VERSION_STAGE   = ""')
    print(f"  Tag             = {tag_name}")
    print(f"  Pre-release     = {is_beta}")
    print()

    if args.dry_run:
        print("[dry-run] Skipping file edits, commit, tag, and push.")
        return

    # Rewrite Config/Version.h
    vh_path = repo_root / "Config" / "Version.h"
    vh = vh_path.read_text(encoding="utf-8")

    date_text = f"{MONTHS[month]} 20{year:02d}"
    copyright_text = f"Copyright (C) 20{year:02d}"

    edits = [
        (r'#define VERSION_TEXT\s+"[^"]*"',   f'#define VERSION_TEXT "{version}"'),
        (r'#define VERSION_NUM\s+[\d,]+',     f'#define VERSION_NUM {version_num}'),
        (r'#define VERSION_LINEAR\s+\d+',     f'#define VERSION_LINEAR {version_linear}'),
        (r'#define VERSION_STAGE\s+"[^"]*"',  '#define VERSION_STAGE ""'),
        (r'#define DATE_TEXT\s+"[^"]*"',      f'#define DATE_TEXT "{date_text}"'),
        (r'#define COPYRIGHT_TEXT\s+"[^"]*"', f'#define COPYRIGHT_TEXT "{copyright_text}"'),
    ]
    for pattern, replacement in edits:
        vh = re.sub(pattern, replacement, vh, count=1)

    vh_path.write_text(vh, encoding="utf-8")
    print("Updated Config/Version.h")

    # Commit and tag
    run(["git", "add", "Config/Version.h"], cwd=repo_root)
    run(["git", "commit", "-m", f"Release {tag_name}"], cwd=repo_root)
    run(["git", "tag", "-a", tag_name, "-m", tag_name], cwd=repo_root)
    print(f"Created commit and tag {tag_name}")

    # Push branch and tag in a single connection (one passphrase prompt)
    run(["git", "push", "origin", "master", tag_name], cwd=repo_root)
    print(f"Pushed master and tag {tag_name} to origin")
    print()
    print("Done. The release workflow will now build both architectures "
          "and create a draft GitHub Release.")


if __name__ == "__main__":
    main()
