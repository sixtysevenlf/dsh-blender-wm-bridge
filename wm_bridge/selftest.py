# -*- coding: utf-8 -*-
"""wm_bridge.selftest · 全链自测 + 定点变异自证

跑法（从 fork 根）：
    python3 -X utf8 -m wm_bridge.selftest
    python3 -X utf8 -m wm_bridge.selftest --mutate

契约：末行打印 `VERDICT=PASS` 或 `VERDICT=FAIL`；退出码 0/1。
反面对照纪律（借灵枢与本插件共同的惯例）：**判据不设反面证明就等于没有判据**。
`--mutate` 逐条把判据短路，断言**恰好的那几项**转红——不多不少。
"""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import sys
import tempfile

if __package__ in (None, ""):                      # 直接 python 跑时的兜底
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from wm_bridge import contract as C
    from wm_bridge import manifest as M
    from wm_bridge import probe as P
    from wm_bridge import cli as CLI
    from wm_bridge import geom as G
    from wm_bridge import oracle as O
    from wm_bridge import SCHEMA_ORACLE
else:
    from . import contract as C
    from . import manifest as M
    from . import probe as P
    from . import cli as CLI
    from . import geom as G
    from . import oracle as O
    from . import SCHEMA_ORACLE

#: 保证没人监听的端口（fail-closed 判据的对照面）
CLOSED_PORT = 59931

GOOD_REC = {"entity": "wolf", "tick": 3, "pos": {"x": 15.04, "y": 1.5, "z": 15.2},
            "category": "animal", "visible": True, "occluded_by": None,
            "screen_bbox": [10.0, 20.0, 30.0, 40.0], "depth": 12.7}


def good_doc():
    return {"schema": SCHEMA_ORACLE,
            "scene": {"name": "chase", "seed": 42, "tick_hz": 30,
                      "world_size": 100, "units": "m"},
            "tracks": [copy.deepcopy(GOOD_REC), {"entity": "rabbit", "tick": 3,
                                        "pos": {"x": 1.0, "y": 0.5, "z": 2.0}}]}


def _sandbox():
    d = tempfile.mkdtemp(prefix="wmb_self_")
    os.makedirs(os.path.join(d, "scene"), exist_ok=True)
    open(os.path.join(d, "scene", "a.jsonl"), "w", encoding="utf-8").write('{"e":"wolf"}\n')
    open(os.path.join(d, "scene", "b.jsonl"), "w", encoding="utf-8").write('{"e":"rabbit"}\n')
    return d


def _closed_probe():
    """在**保证没人监听**的端口上探一次（fail-closed 判据的正面对照）。"""
    keep = {k: os.environ.get(k) for k in ("DSH_BLENDER_WM_ADDON_PORT", "DSH_BLENDER_WM_HTTP_PORT")}
    os.environ["DSH_BLENDER_WM_ADDON_PORT"] = str(CLOSED_PORT)
    os.environ["DSH_BLENDER_WM_HTTP_PORT"] = str(CLOSED_PORT + 1)
    try:
        return P.probe(host="127.0.0.1")
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ==========================================================================
# 几何 / 部件 / 真值：夹具与用例（E/F/G/H/I 组）
# ==========================================================================
def _rz(deg):
    """绕 Blender Z 的旋转（→ lingshu 绕 Y）——本夹具只用这一种，便于手算锚点。"""
    return G.mat3_from_euler_xyz((0.0, 0.0, math.radians(deg)))


def _dump_min(link_deg=35.0, tick_deg=None, anchor_shift=(0.0, 0.0, 0.0),
              frame=0, name="J", local_deg=0.0, track_name=None,
              track_shift=(0.0, 0.0, 0.0)):
    """最小 dump：一个关节 link + 一个件 + 一条真值。

    link_deg : **几何/部件**读到的 link 世界旋转（Blender 轴，绕 Z）
    tick_deg : **oracle** 记的该 link 旋转；None ⇒ 与 link_deg 同帧（应通过）；
               与 link_deg 不同 ⇒ 就是"位姿取了别的帧"（应被守卫抓住）
    """
    if tick_deg is None:
        tick_deg = link_deg
    r_link_bl = _rz(link_deg)
    r_part_bl = G.mat3_mul(r_link_bl, _rz(local_deg))
    r_part_ll = G.axis_rotate(r_part_bl)
    local3 = G.mat3_mul(G.mat3_transpose(r_link_bl), r_part_bl)
    anchor = [1.0 + anchor_shift[0], 2.0 + anchor_shift[1], 3.0 + anchor_shift[2]]
    # 件的 link 局部平移取 0 ⇒ 件的世界平移 == 枢轴平移（便于 anchor 判据手算）
    dump = {
        "schema": "wm_bridge.dump/1", "name": "mini", "frame": frame, "frames": 1,
        "tick_hz": 24.0, "world_size": 10.0, "translate": [0, 0, 0],
        "source": "selftest", "nodes": [name],
        "meshes": [{"name": "P", "verts": [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                    "tris": [[0, 1, 2]], "material": "M_x",
                    "materials": [["M_x", [0.5, 0.5, 0.5]]]}],
        "links": [{"name": name, "anchor": anchor,
                   "parts": [{"src": "P", "dims": [1.0, 1.0, 1.0],
                              "local_center": [0.0, 0.0, 0.0], "vol": 1.0,
                              "world3": [list(r) for r in r_part_bl],
                              "local3": [list(r) for r in local3],
                              "world_trans": list(anchor),
                              "color": [120, 120, 120]}]}],
        "tracks": [{"entity": (name if track_name is None else track_name),
                    "tick": frame, "category": "wmtest",
                    "link": (name if track_name is None else track_name),
                    "pos": [anchor[i] + track_shift[i] for i in range(3)],
                    "rot3": [list(r) for r in _rz(tick_deg)]}],
    }
    return dump


def _oracle_of(dump):
    return O.doc_from_dump(dump)


def _mini_shapes(dump):
    return G.build_shapes_doc(G.links_from_dump(dump), source="selftest",
                              export_frame=dump["frame"])


def ge_geom(out):
    """E 组：轴换算 / OBJ 头 / OBJ 往返。"""
    out.append(("E1 轴换算 det=+1、镜像解 det=−1",
                abs(G.mat3_det(G.AXIS_MAP) - 1.0) < 1e-12
                and abs(G.mat3_det(G.MIRROR_MAP) + 1.0) < 1e-12,
                "det(AXIS)=%s det(MIRROR)=%s" % (G.mat3_det(G.AXIS_MAP),
                                                 G.mat3_det(G.MIRROR_MAP))))
    try:
        G.assert_axis_map(G.MIRROR_MAP)
        ok, why = False, "镜像解竟然被放行"
    except G.GeomError as exc:
        ok, why = "镜像" in str(exc), str(exc)[:48]
    out.append(("E2 镜像解必须被拒（det≠+1）", ok, why))

    out.append(("E3 (x,y,z)→(x,z,−y)",
                G.to_lingshu((1.0, 2.0, 3.0)) == (1.0, 3.0, -2.0),
                str(G.to_lingshu((1.0, 2.0, 3.0)))))

    # 欧拉锚点（实测数据）：Blender 的 euler XYZ = Rz·Ry·Rx，且两解取 L1 更小者
    _ry = lambda deg: G.mat3_from_euler_xyz((0.0, math.radians(deg), 0.0))
    e1 = G.mat3_to_euler_xyz(G.mat3_mul(_ry(35.0), G.mat3_from_euler_xyz(
        (math.radians(-40.0), 0.0, 0.0))))
    d1 = [round(math.degrees(v), 4) for v in e1]
    e2 = [round(math.degrees(v), 4) for v in G.mat3_to_euler_xyz(_ry(-135.0))]
    out.append(("E4 欧拉锚点 (−40,35,0) 与两解取小 (0,−135,0)",
                d1 == [-40.0, 35.0, 0.0] and e2 == [0.0, -135.0, 0.0],
                "%s / %s" % (d1, e2)))

    out.append(("E5 OBJ 头部含 fail-closed 的 normalize 契约行",
                G.NORMALIZE_LINE in "\n".join(G.obj_head())
                and G.require_normalize("\n".join(G.obj_head())),
                G.NORMALIZE_LINE))
    try:
        G.require_normalize("# foo\nv 0 0 0\n")
        ok, why = False, "缺 normalize 行竟然放行"
    except G.GeomError as exc:
        ok, why = "# normalize" in str(exc), str(exc)[:48]
    out.append(("E6 缺 normalize 行必须 raise", ok, why))

    text, rows, summ = G.format_obj(
        [{"name": "Box", "verts": [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
          "tris": [(0, 1, 2)], "material": "M_x",
          "materials": [("M_x", (0.5, 0.25, 0.125))]}], mtl_name="mesh.mtl")
    parsed = G.parse_obj(text)
    text2, rows2, _ = G.format_obj(parsed["meshes"], mtl_name="mesh.mtl")
    out.append(("E7 OBJ 写→读→写 定点（逐字节）且 MTL 行齐",
                text2 == text and rows == ["newmtl M_x", "Kd 0.500000 0.250000 0.125000"],
                "v=%s f=%s" % (summ["vertices"], summ["faces"])))
    try:
        G.format_obj([{"name": "B", "verts": [(0, 0, 0)], "tris": [(0, 1, 2)]}])
        ok, why = False, "越界面索引竟然放行"
    except G.GeomError as exc:
        ok, why = "越界" in str(exc), str(exc)[:40]
    out.append(("E8 面索引越界必须 raise", ok, why))
    try:
        G.format_obj([])
        ok, why = False, "空网格竟然放行"
    except G.GeomError as exc:
        ok, why = "没有任何网格" in str(exc), str(exc)[:40]
    out.append(("E9 空网格必须 raise（不产空件）", ok, why))


def gj_reproducible_obj(out):
    """J 组：OBJ 可复现性——**同输入必须同文件**（面序是独立的一维，见 geom.canonical_tris）。

    判据设计成**确定性**的，不靠 ASLR 概率：
      同一份几何喂两遍，第二遍把**面序列整体打乱 + 每个面环状旋转**（顶点流不动）。
      若写出侧没有规范面序，两遍产物必然不同（差异由我们构造，概率 1）；
      有规范面序则逐字节相同。这样变异（去掉规范面序）**必红**，不是"有时红"。
    """
    verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0),
             (0.5, 0.5, 1.0)]
    tris = [(0, 1, 2), (0, 2, 3), (1, 2, 4), (0, 1, 4), (2, 3, 4), (0, 3, 4)]
    m1 = [{"name": "P", "verts": verts, "tris": tris, "material": "M_x",
           "materials": [("M_x", (0.2, 0.4, 0.6))]}]
    shuffled = list(reversed(tris))
    rot = [tuple(list(t)[k:] + list(t)[:k]) for k, t in
           enumerate([(t[1], t[2], t[0]) for t in shuffled])]
    m2 = [{"name": "P", "verts": verts, "tris": rot, "material": "M_x",
           "materials": [("M_x", (0.2, 0.4, 0.6))]}]
    t1, _r1, _s1 = G.format_obj(m1, mtl_name="mesh.mtl")
    t2, _r2, _s2 = G.format_obj(m2, mtl_name="mesh.mtl")
    out.append(("J1 同几何两种面序输入 ⇒ 产物逐字节相同（面序规范化生效）",
                t1 == t2, "输入面序不同=%s 产物相同=%s" % (tris != rot, t1 == t2)))

    # 直接断言代码路径（不依赖概率）：输出的 f 行必须是「最小索引打头 + 字典序」
    fl = [l for l in t1.split("\n") if l.startswith("f ")]
    parsed = [[int(x) for x in l.split()[1:]] for l in fl]
    minfirst = all(p[0] == min(p) for p in parsed)
    issorted = parsed == sorted(parsed)
    out.append(("J2 输出的 f 行按「最小索引打头 + 字典序」", minfirst and issorted,
                "min_first=%s sorted=%s n=%d" % (minfirst, issorted, len(parsed))))

    # 绕向必须保住：环状旋转 ≠ sorted —— 用 (2,1,0) 区分：
    #   环状旋转 → (0,2,1)（绕向不变）；sorted() → (0,1,2)（绕向翻转）
    cyc = G.canonical_tris([(2, 1, 0)])
    out.append(("J3 规范面序是环状旋转而非 sorted（保绕向）",
                cyc == [(0, 2, 1)] and cyc != [(0, 1, 2)], str(cyc)))
    # 5 轮重复（把"至少一次不同"的强判据也跑一遍，作为对概率路径的兜底观测）
    same = 0
    for _ in range(5):
        a, _x, _y = G.format_obj(m1, mtl_name="mesh.mtl")
        b, _x2, _y2 = G.format_obj(m2, mtl_name="mesh.mtl")
        if a == b:
            same += 1
    out.append(("J4 5 轮重复导出（两种输入序）全部逐字节相同", same == 5,
                "same=%d/5" % same))


def gf_fit(out):
    """F 组：图元拟合——判据是「比值最接近 1」而不是「最大」。"""
    # 解析体积：圆柱 / 立方体 / 方锥 / 球
    cyl_d = (0.8, 0.8, 2.0)
    cyl_v = math.pi / 4 * 0.8 * 0.8 * 2.0
    cube_d = (1.0, 1.0, 1.0)
    pyr_d = (1.2, 1.2, 1.5)
    pyr_v = math.pi / 12 * 1.2 * 1.2 * 1.5
    sph_d = (1.0, 1.0, 1.0)
    sph_v = math.pi / 6 * 1.0 ** 3
    k1, r1 = G.fit_kind(cyl_d, cyl_v)
    out.append(("F1 已知圆柱 ⇒ pillar（不是 pyramid）", k1 == "pillar", "%s %.4f" % (k1, r1)))
    k2, r2 = G.fit_kind(cube_d, 1.0)
    out.append(("F2 已知立方体 ⇒ box", k2 == "box", "%s %.4f" % (k2, r2)))
    k3, r3 = G.fit_kind(pyr_d, pyr_v)
    out.append(("F3 已知方锥 ⇒ pyramid", k3 == "pyramid", "%s %.4f" % (k3, r3)))
    k4, r4 = G.fit_kind(sph_d, sph_v)
    out.append(("F4 已知球 ⇒ sphere", k4 == "sphere", "%s %.4f" % (k4, r4)))

    # F5 判据方向：构造「最大比值解 ≠ 最接近解」——取最大会把长条件判成锥
    dims = (0.2, 1.4, 0.2)
    vol = 0.2 * 1.4 * 0.2 * 0.999        # 几乎是个盒子
    kk, rr = G.fit_kind(dims, vol)
    km, rm = G.max_ratio_kind(dims, vol)
    out.append(("F5 判据是「最接近 1」而非「最大」（两者解不同）",
                kk == "box" and km != kk, "fit=%s(%.4f) max=%s(%.4f)" % (kk, rr, km, rm)))
    try:
        G.fit_kind((1.0, -1.0, 1.0), 1.0)
        ok, why = False, "负尺寸竟然放行"
    except G.GeomError as exc:
        ok, why = "非法" in str(exc), str(exc)[:44]
    out.append(("F6 负尺寸/NaN 必须 raise", ok, why))


def gg_oracle(out):
    """G 组：真值契约（写入前自校）。"""
    sc = O.scene_stub("mini", tick_hz=24, world_size=10, export_frame=0)
    tr = O.track_record("J", 0, (1.0, 2.0, 3.0), rot_quat=[1.0, 0.0, 0.0, 0.0])
    doc = O.build_doc(sc, [tr])
    out.append(("G1 合法真值被接受且带 export_frame",
                doc["schema"] == SCHEMA_ORACLE and doc["scene"]["export_frame"] == 0,
                "%s" % doc["schema"]))
    try:
        O.build_doc({"name": "x", "tick_hz": 24, "world_size": 10, "units": "m"}, [tr])
        ok, why = False, "缺 export_frame 竟然放行"
    except O.OracleContractError as exc:
        ok, why = "export_frame" in str(exc), str(exc)[:44]
    out.append(("G2 缺 export_frame 必须 raise（位姿必须记帧）", ok, why))

    bad = {"entity": "J", "tick": 0, "pos": {"x": float("nan"), "y": 0.0, "z": 0.0}}
    ok, why = C.validate_doc({"schema": SCHEMA_ORACLE, "scene": sc, "tracks": [bad]})
    out.append(("G3 NaN 真值必须被拒", (not ok) and ("非有限" in why), why))
    try:
        O.track_record("J", 0, (1.0, 2.0, 3.0), rot_quat=[1.0, 0.0, 0.0])
        ok, why = False, "rot_quat 长度 3 竟然放行"
    except O.OracleContractError as exc:
        ok, why = "rot_quat" in str(exc), str(exc)[:44]
    out.append(("G4 rot_quat 维度不对必须 raise", ok, why))
    try:
        O.build_doc(sc, [tr, dict(tr)])
        ok, why = False, "(entity,tick) 重复竟然放行"
    except O.OracleContractError as exc:
        ok, why = "重复" in str(exc), str(exc)[:44]
    out.append(("G5 (entity,tick) 重复必须 raise", ok, why))

    d2 = O.build_doc(O.scene_stub("mini", 24, 10, export_frame=5),
                     [O.track_record("J", 0, (0.0, 0.0, 0.0)),
                      O.track_record("J", 5, (1.0, 0.0, 0.0))])
    out.append(("G6 export_frame 在 tick 范围内 ⇒ 无覆盖问题",
                O.frame_coverage_problem(d2) is None, ""))
    d3 = O.build_doc(O.scene_stub("mini", 24, 10, export_frame=9),
                     [O.track_record("J", 0, (0.0, 0.0, 0.0)),
                      O.track_record("J", 5, (1.0, 0.0, 0.0))])
    out.append(("G7 export_frame 越出真值范围 ⇒ 点名（位姿与真值不同帧集合）",
                bool(O.frame_coverage_problem(d3)), str(O.frame_coverage_problem(d3))[:46]))


def gh_cli_export(out):
    """H 组：CLI export-*（不需要 Blender：吃 spec / 重出既有件）。"""
    d = tempfile.mkdtemp(prefix="wmb_cli_")
    try:
        dump = _dump_min()
        sp = os.path.join(d, "spec.json")
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(dump, f, ensure_ascii=False)
        op = os.path.join(d, "mesh.obj")
        rc1 = CLI.main(["export-obj", "--spec", sp, "--out", op,
                        "--mtl", os.path.join(d, "mesh.mtl")])
        body = open(op, encoding="utf-8").read()
        out.append(("H1 export-obj --spec rc=0 且头部含 normalize",
                    rc1 == 0 and G.NORMALIZE_LINE in body, "rc=%s" % rc1))
        shp = os.path.join(d, "shapes.json")
        rc2 = CLI.main(["export-shapes", "--spec", sp, "--out", shp])
        sd = json.load(open(shp, encoding="utf-8"))
        out.append(("H2 export-shapes --spec rc=0 且 export_frame 落进产物",
                    rc2 == 0 and sd.get("export_frame") == 0
                    and sd.get("pos_origin") == "anchor", "rc=%s" % rc2))
        orc = os.path.join(d, "oracle.jsonl")
        rc3 = CLI.main(["export-oracle", "--spec", sp, "--out", orc])
        head = json.loads(open(orc, encoding="utf-8").readline())
        out.append(("H3 export-oracle --spec rc=0 且首行是 scene/schema 头",
                    rc3 == 0 and head.get("schema") == SCHEMA_ORACLE
                    and head["scene"].get("export_frame") == 0, "rc=%s" % rc3))

        sp_bad = os.path.join(d, "bad_spec.json")
        b = _dump_min()
        b.pop("frame")
        with open(sp_bad, "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False)
        out.append(("H4 spec 缺 frame ⇒ rc=2（fail-closed）",
                    CLI.main(["export-obj", "--spec", sp_bad,
                              "--out", os.path.join(d, "x.obj")]) == 2, ""))
        b2 = _dump_min()
        b2["meshes"][0]["verts"][0][0] = float("nan")
        sp_nan = os.path.join(d, "nan_spec.json")
        with open(sp_nan, "w", encoding="utf-8") as f:
            json.dump(b2, f, ensure_ascii=False)
        out.append(("H5 spec 含 NaN 顶点 ⇒ rc=2（不产坏件）",
                    CLI.main(["export-obj", "--spec", sp_nan,
                              "--out", os.path.join(d, "y.obj")]) == 2, ""))

        # 旧件（缺 export_frame）重出：不给 --legacy-frame 必须拒
        old = os.path.join(d, "old_shapes.json")
        with open(old, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in sd.items() if k != "export_frame"}, f,
                      ensure_ascii=False, sort_keys=True)
        rc6 = CLI.main(["export-shapes", "--from-shapes", old,
                        "--out", os.path.join(d, "o1.json")])
        rc7 = CLI.main(["export-shapes", "--from-shapes", old,
                        "--out", os.path.join(d, "o2.json"), "--legacy-frame", 0])
        out.append(("H6 旧件缺 export_frame：不给声明 rc=2 / 给了 rc=0",
                    rc6 == 2 and rc7 == 0, "rc=%s/%s" % (rc6, rc7)))
    finally:
        shutil.rmtree(d, ignore_errors=True)


def gi_pose_guard(out):
    """I 组：跨件守卫（位姿与真值必须同帧）——本轮最重要的守卫。"""
    dump = _dump_min(link_deg=35.0)
    ok, probs = G.check_pose_consistency(_mini_shapes(dump), _oracle_of(dump), dump)
    out.append(("I1 同帧位姿与真值 ⇒ 判定一致", ok, str(probs[:2])))

    # ★ 教训 1：几何/部件位姿取自「别的帧」（u=1 的 +35°），而真值 tick0 是 −35°
    stale = _dump_min(link_deg=35.0, tick_deg=-35.0)
    ok2, probs2 = G.check_pose_consistency(_mini_shapes(stale), _oracle_of(stale), stale)
    out.append(("I2 位姿取自别的帧 ⇒ 必须报 part_pose_mismatch",
                (not ok2) and any(p["kind"] == "part_pose_mismatch" for p in probs2),
                str(sorted({p["kind"] for p in probs2}))))

    moved = _dump_min(anchor_shift=(0.0, 0.0, 1.0),
                      track_shift=(0.0, 0.0, -1.0))   # dump 的枢轴挪了，真值没挪
    ok3, probs3 = G.check_pose_consistency(_mini_shapes(moved), _oracle_of(moved), moved)
    out.append(("I3 枢轴平移与真值不符 ⇒ 必须报 anchor_mismatch",
                (not ok3) and any(p["kind"] == "anchor_mismatch" for p in probs3),
                str(sorted({p["kind"] for p in probs3}))))

    nokey = _dump_min(name="wmtest/model", track_name="MODEL_root")
    ok4, probs4 = G.check_pose_consistency(_mini_shapes(nokey), _oracle_of(nokey), nokey)
    out.append(("I4 link 名与真值实体对不上 ⇒ 必须报 missing_tick（旧件的口径缺陷）",
                (not ok4) and any(p["kind"] == "missing_tick" for p in probs4),
                str(sorted({p["kind"] for p in probs4}))))

    # I5/I6：把"地板"本身当判据 —— 导出精度级的微差必须放过，度级偏差必须抓住。
    # （Lead 正向端到端时 arm 恰好差 1e-6 被误报，故这里把地板两侧都钉死。）
    d0 = G.POSE_TOL
    tiny = _dump_min(link_deg=35.0, tick_deg=35.0 + 1e-6)
    okt, pt = G.check_pose_consistency(_mini_shapes(tiny), _oracle_of(tiny), tiny)
    out.append(("I5 导出精度级微差（1e-6）必须放过（地板 %.0e）" % d0, okt,
                "POSE_TOL=%.0e problems=%s" % (d0, sorted({p['kind'] for p in pt}))))
    big = _dump_min(link_deg=35.0, tick_deg=35.0 + 0.01)
    okb, pb = G.check_pose_consistency(_mini_shapes(big), _oracle_of(big), big)
    out.append(("I6 度级偏差（0.01°）必须抓住（门没被放宽到失效）",
                (not okb) and any(p["kind"] == "part_pose_mismatch" for p in pb),
                str(sorted({p["kind"] for p in pb}))))



def run_checks():
    """返回 [(id, ok, detail)]。纯函数式：每次自带临时沙箱，可反复调用。"""
    out = []
    d = _sandbox()
    try:
        # ---------------- A 契约 ----------------
        ok, why = C.validate_record(copy.deepcopy(GOOD_REC))
        out.append(("A1 合法记录被接受", ok, why))

        bad = copy.deepcopy(GOOD_REC); bad["pos"] = {"x": float("nan"), "y": 1.0, "z": 1.0}
        ok, why = C.validate_record(bad)
        out.append(("A2 NaN 必须被拒", (not ok) and ("非有限" in why), why))

        ok, why = C.validate_record({"entity": "e", "tick": 0, "pos": {"x": True, "y": 0, "z": 0}})
        out.append(("A3 bool 当数值必须被拒", not ok, why))

        ok, why = C.validate_record({"entity": "e", "tick": 0, "pos": {"x": 0.0, "y": 0.0}})
        out.append(("A4 缺轴必须被拒", (not ok) and ("缺轴" in why), why))

        ok, why = C.validate_doc(good_doc())
        out.append(("A5 合法导出被接受", ok, why))

        dup = good_doc(); dup["tracks"].append(copy.deepcopy(GOOD_REC))
        ok, why = C.validate_doc(dup)
        out.append(("A6 (entity,tick) 重复必须被拒", (not ok) and ("重复键" in why), why))

        doc = good_doc(); doc["schema"] = "nope"
        ok, why = C.validate_doc(doc)
        out.append(("A7 schema 不符必须被拒", not ok, why))

        # ---------------- B 清单 ----------------
        root = os.path.join(d, "scene")
        rels = ["a.jsonl", "b.jsonl"]
        mp = os.path.join(d, "manifest.json")
        M.write(root, rels, mp)
        man = M.load(mp)
        ok, probs = M.verify(man, root, strict=True)
        out.append(("B1 干净盘面核验通过", ok and not probs, str(probs[:3])))

        open(os.path.join(root, "a.jsonl"), "a", encoding="utf-8").write("x")
        ok, probs = M.verify(man, root, strict=True)
        out.append(("B2 改动一个字节必须点名",
                    (not ok) and any(k == "changed" for k, _, _ in probs),
                    str(sorted({p[0] for p in probs}))))

        open(os.path.join(root, "c.jsonl"), "w", encoding="utf-8").write("{}")
        ok, probs = M.verify(man, root, strict=True)
        out.append(("B3 strict 下多文件必须点名",
                    any(k == "extra" for k, _, _ in probs),
                    str(sorted({p[0] for p in probs}))))

        ok2, probs2 = M.verify(man, root, strict=False)
        kinds2 = {k for k, _, _ in probs2}
        out.append(("B4 非 strict 容忍 extra 但仍抓 changed",
                    (not ok2) and ("changed" in kinds2) and ("extra" not in kinds2),
                    str(sorted(kinds2))))

        os.remove(os.path.join(root, "b.jsonl"))
        ok, probs = M.verify(man, root, strict=False)
        out.append(("B5 缺文件必须点名",
                    any(k == "missing" for k, _, _ in probs),
                    str(sorted({p[0] for p in probs}))))

        # ---------------- C 探针 fail-closed ----------------
        r = _closed_probe()
        out.append(("C1 死端口必须判不通过（kind=blender-unreachable）",
                    (r.get("ok") is False) and r.get("kind") == "blender-unreachable",
                    "%s / %s" % (r.get("ok"), r.get("kind"))))
        out.append(("C2 不通时必须给 fix", bool(r.get("fix")), str(r.get("fix"))[:36]))
        out.append(("C3 端口来源可追溯", bool(r.get("ports", {}).get("source")),
                    str(r.get("ports", {}).get("source"))))

        # ---------------- D CLI 退出码 ----------------
        keep = {k: os.environ.get(k) for k in ("DSH_BLENDER_WM_ADDON_PORT", "DSH_BLENDER_WM_HTTP_PORT")}
        os.environ["DSH_BLENDER_WM_ADDON_PORT"] = str(CLOSED_PORT)
        os.environ["DSH_BLENDER_WM_HTTP_PORT"] = str(CLOSED_PORT + 1)
        try:
            rc = CLI.main(["probe", "--host", "127.0.0.1"])
        finally:
            for k, v in keep.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        out.append(("D1 探针失败时退出码必须 2（不许 0）", rc == 2, "rc=%s" % rc))

        gp = os.path.join(d, "good.json")
        json.dump(good_doc(), open(gp, "w", encoding="utf-8"), ensure_ascii=False)
        out.append(("D2 合法导出 validate rc=0", CLI.main(["validate", gp]) == 0, ""))

        bp = os.path.join(d, "bad.json")
        bd = good_doc(); bd["tracks"][0]["pos"]["x"] = None
        json.dump(bd, open(bp, "w", encoding="utf-8"), ensure_ascii=False)
        out.append(("D3 坏导出 validate rc=2", CLI.main(["validate", bp]) == 2, ""))

        out.append(("D4 坏盘面清单核验 rc=2", CLI.main(["verify", root, mp]) == 2, ""))

        # ---------------- E–I 几何 / 部件 / 真值（新增面） ----------------
        ge_geom(out)
        gf_fit(out)
        gg_oracle(out)
        gh_cli_export(out)
        gi_pose_guard(out)
        gj_reproducible_obj(out)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def _max_ratio_fit(dims, vol):
    """M5 的变异体：**只换判据方向**（保留原实现的入参校验），再按「比值最大」挑。

    只换这一个机制，变异才是单点的 —— 否则连 F6 的入参校验一起换掉，
    M5 转红的项就不再只指向"方向反了"。
    """
    dims = tuple(float(d) for d in dims)
    if len(dims) != 3 or any((not math.isfinite(d)) or d < 0 for d in dims):
        raise G.GeomError("dims 非法（负数/NaN/Inf）：%r" % (dims,))
    if not math.isfinite(float(vol)) or float(vol) < 0:
        raise G.GeomError("vol 非法：%r" % (vol,))
    return G.max_ratio_kind(dims, vol)


def _weak_pose_guard(shapes_doc, oracle_doc, dump, tol=1e-6):
    """M8 的变异体：只比枢轴平移，**不查件级姿态链**（应被 I2 抓住）。"""
    problems = []
    frame = shapes_doc.get("export_frame")
    tick = {r["entity"]: r for r in (oracle_doc.get("tracks") or [])
            if r.get("tick") == frame}
    for lk in (dump.get("links") or []):
        rec = tick.get(lk.get("name"))
        if rec is None:
            problems.append({"link": lk.get("name"), "kind": "missing_tick",
                             "detail": "no record"})
            continue
        want = G.to_lingshu(lk.get("anchor") or (0.0, 0.0, 0.0))
        for i, ax in enumerate(("x", "y", "z")):
            if abs(float(rec["pos"].get(ax, 0.0)) - want[i]) > tol:
                problems.append({"link": lk.get("name"), "kind": "anchor_mismatch",
                                 "detail": ax})
    return (not problems), problems


#: (名字, [(对象, 属性名, 替换值), ...], 期望转红的检查 id 集合)
MUTATIONS = [
    ("M1 短路 _finite 恒真",
     [(C, "_finite", lambda v: True)],
     # G3 也走同一个 `_finite` 门（oracle 契约复用 contract）——被它一并抓住是**实测**
     # 的额外覆盖面，故如实列进期望集，而不是把断言改宽。
     {"A2 NaN 必须被拒", "A3 bool 当数值必须被拒",
      "D3 坏导出 validate rc=2", "G3 NaN 真值必须被拒"}),
    # 只短路哈希是不够的：verify 还有一条独立的字节数判据会把它抓住（实测发现，见 DESIGN.md §六）。
    # 所以本变异把**三条内容判据一起**短路，模拟"只记总数不看内容"的坏清单。
    ("M2 短路哈希与字节数（坏清单：只记总数）",
     [(M, "raw_sha256", lambda p: "0" * 64), (M, "lf_sha256", lambda p: "0" * 64),
      (os.path, "getsize", lambda p: 13)],
     {"B2 改动一个字节必须点名", "B4 非 strict 容忍 extra 但仍抓 changed"}),
    ("M3 短路 tcp_alive 恒真",
     [(P, "tcp_alive", lambda *a, **k: True)],
     {"C1 死端口必须判不通过（kind=blender-unreachable）", "C2 不通时必须给 fix",
      "D1 探针失败时退出码必须 2（不许 0）"}),
    # ---- 新增面（几何 / 部件 / 真值）的定点变异 ----
    ("M4 轴换算换成镜像解 (x,z,y)（det=−1）",
     [(G, "AXIS_MAP", G.MIRROR_MAP)],
     {"E1 轴换算 det=+1、镜像解 det=−1", "E3 (x,y,z)→(x,z,−y)"}),
    # 只改**判据方向**（保留原函数的入参校验）——把"方向"这一个机制单独变异出来，
    # 否则连 F6 的入参校验一起换掉，变异就不再是单点。
    ("M5 拟合判据改成「比值最大」（踩过的坑）",
     [(G, "fit_kind", _max_ratio_fit)],
     {"F1 已知圆柱 ⇒ pillar（不是 pyramid）", "F2 已知立方体 ⇒ box",
      "F4 已知球 ⇒ sphere", "F5 判据是「最接近 1」而非「最大」（两者解不同）"}),
    ("M6 短路 require_normalize 恒真（OBJ 头契约失效）",
     [(G, "require_normalize", lambda *a, **k: True)],
     {"E6 缺 normalize 行必须 raise"}),
    ("M7 欧拉只取第一解（丢掉 Blender 的「两解取小」）",
     [(G, "mat3_to_euler_xyz",
       lambda m: (math.atan2(m[2][1], m[2][2]),
                  math.atan2(-m[2][0], math.hypot(m[0][0], m[1][0])),
                  math.atan2(m[1][0], m[0][0])))],
     {"E4 欧拉锚点 (−40,35,0) 与两解取小 (0,−135,0)"}),
    # I6 是**只针对件级姿态链**的判据，故拿掉那条链时它必然一起红（实测），
    # 据实列进期望集（不是把断言改宽）。
    ("M8 跨件守卫只看枢轴平移（拿掉件级姿态链）",
     [(G, "check_pose_consistency", _weak_pose_guard)],
     {"I2 位姿取自别的帧 ⇒ 必须报 part_pose_mismatch",
      "I6 度级偏差（0.01°）必须抓住（门没被放宽到失效）"}),
    ("M10 姿态核对地板放宽到 1.0（门失效）",
     [(G, "POSE_TOL", 1.0)],
     {"I3 枢轴平移与真值不符 ⇒ 必须报 anchor_mismatch",
      "I6 度级偏差（0.01°）必须抓住（门没被放宽到失效）"}),
    ("M9 去掉规范面序（面序随输入变 ⇒ 文件不可复现）",
     [(G, "canonical_tris", lambda tris: [tuple(int(i) for i in t) for t in tris])],
     {"J1 同几何两种面序输入 ⇒ 产物逐字节相同（面序规范化生效）",
      "J2 输出的 f 行按「最小索引打头 + 字典序」",
      "J3 规范面序是环状旋转而非 sorted（保绕向）",
      "J4 5 轮重复导出（两种输入序）全部逐字节相同"}),
]


def main(argv=None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    mutate = "--mutate" in args

    checks = run_checks()
    bad = [i for i, o, _ in checks if not o]
    for i, o, detail in checks:
        print("%s  %s%s" % ("[PASS]" if o else "[FAIL]", i,
                            ("  ← " + str(detail)) if not o else ""))
    print("-" * 72)
    print("通过 %d / 失败 %d" % (len(checks) - len(bad), len(bad)))

    if not mutate:
        print("VERDICT=" + ("PASS" if not bad else "FAIL"))
        return 0 if not bad else 1

    print("\n== 定点变异（反面证明）==")
    all_ok = not bad
    for name, patches, expect in MUTATIONS:
        saved = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in patches]
        try:
            for obj, attr, val in patches:
                setattr(obj, attr, val)
            res = run_checks()
            red = {i for i, o, _ in res if not o}
            hit = (red == expect)
            all_ok = all_ok and hit
            print("  %s %s ⇒ 转红 %d 项 %s%s" % (
                "[PASS]" if hit else "[FAIL]", name, len(red), sorted(red),
                "" if hit else "  期望 %s" % sorted(expect)))
        finally:
            for obj, attr, val in saved:
                setattr(obj, attr, val)
    print("VERDICT=" + ("PASS" if all_ok else "FAIL"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
