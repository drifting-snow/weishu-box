# 卫戍盒子 · weishu-box

明日方舟「卫戍协议」**只读**参谋：悬浮壳（overlay）+ 决策内核（advisor）一体发布。

**合规：只读建议，不代点游戏、不读内存、不注入。**

## Layout

```
weishu-box/
  overlay/     # 卫戍盒子壳（pywebview 面板、Live OCR、商店发光、阵容窗、op-log）
  advisor/     # 决策内核（规则引擎、视觉 OCR、battle/clear_margin、数据表）
  README.md    # 本文件
```

| 组件 | 本包来源 tip | 主要能力 |
|------|-------------|---------|
| `overlay/` | `cursor/protocol-level-ocr-597c` | Live/自动 OCR、规程等级 OCR→`regulation_level`、读敌人、读阵容+装备 OCR、op-log、Moji、商店 glow |
| `advisor/` | `main`（含 scoring #3 + shop odds） | 确定性推荐、ASSUMED shop roll odds、battle tick + clear_margin SoT（**不含**已退役的 combat_resolver） |

内核仓库也曾单独存在于 `drifting-snow/weishu-advisor`（private 历史）；**本公开 monorepo 是一体化发布面**。

## 快速开始（Windows）

```powershell
# 1) 内核 venv + 可选视觉依赖
cd advisor
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e ".[vision]"
.\.venv\Scripts\python -m unittest discover -s tests

# 2) 壳依赖 + 本地配置（不要提交 config.json）
cd ..\overlay
py -3.12 -m pip install -r requirements.txt
copy config.example.json config.json
# 默认 kernel_path 已是 ../advisor ；若布局不同可改，或设 WEISHU_KERNEL_PATH

# 3) 启动（游戏/主屏可见；冷启动不自动 OCR）
py -3.12 run_overlay.py
```

- 首次点 **OCR 识别** 或 `Ctrl+Shift+A`；**自动**需用户武装。
- 仅引擎/无 UI：`cd advisor` 后 `python -m advisor.cli --state examples/state_demo.json`。

## 配置

- 复制 `overlay/config.example.json` → `overlay/config.json`（已 gitignore）。
- 默认相对路径：`kernel_path=../advisor`，`kernel_python=../advisor/.venv/Scripts/python.exe`。
- 环境变量：`WEISHU_KERNEL_PATH`、`WEISHU_KERNEL_PYTHON`、调试截图用 `WEISHU_SHOT` / `WEISHU_SHOTS_DIR`。

## 功能清单（本 release）

**壳**
- 手动 / 自动 OCR 循环（冷启动 off）
- 商店决策 Win32 glow（买不起不亮）
- 读敌人（自动按 W → 面板 OCR）
- 读阵容（badge→click→面板名/装备 OCR）
- 录入本局 / 规程难度选择 OCR → `regulation_level`
- 本局 op-log（开始/结束一局）
- Moji OCR 情绪 badge

**内核**
- 买/刷/冻/升本评分；三连 2→3 +100；INVEST 权重；刷新 EV←ASSUMED `shop_odds.tier_probs`；多缺口硬顶 28
- 敌人名录 / 面板 OCR；棋盘 badge；资源 OCR
- battle 离散 tick（输出）+ `clear_margin`（入分）为战斗 SoT

## 隐私

公开树已 scrub：无本机绝对路径、无 `config.json`、无 `session/` 对局/截图、无 QQ/OpenClaw/Cursor store id。本地截图与会话产物请放在 gitignore 目录。

## License

见 `advisor/LICENSE`（内核）；壳与配套文档随本仓一并发布，仅供学习与个人研究。
