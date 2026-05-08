"""
Valorant Config Tweaker
────────────────────────────────────────────────────────────────────────────────
• Reads existing GameUserSettings.ini to detect the user's native resolution —
  no hardcoded assumptions about anyone's monitor.
• Applies all tweaks relative to what is actually in the file.
• Supports preset resolutions AND a fully custom W×H input.
• Uses win32api / win32con (pywin32) to change the Windows display resolution
  before launching Valorant, and restores it on reset.
• Launches Valorant through the Riot Client via subprocess.

Requirements:
    pip install pywin32

Run:
    python valorant_config_tweaker.py
────────────────────────────────────────────────────────────────────────────────
"""

import tkinter as tk
from tkinter import ttk, messagebox
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

# ── optional win32 ────────────────────────────────────────────────────────────
try:
    import win32api
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False

# ── optional ctypes (always present on Windows, used as win32 fallback) ───────
try:
    import ctypes
    CTYPES_AVAILABLE = True
except ImportError:
    CTYPES_AVAILABLE = False

# ──────────────────────────────────────────────────────────────────────────────
# RESOLUTION PRESETS  — (label, w, h)
# index 0  = auto-detect native from config
# last entry = sentinel for "Custom" — w/h come from the text fields
# ──────────────────────────────────────────────────────────────────────────────
CUSTOM_INDEX = -1   # assigned after list is built

RESOLUTION_PRESETS = [
    ("Native  (from display)",        None,  None),
    ("1024×768   4:3 stretched",     1024,   768),
    ("1280×960   4:3 stretched",     1280,   960),
    ("1280×1024  5:4 stretched",     1280,  1024),
    ("1440×1080  4:3 stretched HD",  1440,  1080),
    ("1600×900   16:9",              1600,   900),
    ("1366×768   HD",                1366,   768),
    ("1920×1080  16:9 FHD",          1920,  1080),
    ("2560×1440  16:9 QHD",          2560,  1440),
    ("Custom…",                      None,  None),   # must be last
]

CUSTOM_INDEX   = len(RESOLUTION_PRESETS) - 1
BACKUP_SUFFIX  = ".valorantbak"
SHOOTER_SECTION = "[/Script/ShooterGame.ShooterGameUserSettings]"


# ──────────────────────────────────────────────────────────────────────────────
# WIN32 DISPLAY HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def get_current_display_res() -> tuple[int, int]:
    """
    Returns the primary monitor's native resolution.
    Tries win32api first, then ctypes (no extra install needed), then (0,0).
    GetSystemMetrics(0/1) returns the primary monitor dimensions (SM_CXSCREEN /
    SM_CYSCREEN). SetProcessDPIAware ensures physical pixels on HiDPI displays.
    """
    if WIN32_AVAILABLE:
        try:
            dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
            return (dm.PelsWidth, dm.PelsHeight)
        except Exception:
            pass
    if CTYPES_AVAILABLE:
        try:
            user32 = ctypes.windll.user32          # type: ignore[attr-defined]
            user32.SetProcessDPIAware()
            w = user32.GetSystemMetrics(0)         # SM_CXSCREEN
            h = user32.GetSystemMetrics(1)         # SM_CYSCREEN
            if w > 0 and h > 0:
                return (w, h)
        except Exception:
            pass
    return (0, 0)


def set_display_res(w: int, h: int) -> str:
    if not WIN32_AVAILABLE:
        return "win32api not available — display resolution unchanged."
    dm = win32api.EnumDisplaySettings(None, win32con.ENUM_CURRENT_SETTINGS)
    if dm.PelsWidth == w and dm.PelsHeight == h:
        return f"Display already at {w}×{h}, no change needed."
    dm.PelsWidth  = w
    dm.PelsHeight = h
    dm.Fields     = win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT
    result = win32api.ChangeDisplaySettings(dm, 0)
    codes  = {0: f"✓ Display changed to {w}×{h}.",
              1: f"✓ Display changed to {w}×{h} (restart required).",
              3: f"✓ Display changed to {w}×{h}."}
    errors = {-1: "✗ Invalid mode.", -2: "✗ Not supported.",
              -3: "✗ Bad flags.",    -4: "✗ Bad parameters.",
              -5: "✗ Bad dual view."}
    return codes.get(result, errors.get(result, f"Display change returned code {result}."))


# ──────────────────────────────────────────────────────────────────────────────
# INI HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def find_valorant_configs() -> list[Path]:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Config"
    if not base.exists():
        return []
    return list(base.rglob("GameUserSettings.ini"))


def read_ini_key(content: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}\s*=\s*(.*)$", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_native_resolution(path: Path) -> tuple[int, int]:
    """
    Return the user's true native (hardware) resolution.

    Priority order:
      1. Current Windows display resolution via win32api / ctypes  ← always
         reflects the physical monitor, not whatever Valorant last wrote.
      2. Value stored in the backup INI (original pre-tweak config), used only
         when the display query fails (headless / remote-desktop scenarios).
      3. Value stored in the live config file.
      4. 1920×1080 as a last resort.
    """
    # 1. Ask the OS — most reliable source for *actual* native resolution
    cur = get_current_display_res()
    if cur != (0, 0):
        return cur

    # 2/3. Fall back to the INI files (backup preferred over live config)
    backup = Path(str(path) + BACKUP_SUFFIX)
    for src in (backup, path):
        if not src.exists():
            continue
        try:
            content = src.read_text(encoding="utf-8", errors="replace")
            w = read_ini_key(content, "ResolutionSizeX")
            h = read_ini_key(content, "ResolutionSizeY")
            if w and h:
                return (int(w), int(h))
        except Exception:
            pass

    return (1920, 1080)


def _replace_key(content: str, key: str, value: str) -> tuple[str, int]:
    pattern = re.compile(rf"^({re.escape(key)}\s*=).*$", re.MULTILINE)
    return pattern.subn(rf"\g<1>{value}", content)


def _insert_before_next_section(content: str, after_section: str,
                                 key: str, value: str) -> str:
    sec_m = re.search(re.escape(after_section), content)
    if not sec_m:
        return content + f"\n{after_section}\n{key}={value}\n"
    rest   = content[sec_m.end():]
    next_m = re.search(r"^\[", rest, re.MULTILINE)
    ins    = sec_m.end() + (next_m.start() if next_m else len(rest))
    return content[:ins] + f"{key}={value}\n" + content[ins:]


# ──────────────────────────────────────────────────────────────────────────────
# LAST PLAYED ACCOUNT DETECTION
# ──────────────────────────────────────────────────────────────────────────────
# RiotLocalMachine.ini lives at:
#   %LOCALAPPDATA%\VALORANT\Saved\Config\WindowsClient\RiotLocalMachine.ini
# It stores the Riot Client's local machine state, including the last logged-in
# account.  The known key names (Riot has renamed them across versions) are
# tried in order so the feature keeps working across game updates.

RIOT_LOCAL_MACHINE_INI = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "VALORANT" / "Saved" / "Config" / "WindowsClient" / "RiotLocalMachine.ini"
)

# Candidate key names for the display name / Riot ID components.
# Riot has used several names across client versions — we try all of them.
_GAMENAME_KEYS = ["GameName", "game_name", "Subject_GameName",
                  "LastGameName", "riot_id_game_name"]
_TAGLINE_KEYS  = ["TagLine",  "tag_line",  "Subject_TagLine",
                  "LastTagLine", "riot_id_tagline"]
# PUUID — used as a fallback identifier when display name keys are absent
_PUUID_KEYS    = ["Subject", "puuid", "PUUID", "LastSubject"]
# Login username (Riot login, not display name) — last-resort label
_LOGIN_KEYS    = ["Username", "username", "last_username", "RiotUsername"]


def _try_keys(content: str, keys: list[str]) -> str | None:
    """Return the value of the first key found in content, or None."""
    for key in keys:
        val = read_ini_key(content, key)
        if val and val.strip() not in ("", "None", "null"):
            return val.strip()
    return None


def get_last_played_account() -> dict:
    """
    Parse RiotLocalMachine.ini and return a dict with whatever account info
    can be found.  Keys present in the result:
      - 'game_name'  : display name  (e.g. "Reyna")
      - 'tagline'    : tagline        (e.g. "EUW")   — may be absent
      - 'puuid'      : PUUID string   — may be absent
      - 'login'      : Riot login name — may be absent
      - 'source'     : path that was read
      - 'error'      : set only when something went wrong
    Also checks the per-account GUID profile folders as a secondary source.
    """
    result: dict = {}

    # ── Primary: RiotLocalMachine.ini ────────────────────────────────────────
    ini = RIOT_LOCAL_MACHINE_INI
    if ini.exists():
        try:
            content = ini.read_text(encoding="utf-8", errors="replace")
            result["source"] = str(ini)
            gn = _try_keys(content, _GAMENAME_KEYS)
            tl = _try_keys(content, _TAGLINE_KEYS)
            pu = _try_keys(content, _PUUID_KEYS)
            lo = _try_keys(content, _LOGIN_KEYS)
            if gn: result["game_name"] = gn
            if tl: result["tagline"]   = tl
            if pu: result["puuid"]     = pu
            if lo: result["login"]     = lo
        except Exception as ex:
            result["error"] = str(ex)
    else:
        result["error"] = f"File not found: {ini}"

    # ── Secondary: derive display name from GUID folder name ─────────────────
    # Each account gets its own GUID subfolder under Config.  The most-recently
    # modified one corresponds to the last-played account.  The folder name is
    # the PUUID, so if we already have it we can cross-reference; otherwise we
    # at least surface the PUUID as a fallback identifier.
    if not result.get("game_name"):
        config_base = Path(os.environ.get("LOCALAPPDATA", "")) / "VALORANT" / "Saved" / "Config"
        guid_dirs = sorted(
            [d for d in config_base.iterdir()
             if d.is_dir() and re.fullmatch(r"[0-9a-f\-]{36}", d.name)],
            key=lambda d: d.stat().st_mtime,
            reverse=True
        ) if config_base.exists() else []
        if guid_dirs:
            latest = guid_dirs[0]
            if not result.get("puuid"):
                result["puuid"] = latest.name
            result.setdefault("source", str(latest))
            # Try reading a GameUserSettings inside this folder for any name hint
            gus = latest / "Windows" / "GameUserSettings.ini"
            if not gus.exists():
                gus_candidates = list(latest.rglob("GameUserSettings.ini"))
                gus = gus_candidates[0] if gus_candidates else None
            if gus and gus.exists():
                try:
                    content2 = gus.read_text(encoding="utf-8", errors="replace")
                    for key in _GAMENAME_KEYS + ["PlayerName", "SavedAccountName"]:
                        val = read_ini_key(content2, key)
                        if val and val.strip() not in ("", "None", "null"):
                            result["game_name"] = val.strip()
                            break
                except Exception:
                    pass

    return result


def format_last_account(info: dict) -> str:
    """Turn the result of get_last_played_account() into a one-line string."""
    if "error" in info and not any(k in info for k in ("game_name", "puuid", "login")):
        return f"⚠  {info['error']}"
    if info.get("game_name"):
        name = info["game_name"]
        if info.get("tagline"):
            name += f"#{info['tagline']}"
        return name
    if info.get("login"):
        return info["login"]
    if info.get("puuid"):
        # Show only first 8 chars of PUUID to keep the label tidy
        return f"PUUID: {info['puuid'][:8]}…"
    return "Unknown"


# ──────────────────────────────────────────────────────────────────────────────
# APPLY / RESET LOGIC
# ──────────────────────────────────────────────────────────────────────────────
def apply_tweaks(path: Path, target_w: int, target_h: int, log):
    content = path.read_text(encoding="utf-8", errors="replace")

    # Report what we found in the file
    orig_w  = read_ini_key(content, "ResolutionSizeX") or "?"
    orig_h  = read_ini_key(content, "ResolutionSizeY") or "?"
    orig_fs = read_ini_key(content, "LastConfirmedFullscreenMode") or "?"
    orig_lb = read_ini_key(content, "bShouldLetterbox") or "?"
    log(f"  ℹ  Found in file → resolution: {orig_w}×{orig_h}  "
        f"FullscreenMode: {orig_fs}  Letterbox: {orig_lb}", "info")

    # Backup
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

    # FullscreenMode may be absent in a fresh/default config
    content, n = _replace_key(content, "FullscreenMode", "2")
    if n:
        log("  ✓ FullscreenMode = 2  (updated)", "ok")
    else:
        content = _insert_before_next_section(
            content, SHOOTER_SECTION, "FullscreenMode", "2")
        log("  ✓ FullscreenMode = 2  (inserted — was absent)", "ok")

    path.write_text(content, encoding="utf-8")
    log("  ✅ Config written.", "ok")

    log(f"  ⟳  Changing display to {target_w}×{target_h}…", "info")
    msg = set_display_res(target_w, target_h)
    log(f"  {msg}", "ok" if "✓" in msg else "warn")


def reset_config(path: Path, log):
    backup = Path(str(path) + BACKUP_SUFFIX)
    if not backup.exists():
        log("  ⚠  No backup found. Apply tweaks first to create one.", "warn")
        return

    native_w, native_h = parse_native_resolution(path)
    shutil.copy2(backup, path)
    log(f"  ✅ Config restored from backup: {backup.name}", "ok")

    log(f"  ⟳  Restoring display to {native_w}×{native_h}…", "info")
    msg = set_display_res(native_w, native_h)
    log(f"  {msg}", "ok" if "✓" in msg else "warn")


# ──────────────────────────────────────────────────────────────────────────────
# RIOT CLIENT LAUNCHER
# ──────────────────────────────────────────────────────────────────────────────
RIOT_CLIENT_PATHS = [
    Path(r"C:\Riot Games\Riot Client\RiotClientServices.exe"),
    Path(os.environ.get("PROGRAMFILES",      r"C:\Program Files"))
        / "Riot Games" / "Riot Client" / "RiotClientServices.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Riot Games" / "Riot Client" / "RiotClientServices.exe",
]
RIOT_LAUNCH_ARGS = ["--launch-product=valorant", "--launch-patchline=live"]


def find_riot_client() -> Path | None:
    for p in RIOT_CLIENT_PATHS:
        if p.exists():
            return p
    try:
        r = subprocess.run(["where", "RiotClientServices.exe"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            p = Path(r.stdout.strip().splitlines()[0])
            if p.exists():
                return p
    except Exception:
        pass
    return None


def launch_valorant(log):
    client = find_riot_client()
    if not client:
        log("  ✗ Riot Client not found. Is Valorant installed?", "err")
        log("    Checked: C:\\Riot Games\\Riot Client\\RiotClientServices.exe", "warn")
        return
    log(f"  ⟳  {client.name} {' '.join(RIOT_LAUNCH_ARGS)}", "info")
    try:
        subprocess.Popen([str(client)] + RIOT_LAUNCH_ARGS, close_fds=True)
        log("  ✅ Valorant launch command sent.", "ok")
    except Exception as ex:
        log(f"  ✗ Launch failed: {ex}", "err")


# ──────────────────────────────────────────────────────────────────────────────
# GUI CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
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
# GUI
# ──────────────────────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VALORANT Config Tweaker")

        # ── Title-bar / decoration fix for Intel iGPU and software-rendered ──
        # Some systems (Intel HD/UHD, no dedicated GPU, RDP sessions) lose the
        # native window decorations when heavy theming is applied before the
        # window manager has finished compositing the frame.  The fixes below
        # keep the standard OS title bar visible on all configurations:
        #  • withdraw() / deiconify() defers decoration until Tk is ready.
        #  • wm_attributes("-toolwindow", False) explicitly re-enables the full
        #    caption bar (prevents the no-title-bar "tool window" style).
        #  • update_idletasks() flushes pending geometry before we show the
        #    window, so the WM sees the correct size and style flags together.
        self.withdraw()                           # hide until fully built
        self.wm_attributes("-toolwindow", False)  # ensure full caption bar

        self.geometry("720x820")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._icon()
        self._apply_styles()
        self.configs: list[Path] = []

        # Detect native display resolution before building the UI so the
        # resolution picker can default to "Native" with the real dimensions.
        native = get_current_display_res()
        self._native_display_res: tuple[int, int] = native if native != (0, 0) else (1920, 1080)

        self._build()
        self._scan()

        self.update_idletasks()                   # flush geometry/style
        self.deiconify()                          # now show with title bar

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
        s.configure("TCombobox",
                    fieldbackground=CARD, background=CARD,
                    foreground=TEXT, selectbackground=CARD,
                    selectforeground=TEXT, bordercolor=BORDER,
                    arrowcolor=RED, relief="flat")
        s.map("TCombobox",
              fieldbackground=[("readonly", CARD)],
              foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", CARD)])
        s.configure("Vertical.TScrollbar",
                    background=CARD, troughcolor=SURFACE,
                    arrowcolor=MUTED, bordercolor=CARD)

    # ── main build ────────────────────────────────────────────────────────────
    def _build(self):
        # ── Header ───────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(18, 0))
        tk.Label(hdr, text="VALORANT",        font=HEAD_F, bg=BG, fg=RED ).pack(side="left")
        tk.Label(hdr, text=" CONFIG TWEAKER", font=HEAD_F, bg=BG, fg=TEXT).pack(side="left")
        tk.Label(hdr, text="", font=("Segoe UI", 8), bg=BG,
                 fg=MUTED).pack(side="left", padx=(6,0), pady=(10,0))
        badge_txt = "win32 ✓" if WIN32_AVAILABLE else "win32 ✗  →  pip install pywin32"
        tk.Label(hdr, text=badge_txt, font=("Segoe UI", 8), bg=BG,
                 fg=GREEN if WIN32_AVAILABLE else YELLOW).pack(side="right", pady=(10,0))
        tk.Frame(self, bg=RED, height=2).pack(fill="x", padx=24, pady=(6,0))

        # ── Config file ───────────────────────────────────────────────────────
        self._lbl("CONFIG FILE", 12)
        cf = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        cf.pack(fill="x", padx=24, pady=(4,0))
        self.cfg_var = tk.StringVar(value="Scanning…")
        self.cfg_combo = ttk.Combobox(cf, textvariable=self.cfg_var,
                                      state="readonly", font=MONO_F)
        self.cfg_combo.pack(side="left", fill="x", expand=True, padx=8, pady=7)
        self.cfg_combo.bind("<<ComboboxSelected>>", lambda _: self._refresh_native_label())
        tk.Button(cf, text="📂 Open", font=UI_F, bg=CARD, fg=RED,
                  activebackground=SURFACE, activeforeground=RED, bd=0,
                  cursor="hand2", command=self._open_folder).pack(side="right", padx=8)

        self.native_lbl_var = tk.StringVar(value="Native resolution: —")
        tk.Label(self, textvariable=self.native_lbl_var, font=("Segoe UI", 8),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=28, pady=(3,0))

        # ── Resolution picker ─────────────────────────────────────────────────
        self._lbl("TARGET RESOLUTION  (applied to config + Windows display)", 12)
        res_card = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        res_card.pack(fill="x", padx=24, pady=(4,0))
        self.res_var = tk.IntVar(value=0)
        self.res_var.trace_add("write", self._on_res_change)

        # Pre-populate custom fields with the real native display resolution so
        # the user always sees actual hardware dimensions, not config-file values.
        _nw, _nh = self._native_display_res

        left  = tk.Frame(res_card, bg=CARD)
        right = tk.Frame(res_card, bg=CARD)
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        # All presets except the last (Custom) split across two columns
        presets_except_custom = RESOLUTION_PRESETS[:-1]
        half = (len(presets_except_custom) + 1) // 2
        for i, (label, *_) in enumerate(presets_except_custom):
            col = left if i < half else right
            tk.Radiobutton(col, text=label, variable=self.res_var, value=i,
                           bg=CARD, fg=TEXT, selectcolor=BG,
                           activebackground=CARD, activeforeground=PURPLE,
                           font=UI_F, cursor="hand2",
                           highlightthickness=0).pack(anchor="w", pady=1)

        # ── Custom resolution row ─────────────────────────────────────────────
        custom_row = tk.Frame(res_card, bg=CARD)
        custom_row.pack(fill="x", padx=6, pady=(2, 8))

        self.custom_rb = tk.Radiobutton(
            custom_row, text="Custom:", variable=self.res_var,
            value=CUSTOM_INDEX, bg=CARD, fg=TEXT, selectcolor=BG,
            activebackground=CARD, activeforeground=PURPLE,
            font=UI_F, cursor="hand2", highlightthickness=0)
        self.custom_rb.pack(side="left")

        # Width entry
        self.custom_w_var = tk.StringVar(value=str(_nw))
        self.custom_w_entry = tk.Entry(
            custom_row, textvariable=self.custom_w_var,
            width=6, font=MONO_F, bg=SURFACE, fg=TEXT,
            insertbackground=TEXT, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            disabledbackground=CARD, disabledforeground=MUTED, state="disabled")
        self.custom_w_entry.pack(side="left", padx=(6, 0), ipady=3)

        tk.Label(custom_row, text="×", font=MONO_F,
                 bg=CARD, fg=MUTED).pack(side="left", padx=4)

        # Height entry
        self.custom_h_var = tk.StringVar(value=str(_nh))
        self.custom_h_entry = tk.Entry(
            custom_row, textvariable=self.custom_h_var,
            width=6, font=MONO_F, bg=SURFACE, fg=TEXT,
            insertbackground=TEXT, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
            disabledbackground=CARD, disabledforeground=MUTED, state="disabled")
        self.custom_h_entry.pack(side="left", ipady=3)

        tk.Label(custom_row, text="px  (e.g. 1176×664 for 4:3 on 1366×768)",
                 font=("Segoe UI", 8), bg=CARD, fg=MUTED).pack(side="left", padx=(8,0))

        # ── Changes summary ───────────────────────────────────────────────────
        self._lbl("WHAT GETS CHANGED", 14)
        diff_card = tk.Frame(self, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        diff_card.pack(fill="x", padx=24, pady=(4,0))

        hrow = tk.Frame(diff_card, bg=CARD)
        hrow.pack(fill="x", padx=12, pady=(5,0))
        for txt, w in [("KEY", 38), ("DEFAULT", 12), ("  ", 2), ("TWEAKED", 0)]:
            tk.Label(hrow, text=txt, font=("Segoe UI Semibold", 7),
                     bg=CARD, fg=MUTED, width=w, anchor="w").pack(side="left")
        tk.Frame(diff_card, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(2,2))

        for key, before, after in [
            ("bShouldLetterbox + bLastConfirmed…",   "True",    "False"),
            ("LastConfirmedFullscreenMode",           "0",       "2"),
            ("PreferredFullscreenMode",               "0",       "2"),
            ("FullscreenMode",                        "absent",  "2  ← added"),
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

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=24, pady=(14,0))
        for i in range(3):
            btn_row.columnconfigure(i, weight=1)

        self._btn(btn_row, "⚡  APPLY TWEAKS",
                  RED,       "#c73040", self._apply ).grid(row=0, column=0, padx=(0,4), sticky="ew")
        self._btn(btn_row, "↩  RESET TO DEFAULT",
                  PURPLE,    "#5a47cc", self._reset ).grid(row=0, column=1, padx=4,    sticky="ew")
        self._btn(btn_row, "▶  LAUNCH VALORANT",
                  "#1e7a1e", "#145214", self._launch).grid(row=0, column=2, padx=(4,0), sticky="ew")

        # ── Log ───────────────────────────────────────────────────────────────
        self._lbl("LOG", 12)
        log_wrap = tk.Frame(self, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        log_wrap.pack(fill="both", expand=True, padx=24, pady=(4,20))
        self.log_box = tk.Text(log_wrap, bg=SURFACE, fg=TEXT, font=MONO_F,
                               insertbackground=TEXT, relief="flat", bd=0,
                               state="disabled", wrap="word")
        sb = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_box.tag_config("ok",   foreground=GREEN)
        self.log_box.tag_config("warn", foreground=YELLOW)
        self.log_box.tag_config("err",  foreground=RED)
        self.log_box.tag_config("info", foreground=PURPLE)

    # ── widget helpers ────────────────────────────────────────────────────────
    def _lbl(self, text: str, top: int):
        tk.Label(self, text=text, font=("Segoe UI Semibold", 7),
                 bg=BG, fg=MUTED).pack(anchor="w", padx=24, pady=(top,0))

    def _btn(self, parent, text, color, hover, cmd):
        b = tk.Button(parent, text=text, font=BTN_F, bg=color, fg="#fff",
                      activebackground=hover, activeforeground="#fff",
                      bd=0, pady=11, cursor="hand2", command=cmd, relief="flat")
        b.bind("<Enter>", lambda e: b.configure(bg=hover))
        b.bind("<Leave>", lambda e: b.configure(bg=color))
        return b

    # ── custom resolution toggle ──────────────────────────────────────────────
    def _on_res_change(self, *_):
        is_custom = self.res_var.get() == CUSTOM_INDEX
        state = "normal" if is_custom else "disabled"
        self.custom_w_entry.configure(state=state)
        self.custom_h_entry.configure(state=state)

    # ── thread-safe log ───────────────────────────────────────────────────────
    def _log(self, msg: str, tag: str = ""):
        def _write():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n", tag or "")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _write)

    # ── scan ──────────────────────────────────────────────────────────────────
    def _scan(self):
        self.configs = find_valorant_configs()
        if self.configs:
            paths = [str(p) for p in self.configs]
            self.cfg_combo["values"] = paths
            self.cfg_var.set(paths[0])
            self._log(f"Found {len(self.configs)} config file(s).", "info")
            for p in paths:
                self._log(f"  → {p}", "info")
            self._refresh_native_label()
        else:
            self.cfg_var.set("No Valorant config found")
            self._log("⚠  Valorant config not detected. Is the game installed?", "warn")
            self._log("  Expected: %LOCALAPPDATA%\\VALORANT\\Saved\\Config\\…\\GameUserSettings.ini", "warn")

        if WIN32_AVAILABLE or CTYPES_AVAILABLE:
            cw, ch = self._native_display_res
            self._log(f"Native display resolution: {cw}×{ch}", "info")
        else:
            self._log("⚠  pywin32 not installed — display changes disabled.", "warn")
            self._log("   pip install pywin32", "warn")

    def _refresh_native_label(self):
        # Always show the true hardware resolution queried from the OS.
        nw, nh = self._native_display_res
        self.native_lbl_var.set(f"Native resolution (from display): {nw}×{nh}")

    # ── path selection ────────────────────────────────────────────────────────
    def _selected(self, silent=False) -> "Path | None":
        v = self.cfg_var.get()
        if not v or "No Valorant" in v or "Scanning" in v:
            if not silent:
                messagebox.showerror("No Config", "No config file selected.")
            return None
        p = Path(v)
        if not p.exists():
            if not silent:
                messagebox.showerror("Not Found", f"File not found:\n{p}")
            return None
        return p

    def _resolve_target_res(self, path: Path) -> tuple[int, int] | None:
        """
        Returns (w, h) based on the current radio selection.
        Returns None if Custom is selected but the values are invalid.
        """
        idx = self.res_var.get()

        if idx == CUSTOM_INDEX:
            try:
                w = int(self.custom_w_var.get().strip())
                h = int(self.custom_h_var.get().strip())
                if w < 320 or h < 240 or w > 7680 or h > 4320:
                    raise ValueError("out of range")
                return (w, h)
            except ValueError:
                messagebox.showerror(
                    "Invalid Resolution",
                    "Please enter valid integers for the custom resolution.\n"
                    "Width must be 320–7680, Height 240–4320.")
                return None

        _, w, h = RESOLUTION_PRESETS[idx]
        if w is None:   # Native auto-detect — use OS display resolution
            w, h = self._native_display_res
            self._log(f"  ℹ  Native display resolution: {w}×{h}", "info")
        return (w, h)

    def _open_folder(self):
        p = self._selected()
        if p:
            subprocess.Popen(["explorer", str(p.parent)], shell=True)

    # ── actions ───────────────────────────────────────────────────────────────
    def _apply(self):
        p = self._selected()
        if not p:
            return
        res = self._resolve_target_res(p)
        if res is None:
            return
        tw, th = res
        self._log("\n── APPLYING TWEAKS ─────────────────────────────", "info")
        label = "Custom" if self.res_var.get() == CUSTOM_INDEX \
                else RESOLUTION_PRESETS[self.res_var.get()][0]
        self._log(f"  Target: {label}  →  {tw}×{th}", "info")

        def _work():
            try:
                apply_tweaks(p, tw, th, self._log)
                self.after(0, self._refresh_native_label)
            except Exception as ex:
                self._log(f"  ✗ Error: {ex}", "err")

        threading.Thread(target=_work, daemon=True).start()

    def _reset(self):
        p = self._selected()
        if not p:
            return
        nw, nh = self._native_display_res
        if not messagebox.askyesno("Reset Config",
                f"Restore original config from backup?\n\n"
                f"Display will return to {nw}×{nh}.\n"
                "All tweaks will be undone."):
            return
        self._log("\n── RESETTING TO DEFAULT ────────────────────────", "info")

        def _work():
            try:
                reset_config(p, self._log)
                self.after(0, self._refresh_native_label)
            except Exception as ex:
                self._log(f"  ✗ Error: {ex}", "err")

        threading.Thread(target=_work, daemon=True).start()

    def _launch(self):
        self._log("\n── LAUNCHING VALORANT ──────────────────────────", "info")
        threading.Thread(target=lambda: launch_valorant(self._log), daemon=True).start()


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()
