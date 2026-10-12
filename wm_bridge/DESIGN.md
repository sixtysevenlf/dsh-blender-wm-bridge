# wm_bridge · 世界模型桥 · 设计契约 v0.1

> 本目录是**本 fork 相对原版插件的全部新增面**。原版插件一个字节不动；本包**永不回流**原版。
> 目的：让灵枢（lingshu）的**世界模型七层**能用 Blender 当**外部观察者 / 真值源**，并让 Blender 产出的
> 几何与锚点成为世界模型的**资产供货**——而 lingshu 侧**不引入任何 bpy 依赖**。

---

## 一、为什么是"进程外适配器"而不是"把 bpy 引进 world/"

`lingshu/lingshu/world/world_model.py` 头部逐字写着「**纯标准库 · 零外部依赖（D-005）**」，
而 `docs/architecture.md` 有一条硬纪律：「**轻核承诺：`core` 不因本仓的『完整』而增重**」。

⇒ 任何把 `bpy`（≈ GB 级、绑定 Python 版本、跨驱动不可复现）引入 `lingshu` 的做法都会**同时打破两条硬纪律**。
⇒ 唯一形态：**进程外**，走 stdio/HTTP，与 lingshu 既有的 `world/brain_store.py`（662 行，MCP stdio 客户端）**同构**。

---

## 二、三条硬边界（违反即失败）

| # | 边界 | 判据 |
|---|---|---|
| B1 | **不改 `lingshu` 的 `world/`** | 交付里对 `world/` 的改动行数 = 0；对照面靠外部脚本换 `actual` 来源 |
| B2 | **不把 bpy 带进 lingshu** | `lingshu` 侧的依赖列表不得新增 `bpy` / `blender` |
| B3 | **原版插件零改动** | 原版目录的 md5 清单在本次作业前后逐字节一致 |

---

## 三、接口面（两条腿）

### 腿 A · 外部观察者 / 真值源（价值最高）

世界模型 L5 的 `verify()` 设计为「**外部观察者逐 tick 对比**」，但当前 `actual` 取自**仓内自己写的模拟器**——
典型的**自己评自己**。本桥提供**独立真值**。

导出契约（每条记录一个实体一个 tick）：

```json
{
  "schema": "wm_bridge.oracle/1",
  "scene": {"name": "...", "seed": 42, "tick_hz": 30, "world_size": 100, "units": "m"},
  "tracks": [
    {"entity": "wolf", "category": "animal", "tick": 0,
     "pos": {"x": 15.04, "y": 1.5, "z": 15.2},
     "visible": true, "occluded_by": null,
     "screen_bbox": [x0, y0, x1, y1], "depth": 12.7}
  ],
  "manifest": {"algorithm": "sha256", "files": {"tracks.jsonl": "<hex>"}}
}
```

关键性质：**逐 tick 可对齐**（世界模型的预测带 `target_tick`）、**带遮挡真值**（解 #419/#403 那类
"渲染 0 像素 / 遮挡失效"的判定困境）、**可哈希**（对齐 lingshu 的 `verify_manifest.py --strict`）。

### 腿 B · 几何 / 锚点供货

Blender 产出的 OBJ + manifest 作为世界模型 L2 语义时空图节点的来源（`spatial_coordinates {x,y,z}` 米制）。
**只供货，不当建模后端**：产出物落在 lingshu 仓外，世界模型照旧零依赖读它。

---

## 四、与 lingshu 侧的对接口径

| 本桥提供 | lingshu 侧对应 | 说明 |
|---|---|---|
| `oracle.jsonl` + manifest | `world_model.verify()` 的 `actual` | 外部脚本替换，不改 `world/` |
| 场景节点 JSON（tags + 米制坐标） | `scene_model` store 协议 `get_nodes_by_tag` / `state_attributes` | 与 `brain_store.py` 的适配层同构 |
| `ingest_scene` 的镜像导出 | `cg(op=state_event)`（经脑） | 沿用既有 M3 通道，不新开 |
| SHA-256 清单 | `tools/verify_manifest.py --strict` | 逐项比对，非只看总数 |

---

## 五、提交口径（对齐 lingshu 的 intake 纪律）

1. 走 `docs/intake/` 登记：**件名 / 来源 / 日期 / 双清单结论 / 提交号**；
2. **双清单**：内容政策（无凭据 / 无本机路径字面量 / 无隐私）＋ 隐私清单；
3. 端到端**隔离**验证（不碰在役库 / 不动 GUI 场景）；
4. 每条断言可复跑，打印 `VERDICT=PASS|FAIL`；
5. 缺 Blender / 缺依赖 ⇒ **fail-closed 明确报错**，不静默降级；
6. 文档里主动写明**诚实边界**：本桥提供真值，但**不宣称**世界模型因此更准——
   准不准由换真值后的读数说话。

---

## 六、本轮已实现（不需要 Blender 在场即可验证）

**自测读数**（`python3 -X utf8 -m wm_bridge.selftest`）：**通过 57 / 失败 0 · VERDICT=PASS**
（原 19 条一条未少，新增 E/F/G/H/I/J 六组共 38 条）；
`--mutate`：**10 条定点变异全部按预期命中**（逐条红数见下表）· VERDICT=PASS。

### 6.1 导出面（本轮新增）：把 Lead 临时脚本里的导出收进桥

| 件 | 作用 | 状态 |
|---|---|---|
| `wm_bridge/geom.py` | OBJ+MTL / `lingshu.shapes/1` 部件描述；**轴换算是唯一入口**（det=+1 断言）、5 图元拟合、OBJ 头 fail-closed 契约、**规范面序** | ✅ 已实现 + 自测 |
| `wm_bridge/oracle.py` | `wm_bridge.oracle/1` 真值导出；`build_doc` 出文档即过 `contract.validate_doc`，不过就 raise；**`export_frame` 必填** | ✅ 已实现 + 自测 |
| `wm_bridge/bpy_dump.py` | Blender 侧**只抽原始量**（世界顶点/三角面/局部 bbox/体积/世界矩阵/逐 tick 位姿）→ dump JSON。**顶层零 bpy**，`import bpy` 只在函数体内 | ✅ 已实现（**待 Lead 在 Blender 内跑一次**） |
| `wm_bridge/cli.py` | 新增 `export-obj` / `export-shapes` / `export-oracle`（`--spec` 或 `--from-*`），退出码 0/2 | ✅ 已实现 + 自测 |
| `tests/wm_bridge_artifact_compare.py` | 桥 × 既有产物**逐项对照**（反演路线）+ 两次独立进程可复现性门 | ✅ 已实现（`VERDICT=MATCH`） |
| `tests/wm_bridge_dump_spec_check.py` | **正向端到端**：吃 Blender 真跑出的 spec，与同帧参照 `f0/` 对拍 | ✅ 已实现（`VERDICT=MATCH`） |

**分工是刻意的**：Blender 侧只读矩阵（不得不依赖 bpy 的一小段），
**全部换算与契约在桥里**（纯标准库）⇒ 所有判据都能在没有 Blender 的机器上复跑。
`cli export-*` 吃 `bpy_dump` 抽出的 spec，因此**不需要 Blender** 就能重出与校验三件产物。

### 6.2 实测发现（写进来是因为它们是判据设计的一手证据）

1. **只短路哈希骗不过清单核验**（原有）：`verify()` 里还有独立的字节数判据。
2. **自测自己先红了一次**（原有）：测试夹具浅拷贝污染常量 → 改深拷贝。
3. **顶点确定 ≠ 文件确定：面序是独立的一维**（本轮，Lead 在 `build_models.py` 上定位根因）。
   同一份输入连续导出三轮，`lamp/mesh.obj` 三个不同哈希（`1e97fa3a…→69497223…→bf54bbb1…`）、
   `turret/mesh.obj` 同样每轮一变，而 **顶点流逐位完全相同（最大绝对差 0.000e+00）**——
   变的只有 `f` 行的顺序（`350 换 350`）。根因：`me.calc_loop_triangles()` 对 **ngon 端盖**
   的三角化**按内存地址序迭代**（受 ASLR 影响）；`arm` 稳定是因为它的件里没有 ngon。
   ⇒ 修法：`geom.canonical_tris()` —— ① 每面**环状旋转**到最小索引打头（**不是 `sorted()`**，
   那会翻绕向、法线反）；② 全部面按规范式 `sort()`。
   ⇒ **守卫不许写成概率性的**：ASLR 漂移无法按需复现，所以判据建在**受控的输入序差异**上——
   同一几何喂两种不同面序，产物必须**逐字节相同**（selftest J1/J4 + 对照脚本 [E]），
   去掉规范面序则**必红**（M9 实测转红 4 项）。
4. **位姿会静默取自"别的帧"**：`shapes.json` 的部件位姿一度是**动画循环最后一次赋值**留下的
   位姿（机械臂 = u=1：yaw **+35.0°**），而同一份 `oracle.jsonl` 的 `tick 0` 是 **−35.0°**
   （`tick 119` = **+34.7741°**）——一次导出里两件产物描述了**两个姿态**，单看任何一件都发现不了。
   根因：`matrix_world` 在 `keyframe_insert` 之后没有 `frame_set` 重求值。
   ⇒ 修法：`bpy_dump` 第一步就 `scene.frame_set(frame)`（显式取帧），并把 `frame` 写进两件产物；
   `geom.check_pose_consistency()` 做跨件核对。
5. **跨件核对需要 join key，而旧件没有**：旧 `shapes.json` 的 link 名是 `wmtest/<模型>`，
   而 `oracle.jsonl` 的实体名是 `<模型>_root` ——**没有任何键能把两件 join 起来**，
   这正是"位姿取自哪一帧"长期无人发现的结构性原因。本桥的 `bpy_dump` 用**关节对象名**
   做 link 名（与 oracle 实体同名）⇒ 新件天然可 join；守卫对旧件如实报 `missing_tick`。
6. **欧拉必须复现 Blender 的"两解取小"**：同一个旋转矩阵有两组欧拉解，Blender 取
   **L1 范数更小**的那组（`mat3_normalized_to_eulO` 源码注释：*the one with lowest values in it*）。
   不这么做，`|y|>90°` 时会给出 `(π,−45°,π)` 而不是 `(0,−135°,0)` ——
   实测炮塔四个 ±135° 的炮管件因此对不上。同时 `mat3_to_quaternion` 需规范到 **w ≥ 0**
   （出货 288 条炮塔真值里 w<0 的为 0 条；不做规范会有 23 条整体符号相反）。

### 6.3 既有一致性对照（`tests/wm_bridge_artifact_compare.py`，VERDICT=MATCH）

| 模型 | OBJ/MTL 逐字节 | 顶点/面/件/材质 | spec→OBJ 逐字节 | shapes 数值最大偏差 | 真值 数值最大偏差 | 两次独立进程 |
|---|---|---|---|---|---|---|
| `lamp` | ✅ | 1066 / 2044 / 22 / 3 | ✅ | 0 | 0（40 条） | ✅ |
| `turret` | ✅ | 1052 / 2028 / 19 / 4 | ✅ | 0 | 1e−06（864 条，2 条仅差整体符号=180° 退化点） | ✅ |
| `arm` | ✅ | 196 / 344 / 12 / 4 | ✅ | 0 | 1e−06（600 条） | ✅ |

+ 轴换算**互逆**：53 个件的 `pos/size/rot/kind/color` 反演→正演**逐位回原值**；
+ 面序扰动（spec 的面序列反序 + 每面环转）重出仍与既有 `mesh.obj` **逐字节相同**；
+ 跨件核对：旧件如实报 `missing_tick`（无 join key），把 link 名对齐 oracle 实体后 **ok=True**。

### 6.3b 正向端到端（吃 Blender 真跑出的 spec，`tests/wm_bridge_dump_spec_check.py`）

Blender 内由 Lead 跑 `bpy_dump`（`frame=0`，`wmtest_models.blend`，三个模型各一次，rc=0），
产物在 `/mnt/d/DSH/blender/out/wmtest/spec/*.spec.json`，同帧独立参照在 `.../f0/<模型>/`：

| 模型 | spec 规模 | OBJ vs f0 | MTL | 真值（共同实体逐 tick） | 部件 | 跨件守卫 |
|---|---|---|---|---|---|---|
| `lamp` | 76794 B，meshes 22 / links 1 / tracks 40 | **逐字节相同**（raw 差 13 行，全 signed-zero） | ✅ | 1 实体 × 40 条，max=**0.000e+00** | 22=22 | ok=True（0 问题） |
| `turret` | 247521 B，meshes 19 / links 2 / tracks 864 | **逐字节相同**（raw 差 18 行，同上） | ✅ | 6 实体 × 864 条，max=**0.000e+00** | 19=19（1 box+14 pillar+4 sphere） | ok=True（0 问题） |
| `arm` | 149771 B，meshes 12 / links 5 / tracks 600 | **逐字节相同**（**raw 差 0 行**） | ✅ | 5 实体 × 600 条，max=**0.000e+00** | 12=12（7 box+5 pillar） | ok=True（0 问题） |

**link 分组比旧口径更正确**：本桥按**关节（link）**出类别
（`wmtest/LAMP_root`、`wmtest/TURRET_root`+`wmtest/TURRET_yaw`、`wmtest/ARM_*` 五个），
Lead 的临时脚本按**整机一个类别**出 —— 逐类求和后件数与图元分布完全一致，
但**只有按 link 分组才有"每个 link 自己的锚点"**，这正是关节级预测需要的形态。

**顺带把取帧泄漏再证一次（这次是在几何上）**：旧 `wmtest/arm/mesh.obj` 与 `f0/arm/mesh.obj`
逐顶点比，**196 个顶点里 148 个（75.5%）位移，max |Δ| = 1.506804 m**，而面集合完全相同、
组名与顺序完全相同 ⇒ 差异**纯粹是姿态**。`lamp` 0 个顶点位移、`turret` 32 个（max 1e-6 m，末位舍入）。

### 6.3c 容差是**常量**，且有推导（不许随手调）

| 常量 | 值 | 依据 |
|---|---|---|
| `geom.POSE_TOL` | **1e-5** | 姿态核对要把「欧拉/四元数 → 矩阵 → 相乘」跑一遍，导出精度 6 位小数（量子 1e-6）⇒ 单次换算误差半个末位、两次复合 ~1e-6。阈值压在 1e-6 会在"只差最后一粒"处产生**假失败**（实测：Lead 正向端到端时 `arm` 的 `ARM_shell/ARM_upper/ARM_upper_glow` 恰差 0.000001）。取 **10× 量子** 为地板 |
| `geom.DATA_TOL` | 2e-6 | 数据值（位置/四元数分量）两侧都是 6 位小数，读回无误差；只有"重算一遍"（quat→mat→quat）带 ~6e-7 |

地板放宽**没有**让门失效：真实缺陷的偏差是**度级**的（取错帧 ⇒ 矩阵元素差 ~1.15，两个数量级），
selftest **I5**（1e-6 微差必须放过）/ **I6**（0.01° 偏差必须抓住）分列地板两侧，
变异 **M10**（地板放宽到 1.0）实测转红 `I3`+`I6`。

### 6.4 定点变异（10 条，逐条红数与预期一致）

| 变异 | 改坏什么 | 转红项数 | 转红的是哪些 |
|---|---|---|---|
| M1 短路 `_finite` 恒真 | NaN/bool 门 | 4 | A2 / A3 / D3 / **G3**（G3 走同一判据，实测新增覆盖面） |
| M2 短路哈希+字节数 | 清单内容判据 | 2 | B2 / B4 |
| M3 短路 `tcp_alive` 恒真 | 通道可达性 | 3 | C1 / C2 / D1 |
| M4 轴换算换镜像解 | `AXIS_MAP` det 变 −1 | 2 | E1 / E3 |
| M5 拟合改「比值最大」 | 图元判据方向 | 4 | F1 / F2 / F4 / F5 |
| M6 短路 `require_normalize` | OBJ 头 fail-closed | 1 | E6 |
| M7 欧拉只取第一解 | 两解取小 | 1 | E4 |
| M8 守卫只看枢轴平移 | 件级姿态链 | 1 | I2 |
| M9 去掉规范面序 | 文件可复现性 | 4 | J1 / J2 / J3 / J4 |
| M10 姿态地板放宽到 1.0 | 容差门失效 | 2 | I3 / I6 |
| （覆盖修正）M8 | 拿掉件级姿态链 | 2 | I2 / **I6**（I6 是件级链专属判据，必然一起红） |

---

## 七、未做 / 待裁

- **Blender 侧端到端**：✅ 已由 Lead 跑完（见 §6.3b）——`bpy_dump` 三个模型 rc=0，
  `cli export-*` 正向复跑与同帧参照 `f0/` **逐字节相同**、真值 max=0.000e+00、跨件守卫 0 问题。
  **"我在 Blender 里跑过"这句仍不成立**：Blender 只有 Lead 能驱动，本节读数全部来自
  *他跑出的 spec* + *我在无 Blender 环境的复跑*。
- **DSH 工具名**：本 fork 沿用原版的 15 个 `blender_rt_*` 工具名。
  若**两者同时装进同一个 DSH profile**，`cordis.patch.yml` 自己的注释已警告
  「两个 fiber 会重复注册同名工具」。裁决点：是否把工具名前缀改为 `blender_wm_*`（影响 `src/index.ts` + `runtime/catalog.mjs`）。
- **端口已隔离**：addon `9886` / 后端 `9887` / 启动代理 `9888`（原版 `9876/9877/9878`）。
- **workDir 已隔离**：`dsh-blender-rt` → `dsh-blender-wm-rt`；`D:\DSH\blender-wm\`。
- **安装形态**：本 fork 与原版**不得同 profile 同时装**（bundle id 已改为 `dsh-blender-wm-bridge`）。
- **OBJ 的 MTL 无法从 OBJ 反推**：`export-obj --from-obj` 只重出几何（OBJ 格式不含颜色），
  MTL 必须走 `--spec`（spec 里有材质基色）。这不是缺陷，是格式边界，已在 CLI 帮助里写明。

*本文件随实现推进更新；每条"已实现"都必须有可复跑的自测读数支撑。*
