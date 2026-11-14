# 卫戍协议决策助手 · Guard Protocol Advisor

明日方舟「卫戍协议·规程」自走棋玩法的**只读决策辅助**：识别当前商店，给出买牌 / 刷新 / 冻结 / 升本的最优解，以及阵容盟约、装备与固定练度面板参考。定位对标云顶之弈 / 金铲铲的 overlay 参谋，但**只读取屏幕像素、只给建议，绝不自动点击、不读内存、不封包**。

> ⚠️ **合规声明**：本工具不与游戏客户端交互、不模拟任何输入、不修改游戏数据，所有操作仍由玩家手动完成。游戏举报项明确包含「脚本/作弊」，请自行评估风险，仅用于学习与个人研究。作者不对账号后果负责。

---

## 特性

- **确定性规则引擎**：升本价、等级门控、三合一、装备上限等零容错数学全部写死在规则层，不交给大模型“猜”。
- **统一边际影响标尺（Impact）**：每个买牌/刷新/升本动作按 战力增量 / 经济增量 / 成长增量 三轴打分，归一到每金币并叠加机会成本。
- **精确固定练度面板**：根据游戏内实测的练度固定规则，用游戏解包表的关键帧线性插值，还原每个干员在模式固定等级（E1 Lv55/60、E2 Lv1/50/55/60）下的精确攻击/血量/防御，而非用满级锚点高估。
- **核心零第三方依赖**：规则引擎、全部数据解析器和整套测试只用 Python 标准库；OCR/视觉为可选扩展。
- **可离线运行**：视觉 OCR 使用 RapidOCR 自带 ONNX 模型，运行时不联网、不需显卡。

## 环境要求

- Python ≥ 3.9（开发验证于 3.11，跨平台 Windows / macOS / Linux）
- **核心引擎与测试：无需安装任何第三方库**
- 仅截图 OCR 路径需要可选视觉依赖（见下）

## 快速开始

```bash
# 引擎与测试开箱即用（data/*.json 已随仓库提供，无需先下载数据）
python -m advisor.cli --state examples/state_demo.json --rounds-at-level 1
python -m unittest discover -s tests          # 383 项离线单测
```

### 可选：截图 OCR 视觉栈

```bash
# 推荐用独立虚拟环境（uv 管理的全局 Python 受 PEP 668 保护，不能直接 pip）
uv venv --python 3.11 && uv pip install -e ".[vision]"   # numpy + pillow + rapidocr

# 商店截图 → 识别 → 决策建议（整带 OCR，兼容动态槽位数）
.venv/Scripts/python -m advisor.cli --shot prep.png \
    --round 1 --gold 4 --dispatch-level 1
# 已拥有阵容用 --board 喂入（board_demo.json：名字列表或 {name,count} 均可），
# 驱动羁绊人数/三合一/里程碑评分（含莱塔尼亚召唤体系）；棋盘自动 OCR 待做
# 回合/金币/本数/升本费/本波敌人数现在由 --shot 同一张截图自动 OCR（见 resource_ocr）；
# --round/--gold/--dispatch-level 仅在某个字段识别不到时作为兑底，可省略
.venv/Scripts/python -m advisor.cli --shot prep.png \
    --board examples/board_demo.json --target-bond 莱塔尼亚
# 可选 --enemy-types flying,stealth 手动传入下波敌人画像，激活对策/effDps 评分
# 也可用 --enemy-shot 传放大镜敌人面板截图：只 OCR 敌人名，类型查 data/enemy_catalog.json
.venv/Scripts/python -m advisor.cli --shot prep.png \
    --enemy-shot enemy_panel.png \
    --round 1 --gold 4 --dispatch-level 1 --out result.json
# 局内 ban 位：禁干员（永不推荐买入）/ 禁羁绊（排除以该羁绊为核心的阵容），逗号分隔
.venv/Scripts/python -m advisor.cli --state state.json \
    --ban-operator 卡达,烈夏 --ban-bond 奥术
# 也可直接写进 state JSON："banned_operators": [...], "banned_bonds": [...]
# 可选 --out result.json 将 UTF-8 结果落盘（不依赖控制台代码页）
```

CLI 会自动把 stdout/stderr 重配为 UTF-8，Windows 传统 GBK/cp936 控制台也不会出现中文乱码；需要给下游程序/版本库消费时用 `--out` 写无 BOM 的 UTF-8 文件。

**两条识别路径**：
- `vision/shop_band_ocr.py`（**主路径，已用真实 2560×1440 客户端标定**）：对底部商店带整带 OCR，按名字水平带过滤 + 141 干员/70 道具字典模糊吸附，天然兼容随调度等级变化的槽位数；价格不 OCR（黄圆数字难认），改由数据集 tier 表/道具价格推导。实测 4/4 牌全对（置信度 0.84–0.999）。
- `vision/resource_ocr.py`（**资源数字 OCR，同一张 `--shot` 截图自动读**，用 1 本/2 本两张真实图标定）：输出 `round`（回合）、`enemy_count`（顶部棋子图标=本波敌人总数，用户确认）、`gold`（右下三钻簇金币）、`upgrade_cost`（升级 tile 六边形升本费）、`dispatch_level`（tile 内白色竖条本数，罗马竖条非数字→numpy 列轮廓计数，非 OCR）。**关键标定事实**：升级 tile 水平位置随商店槽位数漂移（1 本 4 槽 tile 中心 x≈775、2 本 5 槽 x≈451），但垂直位置固定、六边形与竖条都水平居中于 tile 的 `LEVEL` 文字，故先 OCR 定位 LEVEL 锡点再动态居中（OCR 偶把 LEVEL 误拼 LEVEI，用 LEV 前缀兼容）；顶部/金币固定 ROI 用分辨率无关 fraction，小数字统一 3x 放大。两张图 10/10 字段全对、零警告；识别不到的字段回退到手动参数并在 stderr 告警。`enemy_count`/`upgrade_cost` 目前只在输出 `resources` 块展示，引擎暂不消费（round/gold/level 已自动填入 state）。纯逻辑（parse_int/anchor_tile_center/count_tier_pips）可无 OCR 模型单测，见 `tests/test_resource_ocr.py`。
- `vision/shop_ocr.py`（旧的固定槽位 ROI 路径，坐标借自开源项目，需按各自客户端重新标定）：保留备用。
- `vision/enemy_panel_ocr.py` + `advisor/enemy_catalog.py`（**敌人放大镜面板，只 OCR 名字**）：面板只显示敌人名与定性特性、无数值，故视觉层只抽取名字（按相对字号阈值滤掉特性句 + 全量名字索引 snap 去掉标题）。识别用 `data/enemy_names.json`（官方解包表生成的 **1791 个全量敌人名**，普通杂兵也认），类型判定查 `data/enemy_catalog.json`（179 个带官方战术分类的敌人→9 大 trait key）。**干净三态**：`tactical`（有战术分类，贡献 trait）/ `untyped`（如源石虫，官方普通敌人、无分类，识别但不触发对策）/ `unknown`（官方索引都没有，新敌人或 OCR 误识，显式告警）。分类直接取自官方 `autoChessData.enemyTypeDatas` 与 `act3autochess.enemyInfoDict`（含旧复刻缺失的 CRITIC 致命/REBORN 复苏），由 `tools/build_enemy_catalog.py` 随版本重建，不依赖任何第三方 GPL 复刻。实测 `源石虫`(untyped)、`寻险水手`(INVISIBLE→stealth) 端到端正确。手动 `--enemy-types` 与 OCR 结果合并去重。**大字典误吸护栏（保守匹配）**：1791 个名字里存在大量近名（x/组长/α 变体），敌人路径在 `vision/match_text.py` 走独立的 `conservative=True` 双门控——相似度门槛 0.85（商店小字典仍 0.60）+ top1 领先 top2 至少 0.12 的独占性要求，且拒绝单字猜测；拥挤近名竞争（如 `险水手` 同时贴近历险/寻险水手）直接判 unknown 而非自信错吸。截断探针审计下错误吸附从 118 降到 20（-83%），残留均为“截断后恰好等于另一个独占真名”的物理歧义；完整名始终 score=1.0 精确命中（179/179），真实面板识别零影响。

未安装视觉依赖时，OCR 自动退回 NullOCR（输出空识别、不报错），核心引擎与全部纯逻辑测试照常运行。

#### OCR 选型与体积优化（面向 GitHub / 离线分发）

中文识别用 **RapidOCR（PP-OCRv4 ONNX 模型，完全离线）**，实机 2560×1440 截图实测干员/道具名置信度 0.84–0.999，模型本体仅约 15 MB。体积大头是运行库而非模型。win_amd64 / py3.11 实测：

| 方案 | 安装后体积 | 识别效果 | `pip check` |
|---|---|---|---|
| 默认 `.[vision]`（opencv-python 带 Qt/GUI + FFmpeg） | ~235 MB | 优秀 | 干净 |
| **headless 4.10 + 去 FFmpeg（推荐）** | **~204 MB** | **完全一致（同 4/4、同置信度）** | 1 条良性元数据提示 |
| rapidocr 3.x（新一代，原生声明 headless） | 相近（多 omegaconf/requests） | 需重测 | 干净 |

我们只识别静态 PNG、从不开窗也不解视频，因此 Qt/GUI 和 FFmpeg 视频插件纯属死重。推荐瘦身（无精度损失，已验证）：

```bash
uv pip install -e ".[vision]"
uv pip uninstall opencv-python
uv pip install "opencv-python-headless==4.10.0.84"   # 同样提供 cv2，无 Qt/GUI
.venv/Scripts/python tools/slim_vision.py --apply      # 移走 FFmpeg 插件（可还原）
```

`tools/slim_vision.py` 只把 FFmpeg 插件**移动**到 cv2 下的备份目录（不删除、可还原）。headless 替换会留一条 `pip check` 元数据提示（rapidocr 1.4.4 声明的是 opencv-python，但 headless 同样提供 `cv2`，运行不受影响）；要彻底干净需迁移到 rapidocr 3.x（API 不兼容，列入路线图）。

## 架构（分层解耦、可独立测试）

```
advisor/                 # 规则引擎（纯标准库）
  model.py               # 一回合休整期的结构化局面模型
  data.py                # 版本化 JSON 数据加载
  rules.py               # 硬规则：升本价、等级门控、盟约激活、三合一
  engine.py              # 启发式决策，输出带理由的 buy/refresh/freeze/upgrade
  board_io.py            # 已拥有阵容输入层（--board JSON，校验/同名合并/数据集补全；棋盘 OCR 复用此出口）
  impact.py              # 统一边际影响标尺（战力/经济/成长三轴 + 机会成本）
  lineup.py              # 阵容层：13 套 archetype 三阶段构筑路线 + 按敌人画像/ban 选排序
compass.py             # 阵容罗盘：从 board 推断在打哪套 + 给计划内商店卡协同分（接进 engine）
roadmap.py             # 构筑路线：输出 early/mid/late 完整阵容、当前阶段/下一步追谁、敌人驱动的换队建议
  enemy_catalog.py       # 敌人名三态解析（tactical/untyped/unknown）→战术分类 trait key
  special_counters.py    # 特例对策层：按具体敌人名查特殊能力对策（冰系死亡爆炸→沉默）
  team_gaps.py           # gate0 队级缺口检测（缺对空/缺穿透折射/缺沉默的布尔盲区→附加分）
  clear_margin.py        # 阶段1 连续清场裕度（真实出怪窗口×规程血量×折减DPS→富余/吃紧→经济或输出附加分）
  buffs.py               # 干员攻击乘数：羁绊面板公式+逐层规则+装备+精锐（净室，不 import 搁置的 scaling）
  battle/                # 阶段2 净室 tick 战场内核（clock/unit/damage/blocking/wave/grid/skills/battle）+ adapter.py 真实数据适配层
  economy.py item_economy.py econ_bonds.py counters.py stack_feasibility.py
vision/                  # 截图识别（可选，依赖 pillow/numpy/rapidocr）
  shop_band_ocr.py       # 主路径：商店整带 OCR + 字典吸附（实机标定，动态槽位）
  resource_ocr.py        # 资源数字 OCR：回合/本波敌人数/金币/升本费 + LEVEL锡点动态定位本数竖条
  enemy_panel_ocr.py     # 放大镜敌人面板：只 OCR 名字（字号阈值滤特性句 + 全量名字索引 snap）
  keybinds.py            # 游戏内快捷键事实源（G升级/S冻结/D刷新/W敌方信息）；只做建议标注，绝不自动按键
  capture.py roi.py preprocess.py ocr.py match_text.py shop_ocr.py matcher.py
tools/                   # 数据构建与抓取（纯标准库）
  fetch_prts_wiki.py     # 抓 PRTS wikitext 缓存（MediaWiki API）
  fetch_game_data.py     # 抓官方解包表（干员/技能/敌人/活动表，CDN 分块续传）
  build_enemy_catalog.py # 官方自走棋表→enemy_catalog.json(179 战术类) + enemy_names.json(1791 全量名)
  parse_*.py             # 各维度解析器，产出 data/*.json
  build_data.py          # 一键构建引擎 JSON（自动跳过缺失的可选数据）
data/                    # 已构建的引擎数据（随仓库提供，可重建）
  enemy_traits.json      # 9 大战术分类→反制标签
  enemy_catalog.json     # 179 个带官方战术分类的敌人（build_enemy_catalog 生成）
  enemy_names.json       # 1791 个全量敌人中文名索引（OCR 识别用，含普通杂兵）；每条带 rank/is_flying/战术类型 + 定性字段 damage_types(物理/法术/无伤害)、apply_ways(近战/远程)、race_tags(种族)、boss_invisible(隐匿Boss)，不含 HP/ATK/DEF/RES 数值
  enemy_special_cases.json # 敌人特例对策层（build_enemy_special_cases 生成，官方 SILENCE 校验）：全量 61 个可沉默敌人，按 10 机制族归类，47 个运行时 active + 14 个折射族存档不触发
  act3_waves.json        # act3 每关真实出怪时间线/总血/清场窗口（build_act3_waves 从官方关卡+enemy_database+activity_table 派生）
tests/                   # 602 项离线单测
examples/                # 手动局面示例 state_demo.json、阵容示例 board_demo.json
```

## 数据管线（可复现构建）

仓库已内置构建好的 `data/*.json`，普通用户无需抓取即可运行。若要重新解析或刷新数据：

```bash
# 1) PRTS 干员 wikitext（职业分支/天赋/技能/属性锚点），缓存到 data/source/prts/
python tools/fetch_prts_wiki.py

# 2) 官方解包表（Kengxxiao 镜像，CDN 分块续传），缓存到 data/source/gamedata/
#    干员表 character_table + 技能表 skill_table（固定练度面板）
#    + 敌人三表：activity_table(自走棋战术分类) / enemy_handbook_table(中文名) /
#      enemy_database(在 levels/enemydata/ 下，含 motion/levelType/属性)
python tools/fetch_game_data.py            # 先 --probe 可只查看远程体积

# 3) 构建全部引擎 JSON；解包表缺失时自动跳过可选阶段并给出提示
#    敌人三表齐全时自动重建 enemy_catalog.json(179 战术类) + enemy_names.json(1791 全量名)
python tools/build_data.py
# 也可单独重建敌人名录：python tools/build_enemy_catalog.py

# 4)（可选）验证精确面板：离线健全性 + 双源锚点对撞；--remote 再拉第二独立解包源
python tools/validate_mode_stats.py
python tools/validate_mode_stats.py --remote
```

`validate_mode_stats.py` 三层校验：① 本地 2.9 万个逐级网格点的范围/单调性/信赖可加性；② 解包表与 PRTS wiki 的满级锚点对撞（141 人）；③ `--remote` 与国际服 YoStar 独立解包源逐关键帧比对。

原始抓取缓存位于 `data/source/`，已在 `.gitignore` 中忽略（体积大、可随时重建），不会提交进仓库。

### 精确固定练度面板是怎么算的

PRTS 的 `{{属性}}` 模板只存 4 个等级锚点（E0 Lv1、E0 满级、E1 满级、E2 满级），没有成长曲线，无法直接得到模式固定等级。因此：

1. `data/mode_levels.json` 记录游戏内实测的六等阶练度固定规则（初始/精锐的精英阶段、等级、技能 Rank、模组等级；技能无专精，封顶 Rank7）。
2. `tools/fetch_game_data.py` 拉取社区解包表 `character_table.json`，每个干员的每个精英阶段含 Lv1 与满级两个 `attributesKeyFrames`。
3. `tools/parse_mode_stats.py` 在两帧间按客户端相同方式**线性插值并四舍五入**，叠加 `favorKeyFrames` 的 100% 信赖固定加值，产出 `data/operator_mode_stats.json`（141 人，初始 + 精锐两态）。

线性插值不是近似假设：解包表每阶段只存首尾两帧、无逐级行，客户端显示中间级只能在两帧间插值；独立的游戏数值设计资料亦确认同精英阶段内属性为线性成长。该结论已用国际服第二独立解包源逐关键帧零差异对撞验证（见上）。

### 战斗指标（阶段 A：重塑战斗分的底层数据）

`tools/parse_combat_metrics.py` 基于精确面板 + Rank7 技能表产出 `data/operator_combat_metrics.json`，用物理意义明确的指标替代星级代理：

- **有效血量 EHP**：物理 `hp/(1-def/(def+100))`、法术 `hp/(1-res/100)`，分类型承伤能力。
- **裸 DPS**：固定练度攻击/攻击间隔。
- **技能 DPS（对单/对群）与医疗 HPS**：解析 skill_table 的 blackboard 倍率。关键语义已用游戏技能文本验证——`atk` 键是**增量**（有效倍率 = 1+atk），`atk_scale`/`heal_scale` 是**总倍率**；固定读 Rank7（levels[6]），不读专精行。
- 召唤/解放/额外投射物/瞬抬治疗等无法用单值表达的机制不硬算，进入 `needs_review`；有数值但附带副作用/条件的进 `notes`，不污染可用性。
- 局限：技能 DPS 为开启期理论值（未建模回转覆盖率）；伤害类型（物/法/真/元素）无干净字段，分类总伤与破甲线属后续阶段 B/C。

### 伤害画像（阶段 B：伤害类型分类 + 破甲线 + 标准档总伤）

解包表没有干净的 `damageType` 字段（模式技能该字段全为 null），因此用三层裁决解析伤害类型，强信号优先：

1. **技能文本关键词**（法术伤害/物理伤害/真实伤害/元素损伤）→ 技能级判定，`source=text`；
2. **特性文本** `native_trait` 关键词 → `source=trait`；
3. **职业默认 + 分支例外**（由真实文本审计得出，非凭记忆）→ `source=default`。

实现为两个零 I/O 纯逻辑模块（`advisor/damage_type.py`、`advisor/damage_calc.py`），便于单测。关键设计：

- **元素损伤是副标签**：神经/侵蚀/灼燃/凋亡附着在物/法主类型上（如本源术师 = 法术 + 元素），不替代主类型。
- **混合类型不硬猜**：单技能含多种伤害类型（如温蒂液氮大炮 = 法术主体 + 位移真伤副效果）不静默套分支默认，先标 `mixed_text`，再由 `data/damage_type_overrides.json` 按 `skill_id` 人工裁定（以主体伤害为准），命中后 `source=override`。这也是后续 ArkDPS 对拍偏差 >5% 时的统一修正入口。
- **护盾不造假数**：吸收伤害的屏障（如夜莺法术护盾）不会因含“法术伤害”字样被判成攻击；矩阵只在阶段 A 产出真实进攻数值（`single_dps`）时生成。

伤害结算与标准档（`tools/parse_damage_profiles.py` → `data/operator_damage_profiles.json`）：

- 物理单次 `max(ATK-DEF, ATK*0.05)`（5% 保底）；破甲线 `DEF=0.95*ATK`、半伤线 `DEF=0.5*ATK`。
- 法术单次 `ATK*(1-RES/100)`，RES 封顶 95；半伤抗性恒为 50。
- 真伤无视双抗；治疗（HEAL）单独成系，不进伤害矩阵。
- **标准采样档**：防御 `[0,100,200,300,400,500,600,800,1000]`、法抗 `[0,10,20,30,40,50,60,70,90]`。ArkDPS 实为 0..1000 连续滑杆、无离散档（经 bundle 逆向确认）；本项目用覆盖全区间的离散档落地 JSON，每个采样点都能在其滑杆输入同值对拍。
- 局限：元素损伤结算、回转覆盖率（周期 DPS）留待阶段 C；矩阵为单次技能动作（含连击/对群）在各档位的伤害。

### 护甲契合 effDps（决策层接入伤害矩阵：看菜下饭）

借鉴 Stronghold bot 的 effDps 思想（**只学方法论，不拷 GPL 代码/数值**），把阶段 B 的伤害矩阵接回选牌评分，让建议随本回合敌人画像变化：

- 模块 `advisor/effdps.py`（纯逻辑，仅依赖标准库与已生成的 JSON）。折减系数用阶段 B 的**连续伤害公式**按真实 DEF/RES 现算（不再读离散矩阵列），因此 DEF 超过旧矩阵 1000 采样上限也能正确落到 5% 保底，**不新造任何敌人数值**。
- **真实敌人数值（已替换旧的三档猜测）**：`tools/build_enemy_stats.py` 从官方解包表 `enemy_database.json` 抽每个敌人的 **level-0** 真实 hp/atk/def/res，产出 `data/enemy_stats.json`（179 敌人全覆盖，名录保持纯定性、数值独立存放；仅官方 Kengxxiao 表 + 自有解析，无 GPL 数据）。`GameState` 只带 9 个战术分类，故按分类取**可出现敌人里最肉的真实 def/res**（延续旧“对最肉敌人也要成立”的最坏值哲学，只是来源从猜测变实测）。DEF/RES 为静态 level-0 值，不随规程等级缩放；敌人血量另由 `advisor/regulation_hp.py` 单独乘等级系数。
- 物理干员按真实 DEF、法术干员按真实 RES 折减；真伤系数恒 1.0；治疗/纯坦无攻击矩阵 → 返回 None（护甲中性，不加分也不编数）。混合伤害类型干员（14 名）优先选与 `baseline_damage_type` 同族的技能矩阵。
- 引擎接入（`engine.py`）：**仅当 `GameState.enemy_types` 非空时启用**，按本店最高 effDps 归一化给最多 `EFFDPS_FULL=18` 分（低于羁绊阈值 60 与三合一 100，只在回合内细化选择、不喧宾夺主），并在理由里输出“护甲契合 effDps…（抗性折减 X%）”。无敌人画像时该项完全情性，旧评分逐字节不变（有测试钉住）。**实测反转旧假设**：折射组真实为高防（worst def 1100）低抗（worst res 20），折射波次下法系卡达保留约 80% 伤害、物理幽灵鲨被压到 5% 保底，故折射应上法系而非物理。测试 `tests/test_effdps.py`（17 项）。

### 敌人特例对策层 + gate0 队伍缺口检测（按具体敌人名触发的附加分）

九分类（`counters.py`）回答“**这一张牌**对本波类型的克制分”，会给所有沾边的卡都加分；它无法表达“队里其实已经有解了”。这两层补的是**队级**问题：“当前棋盘是不是存在一个本波必需、却完全没人能提供的能力？”只在真正的盲区才发动。

- **特例对策层（`advisor/special_counters.py` + `data/enemy_special_cases.json`）**：按**具体敌人名**（不是九分类）触发，收录官方手册 `abilityList[].textFormat == "SILENCE"` 的**全部 61 个可沉默敌人**（SILENCE 是客户端唯一结构化反制标记），按机制自动归 10 族：冰系死亡爆炸(5)/死亡分裂(8)/死亡触发(5)/敌方光环(3)/团队削弱(4)/攻击控制(8)/召唤充能(4)/持续元素(2)/攻击强化(8)，外加 `refraction_essence` 折射族(14)。**两层防重复计**：折射族 14 个沉默非首选（主对策是法系/穿甲），标 `generic_covered=true` 仅存档不触发；其余 47 个 `generic_covered=false` 按敌人名驱动 gate0 沉默缺口。证据门控：`tools/build_enemy_special_cases.py` 全量自动归族（规则按特异性排序），断言每个 SILENCE 敌人都落到命名族、漏网进 `other_silence/needs_review` 并醒目报错（当前 needs_review=0），赛季改数据不会静默漏敌；库内只存族标签 + 对策 + 官方能力原文证据 + PRTS 链接，运行期不读介绍文本。沉默来源本地可验证：拉普兰德/荒芜拉普兰德/霍尔海雅（`mechanic_tags` 含 silence）+ 奥术法阵（`items_structured.mechanics=['silence']`）+ 精准羁绊里程碑。测试 `tests/test_special_counters.py`（8 项，钉住 61/47/14 与折射不触发）。
- **gate0 缺口检测（`advisor/team_gaps.py`，纯布尔、无战斗模拟）**：三类确定性盲区——`anti_air`（飞行波但场上无人对空）、`refraction`（折射波但既无法系也无穿甲/真伤）、`silence`（特例敌人要沉默但场上无人沉默，由 `enemy_names` 驱动，不与九分类的 stealth/revival 重复计）。只有 board **完全**无提供者才算缺口，一旦补上自动关闭。
- **引擎接入（`engine.py` 第 8 步，纯附加、可解释）**：`recommend()` 每波算一次 `detect_team_gaps`，对能**关闭当前开放缺口**的卡按优先级给主缺口 `GAP_BONUS_PRIMARY=15`、其余次缺口各 +8，**硬顶 `GAP_BONUS_CAP=28`**（不再按 +15×N 无界叠；低于羁绊 60 / 三合一 100）；道具仅沉默缺口可由奥术法阵关闭。无敌人画像或无缺口时恒为 0。输出 `team_gaps` 块，理由带“补缺·…”。测试 `tests/test_team_gaps.py` + 引擎集成。这是局内自适应路线的阶段 0（确定性布尔）。
- **评分权重方向（2026-11-13）**：三连/2→3 保持高分（+100，不压进 soft band）；投资型 `INVEST_WEIGHT` 上调；刷新改用 ASSUMED `shop_odds.tier_probs` × 槽位 × 余钱的 EV（可压过非关键 1 张推进，仍低于羁绊差1 / 2→3）。测试见 `tests/test_engine.py` 权重三项。

### 阶段 1：连续清场裕度（`advisor/clear_margin.py`，真实出怪窗口驱动）

gate0 只判“有没有解”（布尔），阶段 1 判“火力够不够在时间内清完”（连续量），全部基于官方解包数据、无占位常量：

- **数据获取**：`tools/fetch_act3_levels.py` 从 Kengxxiao 官方仓库抓回 62 个 act3 关卡（三 CDN 回退，落 gitignored 的 `data/source/gamedata/levels/...`，不进 git）。出怪在 `waves[].fragments[].actions[]`（SPAWN 自带 count/preDelay/interval/routeIndex），`enemy_database` 给每个出怪 id 的 level-0 maxHp/moveSpeed（含不在 179 战术名录里的普通填充怪，实测 unmapped=0），关卡 `options.moveMultiplier=0.5` + `routes` 给移动。
- **派生**：`tools/build_act3_waves.py` → `data/act3_waves.json`，61 关每关算总血、出怪时间线与 `clear_window_t = max(last_spawn + 路径长/(moveSpeed×moveMultiplier))`；同时存 `round_to_level`（`activity_table` 的 battleDataDict，mode_single_1..20 正好对应规程 L1..20，多人四难度锚同一套关卡）。残留近似（显式记在 `_meta.approximations`）：地面 WALK 无 checkpoints，路径先按 Manhattan，FLY 按折点；moveSpeed 的格/秒标定是 `clear_margin` 单点常量。
- **运行时**：`enemy_hp = 关总血 × regulation_hp 规程乘数`、`team_dps = Σ board 干员 effdps`（复用护甲契合的 worst-case 折减，治疗/无矩阵干员跳过不造数）、`margin = team_dps × clear_window / enemy_hp`，1.0 为临界，分 critical/tight/adequate/comfortable 四档。`GameState` 新增 `regulation_level`(1..20，开局 OCR，与调度中心等级区分，向后兼容)。
- **干员加成（`advisor/buffs.py`，净室不 import scaling）**：裸面板 effDps 再乘三来源——①羁绊面板 `bond_panel_formulas.json`（激活即给层数 0 基础加成，如炎 atk+23%；scope bond/all/ranged 与 condition 过滤，additive/total 两种公式）；②逐层规则 `bond_scaling.json`（12 干员每 N 层 +X%，吃 `GameState.bond_stacks`）；③装备 `items_structured.stat_mods` 的 atk_pct/aspd（吃新增的 `GameState.equipment` 干员→道具映射）；另按 `BoardUnit.elite` 乘精锐面板比（elite/initial base_dps，141 干员全覆盖）。新增 `bond_stacks`/`equipment` 两个可选字段，默认空中性、旧 state 逐字节兼容；无层数时激活羁绊仍有基础加成，逐层成长等层数 OCR。物理折减仍按基础面板（忽略攻击 buff 对折减的二阶改善，保守方向）。测试 `tests/test_buffs.py`（8 项）。
- **引擎接入（第 9 步，纯附加、inert）**：critical/tight 波次给输出卡加 12/6 分（治疗不加）；comfortable 抬升本 +10、critical 压升本 −15（不在将漏时劝升本）。无敌人画像/空 board/关卡解析不出/无有效 DPS 时返回 None、零影响。输出新增 `clear_margin` 块（含每干员 `board_dps_detail` 加成明细）。测试 `tests/test_clear_margin.py`（17 项）+ 引擎集成 2 项。阶段 2 battle 内核待续。

### 独立乘数层（scaling：敌人等级 / 羁绊面板，引擎解耦）

> ⚠️ **版本归属（2026-11-13 用户拍板）**：本小节的 `advisor/scaling.py`（`DISPATCH_LEVEL_COEFF` ×1.0→×1.5）属**上版本 act1/act2「盟约」**体系，当前 act3「规程」**不采用、不接入**，文件仅保留作跨版本参考（引擎被测试硬禁 import，本就未通电）。当前版本的敌人成长只有 **HP 一条轴有权威实测**，由独立的净室模块 `advisor/regulation_hp.py` 承载（见下）；ATK/DEF/RES 无逐等级系数，DEF/RES 用 `enemy_stats.json` 的 level-0 静态值。

**act3 规程领袖 HP 曲线（`advisor/regulation_hp.py`，净室自有、不依赖 scaling.py）**：从 PRTS 用户实测领袖表反推的全局乘法，10 个 boss 同系数、重构零误差。L1=1 → L8=10/3 → L14=25/3 → **L20=125/9（≈×13.89）**，三段步长 1/3、5/6、25/27；难度四档锚定同曲线（标准/险境/绝境/终极 = L1/8/14/20），极速模拟 = 0.8×L1。只管 HP，禁止外推到 ATK/DEF/RES；未知等级/模式返回中性 1.0。测试 `tests/test_regulation_hp.py`（8 项）。

固定练度面板（阶段 A/B）不含两个局内 scaling 效果，单独由 `advisor/scaling.py` 处理。该模块**不被 `engine.py` 导入**（有测试断言解耦），决策引擎保持不动；只在需要算局内实际数值时由上层显式调用。

- **敌人随规程等级**：`DISPATCH_LEVEL_COEFF` 录入机制文档 08 的 AC-SP-1..20 总系数表（×1.0→×1.5，作用于敌人 HP/ATK），同盟四档（标准/险境/绝境/终极）另有 `ALLIANCE_COEFF`。
- **干员随羁绊（两套并存机制）**：
  1. **干员个人「作战能力」**：`tools/parse_bond_scaling.py` 从干员条目提取「每 N 层攻击力 +X%」→ `data/bond_scaling.json`（12 名干员，基础/进阶两档），乘数 = `1 +(层数//N)*X%`。
  2. **核心/附加盟约全局面板公式**：本地 BWiki wikitext 只写「受层数影响」，具体表达式取自 **PRTS 盟约记录页**（游戏内动态占位的展开值），整理为 `data/bond_panel_formulas.json`。全是线性式 `(基数+斜率×层数)%`，覆盖攻/防/血：炎(攻)、阿戈尔(血)、坚守(全体血)、助力(全体防)、精准(高台攻)、突袭(技能期攻+血)、维多利亚/谢拉格(条件伤害)。`scaling.bond_panel_multipliers()` 按 PRTS「直接乘算」语义组合多盟约，条件型加成（携带装备/技能期/寒冷）默认不自动套用、需调用方显式声明。
- 另含机制文档 07 的**账号练度加成表**（攻/防/血 +5%/+10%）。
- **诚实的数据边界（不造假）**：本地 wiki **没有**敌人「抗性逐等级」独立数值表，只有总系数和干员侧「无视 X 法抗」；因此敌人 RES/DEF 逐等级增量是显式配置槽（`ENEMY_RES_DELTA`/`ENEMY_DEF_DELTA`，默认空 → 增量 0），日后拿到实测值直接填表、调用处与中性路径测试都不用改。攻速/技力/概率类盟约（萨尔贡/拉特兰/灵巧/迅捷/不屈/奇迹等）不直接改攻/防/血面板，未纳入乘数表。

### 战场模拟内核（advisor/battle：净室重写的 tick 协议引擎）

在阶段 A/B 的静态指标之外，新增一套**离散时间战场模拟内核**，用于回答静态 DPS 覆盖不了的问题：波次叠加的阵线压力、阻挡/漏水、出怪节奏。方法论参考开源 Stronghold-Protocol 的战场「协议」（tick 顺序、属性聚合、伤害管线、阻挡、出怪队列），但**全部用本项目自有 Python 独立重写，不拷贝、不 import 其任何 GPL 代码或数据**（参考源仅存于 gitignored 的 `data/source/_stronghold/`，字段对照见 `docs/stronghold_engine_mapping.md`）。

- `clock.py`：30Hz 固定步长（`TICK=1/30`），时间由整数 tick 推导，长局无浮点漂移。
- `unit.py`：属性聚合 `ATK=((基础+加算)*(1+百分和)+最终加算)*乘区积*练度`，**严格区分 `*_pct`（同类相加）与 `*_mul`（独立乘区）**；攻速 `aspd=clamp(100+Σ,20,600)`、间隔 `interval=bat*100/aspd`。
  - **订正硬 bug #2**：「攻击间隔 +X 秒」走 BAT **绝对加算**通道 `add_bat_flat()`（夕 S3 `base_bat+0.40` → 3.30s），与旧的 `interval×1.4`（4.06s 偏高）彻底区分；`add_bat_pct()` 才是百分比通道。
- `damage.py`：复用阶段 B 减伤公式，补穿甲（先固定后百分比）与受伤乘区，物理/法术均保留 5% 保底。
- `blocking.py`：接触阻挡，地面/空中/装置三种阻挡半径，按阻挡容量与 block_weight 判定，每 tick 3×3 扫描取最近者。
- `wave.py`：`WaveScheduler` 把出怪表展开成 tick 对齐事件；`ReservoirPressure` 蓄水池模型量化前后波叠加——每阻挡格 `L(t+Δt)=max(0,L+(λ-μ)Δt)`，λ 为出怪流入率、μ 为守军有效击杀率，超容量累计 `overflow_time` 即漏水风险。
- `battle.py`：按协议固定顺序编排 tick（出怪→敌人移动/阻挡→友军攻击→蓄水池推进→结束判定），DP/投射物/boss/再部署留显式扩展点。
- 测试 `tests/test_battle_kernel.py`（25 项）钉住间隔口径、穿甲顺序、阻挡容量、蓄水池涨落与端到端 clear/timeout。

### 阶段 2.1/2.2：真实数据适配与离散交叉校验（`advisor/battle/adapter.py`）

首切内核只吃合成 `SpawnSpec`/手搓 Unit，与真实关卡和引擎断线。适配层把决策层真实数据缝进内核，**纯映射、无 GPL、不 import scaling**：

- **敌人**：`act3_waves` 的 `spawns[]` → `SpawnSpec`（first_spawn_t/count/interval/route 直接对应）+ enemy `Unit`；HP 套 `regulation_hp` 规程乘数，def/res/motion 直接取自解包 spawn 行（覆盖率 100%，不依赖 enemy_stats join）；飞行由 `motion==FLY` 设定。
- **我方**：`GameState.board` + combat_metrics + `buffs` → ally `Unit`；atk/interval 取面板，羁绊/逐层/装备/精锐通过内核**自带 ModBucket** 施加（保证 BAT/ASPD 间隔口径仍由内核权威计算）。
- **运动常数护栏**：61 关 `move_multiplier` 全为 0.5，恰等于内核 `MOVE_SCALE`；适配器显式校验，一旦不一致写进 `approximations` 而非隐式漂移。
- **真实射程（阶段 2.3 已替换粗默认）**：干员普攻射程不再用近战 1 格/远程 3 格的欧氏圆猜测，改由 `data/operator_ranges.json`（官方 `character_table.rangeId`→`range_table.grids` 派生的真实偏移格集合，141 人全覆盖、25 种形状、72 人精英化后射程变化）驱动；适配器按红门朝向镜像成世界偏移后写入 `Unit.range_cells`，内核 `_acquire_target` 做纯格 membership（`range_cells=None` 时回退旧欧氏规则，旧测试不变）。
- **敌人会还手（阶段 2.3）**：`data/enemy_attack.json`（`build_enemy_attack.py` 从完整官方 `enemy_database.json` 2234 敌人按 act3 的 49 个出怪 id 派生，42 个攻击单位/7 个非攻击）提供 atk/baseAttackTime/applyWay/rangeRadius；内核新增 `_update_enemy_attacks`——被阻挡敌人打阻挡者、RANGED/ALL 敌人按射程索敌，伤害走同一 `deal_hit` 干路吃干员真实 DEF/RES 减伤，干员阵亡释放阻挡并计 `ally_losses`。真实关卡验证：level_03 灵幛(at力900)潮下陨星承伤 807、一名干员阵亡。诚实边界：官方表无普攻物理/法术类型字段，敌人普攻按物理处理（`_meta.needs_review` 标注）。
- **诚实近似（随结果返回，不隐藏）**：阻挡数仍用职业粗默认（重装挡 3 等，无逐干员阻挡数据）；射程朝向按“统一面朝红门”镜像，实战朝向待核验；多路线折叠为单车道以触发阻挡；敌人普攻物理假设；DP/弹道/治疗/boss 机制未驱动。已驱动的技能范围见阶段 2.4。

### 阶段 2.4：我方/敌方技能驱动（净室状态机，`advisor/battle/skills.py`）

首切内核把干员当纯普攻、敌人技能完全不驱动，系统性低估输出与威胁。阶段 2.4 用官方表的确定性字段补上**可干净建模**的子集，复杂机制诚实存档不硬造：

- **我方定时爆发（`data/operator_skills.json`，`build_operator_skills.py`）**：join `skill_table.spData`（spCost/increment/initSp）与 combat_metrics 的倍率/持续。只收 `INCREASE_WITH_TIME` 自动回复 + additive 攻击力强化 + 倍率>1 + 有限持续的技能（充能=spCost/increment，SP 满自动触发、激活 duration 秒后回充），覆盖 **80/141 干员**。多候选取最高倍率作代表爆发。`total` 来源且倍率≤1 的（钙质化 0.2、沸血燎原 0.35 等 DoT/控制/多段法伤）放进 `special_skill_ids` 存档——它们的数值是每跳占 ATK 比例而非攻击 buff，套成 ATK×0.2 方向就错了。受击/受伤回复（46+6 个）与 spType=8（11 个）依赖战斗事件，本轮不做。
- **内核可逆 buff**：技能倍率走独立的 `Unit.skill_atk_mul`（不混进常驻 mods 桶），`SkillCycle` 充能→激活→回充状态机只在状态切换时 `mark_dirty`，窗口结束精确撤回 1.0。E2E：同队带技能总伤 13659.8 vs 纯普攻 13318.2（+2.6%，短局充能覆盖有限，未虚高），关闭后 `skill_cycles={}`。
- **敌方周期 AoE（物理/法术双通道，`data/enemy_skills.json`，`build_enemy_skills.py`）**：敌人技能高度异构（31/49 有技能，多为召唤/护盾/控制/光环/多阶段 boss）。严格筛选“有限冷却>0+正 atk_scale+有 range_radius+无控制/召唤/护盾/链式键”，伤害家族由**官方描述的“法术伤害”字样裁决**（敌人表无 damageType 字段，无标签则默认物理）。当前 3 个合格：**矩兽 CombatAoe**（atk1500×2.0、range1.6、cd2.0，物理）+ **假想敌：鳍两形态 Discharge**（750×1.25、range1.5、cd24，**法术**）；其余按原因（非周期/无倍率/无 AoE 射程/控制召唤护盾链式）`parked` 存档不猜。内核 `_update_enemy_bursts`（tick 6c）命中范围内所有干员，按 `damage_family` 走 `deal_hit` 的物理（DEF）或法术（RES）主干（都保留 5% 保底），击杀同样释放阻挡。接触点验证：矩兽 5s 2 次物理 AoE 共 4899 伤、1.6 格外零承伤；鳍 Discharge 对 RES0 的拜松打全额 937.5（DEF554 不减免，证明走法术）、对 RES10 的塞雷娅打 843.75（精确吃 10% 法抗）、1.5 格外零承伤。
- **诚实边界**：`ep_damage_ratio` 是**元素（神经）损伤比例而非法伤**——鳍的法术主体已驱动，其 0.4 神经损伤仍存 `elemental_ratio_parked`；昆图斯多阶段、链式传导（chain.atk_scale）、淤困寄生 DoT、召唤物、眩晕/减攻速光环、护盾减伤均**未驱动**（需新增元素/链式/抗性子系统）；敌人普攻因表内无类型字段仍按物理假设；AoE 射程用欧氏圆近似（官方 prefab 形状可能不同）；爆发用 level-0 基础 ATK，不随战斗内 ATK 状态变化。
- **inert 接入引擎**：`recommend` 输出新增 `battle_sim` 块（try 防护，绝不影响 actions/评分）；空 board/无法解析模式时为 None。测试 `tests/test_battle_adapter.py`（17 项，含格化索敌与真实网格注入）+ 引擎集成 3 项。
- **2.2 交叉校验结论**：同一弱/中/强三支队伍，闭式 `clear_margin` 与离散模拟**方向一致**——弱/中 margin≈0.2（critical）模拟均漏 1 个、卡窗口清完；强队 margin 4.07（comfortable）零漏、提前到 48.9s 全清。两条独立算法互为佐证，当前仅 inert 对照、不进总分。

### 阵容层（advisor/lineup.py：跨回合构筑路线，comp library）

单回合选牌（engine）只回答"这商店买哪张"，阵容层回答更上层的问题：**这局该走哪套体系、每个阶段（过渡/中期/大成）具体追哪些人、这套体系克制什么敌人**。

- `data/lineups.json`：人工编排的 13 套 archetype，全部成员与本数（shop_tier）取自真实数据集，`tools/validate_lineups.py` 零误差对账（不凭记忆造名）。默认假设所有种族都在，局内 ban 选由模块参数过滤、不写死进库。
  - **战斗型 9 套**（侧重克制）：奥术法反隐、精准卡西米尔穿甲、伊比利亚乌萨斯 DOT、坚守聚合铁卫续航（4 套首批）+ 炎国元素损伤、萨尔贡流沙控制、维多利亚装备重锤、谢拉格冰冻控制、叙拉古异常真伤（6 大核心羁绊各成一队）。
  - **成长型 2 套**：阿戈尔吞噬成长（战斗内吞前排养层、6 人复活）、莱塔尼亚召唤成长（击倒招“小节”、6 人升级乐部、召唤上限 20）。
  - **发育型 1 套**：投资人奇迹滚雪球（获得时触发翻倍+免费刷新，抢升本节奏）。
  - **万用挂件型 1 套（flex）**：**调和魔王体系**——调和 `activation_need=1`，激活即让场上每个核心盟约激活人数 +1，等价于可下掉任意阵容的一个凑数挂件；魔王（T6 吟游者，不攻击、群疗+微尘+真伤束缚+复活）是群保插件，配合复奏/卡涅利安/锏等多羁绊枢纽同时开更多盟约。某英雄开局赠送的调和“盟约·辅助干员”是运行时临时单位（不在干员数据集，库中只在 `special_mechanic.hero_gift` 描述、不伪造为可校验 unit）。
  - 每套含 early/mid/late 三阶段（人口目标 + 具体干员 + 本数 + 角色定位）、carry/tank/heal 名单、counters/weak 敌人 key、key_tips；魔王体系额外带 `special_mechanic` 结构化机制说明。
- `lineup.recommend_lineups(enemy_types, banned_bonds, available_operators)`：按敌人画像算克制契合分（命中 +10/个、劣势 −8/个）排序，无画像时退化为战斗>万用>成长>发育的稳定序；核心羁绊被 ban 或大核不可得时过滤掉（ban 调和会移除魔王体系）。
- 测试 `tests/test_lineup.py`（19 项）：库一致性、本数曲线、克制排序（隐匿→反隐队第一、折射→物理压过法术、致命→魔王群保前移）、ban/可用性过滤、中性回退、魔王特殊机制与英雄临时单位不伪造。

### 阵容罗盘（advisor/compass.py：把阵容库接进买卡决策）

此前 `lineup.py` 是孤岛——只被自身测试引用，引擎逐卡局部打分、没有跨回合方向，导致商店推荐“各买各的、不凑羁绊”。罗盘补上这层，让选牌向同一套体系收敛：

- **自动推断方向（无需手填 target_bond）**：`infer_lineup` 从已拥有 board 推断在打哪套。证据强度：**具名重合**（board 干员出现在某阵容 early/mid/late 名单，权重 3）> **核心羁绊覆盖**（board 已开某阵容 core_bond，权重 2）。置信分级：≥2 具名或 ≥2 核心羁绊 = `strong`（全权引导）；仅 1 具名 = `weak`（×0.6 轻引导）；空 board 或纯羁绊弱证据不给强方向。空 board 但有敌人画像时，回退到按 `recommend_lineups` 选最克制阵容并显式标 `source=enemy_fallback`。
- **买卡协同分**：`on_plan_bonus` 给计划内干员加分——名单内 **carry +34**、其他名单成员（tank/heal/control）**+26**、不在名单但带核心羁绊 **+18**（弱方向再 ×0.6）。分值刻意压在三合一（100）/羁绊差1人（60）之下、高于旧的通用羁绊 +12，只负责“定方向”，不覆盖硬优先级；计划外卡加 0。引擎 `_score_operator` 注入，输出新增 `lineup` 摘要块（id/name/confidence/source/core_bonds/具名重合/克制）。
- **零回归保证**：推断不出方向（空 board 且无敌人）时返回 None，协同项完全情性，旧评分逐字节不变（428 旧测试全过）。实测：board 有 Miss.Christine+伊桑（奥术队）时，同本同价的卡达（奥术 carry）43 分压过烈夏（乌萨斯散卡）14 分并成为 top_pick；杂散多体系 board 只给 weak 不强锁。
- 测试 `tests/test_compass.py`（15 项）：推断强/弱/无/敌人回退、carry/member/core/off-plan 协同分与弱方向折扣、引擎端到端“计划内压过散卡”、无方向时旧行为。

### 构筑路线与换队（advisor/roadmap.py：把完整阵容用起来）

罗盘只回答“在打哪套 + 这张卡加不加分”，roadmap 把库里现成的三阶段构筑曲线与克制关系变成可执行规划，引擎输出新增 `roadmap`/`pivot` 两块（无方向时均为 null）：

- **完整阵容而非几个核心**：`roadmap.stages` 给出 early（过渡，人口 4-5）/mid（6-7）/late（大成，8 人满配）**全部具名单位**，每个带本数/角色/备注/`owned` 是否已拥有标记，外加每阶段 `goal`（如“先凑 2 奥术激活”“冲 3 奥术里程碑反隐”）、`roles`（carry/tank/heal 名单）、`key_tips`、`ownership`（已拥有/计划总数）。
- **当前阶段 + 下一步追谁**：`current_stage(dispatch_level)` 按调度等级映射阶段（1-2=early、3-4=mid、5-6=late）；`next_targets` 只列**当前本数刷得到（shop_tier≤等级）且尚未拥有**的计划单位，按 carry>tank>heal 优先级排序（如 level2 只给卡达/褐果，自动排除 T3+ 的中期人）。
- **遇特定敌人的换队建议 `pivot`**：仅当 `enemy_types` 命中当前阵容库内 `weak` 弱点 key 时触发。输出 `weak_hit`、库里的补救文案 `weak_why`（多为“外挂某类干员”）、以及**直接克制该敌人的其他阵容** `alternatives`（带 counter_why，排除自身与被 ban 核心羁绊的队）。有可转体系→`should_pivot=true` 给换队裁决；克制队全被 ban→false，建议走外挂补救。它只建议、不自动改写罗盘方向。实测奥术队遇折射→推荐卡西米尔穿甲/叙拉古真伤/维多利亚三队。
- 测试 `tests/test_roadmap.py`（14 项）：阶段映射/钳制、三阶段完整性、拥有标记与计数、本数门控的 next_targets、换队触发/中性不触发/全 ban 回退、引擎端到端与无方向 null。

### 局内环境：敌方词条与 ban 位

- **敌方词条（已接打分，非新功能）**：`GameState.enemy_types`（9 大战术分类 key，如 `stealth`/`flying`）驱动三处——`counters.counter_score` 本体/盟约里程碑克制分（×0.6 入买卡分，含“差 N 人解锁反制”与反协同警告）、`effdps` 按敌方**真实 level-0 DEF/RES**（`data/enemy_stats.json`，连续伤害公式）折减后的护甲契合分、阵容罗盘/`recommend_lineups` 的克制选队。入口 `--enemy-types a,b` 或 `--enemy-shot` 放大镜面板 OCR。
- **ban 位（本次补齐）**：`GameState` 新增 `banned_operators`/`banned_bonds`（默认空、向后兼容，旧 state 无这两字段照常加载）。禁干员在引擎买卡遍历**硬跳过、永不推荐**（全禁时仍给升本/刷新，不会哑火）；禁羁绊让阵容罗盘与 `recommend_lineups` **排除以该羁绊为核心的阵容**（board 推断与敌人回退都生效），但不会否决仅共享该羁绊的单卡。CLI：`--ban-operator 卡达,烈夏`、`--ban-bond 奥术`（逗号分隔），也可写进 state JSON，两路合并去重。测试 `tests/test_bans.py`（8 项）。

### 莱塔尼亚召唤物 DPS（advisor/summon_dps.py：羁绊召唤物专项）

莱塔尼亚核心羁绊击倒敌人召唤的“一个小节/一个乐部”在游戏内按**敌方单位**（SP32/SP33）建模，标准解包表（character_table）与 Stronghold 复刻版（tokens.json 仅 21 个通用 token）都没有；数据从 PRTS 单位页转录到 `data/leithanien_summons.json`（含来源 URL，只存数值事实与短机制转述、不整段搬文案）。

- **事实属性**：小节 HP2350/ATK450/近战/阻挡 1；乐部 HP8500/ATK950/DEF450/RES30/远程/阻挡 2；两者攻击间隔均 3.0s、法术伤害。
- **寿命机制**：均带**禁疗**且每秒流失 10% 最大生命 → 理论 10 秒离场（`NOMINAL_LIFETIME_SEC`），受 3s 间隔限制一生约攻击 3 次。
- **乐部双击周期**：每 3 次攻击后下次 2 连击（4 动作 / 5 命中 = 1.25 命中每动作），并有“在场使莱塔尼亚干员（不含调和）攻速 +20、可叠加”光环。
- **计算口径（输出）**：`panel_dps`（裸）、`effective_dps(stacks, uptime)`（含盟约 +(30+层数)% 攻击加成与走路折损 uptime）、`lifetime_estimate`（一生命中数/总伤）、`formation_upper_bound`（满槽位聚合天花板，明确 `ceiling_only` 非预测）。
- **承伤维度（tank，召唤物会主动追踪并阻挡地面敌人，是临时前排）**：复用 battle 内核同款减伤（物理 `max(ATK−DEF,5%)`、法术 `max(ATK×(1−RES),5%)`、真伤穿透）。`damage_per_hit`/`incoming_dps_from` 给减伤后每下/每秒承伤，`hits_survived` 给纯吃伤击杀数，`survival_seconds` 给“10 秒衰减 vs 被打死”双时钟取 min 的实际在场时间，`tank_profile` 输出决策级汇总（阻挡数按 block_count 限流同时受敌数、为后排吸收的总伤 `damage_absorbed_for_team`）。实测量级：乐部（HP8500/DEF450/RES30/阻挡2）吃 600 物攻仅 150/下、要 57 下，是真坦克；小节（HP2350/零双抗/阻挡1）4 下即熔，只作廉价阻挡垫。
- **诚实边界**：敌人法抗折减、走路到接敌时间、每波实际召唤数量、PRTS 标注（待补充）的归属规则均未建模，缺数返回 None/显式标注、不插值。**选牌引擎已接入**：`summon_synergy_value` 在玩家走莱塔尼亚（目标羁绊或场上已有成员）时给体系成员按 3 人激活/6 人里程碑加分并输出中文理由，非莱塔尼亚上下文完全情性；battle tick 内核的逐召唤物实体模拟仍待做。
- 测试：`tests/test_summon_dps.py`（31 项：PRTS 数值/加成/双击/寿命/容量/减伤承伤/双时钟）+ `tests/test_engine.py` 新增 5 项端到端（情性、非成员不加分、第 3 人激活、build 内提分、6 人里程碑理由）。

## 手动局面 JSON

见 `examples/state_demo.json`，字段对应 `advisor/model.py`：回合、资金、调度等级、难度、目标盟约、商店 5 张牌、已拥有阵容。引擎输出每个动作的分数、中文理由、盟约激活状态与首选建议。

## 路线图

- [x] 数据层 + 硬规则 + 启发式决策 + 手动 JSON CLI
- [x] MAA 式 OCR 识别管线（归一化 ROI + 预处理 + RapidOCR + 字典模糊匹配）
- [x] 统一边际影响标尺（三轴 + 机会成本）与装备三轴评分
- [x] 游戏内实测练度固定规则 + 解包表插值的精确固定等级面板
- [x] 阶段 A 战斗指标（EHP/裸 DPS/Rank7 技能 DPS/HPS）
- [x] 阶段 B 伤害类型分类 + 破甲线 + 标准档总伤矩阵（含 override 修正表）
- [x] 独立乘数层 scaling（敌人规程等级系数 + 个人羁绊攻击规则 + PRTS 盟约全局面板公式 + 账号练度加成），与引擎解耦
- [x] 战场模拟内核 advisor/battle（净室 tick 协议：属性聚合/伤害主干/阻挡/出怪蓄水池），含硬 bug #2 间隔口径订正
- [x] 护甲契合 effDps 接入选牌（effdps.py + engine，敌人画像驱动的物/法折减，无画像时情性）
- [ ] 内核扩展点补齐：DP 经济、投射物飞行、元素爆条 gauge、boss 共享血池、击倒再部署
- [ ] 硬 bug 收尾：#1 标准形态技能 Rank4 上限（替代统一 Rank7）
- [x] #3 莱塔尼亚羁绊召唤物（小节/乐部）独立建模：输出 DPS + 承伤/阻挡 tank 模型，并接入选牌引擎（走莱塔尼亚时按 3/6 人里程碑给体系成员加分，非莱塔尼亚情性）；battle tick 逐召唤物实体模拟与其余干员个人 token 仍待做
- [ ] 接入 range_table.json 做攻击范围/地块网格，替换当前半径近似
- [ ] 用 Stronghold 运行结果对拍净室引擎（另起进程比对，偏差 >5% 排查）
- [ ] 敌人抗性/防御逐等级实测值填入 scaling 配置槽（本地 wiki 缺该表，PRTS 亦未展开）
- [ ] ArkDPS 标准档对拍，偏差 >5% 的干员进 override 表针对性修正
- [x] 用真实 2560×1440 截图端到端跑通商店识别（shop_band_ocr.py 整带 OCR + 字典吸附 + 数据集推导价格），CLI `--shot` 接入
- [x] 已拥有阵容输入桥（board_io.py + CLI `--board`，纯 stdlib 零截图：名字/字典双形态、同名合并、数据集补 bonds/tier、未知名显式警告；驱动羁绊人数/三合一/莱塔尼亚召唤里程碑，10 测试）
- [ ] 1.1：回合/金币/调度等级小数字 OCR（当前手动传入）
- [ ] 1.1：敌人放大镜面板 OCR（实测源石虫/寻险水手名+特性可读准），建「敌人名/特性 → 9 分类」映射，自动喂 enemy_types 激活对策
- [ ] 1.1：开局三界面 OCR——① 确认本局信息（核心/附加盟约 + 右侧特训敌人·隐匿/持续 画像）② 选择策略 ③ 自选编队（V/VI 阶、本局禁用）
- [ ] 评估迁移 rapidocr 3.x（后端解耦、原生 headless 声明让 pip check 干净），迁移前需重测识别并适配新 API
- [ ] 精确面板接入战力轴，替换星级代理；克制分接入引擎与未来分
- [x] 上位替代表、目标阵容构筑路线（comp library：advisor/lineup.py + data/lineups.json，13 套三阶段体系含 9 战斗/2 成长/1 发育/1 调和魔王万用，按敌人画像/ban 排序，19 测试）
- [ ] 本地大模型自然语言解说 + 桌面 overlay（只读显示）

## 数据来源与许可

- **代码与文档**：[PolyForm Noncommercial License 1.0.0](LICENSE)（非商业；完整条款见该文件）。**可以**在非商业目的下使用、修改、再分发（须保留许可与 `Required Notice`）；**不可以**用于任何商业用途，亦不得转授本许可。
- **游戏数据版权**：归 鹰角网络 / 明日方舟 IP 方所有。本仓库为非商业学习研究项目，不分发游戏客户端、不与之交互。上述 PolyForm 许可**不**覆盖 `data/source` 与派生 JSON。
- **Wiki 数据**：经第三方 Wiki（BWiki / PRTS，CC 类许可）整理，请遵守其署名与许可要求。
- **解包数值表**：来自社区项目 [`Kengxxiao/ArknightsGameData`](https://github.com/Kengxxiao/ArknightsGameData)，通过公开 CDN 拉取，版权归原权利方；本仓库仅缓存用于本地可复现构建，缓存不提交。
- 官方未公布抽棋各等阶概率，本项目不编造固定概率，只基于等级门控与实测记录决策。
- **净室合规**：`advisor/battle/` 的战场协议在方法论上参考了 GPL-3.0 的 Stronghold-Protocol，但仅学习其公开游戏机制思想，所有代码与数据均为本项目独立编写/取自自有及宽松来源；GPL 参考源不进仓库（gitignored）、不被 import。

分发或衍生时请保留上述来源声明、PolyForm 条款与合规免责声明。
