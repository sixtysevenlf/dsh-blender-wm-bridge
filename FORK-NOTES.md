# FORK-NOTES · 本 fork 与上游的关系（必读）

> **本仓库是 `dsh-blender-plugin` 的 fork，专供提交，永不回流原版。**
> 原版目录 `/home/sixtyseven67/DSH/dsh-blender-plugin` 在本次作业中**一个字节都没有改动**
> （161 个受保护文件的 md5 清单前后逐字节一致，见 §四）。

---

## 一、这个 fork 是干什么的

在 v1.0.5 的 15 个模型侧工具之上，新增一个**世界模型桥 `wm_bridge/`**，把 Blender 用作
灵枢（`lingshu`）**世界模型七层**的：

1. **外部观察者 / 真值源**（腿 A）——世界模型 L5 的 `verify()` 当前拿**仓内自写的模拟器**当
   `actual`，等于自己评自己；本桥提供**独立的逐 tick 真值**（实体位姿 / 遮挡 / 深度 / 剪影）。
2. **几何与锚点的供货商**（腿 B）——OBJ + SHA-256 清单，作为世界模型 L2 语义时空图节点的来源。

**接口面见 [`wm_bridge/DESIGN.md`](wm_bridge/DESIGN.md)。**

---

## 二、相对上游的全部改动（不多不少）

| # | 改动 | 范围 | 为什么 |
|---|---|---|---|
| 1 | 包名 `@dsh-external/dsh-blender-plugin` → `@dsh-external/dsh-blender-wm-bridge` | 全仓引用 | 与原版在 DSH 里可区分 |
| 2 | **bundle id** `dsh-blender-plugin` → `dsh-blender-wm-bridge` | `cordis.patch.yml` | 文件自己的注释写明：两个 fiber 同名会重复注册 |
| 3 | 端口 **9876/9877/9878 → 9886/9887/9888** | 全仓 | 与原版同时可用、互不抢端口 |
| 4 | workDir `dsh-blender-rt` → `dsh-blender-wm-rt`；`D:\DSH\blender\*` → `D:\DSH\blender-wm\*` | 全仓 | 产物不混、状态不串 |
| 5 | env 前缀 `DSH_BLENDER_*` → `DSH_BLENDER_WM_*` | 全仓 | 同上 |
| 6 | 配置文件 `dsh-blender.config*.json` → `dsh-blender-wm.config*.json` | 文件名 + 引用 | 同上 |
| 7 | **去掉指回原版的硬编码路径** | `scripts/kit_*.py`（改 `__file__` 相对）、`tests/audit_file_selftest.py`、`tests/geo_selftest.py` | 否则 fork 的自测会去操作**原版**——正是要避免的 |
| 8 | **新增 `wm_bridge/`** | 新目录，零 bpy 依赖 | 本 fork 的唯一实质新增面 |
| 8b | `wm_bridge/` 扩到 **9 件**：新增 `geom.py`（OBJ+MTL / `lingshu.shapes/1`）、`oracle.py`（真值 + 契约自校）、`bpy_dump.py`（Blender 侧只抽原始量）；`cli.py` 扩 `export-obj/export-shapes/export-oracle`；`selftest.py` 19→**57** 项、变异 3→**10** 条；`tests/wm_bridge_artifact_compare.py`（反演对照）与 `tests/wm_bridge_dump_spec_check.py`（正向端到端）为两道对照门 | 新增面 | 把原本散在 `hex-model/build_models.py` / `export_shapes.py`（Lead 的临时脚本）里的**几何/部件/真值导出**收进桥：**有契约、有守卫、有定点变异** |
| 9 | 出货面 `files` 加 `wm_bridge` / `FORK-NOTES.md` | `package.json` | 让新增面进包 |

**未改**：15 个 DSH 工具名（`blender_rt_*`）、任何 `runtime/*.py` 的业务逻辑、任何上游 addon。
改工具名会影响 `src/index.ts`（137 KB）与 `runtime/catalog.mjs`，属**待裁**事项（见 §五）。

---

## 三、隔离自检（可复跑）

```bash
cd blender-wm-bridge
# 1) 残留扫描：不该再有原版端口/包名/目录名/env 前缀
grep -rInP "(?<!\d)(9876|9877|9878)(?!\d)" --include='*.mjs' --include='*.ts' --include='*.py' .
grep -rInP "DSH_BLENDER_(?!WM_)" --include='*.mjs' --include='*.ts' --include='*.py' .
grep -rIn "dsh-blender-rt" --include='*.mjs' --include='*.ts' --include='*.py' .
# 2) 新增面自测（不需要 Blender）
python3 -X utf8 -m wm_bridge.selftest
python3 -X utf8 -m wm_bridge.selftest --mutate
```

---

## 四、原版零改动（完整性判据 · **三证并列**）

⚠ **本目录的 13:47/13:53 基线已过期**：`/home/sixtyseven67/DSH/dsh-blender-plugin/`
在 **14:03:50 / 14:05:21** 被**外部整体重新同步**过（不是本会话的改动）——
变化形态是 README 换版 + 新增 `.github/FUNDING.yml` + 删除 2 张 sponsor 图。
完整记录见 `_fork-evidence/RESYNC-FINDING.md`。因此"原版零改动"必须**三证并列**：

| # | 证据 | 读数 |
|---|---|---|
| ① | `cmp -s original-before.md5 original-final.md5`（fork 期间） | **逐字节相同**（161 条一致；`original-after.md5` 同） |
| ② | 现扫 151 条（排除 `.git`/`tmp`/`node_modules`/`*.tgz`/`__pycache__`）vs `original-resync-1403.md5`（14:07 取） | **逐文件 md5 全等**（仅新清单有 0 / 仅基准有 0 / 内容不同 0）⇒ 此后也没动 |
| ③ | 13:53 基线(161) vs 当前(151) | 共 **14 行**差异：2 条 README 内容变化 + 1 条新增 `FUNDING.yml` + 2 张 sponsor 图消失（以上均由 14:03 外部重新同步解释）+ 9 条 `runtime/ext/node_modules/gltf-validator/*`（**扫描口径差异**：旧基线含 `node_modules`、新规则 prune 之；实测这些文件**仍在盘上**） |

`diff -rq 原版 副本` 现在报 **87 行**（65 个文件内容不同 + 22 个 only-in），
其中绝大多数是**本 fork 的登记改动**（§二 的包名/端口/env/workDir/wm_bridge）
与 14:03 那次外部重同步叠加的结果 —— **不要**为了把 diff 抹平去改原版或副本。

---

## 四点五、task-12 收官结论（2026-10-12，Lead 正向端到端 + 本轮阈值修正）

**正向端到端**：Lead 在 Blender 内跑 `python -m wm_bridge.bpy_dump`（`frame=0`，
`wmtest_models.blend`），lamp/turret/arm 三个 spec 均 rc=0；我（无 Blender）用
`cli export-obj/export-shapes/export-oracle --spec` 复跑，与**他独立生成的同帧产物**
`/mnt/d/DSH/blender/out/wmtest/f0/<模型>/` 对拍：

| 模型 | OBJ vs f0 | 真值（共同实体逐 tick） | 部件（件数/图元分布） | 跨件守卫 |
|---|---|---|---|---|
| lamp | 逐字节相同（raw 差 13 行，全 signed-zero） | 1 实体×40 条 **max=0.000e+00** | 22=22 | ok（0 问题） |
| turret | 逐字节相同（raw 差 18 行，同上） | 6 实体×864 条 **max=0.000e+00** | 19=19 | ok（0 问题） |
| arm | 逐字节相同（**raw 差 0 行**） | 5 实体×600 条 **max=0.000e+00** | 12=12 | ok（0 问题） |

⇒ `tests/wm_bridge_dump_spec_check.py` = `VERDICT=MATCH`（可复跑）。

**① 取帧泄漏在几何上再证一次**：旧 `wmtest/arm/mesh.obj` vs `f0/arm/mesh.obj` 逐顶点比，
**196 个顶点里 148 个（75.5%）位移 max 1.506804 m**，面集合与组序完全相同 ⇒ 差异纯姿态。
（lamp 0 个；turret 32 个、max 1e-6 m 属末位舍入。）这条与 `shapes.json` 的
"yaw +35.0° vs oracle tick0 −35.0°"是**同一根因的两条独立证据**（几何侧 + 部件侧），可作已确证。

**② 判据过紧已修（Lead 复核提出的唯一问题）**：姿态核对阈值 1e-6 与**导出精度 6 位小数同量级**，
在 `arm` 的 `ARM_shell/ARM_upper/ARM_upper_glow` 上产生"只差 0.000001"的**假失败**。
改为两个**有推导的常量**：`geom.POSE_TOL = 1e-5`（10× 导出量子）、`geom.DATA_TOL = 2e-6`（数据值）。
为证明**没有把门改松到失效**：新增 selftest **I5**（1e-6 微差必须放过）/ **I6**（0.01° 必须抓住）
与变异 **M10**（地板放宽到 1.0 ⇒ 恰好 `I3`+`I6` 转红）。修正后正向端到端 arm 的
`export-shapes` 由 rc=2 变 **rc=0**、crosscheck **ok=True**。
⚠ 另需澄清：`tests/wm_bridge_artifact_compare.py` 的 [C] 段用的是**数据值**容差（今为 `DATA_TOL`），
与姿态核对**不是同一个**；旧报告里旧件的 `export-shapes rc=2` 是 `missing_tick`（无 join key），
**不是**这条阈值问题的表现 —— 两者已在代码与文档里分开命名。

**③ link 分组口径**：本桥按**关节（link）**出类别，旧临时脚本按整机一个类别。
逐类求和后件数/图元分布一致，但**只有按 link 分组才有每 link 自己的锚点** —— 采纳本桥口径。

---

## 五、待裁 / 未做

| # | 事项 | 影响 | 建议 |
|---|---|---|---|
| 1 | DSH 工具名前缀是否改 `blender_wm_*` | `src/index.ts` + `runtime/catalog.mjs`；只在**两者同时装进同一 profile** 时才必须 | 本 fork 定位"提交用"，**保持原工具名**；若要本地共存，再单独做一次改名批次 |
| 2 | `wm_bridge/bpy_dump.py` 的**Blender 侧跑一次** | 需要 Blender 在场（只有 Lead 能驱动） | 本轮已把导出逻辑收进桥并用既有产物反演对照（`VERDICT=MATCH`）；真机抽取待 Lead 跑 `bpy_dump` 后复跑 `cli export-*` |
| 3 | 是否把本 fork 作为 lingshu `docs/intake/` 登记件提交 | 走对方双清单 + intake 登记 | 使用者下令后再提交 |
| 4 | Blender 侧 addon `MCP for Blender` 不在本包内 | 用户须自备并在 Blender 里 Connect | 上游既有约定，不变 |

---

*本文件随改动更新；每加一条改动都要在 §二 表里留痕。*
