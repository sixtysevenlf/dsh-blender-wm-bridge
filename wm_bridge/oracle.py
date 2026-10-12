# -*- coding: utf-8 -*-
"""wm_bridge.oracle · 真值导出（**纯标准库 · 零 bpy**）

产出 `wm_bridge.oracle/1` 的 JSONL：首行 `{"schema","scene"}`，其后每条一个
`(entity, tick)`。这是世界模型 L5 `verify()` 的**外部 actual** —— 桥的全部价值所在，
所以写入**必须自校**：`build_doc()` 出来立刻过 `contract.validate_doc`，
不过就 raise（fail-closed）。宁可导不出来，也不要把坏真值喂给下游。

---------------------------------------------------------------- 为什么必须记 export_frame
位姿与真值都是**帧相关**的。实测踩过的坑：`shapes.json` 的部件位姿曾取到
「动画循环最后一次赋值」留下的位姿（机械臂 = u=1，yaw **+35°**），而同一份
`oracle.jsonl` 的 `tick 0` 是 u=0（yaw **−35°**）—— 一次导出里两件产物描述了
**两个不同的姿态**，而单看任何一件都发现不了。故：

  · 本模块的 `scene` 要求带 `export_frame`（哪个 tick 被当作"当前姿态"）；
  · `doc_from_tracks(...)` 会拒绝「tracks 里存在 tick > export_frame 却被当作静态姿态」的用法；
  · 跨件核对在 `geom.check_pose_consistency()`。

生效条件总览：
  · `build_doc(scene, tracks)` → dict；schema/scene 键/tick/NaN/重复键任一不合法 ⇒ raise。
  · `write_oracle(path, doc)` → 摘要 dict；写盘前必过 `build_doc` 自校。
  · `read_oracle(path)` → 同一形状的 doc；坏件 ⇒ raise。
"""
from __future__ import annotations

import json
import math
import os

from . import SCHEMA_ORACLE
from . import contract as C

#: `scene` 必备键（与 contract.validate_doc 的门一致，这里显式列出便于报错）
SCENE_REQUIRED = ("name", "tick_hz", "world_size", "units")
#: 真值自带的坐标说明（外部观察者件必须自己讲清"这些数字在哪个轴系里"，
#: 否则消费方只能靠猜 —— 桥的立场：**口径随件走**）
COORDINATES = ("lingshu Y-up / +Z 前向；由 Blender Z-up 经真旋转 "
               "(x,y,z)->(x,z,-y) 换算（det=+1，MIRROR (x,z,y) 被拒）；"
               "单位 m；pos 为世界坐标，rot_quat 为 [w,x,y,z] 世界旋转")


class OracleContractError(Exception):
    """真值导出的契约违反（fail-closed）。"""


def scene_stub(name, tick_hz, world_size, units="m", seed=0, export_frame=0,
               extra=None):
    """构造 `scene` 头。

    `export_frame` 必填（缺省 0 也要**显式**留在文档里）：它是「这份真值把哪一 tick
    当作部件的当前姿态」的声明，跨件核对的锚点。
    """
    if not name or not isinstance(name, str):
        raise OracleContractError("scene.name 须为非空字符串：%r" % (name,))
    if not isinstance(export_frame, int) or isinstance(export_frame, bool):
        raise OracleContractError("export_frame 须为整数：%r" % (export_frame,))
    if export_frame < 0:
        raise OracleContractError("export_frame 不得为负：%r" % (export_frame,))
    sc = {"name": name, "seed": int(seed), "tick_hz": float(tick_hz),
          "world_size": float(world_size), "units": units,
          "export_frame": int(export_frame), "coordinates": COORDINATES}
    for k, v in (extra or {}).items():
        sc.setdefault(k, v)
    return sc


def track_record(entity, tick, pos, rot_quat=None, category="wmtest",
                 link=None, extra=None):
    """构造一条 track；**在这里就把坏值挡住**（NaN/Inf/长度不对/负 tick）。

    `pos` 为 (x, y, z) → 落成 {"x","y","z"}；`rot_quat` 为 [w,x,y,z]。
    """
    if not isinstance(entity, str) or not entity:
        raise OracleContractError("entity 须为非空字符串：%r" % (entity,))
    if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
        raise OracleContractError("tick 须为非负整数：%r" % (tick,))
    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise OracleContractError("%s@%d 的 pos 须为 3 元：%r" % (entity, tick, pos))
    for v in pos:
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)):
            raise OracleContractError("%s@%d 的 pos 含非有限数值：%r" % (entity, tick, pos))
    rec = {"entity": entity, "tick": int(tick), "category": str(category),
           "link": str(link if link is not None else entity),
           "pos": {"x": round(float(pos[0]), 6), "y": round(float(pos[1]), 6),
                   "z": round(float(pos[2]), 6)}}
    if rot_quat is not None:
        if not isinstance(rot_quat, (list, tuple)) or len(rot_quat) != 4:
            raise OracleContractError(
                "%s@%d 的 rot_quat 须为 [w,x,y,z] 4 元：%r" % (entity, tick, rot_quat))
        for v in rot_quat:
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(float(v)):
                raise OracleContractError(
                    "%s@%d 的 rot_quat 含非有限数值：%r" % (entity, tick, rot_quat))
        rec["rot_quat"] = [round(float(v), 6) for v in rot_quat]
    for k, v in (extra or {}).items():
        rec.setdefault(k, v)
    return rec


def build_doc(scene, tracks):
    """组一份导出文档并**当场**过契约。不过就 raise（不返回半成品）。"""
    if not isinstance(scene, dict):
        raise OracleContractError("scene 须为对象")
    for k in SCENE_REQUIRED:
        if k not in scene:
            raise OracleContractError("scene 缺键：%s" % k)
    if "export_frame" not in scene:
        raise OracleContractError(
            "scene 缺 export_frame —— 位姿/真值都帧相关，不声明帧的导出不可复核")
    scene = dict(scene)
    scene.setdefault("coordinates", COORDINATES)   # 旧件/外部传入的 scene 也补上口径说明
    doc = {"schema": SCHEMA_ORACLE, "scene": scene,
           "tracks": [dict(t) for t in (tracks or [])]}
    ok, why = C.validate_doc(doc)
    if not ok:
        raise OracleContractError("真值契约不通过：%s" % why)
    return doc


def frame_coverage_problem(doc):
    """`export_frame` 与真值 tick 覆盖面的关系 → None 或问题串。

    为什么会不一致：`export_frame` 是「部件位姿取自哪一 tick」，它必须落在
    `[min_tick, max_tick]` 内，否则跨件核对**永远**没有可比的那一 tick。
    实测旧件就踩了这条：机械臂的部件位姿取自动画末帧（**u=1，越过后一个 key**），
    而 `oracle` 只记到 tick 119 —— 位姿与真值根本不在同一帧集合里。
    """
    ef = (doc.get("scene") or {}).get("export_frame")
    lo, hi = tick_range(doc)
    if ef is None or lo is None:
        return None
    if not (lo <= ef <= hi):
        return ("export_frame=%d 不在真值 tick 范围 [%d, %d] 内 —— "
                "部件位姿与真值不在同一帧集合，跨件核对无解" % (ef, lo, hi))
    return None


_MISSING = object()


def write_oracle(path, doc):
    """写 JSONL：首行 `{"scene","schema"}`，其后逐行 track（`sort_keys=True`）。

    写盘前**必须**过 `build_doc` 自校 —— 这是本模块的 fail-closed 判据落点。
    """
    doc = build_doc(doc.get("scene"), doc.get("tracks"))   # 再自校一遍，防止调用方手搓
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"schema": doc["schema"], "scene": doc["scene"]},
                           ensure_ascii=False, sort_keys=True) + "\n")
        for t in doc["tracks"]:
            f.write(json.dumps(t, ensure_ascii=False, sort_keys=True) + "\n")
    return {"frames": len({t["tick"] for t in doc["tracks"]}),
            "entities": len({t["entity"] for t in doc["tracks"]}),
            "tracks": len(doc["tracks"]),
            "export_frame": doc["scene"]["export_frame"],
            "bytes": os.path.getsize(path)}


def read_oracle(path, legacy_frame=_MISSING):
    """读回 JSONL 并自校（契约 + 帧声明）。

    旧件（本桥登记口径之前导出的）没有 `export_frame`。**不许猜**：要么调用方
    显式声明 `legacy_frame=N`（并把这次声明记进返回体的 `legacy_frame_declared`），
    要么当场 raise —— 静默补一个默认值正是本桥要消灭的那种"尽力而为"。
    """
    head = None
    tracks = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError as exc:
                raise OracleContractError("第 %d 行不是 JSON：%s" % (i + 1, exc))
            if head is None:
                head = rec
            else:
                tracks.append(rec)
    if head is None:
        raise OracleContractError("空文件：%s" % path)
    if "tracks" not in head and isinstance(head.get("scene"), dict):
        doc = {"schema": head.get("schema"), "scene": dict(head["scene"]),
               "tracks": []}
    else:                                   # 也接受"整份 doc 一行"的形态
        doc = dict(head)
        tracks = list(doc.get("tracks") or [])
    doc["tracks"] = tracks
    ok, why = C.validate_doc(doc)
    if not ok:
        raise OracleContractError("真值契约不通过：%s" % why)
    if "export_frame" not in doc["scene"]:
        if legacy_frame is _MISSING:
            raise OracleContractError(
                "%s：缺 scene.export_frame（旧口径件）。要读它必须显式传 "
                "legacy_frame=N 声明该件的部件位姿取自哪一 tick —— 本桥不替调用方猜帧"
                % path)
        doc["scene"]["export_frame"] = int(legacy_frame)
        doc["legacy_frame_declared"] = True
    return doc


def doc_from_dump(dump):
    """Blender 侧 dump → 真值文档（**轴换算落在桥里**，dump 只存 Blender 轴的原始量）。

    dump["tracks"] 的每条是 `{"entity","tick","pos":[bx,by,bz],"rot3":[[…]]}`；
    这里做 `pos -> (x,z,-y)`、`rot3 -> M·R·Mᵀ -> quat`，再过 `build_doc` 契约。
    """
    from . import geom as G
    sc = dict(dump.get("scene") or {})
    sc.setdefault("name", dump.get("name"))
    sc.setdefault("seed", 0)
    sc.setdefault("tick_hz", dump.get("tick_hz"))
    sc.setdefault("world_size", dump.get("world_size"))
    sc.setdefault("units", "m")
    sc["export_frame"] = dump.get("frame")
    sc.setdefault("source", "dsh-blender-wm-bridge/wm_bridge")
    tracks = []
    for t in (dump.get("tracks") or []):
        pos = G.to_lingshu(t["pos"])
        q = G.mat3_to_quat(G.axis_rotate(t["rot3"]))
        tracks.append(track_record(t["entity"], t["tick"], pos, rot_quat=q,
                                   category=t.get("category") or "wmtest",
                                   link=t.get("link")))
    return build_doc(sc, tracks)


def frame_slice(doc, frame):
    """取某一 tick 的全部记录 → {entity: record}（跨件核对的取数口）。"""
    if not isinstance(frame, int) or isinstance(frame, bool):
        raise OracleContractError("frame 须为整数：%r" % (frame,))
    return {r["entity"]: r for r in doc["tracks"] if r["tick"] == frame}


def tick_range(doc):
    """(min_tick, max_tick)，空则 (None, None)。"""
    ts = [r["tick"] for r in doc["tracks"]]
    return (min(ts), max(ts)) if ts else (None, None)
