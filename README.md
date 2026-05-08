# VALORANT Config Tweaker

A lightweight Python/Tkinter desktop tool that patches `GameUserSettings.ini`,
changes your Windows display resolution, and launches Valorant — all in one
click.

---

## Features

| Feature | Details |
|---|---|
| **INI-aware patching** | Reads your actual config before touching anything — detects your native resolution, existing fullscreen mode, letterbox setting, etc. |
| **Backup & restore** | Creates a `.valorantbak` on first apply. Reset restores from it exactly. |
| **Preset resolutions** | 8 common presets including 4:3 / 5:4 stretched, 16:9 native, 1440p. |
| **Custom resolution** | Enter any W×H you want (e.g. `1176×664`). Validated before applying. |
| **Windows display change** | Uses `win32api.ChangeDisplaySettings` (pywin32) to flip your desktop res before the game loads. Restored on reset. |
| **Riot Client launcher** | Finds `RiotClientServices.exe` and fires it with `--launch-product=valorant`. |
| **Threaded** | Apply / reset / launch run on background threads — the UI never freezes. |

---

## Requirements

- **Python 3.10+**
- **Windows only** (win32api, the Riot Client path, and the INI location are all Windows-specific)
- **pywin32** for the display resolution feature:

```
pip install pywin32
```

Tkinter ships with Python on Windows. No other dependencies.

---

## Installation & Usage

```
# 1. Clone or download the repo
git clone https://github.com/purp-phy/valorant-config-tweaker
cd valorant-config-tweaker

# 2. Install the one dependency
pip install pywin32

# 3. Run
python valorant_config_tweaker.py
```

> **Note:** If `win32api` is not installed the tool will still run — config
> patching and Valorant launching work fine, only the automatic display
> resolution change is skipped (a warning is shown in the log).

---

## What gets changed

The tweaker applies exactly the diff between a stock Valorant config and an
optimised one. It reads your file first and only writes keys it finds (or
inserts missing ones).

| Key | Default | Tweaked |
|---|---|---|
| `bShouldLetterbox` | `True` | `False` |
| `bLastConfirmedShouldLetterbox` | `True` | `False` |
| `LastConfirmedFullscreenMode` | `0` | `2` |
| `PreferredFullscreenMode` | `0` | `2` |
| `FullscreenMode` | *(absent)* | `2` ← inserted |
| `ResolutionSizeX` / `ResolutionSizeY` | native | your pick |
| `LastUserConfirmedResolutionSizeX/Y` | native | your pick |
| `DesiredScreenWidth` / `DesiredScreenHeight` | native | your pick |
| `LastUserConfirmedDesiredScreenWidth/Y` | native | your pick |
| Windows display resolution | native | your pick |

**Fullscreen mode values:**
- `0` = Exclusive Fullscreen
- `1` = Windowed
- `2` = Borderless Window ← what this tool sets

---

## Config file location

The tool auto-scans:

```
%LOCALAPPDATA%\VALORANT\Saved\Config\<account_id>\Windows\GameUserSettings.ini
```

If you have multiple accounts on the same machine, all found configs are listed
in the dropdown — pick the one you want.

---

## Resolution options

| Label | W | H | Aspect |
|---|---|---|---|
| Native (read from config) | auto | auto | your monitor |
| 1024×768 | 1024 | 768 | 4:3 |
| 1280×960 | 1280 | 960 | 4:3 |
| 1280×1024 | 1280 | 1024 | 5:4 |
| 1440×1080 | 1440 | 1080 | 4:3 |
| 1600×900 | 1600 | 900 | 16:9 |
| 1366×768 | 1366 | 768 | 16:9 |
| 1920×1080 | 1920 | 1080 | 16:9 |
| 2560×1440 | 2560 | 1440 | 16:9 |
| **Custom** | **you enter** | **you enter** | any |

For the **Custom** option, select the radio button and type your target width
and height into the two text boxes. Valid range: 320–7680 wide, 240–4320 tall.

---

## Workflow

### Apply tweaks

1. Open the tool — it auto-detects your config and shows `Native resolution: W×H`.
2. Select a resolution preset (or choose **Custom** and type your values).
3. Click **⚡ APPLY TWEAKS**.
   - A backup (`GameUserSettings.ini.valorantbak`) is created on first run.
   - All keys are patched in-place.
   - Windows display resolution is changed immediately via `ChangeDisplaySettings`.
4. Click **▶ LAUNCH VALORANT** to start the game.

### Reset to default

1. Click **↩ RESET TO DEFAULT** and confirm.
   - The `.valorantbak` is copied back over the live config.
   - Windows display resolution is restored to the native value detected from the backup.

---

## Riot Client paths searched

```
C:\Riot Games\Riot Client\RiotClientServices.exe
%PROGRAMFILES%\Riot Games\Riot Client\RiotClientServices.exe
%PROGRAMFILES(X86)%\Riot Games\Riot Client\RiotClientServices.exe
where RiotClientServices.exe   ← fallback PATH search
```

---

## Troubleshooting

**"No Valorant config found"**
Run Valorant at least once so it generates the config file, then reopen the
tool.

**"win32 ✗" badge in the header**
Display resolution changes are disabled. Install pywin32:
```
pip install pywin32
```

**"Riot Client not found"**
Your Riot Games folder is in a non-standard location. Open the folder manually,
find `RiotClientServices.exe`, and either move the Riot Games folder to
`C:\Riot Games\` or add its parent directory to your system `PATH`.

**Config was edited but game shows old settings**
Make sure Valorant is fully closed before applying tweaks. Valorant overwrites
the config on exit.

---

## File structure

```
valorant-config-tweaker/
├── valorant_config_tweaker.py   ← the tool
└── README.md
```

---

## Disclaimer
## Don't contact my ahh plz

This tool edits a local settings file and changes your Windows display
resolution. It does **not** inject into the game process, modify game files, or
interact with the anti-cheat system (Vanguard). It is not affiliated with or
endorsed by Riot Games. Use at your own discretion.

