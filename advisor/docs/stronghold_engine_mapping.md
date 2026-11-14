# Stronghold-Protocol 计算引擎 → 我方净室实现 字段/方法映射

> 目的：仿照 Stronghold-Protocol（GPL-3.0，仅本地研究，代码/数据**不进**本 MIT 仓库）的
> 战场模拟「协议」（tick 主循环、属性聚合、伤害管线、阻挡、出怪队列），用我们自己的
> Python 独立重写。思想/数学公式（PRTS 公开游戏机制）不受版权保护；**不逐行搬运其 JS 代码**。
> 本文只记录"它的字段 ↔ 我们的字段 / 我们落在哪个模块"，作为净室实现与后续对拍的对照表。
>
> 参考源（gitignored，`data/source/_stronghold/repo`）：
> - `server/sim/Battle.js`               一场战斗的容器 + tick 顺序总纲
> - `server/sim/battle/lifecycle.js`     `step()` 主循环
> - `server/sim/units.js`                Unit 模型 + `_recalc()` 属性聚合
> - `server/sim/attack/calculation.js`   `mitigate()` 减伤纯函数
> - `server/sim/attack/hit.js`           完整伤害管线
> - `server/sim/battle/blocking.js`      接触阻挡
> - `server/sim/battle/spawns.js`        出怪队列/路线（蓄水池模型数据源）
> - `server/sim/constants.js`            全部可调常量

## 1. 时间步（tick）协议

| 项 | Stronghold | 我方净室 |
|---|---|---|
| 固定步长 | `TICK = 1/30` 秒（30Hz），`time = tickCount*TICK` 无浮点漂移 | `advisor/battle/clock.py::TICK=1/30`，整数 tick 计数，时间由 tick 推导 |
| 快照频率 | 每 3 tick 一帧（20Hz@2x） | 暂不做渲染快照，只保留事件流 |
| 主循环顺序 | 见下 | `advisor/battle/battle.py::step()` 同序 |

**tick 顺序（逐字取自 Battle.js 头注，作为协议规格，非代码）：**
1. scheduled callbacks（到期定时器）
2. spawns（出怪队列推进）
3. DP（部署点自然回复）
4. buffs（状态/buff 计时 tick）
5. attackCommit（攻速转好的友军锁定当前目标，先于敌人移动）
6. enemies（每个敌人：攻击、移动、阻挡判定）
7. enemy index（重建地块敌人索引，供范围查询）
8. allies（技能 tick → 攻击）
9. rate change 事件
10. projectiles（投射物飞行）
11. redeploys（击倒再部署检查）
12. boss sync
13. tick hook → 移除单位清理 → `time += TICK` → 结束判定

> 我方第一版可裁剪：DP/投射物/boss 池/再部署先留接口或简化，主循环骨架与顺序保持一致，
> 以便日后逐项补齐时不重构。

## 2. 属性聚合（units.js `_recalc`）—— 含硬 bug #2 的权威口径

```
ATK    = ((base_atk + ΣatkFlat) * (1 + ΣatkPct) + atkFinal) * ΠatkMul * cultMul.atk
DEF    =  (base_def + ΣdefFlat) * (1 + ΣdefPct)              * ΠdefMul * cultMul.def
maxHp  =  (base_hp  + ΣhpFlat)  * (1 + ΣhpPct)               * ΠhpMul  * cultMul.hp
RES    = clamp((base_res + ΣresFlat) * ΠresMul, 0, 100)
aspd   = clamp(base_aspd(默认100) + Σaspd, 20, 600)
bat    = base_bat * max(0.1, 1 + ΣbatPct)
interval = bat * 100 / aspd
```

| Stronghold 字段 | 含义 | 我方字段（`battle/unit.py::Stats`） |
|---|---|---|
| `base.bat` | 基础攻击间隔 baseAttackTime | `base_bat` |
| `aspd` | 攻速点数（100 基准） | `aspd` |
| `batPct` | 攻击间隔百分比修正 | `bat_pct` |
| `s.interval` | 实际攻击间隔（秒） | `Stats.interval`（同式计算） |
| `atkFlat/atkPct/atkMul` | 加算/百分/乘算 | 三层独立累加器（见 §6 直接乘算规则） |
| `cultMul` | 自持有练度独立乘区 | 接入现有 `scaling.py` |

### ⚠️ 硬 bug #2 订正（攻击间隔）
Stronghold 把"攻击间隔 +X 秒"类效果建模为 **BAT 绝对加算**后再走
`interval = bat*100/aspd`。夕「写意胜形」`base_attack_time +0.40` 应：
`bat = (base_bat + 0.40)`（绝对加在 BAT 上），**不是** `interval × 1.4`。
例：base_bat=2.9，aspd=100 → 正确 interval=(2.9+0.40)*100/100=**3.30s**，
旧口径 2.9*1.4=4.06s 偏高，作废。净室 `Stats` 用 `bat_flat`（绝对秒）+ `bat_pct` 两个入口。

## 3. 伤害管线（calculation.js `mitigate` / hit.js `resolveDamage`）

减伤纯函数（与我方 `advisor/damage_calc.py` 同口径，已实现）：

| 类型 | Stronghold `mitigate` | 我方现状 |
|---|---|---|
| phys 物理 | `max(amount - max(0,D-defIgnoreFlat)*(1-defIgnorePct), 0.05*amount)` | `physical_hit` ✅（暂无穿甲字段，扩展位预留） |
| arts 法术 | `max(amount*(1 - min(100,effRES)/100), 0.05*amount)`，effRES 先减固定再乘百分比 | `arts_hit` ✅（RES clamp 95；注：Stronghold 法术保底也取 5%，我方目前法术无保底，见待办） |
| elemental 元素 | 走元素抗性 `epDamageResistance`，另有独立 gauge 爆条机制 | 阶段 C，暂留 flag |
| true 真伤 | 不减免 = amount | `true_hit` ✅ |
| heal 治疗 | 独立管线，不进减伤 | 单列 ✅ |

**管线阶段顺序（hit.js，作为协议规格）：**
存活/无敌/睡眠/浮空闪避校验 → hit hook → damageCalculate(源/目标) →
`attackInput`（法术加算）→ 闪避/格挡 injury effects → `calculateBaseDamage`（mitigate +
源侧 dmgDealtMul/physDealtMul/artsDealtMul）→ damageOutput/BeforeApply/Applying hook →
目标侧 dmgTakenMul/类型受伤乘区 → 限伤（leaderHitLimit）→ HP 扣减。

> 我方第一版实现无 hook 总线，按"源面板 → mitigate → 受伤乘区 → 扣 HP"主干即可；
> hook 留成可选回调列表，不阻塞主链。红字判定（final ≥ expected×1.5）属显示层，暂不做。

## 4. 阻挡（blocking.js `_checkBlock`）

| 项 | Stronghold | 我方 |
|---|---|---|
| 地面阻挡半径 | `BLOCK_RADIUS.ground=0.70709997`（平方 0.49999037，格子外接圆） | `battle/blocking.py` 同常量 |
| 空中阻挡半径 | `fly=0.8944`（平方 0.79995137），可被 blockRadiusScale 放大 | 同 |
| 装置阻挡半径 | `device=0.4472` | 同 |
| 阻挡容量 | `Σ被挡敌人 blockWeight ≤ blockCnt` | `Stats.block_cnt` |
| 判定 | 每 tick 对每个未被挡敌人扫 3×3，取中点距离平方 < 半径平方，最近者胜 | 同 |
| 不可阻挡 | unblockable / levitate(浮空) / fear / sleep；围墙地块不能挡地面 | flags 位 |
| 隐匿恢复 | 脱挡后 3s（`STEALTH_RESTORE`）恢复隐匿 | 第一版简化，留字段 |

## 5. 出怪队列 / 蓄水池（spawns.js + waves.json/stages.json）

Stronghold 数据结构（我们从 gitignored 数据学结构，数值用 Kengxxiao/自有解包独立拉）：
- `stage.tiles`：ASCII 网格 + `mapChars` 字符→地块字典（`build` 可否部署 / `groundPass`
  地面通行 / `height` HIGH|LOW / 红门 S / 蓝门 E）。
- `wave.routes[]`：`start`→检查点→`end` 的格坐标路径。
- `wave.spawns[]`：`{time, enemyKey, count, interval, routeIndex}` —— **这就是蓄水池模型的输入**。

**敌方阵线压力（蓄水池）数学形式（我方独立提出，呼应"前10s正常、10–20s前后波叠加"）：**
令敌人 i 沿路线的到达蓝门剩余行进时间为 `τ_i(t)`，定义在阻挡格 `g`、时刻 `t` 的
在压敌数（蓄水水位）：
```
L_g(t) = Σ_i  1[敌人i在t时刻处于格g的阻挡/排队序列中]
```
出怪流入率 `λ(t) = Σ_spawn (count/interval) 的瞬时叠加`，清空率
`μ_g(t) = 该格守军有效击杀率（DPS/敌人有效HP）`。离散化到 tick：
```
L_g(t+Δt) = max(0, L_g(t) + (λ_g(t) - μ_g(t))·Δt)
```
- `λ_g(t)` 由 spawns 时间表 + 路线行进延迟推出（后波到达即与前波残量叠加）；
- `μ_g(t)` 由守军 `interval`/单发伤害/破甲结果推出；
- `L_g` 超过阻挡容量且 `μ<λ` 持续 → 漏水（leak）风险，对应 Stronghold 的 `leakedCount`。
这给出"波次叠加导致阵线压力抬升"的可计算形式，落在 `battle/wave_pressure.py`。

## 6. 百分比加算的叠乘规则（constants.js `DIRECT_BONUS_STACKING='add'`）

卫戍体系里盟约/策略/装备/机变/特质的"攻击力+X%"一律是**直接乘算类，彼此相加后一次乘**：
```
A = (A0 + D_p) * (1 + D_t)，其中 D_t = t1 + t2 + … + tn（所有同类百分比求和）
```
"提升至 X%/X 倍"类（炎佑 ×1.5、攻击海怪提升至150%）才是独立乘区 `Πmul`。
→ 我方 `Stats` 严格区分 `*_pct`（相加）与 `*_mul`（相乘）两个桶，避免 v2.5 曾出现的
600 层 ×74 失控 bug。与现有 `scaling.py` 的盟约面板乘数衔接：面板乘数进 `*_mul`。

## 7. 常量对照（constants.js → battle/constants.py）

| 常量 | 值 | 用途 |
|---|---|---|
| `TICK` | 1/30 | 步长 |
| `MIN_DAMAGE_RATIO` | 0.05 | 物理/法术保底 5% |
| `ASPD_MIN/MAX` | 20/600 | 攻速钳制 |
| `MOVE_SCALE` | 0.5 | tiles/s = moveSpeed*0.5 |
| `ALLY_COLLIDER_RADIUS` | 0.25 | 友军碰撞圆 |
| `ENEMY_COLLIDER_RADIUS` | 0.1 | 敌人碰撞圆 |
| `BLOCK_RADIUS` | 见 §4 | 阻挡 |
| `STEALTH_RESTORE` | 3s | 脱挡回隐 |
| `PROJECTILE_SPEED` | 12（各类 8~16） | 投射物格/秒 |
| `ELEMENT_GAUGE_MAX` | 1000（BOSS 2000） | 元素条上限 |
| `DP_DEFAULTS` | init10/每秒1/上限99 | 部署点 |

## 8. 净室模块规划（`advisor/battle/`，全部新写，不 import 任何 GPL 文件）

| 我方模块 | 职责 | 对应 Stronghold |
|---|---|---|
| `clock.py` | tick/时间 | TICK 约定 |
| `constants.py` | §7 常量 | constants.js（数值为 PRTS 机制事实） |
| `unit.py` | Unit + `Stats` 属性聚合（§2） | units.js |
| `damage.py` | 复用 `damage_calc` + 穿甲/受伤乘区主干（§3） | calculation/hit.js |
| `blocking.py` | 接触阻挡（§4） | blocking.js |
| `grid.py` | 地块网格/通行/部署位 | grid.js + stages 结构 |
| `wave.py` | 出怪队列/路线/蓄水池压力（§5） | spawns.js |
| `battle.py` | `step()` 主循环编排（§1） | Battle/lifecycle.js |

**合规边界**：本目录只含我们自己写的 Python 与自有/公开来源数据；不读取、不拷贝、
不 import `data/source/_stronghold/` 下任何文件。对拍时以其运行结果当"标准答案"另起进程比对。
