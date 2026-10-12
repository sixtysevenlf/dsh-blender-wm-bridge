# -*- coding: utf-8 -*-
"""wm_bridge.contract · 真值记录契约（schema 校验 + NaN/Inf 门）

为什么单独成件：灵枢侧的同类教训是「**契约不成立的字段被下游静默消费**」——
`world/gap_dual.py` 的 `d_task` 入参对 D_meta 零作用、`anchor_verify` 把 NaN 钳成上界……
所以本桥的**每个字段在进入 lingshu 之前**必须先过这里，坏值一律拒收，不做"尽力而为"的转换。

生效条件：validate_record(rec) 在 rec 满足 SCHEMA_ORACLE 全部字段约束时返回 (True, "")；
否则返回 (False, 原因串)。只读，不改 rec。
"""
from __future__ import annotations

import math

from . import SCHEMA_ORACLE

#: 一条真值记录必须有的键（缺一即拒——下游按这些键对齐预测）
REQUIRED = ("entity", "tick", "pos")
#: pos 的三轴
AXES = ("x", "y", "z")
#: 可选键及其类型（给了就必须对）
OPTIONAL_TYPES = {
    "category": str,
    "visible": bool,
    "occluded_by": (str, type(None)),
    "screen_bbox": list,
    "depth": (int, float),
    # —— 以下三项由 Blender 侧真值导出实际产生（六足步行机实测需要），故登记为契约一部分 ——
    "link": str,                 # 该实体所属的机构 link 名
    "joint_deg": (int, float),   # 该 tick 的关节角（度）
    "rot_quat": list,            # 世界旋转 [w, x, y, z]
}


def _finite(v) -> bool:
    """生效条件：v 是 bool 时返回 False（bool 是 int 子类，不该被当数值放行）；
    v 是 int/float 且有限（非 NaN / 非 ±Inf）时返回 True；其余 False。"""
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    return math.isfinite(float(v))


def validate_record(rec) -> tuple[bool, str]:
    """校验一条 oracle 记录；返回 (ok, reason)。"""
    if not isinstance(rec, dict):
        return False, "记录不是对象：%s" % type(rec).__name__
    for k in REQUIRED:
        if k not in rec:
            return False, "缺必填键：%s" % k
    if not isinstance(rec["entity"], str) or not rec["entity"]:
        return False, "entity 须为非空字符串，实为 %r" % (rec["entity"],)
    if not isinstance(rec["tick"], int) or isinstance(rec["tick"], bool):
        return False, "tick 须为整数，实为 %r" % (rec["tick"],)
    if rec["tick"] < 0:
        return False, "tick 不得为负：%r" % (rec["tick"],)
    pos = rec["pos"]
    if not isinstance(pos, dict):
        return False, "pos 须为对象，实为 %s" % type(pos).__name__
    for a in AXES:
        if a not in pos:
            return False, "pos 缺轴：%s" % a
        # NaN / Inf 门：灵枢 world 侧的 NaN 事故就出在这里（被 min/max 钳成上界）
        if not _finite(pos[a]):
            return False, "pos.%s 非有限数值：%r（NaN/Inf/bool 一律拒收）" % (a, pos[a])
    for k, typ in OPTIONAL_TYPES.items():
        if k in rec and rec[k] is not None and not isinstance(rec[k], typ):
            return False, "%s 类型不符：期望 %s，实为 %s" % (
                k, getattr(typ, "__name__", typ), type(rec[k]).__name__)
    if "screen_bbox" in rec and rec["screen_bbox"] is not None:
        bb = rec["screen_bbox"]
        if len(bb) != 4 or not all(_finite(v) for v in bb):
            return False, "screen_bbox 须为 4 个有限数值，实为 %r" % (bb,)
    if "depth" in rec and rec["depth"] is not None and not _finite(rec["depth"]):
        return False, "depth 非有限数值：%r" % (rec["depth"],)
    if "joint_deg" in rec and rec["joint_deg"] is not None and not _finite(rec["joint_deg"]):
        return False, "joint_deg 非有限数值：%r" % (rec["joint_deg"],)
    if "rot_quat" in rec and rec["rot_quat"] is not None:
        q = rec["rot_quat"]
        if len(q) != 4 or not all(_finite(v) for v in q):
            return False, "rot_quat 须为 4 个有限数值 [w,x,y,z]，实为 %r" % (q,)
    return True, ""


def validate_doc(doc) -> tuple[bool, str]:
    """校验一份完整导出的顶层结构（schema / scene / tracks）。"""
    if not isinstance(doc, dict):
        return False, "顶层不是对象"
    if doc.get("schema") != SCHEMA_ORACLE:
        return False, "schema 不符：期望 %s，实为 %r" % (SCHEMA_ORACLE, doc.get("schema"))
    scene = doc.get("scene")
    if not isinstance(scene, dict):
        return False, "缺 scene 对象"
    for k in ("name", "tick_hz", "world_size", "units"):
        if k not in scene:
            return False, "scene 缺键：%s" % k
    tracks = doc.get("tracks")
    if not isinstance(tracks, list):
        return False, "tracks 须为列表"
    seen = set()
    for i, r in enumerate(tracks):
        ok, why = validate_record(r)
        if not ok:
            return False, "tracks[%d]：%s" % (i, why)
        # 同一 (entity, tick) 不得重复——重复会让逐 tick 对齐产生歧义
        key = (r["entity"], r["tick"])
        if key in seen:
            return False, "tracks 重复键 (entity, tick)=%r" % (key,)
        seen.add(key)
    return True, ""
