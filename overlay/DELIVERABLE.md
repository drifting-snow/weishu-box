# 卫戍盒子 overlay · 本机可运行交付

**Checkout:** `overlay/`  
**Kernel (sibling, do not modify from this shell):** `advisor/` (sibling in monorepo)  
**Screenshots ref:** `$WEISHU_SHOTS_DIR` (local screenshots; not shipped)  
**Feature branch:** `cursor/equip-ocr-lineup-ad5e` (from `cursor/overlay-deliverable-2f83`)

## Remote

No GitHub remote for this repo (sibling `weishu-advisor` is `drifting-snow/weishu-advisor`). Run from this folder. To publish later:

```powershell
cd overlay
gh repo create drifting-snow/weishu-box-overlay --private --source=. --remote=origin
git push -u origin HEAD
```

## Clean start (live game)

Cold launch must **not** use `--demo` wallpaper and must **not** auto-OCR.

```powershell
cd overlay
copy config.example.json config.json   # first time only; already gitignored
# Edit kernel_path / kernel_python if paths differ
py -3.12 -m pip install -r requirements.txt
py -3.12 run_overlay.py
# or: py -3.12 -m shell.main
```

Preconditions:

1. Game (or primary screen) visible — overlay grabs primary via `ImageGrab`, no image popup.
2. Kernel venv present at path in `config.json`.
3. Optional: delete `session\` junk; match logs recreate on launch / 「开始新一局」.

After launch you get the advice panel + lineup companion. Status shows 就绪; Moji idle. Click **OCR 识别** or `Ctrl+Shift+A` for the first live cycle. Arm **自动** only when you want the loop.

## 「读阵容」+ 装备 OCR

1. Be on the **ordinary unselected** prepare screen (no orange select overlay).
2. Click **读阵容** (not inside 自动 shop loop).
3. Shell: ESC → `detect_badges` → for each badge: ROI-gated left-click → panel name + equip OCR → ESC.
4. Results land in `session/board_cache.json`, `_last_board` / `_last_equipment`, lineup companion, and op_log (`board_source=click_panel`).
5. Later shop **OCR 识别 / 自动** shots keep that board locked (strip OCR will not overwrite) until **开始新一局**.

ROI notes / shot review: equip OCR ROI notes live with the Project docs (not required to run).

## Feature checklist

| Feature | Status |
|--------|--------|
| Manual OCR (`OCR 识别` / `Ctrl+Shift+A`) | Present |
| 自动 loop (user-armed; cold launch off) | Present |
| Shop decision glow (Win32 color-key) | Present |
| Op-log + 「开始新一局」/「结束一局」 | Present |
| Moji OCR emotion badge | Present |
| 「读敌人」(W → wait → OCR) | Present |
| 「读阵容」explicit button | **Wired** — badge→click→panel/equip OCR |
| Lineup companion window | Present (隐 collapses, does not destroy) |
| Equip OCR ROIs | **Wired** (name ROI + equip name ROI @1440p) |

## Known gaps / broken notes

- IV–VI head badges still under-detected in kernel `board_badge` (shell only clicks what is returned).
- Multi-equip-slot panels barely sampled; OCR assumes one primary equip name line.
- Shop auto shot still *runs* legacy board-strip OCR, but when a click-panel cache exists the shell passes `board_locked` so strip cannot overwrite.
- 「开始新一局」intentionally starts one OCR into the new log folder (user-initiated, not cold launch) and clears board cache.
- `config.json` is local-only (gitignored).
