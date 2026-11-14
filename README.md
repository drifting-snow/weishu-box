# 卫戍盒子 · weishu-box

「卫戍盒子」— 明日方舟「卫戍协议」桌面参谋：置顶 Overlay 读屏（商店 / 棋盘 / 规程等级 / 阵容装备），顾问内核给出可解释建议（高亮、刷新 EV、缺口与 clear_margin）。本仓库一体打包壳 `overlay/` + 内核 `advisor/`；**只读辅助，不代点击、不读内存、不注入**。

**v1.0：** 自动 OCR 环、操作日志与开局/结束、读敌人、规程等级 → `regulation_level`、读阵容 / 装备 OCR、商店打分权重（三连保持、刷新 EV、多缺口封顶）。

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

## 测试姿态

Advisor 全量单测中，`tests/test_roadmap.py`（阵容/路线图 WIP）可能有已知红例；视觉 / 敌人名录 / 引擎核心路径应保持绿。公开 tip 以 `advisor/` @ `756876f` 为准。首次跑 overlay 视觉前，如缺本机 ROI 标定，需按 advisor 文档做一次本地校准（勿提交机器相关 `config.local.json`）。

## 隐私

公开树已 scrub：无本机绝对路径、无 `config.json`、无 `session/` 对局/截图、无 QQ/OpenClaw/Cursor store id。本地截图与会话产物请放在 gitignore 目录。

## License

本仓库代码与文档采用 **[PolyForm Noncommercial License 1.0.0](LICENSE)**（取代原 MIT）。完整条款见根目录与 `advisor/LICENSE`。

**他人可以：** 在非商业目的下使用、研究、修改与再分发本仓库代码与文档（须保留本许可全文或 URL，以及 `Required Notice`）。个人学习、业余爱好、教育研究等属许可范围内的用途。

**他人不可以：** 将本仓库用于任何商业目的（例如售卖、收费服务、广告变现、商业产品/SaaS 内嵌等）；亦不得转授本许可。游戏客户端相关的脚本/作弊风险仍由使用者自行评估。

**游戏数据说明：** `data/source` 与派生 JSON 数据集版权归鹰角网络 / 明日方舟 IP 方；仅作非商业研究引用，另受上游 Wiki/数据项目许可约束（见 `advisor/README.md`「数据来源与许可」）。本 PolyForm 许可**不**覆盖这些第三方游戏数据。
