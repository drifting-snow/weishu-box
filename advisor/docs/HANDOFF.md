# HANDOFF — 明日恢复索引（2026-11-14 更新）

> 目的：让下一个会话 5 分钟进入状态。本文是**索引 + 状态快照**，机制细节见各模块 docstring 与 `docs/board_click_ocr_design.md`。
> 项目根：`advisor/`（本 monorepo 子目录）　公开 tip：`756876f`（merge #4；含 scoring #3 + shop odds）

---

## 0. 一分钟自检（恢复后先跑）

``powershell
cd advisor
.\.venv\Scripts\python.exe -m unittest discover -s tests          # 全量，期望 478
.\.venv\Scripts\python.exe -m unittest tests.test_board_badge tests.test_match_text tests.test_enemy_catalog tests.test_enemy_panel_ocr tests.test_resource_ocr  # 视觉+名录，期望全绿
git status --short                                                # 看在途未提交工作
``

- 全量当前 **478 测试，4 红，全在 `tests/test_roadmap.py`**（阵容/路线图层，**与视觉无关**，见 §5）。
- 视觉 + 敌人名录相关 **74 测试全绿**；其中 `test_board_badge` 9 个、保守匹配 `ConservativeModeTest` 8 个 + `MatchRankedTest` 4 个。

---

## 1. 两条已落地的主线

### A. 敌人战术名录（方案 A，已提交，用户拍板）
**起因**：停更的 GPL Stronghold 复刻只有 act2、缺新赛季敌人。改用官方 Kengxxiao 解包表自建，官方自带战术分类，无需自造规则。

- 源表（**gitignored，不入库**）：`data/source/gamedata/` 下 `activity_table.json`、`enemy_handbook_table.json`、`enemy_database.json`（database 在 `levels/enemydata/`，不在 excel）。
- 构建器：`tools/build_enemy_catalog.py`（纯标准库）；已挂进 `tools/build_data.py` 可选阶段；`tools/fetch_game_data.py` 加了 3 个 target。
- 产物（**已跟踪入库**）：
  - `data/enemy_catalog.json` — **179 个带官方战术分类的特训/特殊敌人 → 9 个 trait key**（SPECIAL/FLY/TIMES/ELEMENT/DOT/INVISIBLE/REFLECTION/**CRITIC 致命**/**REBORN 复苏**，后两类正是 Stronghold 缺的）。含 enemy_ids 溯源、rank、is_flying、来源标签、sortId 排序；带"未来新增未映射类型直接报错"防回归断言。
  - `data/enemy_names.json` — **1791 个全量敌人名索引**（含普通杂兵），富字段：damage_types / apply_ways / race_tags / boss_invisible / rank，多 id 同名取并集。
- 查询层 `advisor/enemy_catalog.py`：干净三态 `tactical`（有分类→出对策）/ `untyped`（官方普通敌人如源石虫，识别但静默）/ `unknown`（索引都没有→显式告警）。
- 视觉入口 `vision/enemy_panel_ocr.py`：放大镜面板**只 OCR 名字**（字号阈值滤特性句、全量索引 snap 去标题）；CLI `--enemy-shot`，与手动 `--enemy-types` 合并去重。
- 关键提交：`20b23af`（静态弱点）→ `ebc8745`（面板 OCR）→ `76566b3`（名录主体）→ `1852c8b`（**保守匹配 + 富字段索引**）。
- 许可证红线：Stronghold 为 GPL-3.0，本仓 MIT；其代码/数据只存 `data/source/_stronghold/`（gitignored），**不得拷贝入库**。官方表同理只缓存不入库。

### B. 棋盘头顶精英标记识别（部分落地，Ⅳ–Ⅵ 召回待重构）
- 模块：`vision/board_badge.py`（纯 numpy FFT-NCC + 形状门控 + 网格聚类），无新依赖。
- **Ⅰ–Ⅲ（暗底亮竖条）在稀疏普通态帧达 100% precision/recall**，已验证 4 帧。
- 提交：`41494b0`（检测器）→ `458b4f4`（4 帧验证）→ `2d54bec`（纠正为 Ⅰ–Ⅵ 六档）→ `08523f8`（**修 NCC 塌缩 + 文档化 Ⅳ–Ⅵ 失败**）。
- 检测帧必须是**普通未选中态**（选中态全屏橙高亮冲对比，`high_selected.png` 仅参考、不作检测帧）。

---

## 2. 高本帧实证：为什么 Ⅳ–Ⅵ 现在认不出（详见 `docs/board_click_ocr_design.md` §8.6）

样本 `_diag/vision/high_normal.png`（规程13/回合9，含 Ⅳ青×1 / Ⅴ黄×1 / Ⅵ橙×2 + 多个 Ⅲ绿/Ⅰ黑）。现有 `detect_badges` 只出 6 个且全判 tier=1。五条根因（都有诊断脚本证据，存 `_diag/vision/`）：

1. **极性反转**：Ⅰ–Ⅲ 暗底亮条；Ⅳ–Ⅵ 亮彩底 + **深色罗马数字**（Ⅴ含斜线）。旧 `darkening≥25`（要求标记比背景暗）把亮底标记系统性误杀。
2. **字形变了**：数竖条的列分组对罗马字 Ⅳ/Ⅴ/Ⅵ 原理上失效，判级须改颜色或点击后面板 OCR。
3. **暖色颜色分割判死刑**：本关沙漠地砖本身就是橙色相（橙掩码 51.8 万 px 淹没），饱和度主峰 S≈0.5 与 Ⅵ标记(0.5–0.63) 重叠、Ⅴ仅 0.16。**冷色可分**（绿140–170°、青170–200°掩码干净），暖色在沙漠关不可分。脚本：`hue_scan.py`/`color_mask_viz.py`/`warm_sat_analysis.py`。
4. **反相模板失败**：`255-x` 破坏圆角外框边缘关系，18 峰全落空地/木板/箱子。NORMAL 模板反而能框住彩标 → **NCC 跟外框、对极性不敏感，问题在门控不在模板**。脚本：`inverted_ncc.py`。
5. **NCC 塌缩（已修，`08523f8`）**：近平坦区（冻结/刷新按钮 std≈1.7）把相关系数撑出数学范围（实测 2.21/3.78，合成复现 3.4–3.6）。已硬剔除 `|score|>1`（真 NCC 必 ∈[-1,1]）+ 2 个回归测试。注：这是数学正确性加固，**不是** Ⅳ–Ⅵ 召回的决定因素。

旧的 darkening "26.7 vs 23.1 干净鸿沟" **只在稀疏帧成立**；高本帧真标记 dark_signed 跨度 -12~+58、假阳性 -12~+13，严重重叠，饱和度也分不开。

---

## 3. 明日 TODO（按优先级）

### P1 — 棋盘 Ⅳ–Ⅵ 召回重构（核心未竟，路线已在 §8.6，勿单图过拟合）
1. **先要一张非沙漠底色地图的高本帧**（冷色/深背景），用于双轨验证 + 暖色标记跨背景泛化。这是动门控前的硬前置。
2. `vision/board_badge.py` 门控从单向 `darkening` 改**极性自适应**：取 `|标记块均值 − 外围环均值|` 绝对对比 + 内部高对比边缘测试（亮条 **或** 深色罗马字），不规定谁亮谁暗。
3. 上**网格晶格约束**（RANSAC/霍夫估行列步长，只留等距点阵内候选、剔散点），压箱子/地砖/红框假阳性；ROI 继续硬排右侧敌人红框区与冻结/刷新按钮。
4. 判级：冷色（Ⅲ绿/Ⅳ青）可由色相约分；暖色 Ⅴ/Ⅵ 在沙漠关颜色不可靠，**高档位一律以点击后面板 OCR 的 Ⅰ–Ⅵ 文案为准**，标记只负责定位+计数。
5. 双轨回归：现有 9 个合成测试锁 Ⅰ–Ⅲ 暗底路径不回归；新门控须同时过稀疏旧帧（保 P/R）和高本帧（提召回）。

### P2 — 收口当前未提交的视觉在途工作（见 §4，先确认归属再提交，勿 `git add -A`）
- `vision/resource_ocr.py`：金币 ROI 下移避开刷新费用气泡（修"误读气泡→建议刷新"），新增零形字符 O/Ｏ→0 的 `_digit_part`。有对应测试。
- `vision/match_text.py`：在 `1852c8b` 保守匹配之上扩充 `DEFAULT_CORRECTION`（折桠/青枳别名）。
- 验证：视觉+名录 74 测试已全绿；提交前再跑一次全量并人工确认 diff 仅含视觉线文件。

### P3 — lineup/roadmap 红线失配（**非视觉线，别人在途**）
- `tests/test_roadmap.py` 4 红：阵容数量(21≠12)、mid 目标干员、ownership 计数等断言，对不上 `lineups.json` 重设计（提交 `66274c0`/`49f511e`/`981f6a3` + 未跟踪 `tools/_rebalance_lineups_quality.py`）。
- `test_roadmap` 只 import 引擎层（data/model/lineup/compass/roadmap/engine），**零 vision 依赖**，确认与本仓视觉改动无关。接手前先和在途作者对齐，不要单方面改测试或数据。

### 更长线（来自产品 backlog，本轮未动）
- 视觉桥剩余：回合/金币/调度等级**小数字 OCR**（金币=右下 ◆三钻簇、本数=升级 tile 白条、升本费=六边形）；棋盘地块/备战区识别（点击小人读详情、独立文件、每回合更新）。
- battle tick 内核：把每个小节/乐部当独立实体逐帧模拟（召唤数/走路接敌/真实挡怪）；现仅引擎里程碑评分 + 静态 DPS/承伤锚点。
- 莱塔尼亚个人召唤物真实自走棋数值：仅黑键有原版 token（塔防占位 ATK100 无技能），PRTS 无页，**待游戏内实测，禁止假数填充**。
- ~~`ENEMY_TYPE_BANDS` 仍为占位假设，待实测敌人 DEF/RES 替换~~ **已完成（2026-11-13）**：三档猜测已删除，改由 `data/enemy_stats.json` 真实 level-0 def/res（`tools/build_enemy_stats.py` 生成）+ 连续伤害公式驱动，折射高防低抗的旧假设已被实测纠正；`range_table.json` 未接入。
- 运营节奏/跨回合字段：用户指示"打分之后再做"，暂不写 `lineups.json`。
- 1.0 全流程端到端实测未完成（商店 OCR、敌人面板已通；棋盘、胜负闭环未实测）。

---

## 4. 工作区在途工作边界（历史快照 · 公开固定 tip 可忽略）

| 文件 | 状态 | 归属线 | 说明 |
|---|---|---|---|
| `vision/match_text.py` / `tests/test_match_text.py` | M 未提交 | 视觉 | 保守匹配核心已在 `1852c8b`；此为其上修正字典微调 |
| `vision/resource_ocr.py` / `tests/test_resource_ocr.py` | M 未提交 | 视觉 | 金币 ROI 修复 + O→0，P2 收口对象 |
| `vision/board_strip_ocr.py` | ?? 未跟踪 | 视觉 | 备战/手牌条 OCR（operator 名 snap），新模块 |
| `tools/_rebalance_lineups_quality.py` | ?? 未跟踪 | **lineup** | 阵容再平衡脚本，对应 P3 红测试，勿当视觉文件提交 |

- 我的两个视觉提交 `08523f8`、`2d54bec` 只碰 `vision/board_badge.py` + 其测试 + 设计文档，边界干净。
- **纪律：只 `git add` 自己负责的路径，绝不 `git add -A`，避免捎带 lineup 在途工作。**

---

## 5. 关键事实速查

- **敌人名录**：179 战术敌人 / 9 类 / 1791 全量名索引；三态 tactical·untyped·unknown；权威名字源统一用 handbook（database 有 30 个译名漂移）。
- **保守匹配护栏实数**（`_diag/vision/audit_conservative.py`）：1119 截断探针下，默认模式误吸 **118**，保守模式降到 **20（-83%）**；179 个战术全名**零漏识别**；残留 20 全是"精英长名→基型短名"安全降级（XX长→XX、变异α→基型，战术分类一致）。常量 `CONSERVATIVE_THRESHOLD=0.85`、`CONSERVATIVE_GAP=0.12`；单字输入直接拒。
- **敌人面板**：只给名字 + 定性特性文字，**不给 HP/攻/防/抗数值**；本波源石虫(untyped 中性)、寻险水手(→INVISIBLE/stealth)。
- **资源语义（用户口径，已纠正误读）**：红框 ◆4 三钻簇=当前金币 4；黄框白竖条=当前本数 1（填充段=调度等级）；六边形"5"=升本费用，4<5 还差 1 块。顶部 ♟25 是另一种资源，不是金币。
- 截图源目录：`$WEISHU_SHOTS_DIR`（本地截图）；工作副本在本地 `_diag/vision/`（不随公开仓发布）（2560×1440，16:9）。

## 6. 红线（不可越）

- **操作红线**：模拟点击只用于**识别**（点小人读详情、点放大镜读面板），**不得代替用户操作游戏**；升本/刷新/买怪/摆位用户自己做。
- **许可证**：GPL Stronghold 与官方解包表只缓存到 gitignored 的 `data/source/`，不入库；只通过自有解析器读事实。
- **数据真实性**：缺数据留显式空槽/`needs_review`，不插值造假；名录只存分类与定性字段，**不含 HP/ATK/DEF/RES**。
- **环境**：Windows 控制台强制 UTF-8；JSON 用 `--out` 落盘避免 GBK 乱码；严格 `-W error::ResourceWarning` 下文件句柄用 `with open`。
- 默认全种族可用，ban 选在查询期过滤；`盟约·辅助干员` 是运行时临时单位不入 `operators.json`；`魔王` 是真实干员。

## 7. 关键文件地图

| 用途 | 文件 |
|---|---|
| 名录构建器 | `tools/build_enemy_catalog.py`（数据管线集成在 `tools/build_data.py`） |
| 名录/名索引数据 | `data/enemy_catalog.json`、`data/enemy_names.json` |
| 敌人三态查询 | `advisor/enemy_catalog.py` |
| 敌人面板 OCR | `vision/enemy_panel_ocr.py` |
| 模糊匹配（含保守模式） | `vision/match_text.py` |
| 棋盘标记检测 | `vision/board_badge.py` |
| 资源（金币/回合）OCR | `vision/resource_ocr.py` |
| 视觉设计与实证 | `docs/board_click_ocr_design.md`（§8.5 旧管线 / §8.6 高本帧实证+重构路线） |
| 诊断脚本 | `_diag/vision/*.py`（本地诊断；不随公开仓发布：audit_*/hue/warm/inverted/gate/collapse 等） |

## 8. 交付状态快照（2026-11-14）

### 评分权重 — **已合入 main**
- **Merge**：PR #3 (scoring + shop odds) → `main` @ `756876f`（2026-11-14）；分支 `cursor/scoring-weights-394c`
- **#1 shop odds**：已 **close as superseded**（PR #1）；#3 含同一 ASSUMED `data/shop_roll_odds.json` + `advisor/shop_odds.py` 并已接入 refresh EV，勿再合以免冲突
- **三连/2→3**：仍 +100，不压进 soft band
- **经济/刷新 EV**：`INVEST_WEIGHT` 上调；`engine._score_refresh` 用 ASSUMED `shop_odds.tier_probs` × 槽位 × 余钱；soft≤58 可被刷新压过，critical≥70（羁绊差1 / 2→3）仍压刷新
- **多缺口**：priority silence>refraction>anti_air；primary15 + secondary8；硬顶 **28**（废止 +15×N）

### PR#2 combat_resolver — **保持退役**
- PR #2 closed、**未合并**；不 rebase / 不落地
- SoT：**`advisor/battle` tick**（output-only）+ **`clear_margin`**（喂分）；无第三条并行战斗模型

### 装备 OCR / Overlay
- **Equip OCR**：仍等用户截图后再做 ROI / 面板装备识别（不挡本轮交付）
- **Overlay**：由壳工程「卫戍盒子」(`weishu-box-overlay`) 持有；本 kernel 仓不改 overlay
