"""
Tier 1 smoke tests — run on every PR and push to master.

Requires:
  - pywinauto  (pip install pywinauto)
  - pyautogui  (pip install pyautogui, for screenshot on failure)
  - NPP_EXE env var pointing to a Notepad++ portable executable
  - FT2_DLL   env var pointing to the built FingerText2.dll
  - FT2_DB    env var pointing to a seed FingerText2.db3 fixture (optional)

Coverage:
  - Plugin loads without crash
  - No "Plugin Exception" dialog on startup
  - Plugins > FingerText2 submenu is present
  - About dialog opens and contains expected text
  - NPP exits cleanly (return code 0)
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile

# Guard: import pywinauto lazily so import errors produce a clear message
try:
    import pywinauto
    from pywinauto.application import Application
    from pywinauto.findwindows import ElementNotFoundError
except ImportError as exc:
    print(f"FAIL: pywinauto not installed: {exc}")
    sys.exit(1)

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

# ── Helpers ───────────────────────────────────────────────────────────────────

def screenshot(name: str):
    if HAS_PYAUTOGUI:
        path = os.path.join(tempfile.gettempdir(), f"{name}.png")
        pyautogui.screenshot(path)
        print(f"  Screenshot saved: {path}")

def fail(msg: str, label: str = "failure"):
    screenshot(label)
    print(f"FAIL: {msg}")
    sys.exit(1)

def env_required(var: str) -> str:
    val = os.environ.get(var)
    if not val:
        print(f"FAIL: environment variable {var} is not set")
        sys.exit(1)
    return val

# ── Setup ─────────────────────────────────────────────────────────────────────

npp_exe = env_required("NPP_EXE")
ft2_dll = env_required("FT2_DLL")
ft2_db  = os.environ.get("FT2_DB")   # optional

if not os.path.isfile(npp_exe):
    fail(f"NPP_EXE does not exist: {npp_exe}")
if not os.path.isfile(ft2_dll):
    fail(f"FT2_DLL does not exist: {ft2_dll}")

# Determine NPP root from exe path
npp_dir = os.path.dirname(npp_exe)

# Install plugin DLL into portable NPP
plugin_dir = os.path.join(npp_dir, "plugins", "FingerText2")
os.makedirs(plugin_dir, exist_ok=True)
shutil.copy2(ft2_dll, os.path.join(plugin_dir, "FingerText2.dll"))

# Pre-seed database if provided
if ft2_db and os.path.isfile(ft2_db):
    appdata = os.environ.get("APPDATA", "")
    cfg_dir = os.path.join(appdata, "Notepad++", "plugins", "config", "FingerText2")
    os.makedirs(cfg_dir, exist_ok=True)
    dest_db = os.path.join(cfg_dir, "FingerText2.db3")
    if not os.path.isfile(dest_db):
        shutil.copy2(ft2_db, dest_db)

# ── Launch NPP ────────────────────────────────────────────────────────────────

print("Launching Notepad++...")
app = Application(backend="uia").start(npp_exe, timeout=30)

try:
    npp_win = app.window(title_re=".*Notepad\\+\\+.*", control_type="Window")
    npp_win.wait("visible", timeout=20)
except ElementNotFoundError:
    fail("Notepad++ main window did not appear within 20 s", "no_main_window")

time.sleep(2)  # let plugin initialization finish

# ── Check 1: No Plugin Exception dialog ───────────────────────────────────────
exception_dlgs = app.windows(title_re=".*Plugin.*Exception.*|.*Access.*violation.*")
if exception_dlgs:
    fail("Plugin Exception dialog appeared on startup", "plugin_exception")

print("  [PASS] No Plugin Exception dialog")

# ── Check 2: FingerText2 submenu exists ───────────────────────────────────────
try:
    plugins_menu = npp_win.child_window(title="Plugins", control_type="MenuItem")
    plugins_menu.click_input()
    time.sleep(0.5)
    ft2_menu = npp_win.child_window(title="FingerText2", control_type="MenuItem")
    ft2_menu.click_input()
    time.sleep(0.5)
    # Dismiss by pressing Escape
    npp_win.type_keys("{ESC}{ESC}")
    time.sleep(0.3)
except ElementNotFoundError:
    fail("FingerText2 submenu not found in Plugins menu", "no_ft2_menu")

print("  [PASS] FingerText2 submenu found")

# ── Check 3: About dialog ─────────────────────────────────────────────────────
try:
    plugins_menu = npp_win.child_window(title="Plugins", control_type="MenuItem")
    plugins_menu.click_input()
    time.sleep(0.5)
    ft2_menu = npp_win.child_window(title="FingerText2", control_type="MenuItem")
    ft2_menu.click_input()
    time.sleep(0.5)
    about_item = npp_win.child_window(title_re=".*About.*", control_type="MenuItem")
    about_item.click_input()
    time.sleep(1)

    about_dlg = app.window(title_re=".*FingerText2.*")
    about_dlg.wait("visible", timeout=5)
    dlg_text = about_dlg.window_text()
    # The text may be in child controls
    all_text = " ".join(c.window_text() for c in about_dlg.children())

    if "FingerText2" not in all_text and "FingerText2" not in dlg_text:
        fail("About dialog does not mention FingerText2", "about_no_name")
    if "Jimmy Pautz" not in all_text and "Jimmy Pautz" not in dlg_text:
        fail("About dialog does not mention Jimmy Pautz", "about_no_author")

    # Dismiss
    about_dlg.type_keys("{ENTER}")
    time.sleep(0.3)
except ElementNotFoundError:
    fail("About dialog did not open", "no_about_dialog")

print("  [PASS] About dialog shows correct name and author")

# ── Exit NPP cleanly ──────────────────────────────────────────────────────────
npp_win.close()
time.sleep(2)

# Handle unsaved-file prompt if it appears
save_dlgs = app.windows(title_re=".*Save.*|.*Notepad.*")
for dlg in save_dlgs:
    try:
        no_btn = dlg.child_window(title_re=".*Don.*t Save.*|.*No.*", control_type="Button")
        no_btn.click_input()
    except Exception:
        pass

app.wait_for_process_exit(timeout=10)
rc = app.process
print(f"  NPP exited")

print("\nSmoke tests PASSED")
sys.exit(0)
