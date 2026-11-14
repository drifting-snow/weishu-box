# weishu-box-overlay（卫戍盒子壳）

明日方舟「卫戍协议」只读商店参谋悬浮窗。决策内核在独立仓库 `weishu-advisor`，本仓只做壳：置顶半透明面板、Live OCR、商店发光框、阵容伴生窗。

**合规：只读建议，不代点游戏、不读内存、不注入。**

> 本机可运行交付说明见 **[DELIVERABLE.md](./DELIVERABLE.md)**（冷启动路径、功能清单、无 remote 时如何跑）。

## 为何 pywebview（非 Tauri）

本机当前无 `cargo`/`rustc`，无法立刻跑 Tauri。MVP 用 **Python + pywebview (WebView2)**；后期可迁 Tauri，HTML UI 可复用。

## 运行（Live 游戏 · 无 demo）

```powershell
cd overlay
py -3.12 -m pip install -r requirements.txt
copy config.example.json config.json   # 按需改 kernel_path / kernel_python
py -3.12 run_overlay.py
```

或：`py -3.12 -m shell.main`

- **无** `--demo` 壁纸；不弹截图查看器。
- **冷启动不自动 OCR**；点「OCR 识别」/`Ctrl+Shift+A` 才抓主屏。
- 「自动」由用户武装后才周期 OCR；首次手动成功也会武装并保持。

决策高亮：分析后才懒创建 **Win32 color-key** 发光框层（非 WebView2）。启动只开小面板 + 阵容伴生窗。

### 热键

| 热键 | 作用 |
|------|------|
| `Ctrl+Shift+W` | 折叠/展开参谋窗 |
| `Ctrl+Shift+A` | Live 抓主屏 → OCR → 推荐 + 游戏上发光框 |
| 面板「交互」 | 临时可点面板 |

### 主按钮

| 按钮 | 作用 |
|------|------|
| OCR 识别 | 手动 Live 周期 |
| 自动 | 武装/关闭自动 OCR |
| 开始新一局 / 结束一局 | 本局 op-log 文件夹 |
| 读敌人 | 自动按 W → 0.5s → 敌人面板 OCR |
| 读阵容 | 显式：badge→只读点击→面板名/装备 OCR→ESC；结果缓存，不进自动商店循环 |
| 录入本局 | 规程难度选择 / 合约/策略 OCR → 阵容窗「本局环境」（`procedure_level`→内核 `regulation_level`） |

### 模式

1. **Live（主路径）**：`ImageGrab` 抓主屏 → sidecar OCR → 推荐 + glow。
2. **State**：手填元数据，调 `--state`（轻量，无 OCR）。
3. **Mock**：本地 JSON，不调内核。
4. **文件 Shot**：仅当用户主动选文件时。

内核默认路径：monorepo 同级 `../advisor`（可用 `config.json` / `WEISHU_KERNEL_PATH` 覆盖），解释器优先其 `.venv/Scripts/python.exe`。

## 目录

```
shell/          # pywebview 入口、Win32、sidecar、op_log、advice_filter
shell/ui/       # HTML/CSS/JS 面板 + roster 伴生窗 + Moji
mock/           # 示例推荐 JSON
tools/          # 本地标定/调试脚本（可选）
session/        # 本机产物（gitignore）
DELIVERABLE.md  # 交付与功能清单
```

## OCR 节奏

- 手动 / 热键：即时一轮。
- 自动：用户武装后，见仓库根 README / 开发笔记（interval≈4.5s、gap、backoff；冷启动 off）。
