# -*- coding: utf-8 -*-
"""wm_bridge.bpy_dump · Blender 侧**原始量**抽取（本包唯一需要 bpy 的文件）

分工（这条分工是整个设计的关键）：
    bpy_dump.py            **只抽原始量**：世界顶点、三角面、局部包围盒、体积、
                           世界旋转矩阵、每个 tick 的枢轴位姿 —— 全是 Blender 轴的原始数。
    geom.py / oracle.py    **做全部换算与契约**：轴换算、图元拟合、欧拉、四元数、
                           schema、fail-closed 校验。

这样切线在两边：
  · 换算逻辑可以在**没有 Blender** 的机器上被完整自测（`wm_bridge.selftest`）；
  · Blender 侧只剩"读矩阵"这种不得不依赖 bpy 的一小段。

`import bpy` **只在函数体内**（模块顶层零 bpy），所以本文件在 WSL 里也能被 import
（只读 docstring / 常量、跑 `--help`），不会把 bpy 依赖带进 lingshu。

---------------------------------------------------------------- 三条实测教训（已用断言挡住）
1. **必须显式 `scene.frame_set(frame)` 再读几何**。
   踩过的坑：不设帧时 `matrix_world` 反映的是**动画循环最后一次赋值**留下的位姿
   —— 机械臂的部件位姿一度是 u=1（yaw **+35°**），而同一份 `oracle.jsonl` 的
   `tick 0` 是 u=0（yaw **−35°**）：一次导出里两件产物描述了**两个姿态**。
   本文件抽完几何后立刻回读同一帧的关节位姿，交给
   `geom.check_pose_consistency` 当场核对（`cli export-*` 也会复跑一次）。
2. **尺寸用局部 bbox × 缩放（真 OBB）**，不用 `ob.dimensions`（世界 AABB）。
   世界 AABB 在旋转件上**虚胖**（小腿 35° 时长度被算成投影复合值），
   volume/dims 比值整体偏小、图元判据跟着偏。
3. **轴换算不在这里做** —— 这里只交 Blender 轴的原始矩阵，换算见 geom 的
   `AXIS_MAP` / `assert_axis_map`：必须是真旋转 det=+1，镜像解 (x,z,y) 会被拒。

用法（在 Blender 里跑，无头也行）：
    python -m wm_bridge.bpy_dump --out spec.json --collection LAMP \\
        --name lamp --frame 0 --frames 40 --tick-hz 24 --world-size 50
    python -m wm_bridge.bpy_dump --out geo.json --collection LAMP --no-tracks
退出码：0 成功；2 失败（fail-closed：抽不出就把话说清楚，不产半成品）。
"""
from __future__ import annotations

import argparse
import json
import os
import traceback

DUMP_SCHEMA = "wm_bridge.dump/1"


class BpyDumpError(Exception):
    """抽取失败（fail-closed）。"""


def _bpy():
    """惰性取 bpy（顶层零依赖；没有 bpy 时给出可操作的报错）。"""
    try:
        import bpy                                        # noqa: F401
    except ImportError as exc:
        raise BpyDumpError(
            "bpy 不可用：本命令必须在 Blender 内运行（%s）。"
            "桥的其余部分（selftest / cli export-* --spec）不需要 Blender。" % exc)
    return bpy


def lin2srgb(c):
    c = max(0.0, min(1.0, float(c)))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _base_color_of(m):
    """单个材质的线性基色（无 Principled 时回落到既有缺省灰）。"""
    nt = getattr(m, "node_tree", None)
    if nt is None:
        return [0.6, 0.6, 0.62]
    b = next((n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
    if b is None or "Base Color" not in b.inputs:
        return [0.6, 0.6, 0.62]
    return [round(float(v), 6) for v in b.inputs["Base Color"].default_value[:3]]


def obj_color(ob):
    """件色：线性基色 → sRGB 0..255；发光件按发光色提亮（照抄既有口径）。"""
    for m in ob.data.materials:
        if not m or getattr(m, "node_tree", None) is None:
            continue
        b = next((n for n in m.node_tree.nodes
                  if n.bl_idname == "ShaderNodeBsdfPrincipled"), None)
        if b is None:
            continue
        try:
            lin = list(_base_color_of(m))
            if "Emission Strength" in b.inputs \
                    and float(b.inputs["Emission Strength"].default_value) > 0.5:
                e = b.inputs.get("Emission Color") or b.inputs.get("Emission")
                if e is not None:
                    lin = [min(1.0, float(e.default_value[i]) * 0.85 + lin[i] * 0.15)
                           for i in range(3)]
            return [int(round(lin2srgb(v) * 255)) for v in lin]
        except Exception:                                  # noqa: BLE001
            break
    return [170, 170, 175]


def _mesh_for(ob, dg):
    """该对象**本次导出用的那份网格**（与 verts/tris 同一份）。"""
    if dg is None:
        return ob.data
    return ob.evaluated_get(dg).to_mesh()


def mesh_volume(me):
    """有符号四面体求和取绝对体积（闭合网格；非闭合件误差会体现在拟合比上）。"""
    me.calc_loop_triangles()
    vs = me.vertices
    v = 0.0
    for t in me.loop_triangles:
        a, b, c = (vs[i].co for i in t.vertices)
        v += a.dot(b.cross(c)) / 6.0
    return abs(v)


def nearest_joint(ob, joints):
    """件的**最近关节祖先**（含自身是关节的情形）→ 关节对象或 None。

    比"直接子节点减去子树"稳：多级关节下不会把孙件算进祖父 link。
    """
    cur = ob
    while cur is not None:
        if cur in joints:
            return cur
        cur = cur.parent
    return None


def collect(collections=None, frame=0, frames=1, name="scene", tick_hz=24.0,
            world_size=50.0, scene_extra=None, with_tracks=True,
            translate=(0.0, 0.0, 0.0), mesh_source="evaluated",
            allow_raw_with_modifiers=False):
    """抽一份 dump（返回 dict）。

    ⚠ 第一步就是 `scene.frame_set(frame)`：几何/部件位姿必须**显式取帧**，
    不能吃"上一次循环留下的位姿"（模块 docstring 教训 1）。

    ★ `mesh_source`（第 4 轮优化 #5）——**导出的是哪一份网格**：
      · `"evaluated"`（默认，语义正确）：走 `evaluated_get(depsgraph).to_mesh()`
        ⇒ 导出的是**修改器参与后**的网格，也就是**你在 Blender 里看到的/渲染的那件东西**。
      · `"raw"`：直接用 `ob.data` —— **修改器完全不参与**（旧行为）。

    **病史（第 4 轮实测）**：`build_models.py` / `build_hexapod.py` 给对象挂了**活的 Bevel
    修改器**（从未 apply），而旧实现只导 `ob.data` ⇒
      · `wmtest_models.blend`：53 件里 **36 件**带修改器，raw 4416 tris vs 求值 **9440 tris（2.14×）**；
        `TURRET_body` 是 raw 20/36 → 求值 **140/276**；`ARM_upper` 是 raw 8/12（**纯立方体**）
        → 求值 56/108。⇒ 世界模型看到的是**另一件东西**（与"渲出的就是同一件"的论断冲突）。
      · `gearbox.blend`：22 件里 5 件（`GB_base` 等）同样受害（1.02×，因为齿轮占了绝大多数三角）。

    **fail-closed**：`mesh_source="raw"` 且**有对象带活修改器**时**直接报错**（除非显式
    `allow_raw_with_modifiers=True`）。这样"导出与渲染不是同一件东西"**不可能再静默发生** ——
    这正是这条缺陷此前能长期存在的原因。
    """
    from mathutils import Vector
    bpy = _bpy()
    sc = bpy.context.scene
    sc.frame_set(int(frame))              # ← 教训 1 的修法：位姿取帧是显式动作
    try:
        bpy.context.view_layer.update()
    except Exception:                                       # noqa: BLE001
        pass
    colls = list(collections or [c for c in bpy.data.collections if c.all_objects])
    objs = [o for c in colls for o in c.all_objects]
    joints = [o for o in objs if o.type == "EMPTY"]
    meshes = sorted([o for o in objs if o.type == "MESH"], key=lambda o: o.name)
    if not meshes:
        raise BpyDumpError("选中的集合里没有 MESH 对象（--collection 选对了吗？）")

    scene = {"name": name, "seed": 0, "tick_hz": float(tick_hz),
             "world_size": float(world_size), "units": "m",
             "cycle_frames": int(frames)}
    if scene_extra:
        scene.update({k: v for k, v in scene_extra.items() if v is not None})
    mods_by_obj = {ob.name: [m.name + ":" + m.type for m in ob.modifiers] for ob in meshes}
    n_with_mods = sum(1 for v in mods_by_obj.values() if v)
    if mesh_source == "raw" and n_with_mods and not allow_raw_with_modifiers:
        raise BpyDumpError(
            "mesh_source='raw' 但选中的 %d/%d 个 MESH 对象带**活修改器**：%s … —— "
            "导出件将**不是** Blender 渲染的那件东西（这是第 4 轮 #5 的实测缺陷）。"
            "请改用 `mesh_source='evaluated'`（默认），或显式传 "
            "`allow_raw_with_modifiers=True` 并**在产物里写明**你接受这个差异。"
            % (n_with_mods, len(meshes), sorted(k for k, v in mods_by_obj.items() if v)[:6]))
    _dg = bpy.context.evaluated_depsgraph_get() if mesh_source == "evaluated" else None

    out = {"schema": DUMP_SCHEMA, "name": name, "frame": int(frame),
           "frames": int(frames), "tick_hz": float(tick_hz),
           "world_size": float(world_size), "translate": list(translate),
           "source": "dsh-blender-wm-bridge/wm_bridge.bpy_dump",
           "mesh_source": mesh_source,
           "modifier_report": {"meshes": len(meshes), "with_live_modifiers": n_with_mods,
                               "objects": sorted(k for k, v in mods_by_obj.items() if v)},
           "collections": [c.name for c in colls], "scene": scene,
           "meshes": [], "links": [], "nodes": [o.name for o in joints],
           "tracks": []}

    for ob in meshes:
        mw = ob.matrix_world
        _ev = ob.evaluated_get(_dg) if _dg is not None else None
        me = _ev.to_mesh() if _ev is not None else ob.data
        verts = [[round(float(c), 6) for c in (mw @ v.co)] for v in me.vertices]
        me.calc_loop_triangles()
        tris = [[int(i) for i in t.vertices] for t in me.loop_triangles]
        mats, seen = [], set()
        for m in (me.materials or []):
            if m is None or m.name in seen:
                continue
            seen.add(m.name)
            mats.append([m.name, _base_color_of(m)])
        out["meshes"].append({
            "name": ob.name, "verts": verts, "tris": tris,
            "material": (me.materials[0].name
                         if me.materials and me.materials[0] else "M_default"),
            "materials": mats,
            "n_modifiers": len(mods_by_obj.get(ob.name) or []),
            "modifiers": list(mods_by_obj.get(ob.name) or [])})

    by_joint = {}
    if _dg is not None:                     # 释放 Blender 求值网格（否则会越攒越多）
        for ob in meshes:
            try:
                ob.evaluated_get(_dg).to_mesh_clear()
            except Exception:                               # noqa: BLE001
                pass
    for ob in meshes:
        by_joint.setdefault(nearest_joint(ob, joints), []).append(ob)
    for j, obs in sorted(by_joint.items(), key=lambda kv: (kv[0] is None,
                                                          kv[0].name if kv[0] else "")):
        anchor_ob = j if j is not None else obs[0]
        parts = []
        for ob in obs:
            bb = [Vector(v) for v in ob.bound_box]
            xs = [v.x for v in bb]
            ys = [v.y for v in bb]
            zs = [v.z for v in bb]
            sca = ob.matrix_world.to_scale()
            dims = [max(0.0, (max(xs) - min(xs)) * abs(sca.x)),
                    max(0.0, (max(ys) - min(ys)) * abs(sca.y)),
                    max(0.0, (max(zs) - min(zs)) * abs(sca.z))]
            if min(dims) <= 0:
                continue
            mw = ob.matrix_world
            w3 = mw.to_quaternion().to_matrix()      # 正交化（吃掉缩放）
            # 该件相对**所属枢轴**的局部旋转（帧无关：本数据集只有关节被动画化）。
            # 跨件守卫用它核对「件级姿态链」：R_link(frame) · local3 == world3。
            l3 = (anchor_ob.matrix_world.to_quaternion().inverted()
                  @ mw.to_quaternion()).to_matrix()
            parts.append({
                "src": ob.name,
                "dims": [round(v, 6) for v in dims],
                "local_center": [round((max(xs) + min(xs)) / 2, 6),
                                 round((max(ys) + min(ys)) / 2, 6),
                                 round((max(zs) + min(zs)) / 2, 6)],
                # vol 与导出网格**同源**（evaluated 时用求值网格的顶点），否则件匹配
                # 会拿"另一种形状"的体积去对，口径就不一致了。
                "vol": round(mesh_volume(_mesh_for(ob, _dg)) * abs(mw.to_3x3().determinant()), 9),
                "world3": [[round(float(w3[i][k]), 9) for k in range(3)]
                           for i in range(3)],
                "local3": [[round(float(l3[i][k]), 9) for k in range(3)]
                           for i in range(3)],
                "world_trans": [round(float(v), 6) for v in mw.translation],
                "color": obj_color(ob)})
        if parts:
            out["links"].append({
                "name": anchor_ob.name,
                "anchor": [round(float(v), 6)
                           for v in anchor_ob.matrix_world.translation],
                "parts": parts})

    if with_tracks:
        if not joints:
            raise BpyDumpError("没有关节（EMPTY）对象，真值没有可记的实体")
        for t in range(int(frames)):
            sc.frame_set(t)
            for ob in joints:
                mw = ob.matrix_world
                w3 = mw.to_quaternion().to_matrix()
                out["tracks"].append({
                    "entity": ob.name, "tick": t, "category": "wmtest",
                    "link": ob.name,
                    "pos": [round(float(v), 6) for v in mw.translation],
                    "rot3": [[round(float(w3[i][k]), 9) for k in range(3)]
                             for i in range(3)]})
        sc.frame_set(int(frame))   # 抽完把帧放回声明的那一帧（可复核、可复跑）
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="wm_bridge.bpy_dump",
        description="Blender 侧原始量抽取（必须跑在 Blender 内）")
    ap.add_argument("--out", required=True, help="dump JSON 输出路径")
    ap.add_argument("--collection", action="append", default=[],
                    help="集合名（可重复；缺省=全部有对象的集合）")
    ap.add_argument("--name", default="scene")
    ap.add_argument("--frame", type=int, default=0,
                    help="几何/部件位姿取自哪一帧（显式声明，写进产物）")
    ap.add_argument("--frames", type=int, default=1,
                    help="真值 tick 数（记 0..frames-1）")
    ap.add_argument("--tick-hz", type=float, default=24.0)
    ap.add_argument("--world-size", type=float, default=50.0)
    ap.add_argument("--motion", default=None,
                    help="scene.motion 备注（static / periodic_rotation / …）")
    ap.add_argument("--translate", default="0,0,0")
    ap.add_argument("--no-tracks", action="store_true", help="只抽几何（不抽真值）")
    ap.add_argument("--mesh-source", dest="mesh_source", default="evaluated",
                    choices=["raw", "evaluated"],
                    help="导出哪一份网格：evaluated（默认，= Blender 渲染的那件）/ raw（修改器不参与）")
    ap.add_argument("--allow-raw-with-modifiers", dest="allow_raw", action="store_true",
                    help="允许 raw + 活修改器（会**在产物里写明**你接受这个差异）")
    args = ap.parse_args(argv)
    try:
        bpy = _bpy()
        colls = ([bpy.data.collections[n] for n in args.collection]
                 if args.collection else None)
        tr = tuple(float(x) for x in args.translate.split(","))
        dump = collect(colls, frame=args.frame, frames=args.frames, name=args.name,
                       tick_hz=args.tick_hz, world_size=args.world_size,
                       scene_extra=({"motion": args.motion} if args.motion else None),
                       with_tracks=not args.no_tracks, translate=tr,
                       mesh_source=args.mesh_source,
                       allow_raw_with_modifiers=args.allow_raw)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(dump, f, ensure_ascii=False, sort_keys=True)
        print("BPYDUMP " + json.dumps(
            {"ok": True, "out": args.out, "frame": dump["frame"],
             "frames": dump["frames"], "meshes": len(dump["meshes"]),
             "links": len(dump["links"]), "tracks": len(dump["tracks"]),
             "nodes": dump["nodes"], "mesh_source": dump.get("mesh_source"),
             "with_live_modifiers": (dump.get("modifier_report") or {}).get("with_live_modifiers")},
            ensure_ascii=False, separators=(",", ":")))
        return 0
    except BpyDumpError as exc:
        print("BPYDUMP " + json.dumps({"ok": False, "error": str(exc)},
                                      ensure_ascii=False))
        return 2
    except Exception as exc:                                # noqa: BLE001
        print("BPYDUMP " + json.dumps(
            {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
             "tb": traceback.format_exc()[-600:]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
