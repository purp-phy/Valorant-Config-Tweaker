"""
Valorant Config Tweaker
────────────────────────────────────────────────────────────────────────────────
Applies / resets Valorant GameUserSettings.ini stretch tweaks.
No hardcoded paths — all account folders are detected from LOCALAPPDATA.
Display resolution is changed via Windows API (ctypes, no extra installs).
pywin32 is used when available but never required.

Run:
    python valorant_config_tweaker.py
────────────────────────────────────────────────────────────────────────────────
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# ── optional pywin32 (better display API, not required) ───────────────────────
try:
    import win32api, win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

# ── constants ─────────────────────────────────────────────────────────────────
PUUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(-[a-z0-9]+)?$"
)

VALORANT_CONFIG_BASE = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Config"
)
RIOT_LOCAL_MACHINE_INI = VALORANT_CONFIG_BASE / "WindowsClient" / "RiotLocalMachine.ini"
LABELS_FILE   = Path(__file__).resolve().parent / "valorant_account_labels.json"
BACKUP_SUFFIX = ".valorantbak"
SHOOTER_SECTION = "[/Script/ShooterGame.ShooterGameUserSettings]"

RESOLUTION_PRESETS = [
    ("Native  (monitor max)",           None,  None),
    ("1024×768   4:3 stretched",        1024,   768),
    ("1280×960   4:3 stretched",        1280,   960),
    ("1280×1024  5:4 stretched",        1280,  1024),
    ("1440×1080  4:3 stretched HD",     1440,  1080),
    ("1600×900   16:9",                 1600,   900),
    ("1366×768   HD",                   1366,   768),
    ("1920×1080  16:9 FHD",             1920,  1080),
    ("2560×1440  16:9 QHD",             2560,  1440),
    ("Custom…",                         None,  None),  # must stay last
]
CUSTOM_INDEX = len(RESOLUTION_PRESETS) - 1

RIOT_LAUNCH_ARGS = ["--launch-product=valorant", "--launch-patchline=live"]

# ── GUI colours / fonts ───────────────────────────────────────────────────────
BG      = "#0d0d12"
SURFACE = "#111118"
CARD    = "#1a1a26"
BORDER  = "#252535"
RED     = "#ff4655"
PURPLE  = "#7b61ff"
GREEN   = "#00d4aa"
YELLOW  = "#ffb347"
TEXT    = "#e8e8f0"
MUTED   = "#55556a"
HEAD_F  = ("Impact", 21)
UI_F    = ("Segoe UI", 9)
BTN_F   = ("Segoe UI Semibold", 10)
MONO_F  = ("Consolas", 9)


# ──────────────────────────────────────────────────────────────────────────────
# WINDOWS DISPLAY API
# ──────────────────────────────────────────────────────────────────────────────

# DEVMODE struct used by ctypes ChangeDisplaySettingsW
class _DEVMODE(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName",         ctypes.c_wchar * 32),
        ("dmSpecVersion",        ctypes.c_ushort),
        ("dmDriverVersion",      ctypes.c_ushort),
        ("dmSize",               ctypes.c_ushort),
        ("dmDriverExtra",        ctypes.c_ushort),
        ("dmFields",             ctypes.c_ulong),
        ("dmPositionX",          ctypes.c_long),
        ("dmPositionY",          ctypes.c_long),
        ("dmDisplayOrientation", ctypes.c_ulong),
        ("dmDisplayFixedOutput", ctypes.c_ulong),
        ("dmColor",              ctypes.c_short),
        ("dmDuplex",             ctypes.c_short),
        ("dmYResolution",        ctypes.c_short),
        ("dmTTOption",           ctypes.c_short),
        ("dmCollate",            ctypes.c_short),
        ("dmFormName",           ctypes.c_wchar * 32),
        ("dmLogPixels",          ctypes.c_ushort),
        ("dmBitsPerPel",         ctypes.c_ulong),
        ("dmPelsWidth",          ctypes.c_ulong),
        ("dmPelsHeight",         ctypes.c_ulong),
        ("dmDisplayFlags",       ctypes.c_ulong),
        ("dmDisplayFrequency",   ctypes.c_ulong),
        ("dmICMMethod",          ctypes.c_ulong),
        ("dmICMIntent",          ctypes.c_ulong),
        ("dmMediaType",          ctypes.c_ulong),
        ("dmDitherType",         ctypes.c_ulong),
        ("dmReserved1",          ctypes.c_ulong),
        ("dmReserved2",          ctypes.c_ulong),
        ("dmPanningWidth",       ctypes.c_ulong),
        ("dmPanningHeight",      ctypes.c_ulong),
    ]


def get_native_display_res() -> tuple[int, int]:
    """
    Return the monitor's maximum supported resolution by enumerating every mode
    the display adapter exposes and picking the highest pixel count.
    This is correct even when Windows is currently running at a lower resolution.
    Falls back to ctypes GetDeviceCaps (DESKTOPHORZRES/DESKTOPVERTRES), then (0,0).
    """
    # win32api path
    if WIN32_AVAILABLE:
        try:
            best_w = best_h = 0
            i = 0
            while True:
                try:
                    dm = win32api.EnumDisplaySettings(None, i)
                    if dm.PelsWidth * dm.PelsHeight > best_w * best_h:
                        best_w, best_h = dm.PelsWidth, dm.PelsHeight
                    i += 1
                except Exception:
                    break
            if best_w > 0:
                return (best_w, best_h)
        except Exception:
            pass

    # ctypes path — GetDeviceCaps with DESKTOPHORZRES/DESKTOPVERTRES returns
    # physical panel dimensions regardless of the current Windows setting
    try:
        gdi32  = ctypes.windll.gdi32   # type: ignore[attr-defined]
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.SetProcessDPIAware()
        hdc = user32.GetDC(0)
        w = gdi32.GetDeviceCaps(hdc, 118)  # DESKTOPHORZRES
        h = gdi32.GetDeviceCaps(hdc, 117)  # DESKTOPVERTRES
        user32.ReleaseDC(0, hdc)
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass

    return (0, 0)


def get_current_display_res() -> tuple[int, int]:
    """Return the resolution Windows is currently set to."""
    if WIN32_AVAILABLE:
        try:
            dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            return (dm.PelsWidth, dm.PelsHeight)
        except Exception:
            pass
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.SetProcessDPIAware()
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        if w > 0 and h > 0:
            return (w, h)
    except Exception:
        pass
    return (0, 0)


def set_display_res(w: int, h: int) -> str:
    """
    Change Windows display resolution.
    Tries win32api first, falls back to ctypes — works without pywin32.
    Returns a human-readable result string starting with ✓ or ✗.
    """
    if WIN32_AVAILABLE:
        try:
            dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            if dm.PelsWidth == w and dm.PelsHeight == h:
                return f"Display already at {w}×{h}."
            dm.PelsWidth  = w
            dm.PelsHeight = h
            dm.Fields     = win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT
            r = win32api.ChangeDisplaySettings(dm, 0)
            if r in (0, 3):
                return f"✓ Display changed to {w}×{h}."
            if r == 1:
                return f"✓ Display changed to {w}×{h} (restart required)."
            return f"✗ ChangeDisplaySettings returned {r}."
        except Exception:
            pass  # fall through to ctypes

    # ctypes — always available on Windows, no pip required
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        cw = user32.GetSystemMetrics(0)
        ch = user32.GetSystemMetrics(1)
        if cw == w and ch == h:
            return f"Display already at {w}×{h}."
        dm = _DEVMODE()
        dm.dmSize       = ctypes.sizeof(_DEVMODE)
        dm.dmPelsWidth  = w
        dm.dmPelsHeight = h
        dm.dmFields     = 0x00080000 | 0x00100000  # DM_PELSWIDTH | DM_PELSHEIGHT
        r = user32.ChangeDisplaySettingsW(ctypes.byref(dm), 0)
        if r == 0:
            return f"✓ Display changed to {w}×{h}."
        return f"✗ ChangeDisplaySettings returned {r} (mode may not be supported)."
    except Exception as ex:
        return f"✗ Display change failed: {ex}"


def restore_native_display_res(log) -> None:
    """
    Change Windows display resolution back to the monitor's native maximum
    without touching any config file or backup.
    """
    nw, nh = get_native_display_res()
    if nw == 0 or nh == 0:
        nw, nh = get_current_display_res()
    if nw == 0 or nh == 0:
        log("  ✗ Cannot determine native resolution.", "err")
        return
    log(f"  ⟳  Restoring display to native {nw}×{nh}…", "info")
    msg = set_display_res(nw, nh)
    log(f"  {msg}", "ok" if "✓" in msg else "warn")


# ──────────────────────────────────────────────────────────────────────────────
# INI HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def read_ini_key(content: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}\s*=\s*(.*)$", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def _replace_key(content: str, key: str, value: str) -> tuple[str, int]:
    """Replace key=<anything> with key=value. Returns (new_content, count)."""
    pattern = re.compile(rf"^({re.escape(key)}\s*=).*$", re.MULTILINE)
    return pattern.subn(rf"\g<1>{value}", content)


def _remove_key(content: str, key: str) -> tuple[str, int]:
    """Remove a key=value line entirely. Returns (new_content, count)."""
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*\n?", re.MULTILINE)
    return pattern.subn("", content)


def _insert_into_section(content: str, section: str, key: str, value: str) -> str:
    """Insert key=value at the end of a section (before the next section header)."""
    sec_m = re.search(re.escape(section), content)
    if not sec_m:
        return content + f"\n{section}\n{key}={value}\n"
    rest   = content[sec_m.end():]
    next_m = re.search(r"^\[", rest, re.MULTILINE)
    ins    = sec_m.end() + (next_m.start() if next_m else len(rest))
    return content[:ins] + f"{key}={value}\n" + content[ins:]


# ──────────────────────────────────────────────────────────────────────────────
# ACCOUNT DETECTION
# ──────────────────────────────────────────────────────────────────────────────

def get_all_accounts() -> list[dict]:
    """
    Enumerate every PUUID subfolder under Config/.
    Returns list of dicts sorted by most-recently-modified first:
      puuid, config_path (Path or None), last_modified (float mtime)
    """
    if not VALORANT_CONFIG_BASE.exists():
        return []
    accounts: list[dict] = []
    try:
        for d in VALORANT_CONFIG_BASE.iterdir():
            if not (d.is_dir() and PUUID_RE.match(d.name)):
                continue
            cfg = d / "WindowsClient" / "GameUserSettings.ini"
            try:
                mtime = d.stat().st_mtime
            except Exception:
                mtime = 0.0
            accounts.append({
                "puuid":         d.name,
                "config_path":   cfg if cfg.exists() else None,
                "last_modified": mtime,
            })
    except Exception:
        pass
    accounts.sort(key=lambda a: a["last_modified"], reverse=True)
    return accounts


def get_last_played_puuid() -> str | None:
    """
    Scan RiotLocalMachine.ini for the first value that looks like a PUUID.
    We scan all values instead of hardcoding a key name — it changes between
    Riot client versions.
    """
    try:
        if not RIOT_LOCAL_MACHINE_INI.exists():
            return None
        for line in RIOT_LOCAL_MACHINE_INI.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line:
                continue
            val = line.split("=", 1)[1].strip()
            if PUUID_RE.match(val):
                return val
    except Exception:
        pass
    return None


def get_valorant_configs() -> list[Path]:
    """Return GameUserSettings.ini paths for all detected accounts."""
    return [
        a["config_path"] for a in get_all_accounts()
        if a["config_path"] is not None
    ]


# ──────────────────────────────────────────────────────────────────────────────
# LABEL PERSISTENCE
# ──────────────────────────────────────────────────────────────────────────────

def _load_labels() -> dict[str, str]:
    try:
        if LABELS_FILE.exists():
            return json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_labels(labels: dict[str, str]) -> bool:
    try:
        LABELS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LABELS_FILE.write_text(
            json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# STRETCH STATUS
# ──────────────────────────────────────────────────────────────────────────────

def _is_stretched_res(w: int, h: int) -> bool:
    """
    True if the resolution is not 16:9.
    16:9 = native / normal fullscreen (not stretched).
    Anything else (4:3, 5:4, custom like 1568×1080) = stretched.
    """
    return h > 0 and abs(w / h - 16 / 9) > 0.05


def read_stretch_status(config_path) -> dict:
    """
    Returns:
      res       : "W×H" or "?"
      stretched : True  = exclusive fullscreen + no letterbox + non-16:9 res
                  False = anything else (normal, windowed, 16:9)
      tweaked   : True if our .valorantbak backup exists on disk
    """
    out = {"res": "?", "stretched": False, "tweaked": False}
    if config_path is None:
        return out

    path = Path(config_path)
    out["tweaked"] = Path(str(path) + BACKUP_SUFFIX).exists()

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out

    w_str = read_ini_key(content, "ResolutionSizeX")
    h_str = read_ini_key(content, "ResolutionSizeY")
    # LastConfirmedFullscreenMode is the ground truth for what actually ran last
    fs    = read_ini_key(content, "LastConfirmedFullscreenMode")
    lb    = read_ini_key(content, "bShouldLetterbox")

    w = h = 0
    if w_str and h_str:
        try:
            w, h = int(w_str), int(h_str)
            out["res"] = f"{w}×{h}"
        except ValueError:
            pass

    # Stretched = exclusive fullscreen (mode 2) + letterbox off + non-16:9 res
    exclusive_fs  = fs is not None and fs.strip() == "2"
    letterbox_off = lb is not None and lb.strip().lower() == "false"
    out["stretched"] = exclusive_fs and letterbox_off and w > 0 and _is_stretched_res(w, h)

    return out


# ──────────────────────────────────────────────────────────────────────────────
# APPLY / RESET
# ──────────────────────────────────────────────────────────────────────────────

# Keys touched by apply_tweaks (excluding FullscreenMode which may be inserted)
_TWEAK_KEYS = (
    "bShouldLetterbox",
    "bLastConfirmedShouldLetterbox",
    "LastConfirmedFullscreenMode",
    "PreferredFullscreenMode",
    "ResolutionSizeX",
    "ResolutionSizeY",
    "LastUserConfirmedResolutionSizeX",
    "LastUserConfirmedResolutionSizeY",
    "DesiredScreenWidth",
    "DesiredScreenHeight",
    "LastUserConfirmedDesiredScreenWidth",
    "LastUserConfirmedDesiredScreenHeight",
)


def apply_tweaks(path: Path, target_w: int, target_h: int, log) -> None:
    content = path.read_text(encoding="utf-8", errors="replace")

    orig_w  = read_ini_key(content, "ResolutionSizeX") or "?"
    orig_h  = read_ini_key(content, "ResolutionSizeY") or "?"
    orig_fs = read_ini_key(content, "LastConfirmedFullscreenMode") or "?"
    orig_lb = read_ini_key(content, "bShouldLetterbox") or "?"
    log(f"  ℹ  Current → {orig_w}×{orig_h}  FullscreenMode={orig_fs}  Letterbox={orig_lb}", "info")

    # Backup (only on first apply — preserves the unmodified original)
    backup = Path(str(path) + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(path, backup)
        log(f"  ✓ Backup created → {backup.name}", "ok")
    else:
        log("  ℹ  Backup already exists, keeping original.", "info")

    tweaks = {
        "bShouldLetterbox":                      "False",
        "bLastConfirmedShouldLetterbox":          "False",
        "LastConfirmedFullscreenMode":            "2",
        "PreferredFullscreenMode":                "2",
        "ResolutionSizeX":                        str(target_w),
        "ResolutionSizeY":                        str(target_h),
        "LastUserConfirmedResolutionSizeX":       str(target_w),
        "LastUserConfirmedResolutionSizeY":       str(target_h),
        "DesiredScreenWidth":                     str(target_w),
        "DesiredScreenHeight":                    str(target_h),
        "LastUserConfirmedDesiredScreenWidth":    str(target_w),
        "LastUserConfirmedDesiredScreenHeight":   str(target_h),
    }

    for key, value in tweaks.items():
        content, n = _replace_key(content, key, value)
        if n:
            log(f"  ✓ {key} = {value}", "ok")
        else:
            log(f"  ⚠  {key} not found in file, skipping.", "warn")

    # FullscreenMode is absent in a stock config — insert it if needed
    content, n = _replace_key(content, "FullscreenMode", "2")
    if n:
        log("  ✓ FullscreenMode = 2", "ok")
    else:
        content = _insert_into_section(content, SHOOTER_SECTION, "FullscreenMode", "2")
        log("  ✓ FullscreenMode = 2 (inserted)", "ok")

    path.write_text(content, encoding="utf-8")
    log("  ✅ Config written.", "ok")


def reset_config(path: Path, log) -> None:
    """
    Revert all tweaked keys back to native-resolution defaults.
    Native resolution = monitor's hardware maximum (from Windows API).
    FullscreenMode is removed entirely if present — it's not in stock configs.
    Backup is deleted so the TWEAKED badge clears.
    """
    if not path.exists():
        log("  ⚠  Config file not found.", "warn")
        return

    # Native res comes from the OS — not the INI, not a backup
    nw, nh = get_native_display_res()
    if nw == 0 or nh == 0:
        # Last resort: whatever Windows is currently set to
        nw, nh = get_current_display_res()
    if nw == 0 or nh == 0:
        log("  ✗ Cannot determine native resolution — aborting.", "err")
        return

    log(f"  ℹ  Resetting to native {nw}×{nh}", "info")
    content = path.read_text(encoding="utf-8", errors="replace")

    defaults = {
        "bShouldLetterbox":                    "True",
        "bLastConfirmedShouldLetterbox":        "True",
        "LastConfirmedFullscreenMode":          "0",
        "PreferredFullscreenMode":              "1",
        "ResolutionSizeX":                      str(nw),
        "ResolutionSizeY":                      str(nh),
        "LastUserConfirmedResolutionSizeX":     str(nw),
        "LastUserConfirmedResolutionSizeY":     str(nh),
        "DesiredScreenWidth":                   str(nw),
        "DesiredScreenHeight":                  str(nh),
        "LastUserConfirmedDesiredScreenWidth":  str(nw),
        "LastUserConfirmedDesiredScreenHeight": str(nh),
    }

    for key, value in defaults.items():
        content, n = _replace_key(content, key, value)
        if n:
            log(f"  ✓ {key} = {value}", "ok")
        else:
            log(f"  ⚠  {key} not found, skipping.", "warn")

    # FullscreenMode was injected by apply — remove it entirely to match stock config
    content, n = _remove_key(content, "FullscreenMode")
    if n:
        log("  ✓ FullscreenMode removed (not in stock config)", "ok")

    path.write_text(content, encoding="utf-8")
    log("  ✅ Config reset to defaults.", "ok")

    # Remove backup so TWEAKED badge clears
    backup = Path(str(path) + BACKUP_SUFFIX)
    if backup.exists():
        try:
            backup.unlink()
            log("  ✓ Backup removed.", "ok")
        except Exception as ex:
            log(f"  ⚠  Could not remove backup: {ex}", "warn")

    # Restore display to native
    log(f"  ⟳  Restoring display to {nw}×{nh}…", "info")
    msg = set_display_res(nw, nh)
    log(f"  {msg}", "ok" if "✓" in msg else "warn")


# ──────────────────────────────────────────────────────────────────────────────
# RIOT CLIENT LAUNCHER
# ──────────────────────────────────────────────────────────────────────────────

def _find_riot_via_windows_search() -> Path | None:
    """Query Windows Search index via PowerShell + ADODB for RiotClientServices.exe."""
    sql    = "SELECT System.ItemPathDisplay FROM SystemIndex WHERE System.FileName = 'RiotClientServices.exe'"
    ps_cmd = "; ".join([
        "try",
        "$c = New-Object -ComObject ADODB.Connection",
        "$c.Open(\"Provider=Search.CollatorDSO;Extended Properties=Application=Windows\")",
        "$r = New-Object -ComObject ADODB.Recordset",
        f"$r.Open(\"{sql}\", $c)",
        "while (-not $r.EOF) { $r.Fields.Item(\"System.ItemPathDisplay\").Value; $r.MoveNext() }",
        "$r.Close()", "$c.Close()",
        "} catch { }",
    ])
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.lower().endswith("riotclientservices.exe"):
                p = Path(line)
                if p.exists():
                    return p
    except Exception:
        pass
    return None


def _find_riot_via_process() -> Path | None:
    """Get RiotClientServices.exe path from the running process list."""
    for cmd, parse in [
        (
            ["wmic", "process", "where", "name='RiotClientServices.exe'",
             "get", "ExecutablePath", "/value"],
            lambda ln: ln.split("=", 1)[1].strip() if ln.lower().startswith("executablepath=") else None,
        ),
        (
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-Process -Name RiotClientServices -ErrorAction SilentlyContinue).Path"],
            lambda ln: ln.strip() if ln.strip().lower().endswith(".exe") else None,
        ),
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            for line in r.stdout.splitlines():
                val = parse(line)
                if val:
                    p = Path(val)
                    if p.exists():
                        return p
        except Exception:
            continue
    return None


def find_riot_client() -> tuple[Path | None, str]:
    """Locate RiotClientServices.exe. Returns (path, method_description)."""
    p = _find_riot_via_windows_search()
    if p:
        return p, f"Windows Search → {p}"
    p = _find_riot_via_process()
    if p:
        return p, f"running process → {p}"
    return None, "not found"


def launch_valorant(log, target_w: int = 0, target_h: int = 0) -> None:
    client, method = find_riot_client()
    if not client:
        log("  ✗ Riot Client not found.", "err")
        log("  Make sure Valorant is installed and Windows Search has indexed your drives.", "warn")
        return

    log(f"  ✓ Found via {method}", "info")

    if target_w > 0 and target_h > 0:
        log(f"  ⟳  Setting display to {target_w}×{target_h}…", "info")
        msg = set_display_res(target_w, target_h)
        log(f"  {msg}", "ok" if "✓" in msg else "warn")

    log(f"  ⟳  Launching: {client.name} {' '.join(RIOT_LAUNCH_ARGS)}", "info")
    try:
        subprocess.Popen([str(client)] + RIOT_LAUNCH_ARGS, close_fds=True)
        log("  ✅ Valorant launched.", "ok")
    except Exception as ex:
        log(f"  ✗ Launch failed: {ex}", "err")


# ──────────────────────────────────────────────────────────────────────────────
# GUI
# ──────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VALORANT Config Tweaker")
        self.withdraw()
        self.wm_attributes("-toolwindow", False)
        self.geometry("720x980")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._apply_styles()
        self._icon()

        self._config_paths: list[Path] = []
        self._native_res: tuple[int, int] = get_native_display_res() or (1920, 1080)
        self._selected_puuid: str | None = None

        self._build()
        self._scan()

        self.update_idletasks()
        self.deiconify()

    # ── setup ─────────────────────────────────────────────────────────────────

    def _icon(self):
        try:
            img = tk.PhotoImage(width=16, height=16)
            img.put(("#ff4655",), to=(0, 0, 15, 15))
            self.iconphoto(True, img)
        except Exception:
            pass

    def _apply_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=CARD, background=CARD,
                    foreground=TEXT, selectforeground=TEXT,
                    bordercolor=BORDER, arrowcolor=RED, relief="flat")
        s.map("TCombobox",
              fieldbackground=[("readonly", CARD)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", CARD)])
        s.configure("Vertical.TScrollbar",
                    background=CARD, troughcolor=SURFACE,
                    arrowcolor=MUTED, bordercolor=CARD)

    # ── build ─────────────────────────────────────────────────────────────────

    def _build(self):
        nw, nh = self._native_res

        # Header
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(18, 0))
        tk.Label(hdr, text="VALORANT",        font=HEAD_F, bg=BG, fg=RED ).pack(side="left")
        tk.Label(hdr, text=" CONFIG TWEAKER", font=HEAD_F, bg=BG, fg=TEXT).pack(side="left")
        badge_txt = "win32 ✓" if WIN32_AVAILABLE else "win32 ✗  →  pip install pywin32 (optional)"
        tk.Label(hdr, text=badge_txt, font=("Segoe UI", 8), bg=BG,
                 fg=GREEN if WIN32_AVAILABLE else YELLOW).pack(side="right", pady=(10, 0))
        tk.Frame(self, bg=RED, height=2).pack(fill="x", padx=24, pady=(6, 0))

        self.native_lbl_var = tk.StringVar(value=f"Native resolution (monitor max): {nw}×{nh}")

        # Account manager
        self._section_lbl("ACCOUNTS  —  click a row to select  (last played highlighted)", 12)
        acc_outer = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        acc_outer.pack(fill="x", padx=24, pady=(4, 0))

        acc_hdr = tk.Frame(acc_outer, bg=CARD)
        acc_hdr.pack(fill="x", padx=10, pady=(6, 2))
        for txt, w in [("ACCOUNT ID (PUUID)", 28), ("CUSTOM LABEL", 20), ("LAST USED", 10)]:
            tk.Label(acc_hdr, text=txt, font=("Segoe UI Semibold", 7),
                     bg=CARD, fg=MUTED, width=w, anchor="w").pack(side="left")
        tk.Button(acc_hdr, text="📂 Open folder", font=("Segoe UI", 8), bg=CARD, fg=RED,
                  activebackground=SURFACE, activeforeground=RED, bd=0,
                  cursor="hand2", command=self._open_folder).pack(side="right")
        tk.Label(acc_hdr, textvariable=self.native_lbl_var, font=("Segoe UI", 8),
                 bg=CARD, fg=MUTED).pack(side="right", padx=(0, 12))
        tk.Frame(acc_outer, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(0, 2))

        self._acc_canvas = tk.Canvas(acc_outer, bg=CARD, highlightthickness=0, height=120)
        acc_scroll = ttk.Scrollbar(acc_outer, orient="vertical", command=self._acc_canvas.yview)
        self._acc_canvas.configure(yscrollcommand=acc_scroll.set)
        acc_scroll.pack(side="right", fill="y")
        self._acc_canvas.pack(fill="x")

        self._acc_frame = tk.Frame(self._acc_canvas, bg=CARD)
        self._acc_win   = self._acc_canvas.create_window((0, 0), window=self._acc_frame, anchor="nw")
        self._acc_frame.bind("<Configure>",
            lambda e: self._acc_canvas.configure(scrollregion=self._acc_canvas.bbox("all")))
        self._acc_canvas.bind("<Configure>",
            lambda e: self._acc_canvas.itemconfig(self._acc_win, width=e.width))

        btn_bar = tk.Frame(acc_outer, bg=CARD)
        btn_bar.pack(fill="x", padx=10, pady=(4, 6))
        tk.Button(btn_bar, text="↺ Refresh accounts", font=("Segoe UI", 8),
                  bg=CARD, fg=PURPLE, activebackground=SURFACE, activeforeground=PURPLE,
                  bd=0, cursor="hand2", pady=4,
                  command=self._load_accounts).pack(side="right")

        self._acc_label_vars: dict[str, tk.StringVar] = {}
        self._acc_rows:       dict[str, tk.Frame]     = {}

        # Resolution picker
        self._section_lbl("TARGET RESOLUTION", 12)
        res_card = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        res_card.pack(fill="x", padx=24, pady=(4, 0))
        self.res_var = tk.IntVar(value=0)
        self.res_var.trace_add("write", self._on_res_change)

        left  = tk.Frame(res_card, bg=CARD)
        right = tk.Frame(res_card, bg=CARD)
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        presets_no_custom = RESOLUTION_PRESETS[:-1]
        half = (len(presets_no_custom) + 1) // 2
        for i, (label, *_) in enumerate(presets_no_custom):
            col = left if i < half else right
            tk.Radiobutton(col, text=label, variable=self.res_var, value=i,
                           bg=CARD, fg=TEXT, selectcolor=BG,
                           activebackground=CARD, activeforeground=PURPLE,
                           font=UI_F, cursor="hand2",
                           highlightthickness=0).pack(anchor="w", pady=1)

        custom_row = tk.Frame(res_card, bg=CARD)
        custom_row.pack(fill="x", padx=6, pady=(2, 8))
        tk.Radiobutton(custom_row, text="Custom:", variable=self.res_var, value=CUSTOM_INDEX,
                       bg=CARD, fg=TEXT, selectcolor=BG, activebackground=CARD,
                       activeforeground=PURPLE, font=UI_F, cursor="hand2",
                       highlightthickness=0).pack(side="left")

        self.custom_w_var = tk.StringVar(value=str(nw))
        self.custom_w_entry = tk.Entry(
            custom_row, textvariable=self.custom_w_var, width=6, font=MONO_F,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            disabledbackground=CARD, disabledforeground=MUTED, state="disabled")
        self.custom_w_entry.pack(side="left", padx=(6, 0), ipady=3)

        tk.Label(custom_row, text="×", font=MONO_F, bg=CARD, fg=MUTED).pack(side="left", padx=4)

        self.custom_h_var = tk.StringVar(value=str(nh))
        self.custom_h_entry = tk.Entry(
            custom_row, textvariable=self.custom_h_var, width=6, font=MONO_F,
            bg=SURFACE, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            disabledbackground=CARD, disabledforeground=MUTED, state="disabled")
        self.custom_h_entry.pack(side="left", ipady=3)

        tk.Label(custom_row, text="px", font=("Segoe UI", 8),
                 bg=CARD, fg=MUTED).pack(side="left", padx=(8, 0))

        # What gets changed table
        self._section_lbl("WHAT GETS CHANGED", 14)
        diff_card = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        diff_card.pack(fill="x", padx=24, pady=(4, 0))

        hrow = tk.Frame(diff_card, bg=CARD)
        hrow.pack(fill="x", padx=12, pady=(5, 0))
        for txt, w in [("KEY", 38), ("DEFAULT", 12), ("  ", 2), ("TWEAKED", 0)]:
            tk.Label(hrow, text=txt, font=("Segoe UI Semibold", 7),
                     bg=CARD, fg=MUTED, width=w, anchor="w").pack(side="left")
        tk.Frame(diff_card, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(2, 2))

        for key, before, after in [
            ("bShouldLetterbox + bLastConfirmed…",   "True",    "False"),
            ("LastConfirmedFullscreenMode",           "0",       "2"),
            ("PreferredFullscreenMode",               "1",       "2"),
            ("FullscreenMode",                        "absent",  "2  ← inserted"),
            ("ResolutionSizeX/Y + all res fields",    "native",  "← your pick"),
            ("Windows display resolution",            "native",  "← your pick"),
        ]:
            row = tk.Frame(diff_card, bg=CARD)
            row.pack(fill="x", padx=12, pady=1)
            tk.Label(row, text=key,    font=MONO_F, bg=CARD, fg=TEXT,
                     width=38, anchor="w").pack(side="left")
            tk.Label(row, text=before, font=MONO_F, bg=CARD, fg=YELLOW,
                     width=12, anchor="w").pack(side="left")
            tk.Label(row, text="→",   font=MONO_F, bg=CARD, fg=MUTED,
                     width=3).pack(side="left")
            tk.Label(row, text=after,  font=MONO_F, bg=CARD, fg=GREEN,
                     anchor="w").pack(side="left")
        tk.Frame(diff_card, bg=BG).pack(pady=4)

        # Action buttons
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=24, pady=(14, 0))
        for i in range(4):
            btn_row.columnconfigure(i, weight=1)
        self._btn(btn_row, "⚡  APPLY TWEAKS",      RED,       "#c73040", self._apply          ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self._btn(btn_row, "↩  RESET TO DEFAULT",   PURPLE,    "#5a47cc", self._reset          ).grid(row=0, column=1, padx=4,     sticky="ew")
        self._btn(btn_row, "🖥  RESTORE DISPLAY",    YELLOW,    "#cc8a2a", self._restore_display).grid(row=0, column=2, padx=4,     sticky="ew")
        self._btn(btn_row, "▶  LAUNCH VALORANT",    "#1e7a1e", "#145214", self._launch         ).grid(row=0, column=3, padx=(4, 0), sticky="ew")

        # Log
        self._section_lbl("LOG", 12)
        log_wrap = tk.Frame(self, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        log_wrap.pack(fill="both", expand=True, padx=24, pady=(4, 20))
        self.log_box = tk.Text(log_wrap, bg=SURFACE, fg=TEXT, font=MONO_F,
                               insertbackground=TEXT, relief="flat", bd=0,
                               state="disabled", wrap="word")
        sb = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)
        for tag, color in [("ok", GREEN), ("warn", YELLOW), ("err", RED), ("info", PURPLE)]:
            self.log_box.tag_config(tag, foreground=color)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _section_lbl(self, text: str, top: int):
        tk.Label(self, text=text, font=("Segoe UI Semibold", 7),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=24, pady=(top, 0))

    def _btn(self, parent, text, color, hover, cmd):
        b = tk.Button(parent, text=text, font=BTN_F, bg=color, fg="#fff",
                      activebackground=hover, activeforeground="#fff",
                      bd=0, pady=11, cursor="hand2", command=cmd, relief="flat")
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=color))
        return b

    def _log(self, msg: str, tag: str = ""):
        def _write():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n", tag or "")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _write)

    def _on_res_change(self, *_):
        is_custom = self.res_var.get() == CUSTOM_INDEX
        state = "normal" if is_custom else "disabled"
        self.custom_w_entry.configure(state=state)
        self.custom_h_entry.configure(state=state)

    def _update_native_lbl(self):
        nw, nh = self._native_res
        self.native_lbl_var.set(f"Native resolution (monitor max): {nw}×{nh}")

    def _selected(self, silent=False) -> "Path | None":
        if not self._selected_puuid:
            if not silent:
                messagebox.showerror("No Account", "Click an account row to select it first.")
            return None
        # find config path for selected puuid
        for acc in get_all_accounts():
            if acc["puuid"] == self._selected_puuid and acc["config_path"]:
                p = acc["config_path"]
                if p.exists():
                    return p
                if not silent:
                    messagebox.showerror("Not Found", f"Config not found:\n{p}")
                return None
        if not silent:
            messagebox.showerror("Not Found", "No config file for selected account.")
        return None

    def _resolve_target_res(self) -> tuple[int, int] | None:
        idx = self.res_var.get()
        if idx == CUSTOM_INDEX:
            try:
                w = int(self.custom_w_var.get().strip())
                h = int(self.custom_h_var.get().strip())
                if not (320 <= w <= 7680 and 240 <= h <= 4320):
                    raise ValueError
                return (w, h)
            except ValueError:
                messagebox.showerror("Invalid Resolution",
                    "Enter valid integers.\nWidth: 320–7680  Height: 240–4320.")
                return None
        _, w, h = RESOLUTION_PRESETS[idx]
        if w is None:
            w, h = self._native_res
            self._log(f"  ℹ  Native display resolution: {w}×{h}", "info")
        return (w, h)

    def _open_folder(self):
        p = self._selected(silent=True)
        if p:
            subprocess.Popen(["explorer", str(p.parent)], shell=True)
        elif self._selected_puuid:
            messagebox.showerror("Not Found", "No config file for selected account.")
        else:
            messagebox.showinfo("No Selection", "Click an account row to select it first.")

    # ── scan ──────────────────────────────────────────────────────────────────

    def _scan(self):
        configs = get_valorant_configs()
        if configs:
            self._config_paths = configs
            self._log(f"Found {len(configs)} config file(s).", "info")
            for p in configs:
                self._log(f"  → {p}", "info")
        else:
            self._config_paths = []
            self._log("⚠  No Valorant config detected.", "warn")
            self._log("  Expected: %LOCALAPPDATA%\\VALORANT\\Saved\\Config\\<PUUID>\\WindowsClient\\GameUserSettings.ini", "warn")

        nw, nh = self._native_res
        self._log(f"Monitor native resolution: {nw}×{nh}", "info")
        self._load_accounts()

    # ── account list ──────────────────────────────────────────────────────────

    def _load_accounts(self):
        accounts   = get_all_accounts()
        labels     = _load_labels()
        last_puuid = get_last_played_puuid()

        # auto-select last played on first load if nothing selected yet
        if self._selected_puuid is None and last_puuid:
            self._selected_puuid = last_puuid
        elif self._selected_puuid is None and accounts:
            self._selected_puuid = accounts[0]["puuid"]

        for widget in self._acc_frame.winfo_children():
            widget.destroy()
        self._acc_label_vars.clear()
        self._acc_rows.clear()

        if not accounts:
            tk.Label(self._acc_frame, text="No accounts found.",
                     font=UI_F, bg=CARD, fg=MUTED).pack(pady=(8, 2))
            tk.Label(self._acc_frame, text=f"Scanned: {VALORANT_CONFIG_BASE}",
                     font=("Consolas", 7), bg=CARD, fg=MUTED).pack(pady=(0, 8))
            self._log(f"  ⚠  No PUUID folders found under {VALORANT_CONFIG_BASE}", "warn")
            return

        for acc in accounts:
            puuid     = acc["puuid"]
            is_last   = (puuid == last_puuid)
            is_sel    = (puuid == self._selected_puuid)
            row_bg    = "#1e1e2e" if is_last else CARD
            row_fg    = GREEN     if is_last else TEXT
            status    = read_stretch_status(acc.get("config_path"))
            label     = labels.get(puuid, "")

            sel_color = RED if is_sel else (BORDER if is_last else row_bg)
            row = tk.Frame(self._acc_frame, bg=row_bg,
                           highlightbackground=sel_color,
                           highlightthickness=2 if is_sel else 1,
                           cursor="hand2")
            row.pack(fill="x", padx=4, pady=2)
            self._acc_rows[puuid] = row

            # left accent bar — red if selected, green if last-played, else plain
            accent_color = RED if is_sel else (GREEN if is_last else row_bg)
            tk.Frame(row, bg=accent_color, width=4).pack(side="left", fill="y")

            inner = tk.Frame(row, bg=row_bg, cursor="hand2")
            inner.pack(side="left", fill="x", expand=True, padx=(6, 6), pady=4)

            # ── click anywhere on row to select ──────────────────────────────
            def _make_select(p=puuid):
                def _select(event=None):
                    self._selected_puuid = p
                    self._log(f"  ● Selected account: {p[:8]}…", "info")
                    self.after(0, self._load_accounts)
                return _select
            select_fn = _make_select()
            for widget in (row, inner):
                widget.bind("<Button-1>", select_fn)

            # Row 1: PUUID / label  +  SELECTED badge  +  LAST PLAYED badge  +  timestamp
            id_row = tk.Frame(inner, bg=row_bg, cursor="hand2")
            id_row.pack(fill="x")
            id_row.bind("<Button-1>", select_fn)

            if label:
                l1 = tk.Label(id_row, text=label, font=("Segoe UI Semibold", 10),
                         bg=row_bg, fg=row_fg, anchor="w", cursor="hand2")
                l1.pack(side="left")
                l1.bind("<Button-1>", select_fn)
                l2 = tk.Label(id_row, text=f"  {puuid}", font=MONO_F,
                         bg=row_bg, fg=MUTED, anchor="w", cursor="hand2")
                l2.pack(side="left")
                l2.bind("<Button-1>", select_fn)
            else:
                l1 = tk.Label(id_row, text=puuid, font=MONO_F,
                         bg=row_bg, fg=row_fg, anchor="w", cursor="hand2")
                l1.pack(side="left")
                l1.bind("<Button-1>", select_fn)

            if is_sel:
                tk.Label(id_row, text="● SELECTED", font=("Segoe UI Semibold", 7),
                         bg=row_bg, fg=RED).pack(side="left", padx=(6, 0))
            if is_last:
                tk.Label(id_row, text="● LAST PLAYED", font=("Segoe UI Semibold", 7),
                         bg=row_bg, fg=GREEN).pack(side="left", padx=(6, 0))

            mtime = time.strftime("%Y-%m-%d  %H:%M", time.localtime(acc["last_modified"]))
            tk.Label(id_row, text=mtime, font=("Segoe UI", 8),
                     bg=row_bg, fg=MUTED).pack(side="right", padx=6)

            # Row 2: stretch pill  +  resolution  +  tweaked badge
            st_row = tk.Frame(inner, bg=row_bg, cursor="hand2")
            st_row.pack(fill="x", pady=(2, 0))
            st_row.bind("<Button-1>", select_fn)

            if status["stretched"]:
                pill_bg, pill_fg, pill_txt = GREEN,  "#000", "✔ STRETCHED"
            else:
                pill_bg, pill_fg, pill_txt = BORDER, MUTED, "✘ NOT STRETCHED"

            tk.Label(st_row, text=pill_txt, font=("Segoe UI Semibold", 7),
                     bg=pill_bg, fg=pill_fg, padx=5, pady=1).pack(side="left")
            tk.Label(st_row, text=status["res"], font=MONO_F,
                     bg=row_bg, fg=MUTED).pack(side="left", padx=(6, 0))

            if status["tweaked"]:
                tk.Label(st_row, text="TWEAKED", font=("Segoe UI Semibold", 7),
                         bg="#2a1a00", fg=YELLOW, padx=5, pady=1).pack(side="left", padx=(6, 0))

            # Row 3: label entry  +  save  +  copy ID
            lbl_row = tk.Frame(inner, bg=row_bg)
            lbl_row.pack(fill="x", pady=(3, 0))

            tk.Label(lbl_row, text="Label:", font=("Segoe UI", 8),
                     bg=row_bg, fg=MUTED).pack(side="left")

            var = tk.StringVar(value=label)
            self._acc_label_vars[puuid] = var

            entry = tk.Entry(lbl_row, textvariable=var, font=("Segoe UI", 9),
                             bg=SURFACE, fg=TEXT, insertbackground=TEXT,
                             relief="flat", highlightbackground=BORDER,
                             highlightthickness=1, width=28)
            entry.pack(side="left", padx=(4, 6), ipady=2)

            def _make_save(p=puuid, v=var):
                btn_holder = [None]

                def _save(event=None):
                    val = v.get().strip()
                    lbs = _load_labels()
                    if val:
                        lbs[p] = val
                    else:
                        lbs.pop(p, None)
                    ok  = _save_labels(lbs)
                    btn = btn_holder[0]
                    if btn:
                        btn.configure(text="✓" if ok else "✗",
                                      bg=GREEN if ok else RED)
                        btn.after(1200, lambda: btn.configure(text="Save", bg=PURPLE))
                    self._log(
                        f"  {'✓' if ok else '✗'} Label {'saved' if ok else 'FAILED'}: "
                        f"{p[:8]}… → \"{val}\"",
                        "ok" if ok else "err"
                    )
                    if ok:
                        self.after(100, self._load_accounts)

                return _save, btn_holder

            save_fn, btn_holder = _make_save()
            entry.bind("<Return>",   save_fn)
            entry.bind("<FocusOut>", save_fn)

            save_btn = tk.Button(lbl_row, text="Save", font=("Segoe UI", 8),
                                 bg=PURPLE, fg="#fff", activebackground="#5a47cc",
                                 activeforeground="#fff", bd=0, padx=8, pady=2,
                                 cursor="hand2", command=save_fn)
            save_btn.pack(side="left")
            btn_holder[0] = save_btn

            def _make_copy(p=puuid):
                def _copy():
                    self.clipboard_clear()
                    self.clipboard_append(p)
                    self._log(f"  Copied PUUID: {p}", "info")
                return _copy

            tk.Button(lbl_row, text="📋 Copy ID", font=("Segoe UI", 8),
                      bg=CARD, fg=MUTED, activebackground=SURFACE,
                      activeforeground=TEXT, bd=0, padx=6, pady=2,
                      cursor="hand2", command=_make_copy()).pack(side="left", padx=(4, 0))

    # ── actions ───────────────────────────────────────────────────────────────

    def _apply(self):
        p = self._selected()
        if not p:
            return
        res = self._resolve_target_res()
        if res is None:
            return
        tw, th = res
        label = ("Custom" if self.res_var.get() == CUSTOM_INDEX
                 else RESOLUTION_PRESETS[self.res_var.get()][0])
        self._log("\n── APPLYING TWEAKS ─────────────────────────────", "info")
        self._log(f"  Target: {label}  →  {tw}×{th}", "info")

        def _work():
            try:
                apply_tweaks(p, tw, th, self._log)
            except Exception as ex:
                self._log(f"  ✗ Error: {ex}", "err")
            self.after(0, self._load_accounts)

        threading.Thread(target=_work, daemon=True).start()

    def _reset(self):
        p = self._selected()
        if not p:
            return
        nw, nh = self._native_res
        if not messagebox.askyesno(
                "Reset Config",
                f"Reset config to defaults?\n\n"
                f"All tweaks will be undone.\n"
                f"Display will return to native {nw}×{nh}."):
            return
        self._log("\n── RESETTING TO DEFAULT ────────────────────────", "info")

        def _work():
            try:
                reset_config(p, self._log)
            except Exception as ex:
                self._log(f"  ✗ Error: {ex}", "err")
            self.after(0, self._load_accounts)

        threading.Thread(target=_work, daemon=True).start()

    def _launch(self):
        self._log("\n── LAUNCHING VALORANT ──────────────────────────", "info")
        res = self._resolve_target_res()
        tw, th = res if res else (0, 0)
        threading.Thread(
            target=lambda: launch_valorant(self._log, tw, th),
            daemon=True
        ).start()

    def _restore_display(self):
        self._log("\n── RESTORING DISPLAY RESOLUTION ─────────────────", "info")
        self._log("  ℹ  No config files will be changed.", "info")
        threading.Thread(
            target=lambda: restore_native_display_res(self._log),
            daemon=True
        ).start()


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()
