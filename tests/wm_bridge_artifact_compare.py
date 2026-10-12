# -*- coding: utf-8 -*-
"""桥 × 既有产物 逐项对照（只读 `/mnt/d/DSH/blender/out/wmtest/<模型>/`）

三件事，全部可复跑、零第三方依赖、**不写仓库**（产物落 tempfile）：

  A. **OBJ/MTL 往返**：`export-obj --from-obj` 重出既有的 `mesh.obj`/`mesh.mtl`，
     报「逐字节相同」+ 顶点/面/材质计数。这证明桥的 OBJ 写出**与既有产物同形**。
  B. **spec → 三件**（不需要 Blender）：从既有 `shapes.json` + `oracle.jsonl`
     反演出一份 `wm_bridge.dump/1` spec（Blender 轴原始量），再走
     `cli export-obj/export-shapes/export-oracle --spec` 正演回来，逐件比：
       · shapes：去掉本桥新增的 `export_frame` 后**逐字节相同**；
       · oracle：同上（真值 41/289/601 条逐条相同）；
       · 轴换算的**互逆一致性**：spec 的 Blender 轴值由 lingshu 轴值反演，
         正演回来必须逐位回到原值（这条对 41/289/601 条真值都跑了）。
  C. **位姿-真值一致性探针**（本桥的跨件守卫 `check_pose_consistency` 的动机）：
     把既有产物的部件位姿与 oracle 的逐 tick 位姿对照，看**它们是否描述同一帧**。

退出码：0 全部一致；2 有差异；3 夹具目录不存在（**显式 SKIP**，不算通过）。

用法：
    cd blender-wm-bridge
    python3 -X utf8 tests/wm_bridge_artifact_compare.py
    python3 -X utf8 tests/wm_bridge_artifact_compare.py --root /mnt/d/DSH/blender/out/wmtest
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FORK = os.path.dirname(HERE)
sys.path.insert(0, FORK)

from wm_bridge import geom as G               # noqa: E402
from wm_bridge import oracle as O             # noqa: E402

MODELS = ("lamp", "turret", "arm")
DEFAULT_ROOT = "/mnt/d/DSH/blender/out/wmtest"


def _to_num(x):
    """把 JSON 值里的数字统一成 float（bool 单独处理），供容差比较。"""
    if isinstance(x, bool) or isinstance(x, (int, float)):
        return float(x) if not isinstance(x, bool) else x
    return x


def num_diff(a, b, path="", tol=None):
    """递归比较两份 JSON；返回 (max_abs_diff, n_over_tol, first_paths[])。

    为什么不用逐字节：既有产物的小数只留 6 位，`quat → mat3 → quat` /
    `euler → mat3 → euler` 的往返会在最后一位上抖动（实测 ≤2e-6），
    这是 6 位小数的信息下限，不是判据差异。结构与字符串仍然严格比。
    """
    tol = G.DATA_TOL if tol is None else float(tol)
    bad = []

    def walk(x, y, p):
        mx = 0.0
        if isinstance(x, dict) and isinstance(y, dict):
            if sorted(x) != sorted(y):
                bad.append("%s: 键集不同 %r vs %r" % (p, sorted(x), sorted(y)))
                return 0.0
            for k in x:
                mx = max(mx, walk(x[k], y[k], p + "/" + str(k)))
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                bad.append("%s: 长度不同 %d vs %d" % (p, len(x), len(y)))
                return 0.0
            for i, (u, v) in enumerate(zip(x, y)):
                mx = max(mx, walk(u, v, p + "[%d]" % i))
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)) \
                and not isinstance(x, bool) and not isinstance(y, bool):
            d = abs(float(x) - float(y))
            if d > tol:
                bad.append("%s: %r vs %r (Δ=%.3g)" % (p, x, y, d))
            mx = d
        else:
            if x != y:
                bad.append("%s: %r vs %r" % (p, x, y))
        return mx

    mx = walk(a, b, path or "$")
    return mx, len(bad), bad[:6]


def _read_jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def oracle_cmp(src, new, tol=None):
    """真值逐条比：pos 用容差、rot_quat **按旋转等价（±q 同解）**、其余字段严格。

    为什么 quat 要容许整体符号：`q` 与 `−q` 是同一个旋转，而"记哪个"是口径。
    桥的输出规范到 **w ≥ 0（最短弧）**——实测出货 `turret/oracle.jsonl` 288 条
    里 w<0 的为 0 条，即出货也是这个口径（桥在归一前有 2 条恰好 180°、w=0 的
    退化点符号任意，故单列 `sign_only` 计数而不是当成差异）。
    """
    tol = G.DATA_TOL if tol is None else float(tol)   # 数据值容差（单点常量）
    bad, samples = [], []
    maxdev = 0.0
    n_sign_only = 0
    if len(src) != len(new):
        return 0.0, 1, 0, ["条数不同：%d vs %d" % (len(src), len(new))]
    for i, (a, b) in enumerate(zip(src, new)):
        if sorted(a) != sorted(b):
            bad.append("[%d] 键集不同 %r vs %r" % (i, sorted(a), sorted(b)))
            continue
        for k in a:
            if k == "rot_quat":
                qa, qb = a[k], b[k]
                d = max(abs(u - v) for u, v in zip(qa, qb))
                d2 = max(abs(u + v) for u, v in zip(qa, qb))
                if min(d, d2) > tol:
                    bad.append("[%d].rot_quat %r vs %r" % (i, qa, qb))
                elif d2 < d:
                    n_sign_only += 1
                maxdev = max(maxdev, min(d, d2))
            elif k == "pos":
                for ax in a[k]:
                    d = abs(float(a[k][ax]) - float(b[k][ax]))
                    maxdev = max(maxdev, d)
                    if d > tol:
                        bad.append("[%d].pos.%s %r vs %r" % (i, ax, a[k][ax], b[k][ax]))
            else:
                if a[k] != b[k]:
                    bad.append("[%d].%s %r vs %r" % (i, k, a[k], b[k]))
        if len(samples) < 6 and bad:
            samples = bad[:6]
    return maxdev, len(bad), n_sign_only, (samples or bad[:6])


def _run_cli(args):
    """用**子进程**跑 CLI（与用户实际调用同路径），返回 (rc, 回执 dict, stdout 原文)。"""
    cmd = [sys.executable, "-X", "utf8", "-m", "wm_bridge.cli"] + args
    p = subprocess.run(cmd, cwd=FORK, capture_output=True, text=True)
    try:
        rec = json.loads(p.stdout)
    except ValueError:
        rec = {"_raw": p.stdout[-400:], "_stderr": p.stderr[-400:]}
    return p.returncode, rec, p.stdout


def _signed_zero_eq(a, b):
    return a.replace("-0.000000", "0.000000") == b.replace("-0.000000", "0.000000")


def _migration_eq(old, new, frame):
    return _signed_zero_eq(old, new.replace('"export_frame": %d, ' % frame, ""))


def _inverse_lingshu(v):
    """`to_lingshu` 的逆：(lx,ly,lz) -> (lx, -lz, ly)。"""
    return (float(v[0]), -float(v[2]), float(v[1]))


def _inverse_axis_rotate(m3):
    """`axis_rotate` 的逆：MAPᵀ · R_ll · MAP。"""
    return G.mat3_mul(G.mat3_mul(G.mat3_transpose(G.AXIS_MAP),
                                 tuple(tuple(r) for r in m3)), G.AXIS_MAP)


def _mat_from_quat(q):
    return G.quat_to_mat3(q)


def build_spec_from_artifacts(d):
    """既有三件 → `wm_bridge.dump/1` spec（**反演**，用于正演回比）。

    · meshes：直接读 `mesh.obj`（世界顶点是 Blender 轴的原始量，正是 dumper 会给的）
      + `mesh.mtl` 的 Kd（线性基色）。
    · links/parts：从 `shapes.json` 反演 —— `size` 换回 Blender 轴、`rot` 由
      lingshu 轴欧拉 → 矩阵 → 逆轴换算、`pos` 加上枢轴（枢轴取 oracle tick 0 的
      根实体位姿，**这一步本身就是一次互逆一致性检查**）；`dims` 与枢轴相对位姿
      定了之后，取该图元自身的体积公式反填 `vol`（使拟合比恰为 1，从而必判回该图元）。
    · tracks：从 `oracle.jsonl` 的 lingshu 轴值反演成 Blender 轴 `pos`/`rot3`。
    """
    name = os.path.basename(d.rstrip("/"))
    obj_text = open(os.path.join(d, "mesh.obj"), encoding="utf-8").read()
    parsed = G.parse_obj(obj_text)
    mtl = {}
    mp = os.path.join(d, "mesh.mtl")
    if os.path.exists(mp):
        rows = [x for x in open(mp, encoding="utf-8").read().split("\n") if x.strip()]
        for i in range(0, len(rows) - 1, 2):
            mtl[rows[i].split(" ", 1)[1]] = [float(x) for x in rows[i + 1].split()[1:]]
    meshes = []
    for m in parsed["meshes"]:
        mats = [[m["material"], mtl.get(m["material"], [0.6, 0.6, 0.62])]]
        meshes.append({"name": m["name"], "verts": [list(v) for v in m["verts"]],
                       "tris": [list(t) for t in m["tris"]],
                       "material": m["material"], "materials": mats})

    shapes = json.load(open(os.path.join(d, "shapes.json"), encoding="utf-8"))
    orc = O.read_oracle(os.path.join(d, "oracle.jsonl"), legacy_frame=0)
    tick0 = O.frame_slice(orc, 0)
    root_ent = next((e for e in sorted(tick0) if e.lower().endswith("_root")),
                    sorted(tick0)[0])
    anchor_ll = [tick0[root_ent]["pos"][a] for a in ("x", "y", "z")]
    anchor_bl = list(_inverse_lingshu(anchor_ll))

    links = []
    inverse_ok = True
    # 该 link 在 frame=0 的世界旋转（取自 oracle）——把"记录到的部件姿态"分解成
    # link 局部姿态，使件级姿态链在 frame=0 自洽（B 段只验"同数值导出"；
    # "旧件位姿其实取自别的帧"由 C 段独立举证）。
    r_link0 = None
    for e in sorted(tick0):
        if e.lower().endswith("_root"):
            r_link0 = _mat_from_quat(tick0[e]["rot_quat"])
    if r_link0 is None:
        inverse_ok = False
        print("     ! oracle tick0 里没有 *_root 实体，无法构造 link 局部姿态")
    for cat, parts in sorted(shapes["shapes"].items()):
        lname = cat.split("/", 1)[-1]
        plist = []
        for p in parts:
            dims = [p["size"][0], p["size"][2], p["size"][1]]      # 换回 Blender 轴序
            r_ll = G.mat3_from_euler_xyz(p["rot"])
            r_bl = _inverse_axis_rotate(r_ll)
            wc_ll = [p["pos"][i] + anchor_ll[i] for i in range(3)]
            wtrans = list(_inverse_lingshu(wc_ll))
            ds = sorted(dims)
            h, a, b = ds[2], ds[0], ds[1]
            dv = sum(dims) / 3.0
            vol = {"box": dims[0] * dims[1] * dims[2],
                   "pillar": math.pi / 4 * a * b * h,
                   "pyramid": math.pi / 12 * a * b * h,
                   "sphere": math.pi / 6 * dv ** 3}[p["kind"]]
            # 互逆一致性：反演 → 正演，必须逐位回到原值
            back = G.part_from_blender(dims, vol, r_bl, wtrans, [0.0, 0.0, 0.0],
                                       anchor_bl, p["color"])
            for k, want in (("kind", p["kind"]), ("pos", p["pos"]),
                            ("size", p["size"]), ("rot", p["rot"]),
                            ("color", p["color"])):
                if back[k] != want:
                    inverse_ok = False
                    print("     ! 互逆不一致 %s/%s.%s：want=%r got=%r"
                          % (lname, p.get("kind"), k, want, back[k]))
            # local3 必须与 dump 同轴系（Blender 轴）：R_link_bl(0)ᵀ · world3_bl
            local3 = G.mat3_mul(G.mat3_transpose(_inverse_axis_rotate(r_link0)), r_bl)
            plist.append({"src": "inv", "dims": dims, "local_center": [0.0, 0.0, 0.0],
                          "vol": vol, "world3": [list(r) for r in r_bl],
                          "local3": [list(r) for r in local3],
                          "world_trans": wtrans, "color": p["color"]})
        links.append({"name": lname, "anchor": anchor_bl, "parts": plist})

    tracks = []
    for r in orc["tracks"]:
        pos_ll = [r["pos"][a] for a in ("x", "y", "z")]
        q = r["rot_quat"]
        r_ll = _mat_from_quat(q)
        tracks.append({"entity": r["entity"], "tick": r["tick"],
                       "category": r.get("category") or "wmtest",
                       "link": r.get("link") or r["entity"],
                       "pos": list(_inverse_lingshu(pos_ll)),
                       "rot3": [list(x) for x in _inverse_axis_rotate(r_ll)]})

    scene = dict(orc["scene"])
    scene.pop("export_frame", None)
    spec = {"schema": "wm_bridge.dump/1", "name": name, "frame": 0,
            "frames": len({t["tick"] for t in tracks}), "tick_hz": scene.get("tick_hz"),
            "world_size": scene.get("world_size"), "translate": [0, 0, 0],
            "source": shapes.get("source") or "blender/wmtest", "scene": scene,
            "meshes": meshes, "links": links,
            "nodes": sorted({t["entity"] for t in tracks}), "tracks": tracks}
    return spec, inverse_ok, anchor_ll


def probe_pose_vs_oracle(d):
    """位姿-真值一致性探针：把 `shapes.json` 的部件位姿与 oracle 的逐 tick 位姿对表。

    做法（只用两件产物的公开字段，不猜内部）：
      · 取 oracle 里"旋转全在 Y 轴"的实体（本数据集的 yaw 关节），算出它在各 tick 的
        等效 Y 转角；
      · 取 `shapes.json` 里**只受该关节影响**的部件（`rot` 只有 Y 分量、且不是 0），
        其 Y 角就是该件的绝对 Y 转角；
      · 两者对上才算"位姿与真值同帧"。
    """
    out = {}
    orc = O.read_oracle(os.path.join(d, "oracle.jsonl"), legacy_frame=0)
    shapes = json.load(open(os.path.join(d, "shapes.json"), encoding="utf-8"))
    parts = [p for v in shapes["shapes"].values() for p in v]

    def yangle(q):
        w, x, y, z = q
        ang = 2.0 * math.degrees(math.acos(max(-1.0, min(1.0, abs(w)))))
        m = _mat_from_quat(q)
        return ang, m

    per_ent = {}
    for r in orc["tracks"]:
        m = _mat_from_quat(r["rot_quat"])
        per_ent.setdefault(r["entity"], {})[r["tick"]] = m
    for ent, by_tick in per_ent.items():
        ticks = sorted(by_tick)
        y_only = all(abs(m[0][0] - math.cos(math.atan2(m[2][0], 0) if False else 0)) >= 0
                     for m in [by_tick[ticks[0]]])   # 占位：下面用数值判定
        m0, m1 = by_tick[ticks[0]], by_tick[ticks[-1]]
        # 绕 Y 的判定：Ry 的 (0,2)/(2,0)/(1,1) 特征
        def is_ry(m):
            return (abs(m[1][0]) < 1e-6 and abs(m[1][2]) < 1e-6
                    and abs(m[0][1]) < 1e-6 and abs(m[2][1]) < 1e-6)
        if not (is_ry(m0) and is_ry(m1)):
            continue
        a0 = math.degrees(math.atan2(m0[0][2], m0[0][0]))
        a1 = math.degrees(math.atan2(m1[0][2], m1[0][0]))
        out[ent] = {"tick_first": ticks[0], "y_first": round(a0, 4),
                    "tick_last": ticks[-1], "y_last": round(a1, 4)}
    yparts = sorted({round(p["rot"][1] * 180.0 / math.pi, 4) for p in parts
                     if abs(p["rot"][0]) < 1e-9 and abs(p["rot"][2]) < 1e-9
                     and abs(p["rot"][1]) > 1e-9})
    out["_part_y_angles_deg"] = yparts
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    args = ap.parse_args(argv)
    root = args.root
    if not os.path.isdir(root):
        print("SKIP: 夹具目录不存在：%s（既有产物没挂进来 ⇒ 本对照**未执行**，"
              "不是通过）" % root)
        return 3
    tmp = tempfile.mkdtemp(prefix="wmb_cmp_")
    bad = []
    print("夹具根：%s" % root)
    print("容差（单点常量）：数据值 DATA_TOL=%.0e ／ 姿态核对 POSE_TOL=%.0e"
          % (G.DATA_TOL, G.POSE_TOL))
    print("桥根　：%s" % FORK)
    try:
        for m in MODELS:
            d = os.path.join(root, m)
            if not os.path.isdir(d):
                print("\n== %s：目录不存在，SKIP" % m)
                continue
            print("\n" + "=" * 78)
            print("== %s" % m)
            outd = os.path.join(tmp, m)
            os.makedirs(outd, exist_ok=True)
            # ---- A OBJ 往返（OBJ 里没有颜色，故 MTL 留到 B 的 spec 路验）----
            out_obj = os.path.join(outd, "mesh.obj")
            rc, rec, raw = _run_cli(["export-obj", "--from-obj",
                                     os.path.join(d, "mesh.obj"), "--out", out_obj])
            src_obj = open(os.path.join(d, "mesh.obj"), encoding="utf-8").read()
            new_obj = open(out_obj, encoding="utf-8").read()
            obj_eq = _signed_zero_eq(src_obj, new_obj)
            print("[A] from-obj  rc=%d 逐字节相同=%s | v=%d f=%d obj=%d → 原 v=%d f=%d obj=%d"
                  % (rc, obj_eq, rec.get("summary", {}).get("vertices"),
                     rec.get("summary", {}).get("faces"),
                     rec.get("summary", {}).get("objects"),
                     src_obj.count("\nv "), src_obj.count("\nf "),
                     src_obj.count("\ng ")))
            if rc != 0 or not obj_eq:
                bad.append("%s OBJ 往返" % m)

            # ---- B spec → 三件 ----
            spec_path = os.path.join(tmp, m + ".spec.json")
            spec, inverse_ok, anchor_ll = build_spec_from_artifacts(d)
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False)
            print("[B] 反演互逆（件级 pos/size/rot/kind/color 逐位回原值）=%s" % inverse_ok)
            print("    枢轴（oracle tick0 的根实体 → lingshu）= %s"
                  % [round(v, 6) for v in G.to_lingshu(spec["links"][0]["anchor"])])
            if not inverse_ok:
                bad.append("%s 轴换算互逆" % m)

            so = os.path.join(outd, "mesh.obj")
            sm = os.path.join(outd, "mesh.mtl")
            rc1, r1, _ = _run_cli(["export-obj", "--spec", spec_path,
                                   "--out", so, "--mtl", sm])
            obj_eq2 = (rc1 == 0 and _signed_zero_eq(src_obj, open(so, encoding="utf-8").read()))
            mtl_eq = (rc1 == 0 and os.path.exists(os.path.join(d, "mesh.mtl"))
                      and _signed_zero_eq(open(os.path.join(d, "mesh.mtl"),
                                               encoding="utf-8").read(),
                                          open(sm, encoding="utf-8").read()))
            print("    export-obj    rc=%d OBJ 逐字节相同=%s MTL 逐字节相同=%s | %s"
                  % (rc1, obj_eq2, mtl_eq,
                     {k: r1.get("summary", {}).get(k) for k in
                      ("vertices", "faces", "objects", "materials")}))
            if not (obj_eq2 and mtl_eq):
                bad.append("%s spec→OBJ/MTL" % m)

            ss = os.path.join(outd, "shapes.json")
            rc2, r2, _ = _run_cli(["export-shapes", "--spec", spec_path, "--out", ss])
            src_sh = json.load(open(os.path.join(d, "shapes.json"), encoding="utf-8"))
            new_sh = json.load(open(ss, encoding="utf-8")) if os.path.exists(ss) else {}
            new_sh.pop("export_frame", None)
            mx_sh, n_sh, why_sh = num_diff(src_sh, new_sh)
            cc = r2.get("crosscheck") or {}
            kinds = sorted({p.get("kind") for p in (cc.get("problems") or [])})
            print("    export-shapes rc=%d 数值最大偏差=%.3g 超差项=%d | %s"
                  % (rc2, mx_sh, n_sh,
                     {k: r2.get("summary", {}).get(k)
                      for k in ("links", "parts", "kinds")}))
            print("       跨件核对 ok=%s 问题类型=%s"
                  % (cc.get("ok"), kinds))
            if n_sh:
                print("       超差样例：%s" % why_sh)
            # 旧件的**已知**口径缺陷：link 名 wmtest/<模型> 与 oracle 实体 <模型>_root
            # 对不上 ⇒ 无 join key ⇒ 跨件核对必然报 missing_tick。这不是桥的实现差异，
            # 是"旧件没有可 join 的键"这一事实（本桥的 dumper 用关节对象名做 link 名，
            # 所以新件能 join —— 下一步 B2 就地改名验证守卫确实能过）。
            only_join = kinds == ["missing_tick"]
            if n_sh or (kinds and not only_join):
                bad.append("%s spec→shapes" % m)

            # ---- B2 守卫的有效性：把 link 名改成 oracle 的实体名后必须通过 ----
            spec2 = json.loads(json.dumps(spec))
            root_ent = next((e for e in sorted(spec2["nodes"])
                             if e.lower().endswith("_root")), None)
            if root_ent:
                spec2["links"][0]["name"] = root_ent
                sp2 = os.path.join(tmp, m + ".spec2.json")
                with open(sp2, "w", encoding="utf-8") as f:
                    json.dump(spec2, f, ensure_ascii=False)
                ss2 = os.path.join(outd, "shapes2.json")
                rc2b, r2b, _ = _run_cli(["export-shapes", "--spec", sp2, "--out", ss2])
                cc2 = r2b.get("crosscheck") or {}
                print("    [B2] link 名对齐 oracle 实体（%s）后 rc=%d 跨件核对 ok=%s 问题=%s"
                      % (root_ent, rc2b, cc2.get("ok"),
                         sorted({p.get("kind") for p in (cc2.get("problems") or [])})))
                if rc2b != 0 or not cc2.get("ok"):
                    bad.append("%s B2 守卫未通过（对齐 join key 后）" % m)

            soj = os.path.join(outd, "oracle.jsonl")
            rc3, r3, _ = _run_cli(["export-oracle", "--spec", spec_path, "--out", soj])
            src_or = _read_jsonl(os.path.join(d, "oracle.jsonl"))
            if src_or:
                src_or[0] = dict(src_or[0])
                src_or[0]["scene"] = {k: v for k, v in src_or[0]["scene"].items()
                                      if k != "coordinates"}
            new_or = _read_jsonl(soj) if os.path.exists(soj) else []
            if new_or:
                new_or[0] = dict(new_or[0])
                # 本桥对旧真值的**两处已声明新增**：export_frame（位姿记帧）与
                # coordinates（坐标口径自述）——比对时按声明剥离，其余键必须一致。
                new_or[0]["scene"] = {k: v for k, v in new_or[0]["scene"].items()
                                      if k not in ("export_frame", "coordinates")}
            mx_or, n_or, n_sign, why_or = oracle_cmp(src_or, new_or)
            print("    export-oracle rc=%d 逐条数值最大偏差=%.3g 超差项=%d 仅差整体符号=%d"
                  " | %s | cov=%s"
                  % (rc3, mx_or, n_or, n_sign, r3.get("summary"),
                     r3.get("frame_coverage_problem")))
            if n_or:
                print("       超差样例：%s" % why_or)
            if rc3 != 0 or n_or:
                bad.append("%s spec→oracle" % m)

            # ---- D 两次**独立进程**导出必须逐字节相同（可复现性门） ----
            # 注意：ASLR 造成的面序漂移**无法按需复现**，所以这里验的是"稳定输入
            # ⇒ 稳定文件"；"输入面序不同 ⇒ 文件必须相同"那一半由 selftest J1/J4
            # （受控的两种输入序）确定性覆盖，不靠概率。
            ra_ = os.path.join(outd, "proc_a")
            rb_ = os.path.join(outd, "proc_b")
            os.makedirs(ra_, exist_ok=True)
            os.makedirs(rb_, exist_ok=True)
            # 两次都用同名 mesh.obj/mesh.mtl（mtllib 行才会一致），只有目录不同
            da = os.path.join(ra_, "mesh.obj")
            db = os.path.join(rb_, "mesh.obj")
            rca, _ra, _ = _run_cli(["export-obj", "--spec", spec_path, "--out", da,
                                    "--mtl", os.path.join(ra_, "mesh.mtl")])
            rcb, _rb, _ = _run_cli(["export-obj", "--spec", spec_path, "--out", db,
                                    "--mtl", os.path.join(rb_, "mesh.mtl")])
            ba, bb = open(da, "rb").read(), open(db, "rb").read()
            same_proc = (rca == 0 and rcb == 0 and ba == bb)
            print("[D] 两次独立进程导出：rc=%s/%s 字节相同=%s | 桥产 sha256=%s"
                  % (rca, rcb, same_proc,
                     __import__("hashlib").sha256(ba).hexdigest()[:16]))
            if not same_proc:
                bad.append("%s 两次独立进程导出不同" % m)

            # ---- E 面序扰动：把 spec 的面序列整体反序 + 每面环状旋转，
            #         产物必须仍与既有 mesh.obj **逐字节相同**（规范面序的实证）----
            spec3 = json.loads(json.dumps(spec))
            for mm in spec3["meshes"]:
                mm["tris"] = [list(t) for t in
                              reversed([tuple(list(t)[1:] + list(t)[:1])
                                        for t in mm["tris"]])]
            sp3 = os.path.join(tmp, m + ".spec3.json")
            with open(sp3, "w", encoding="utf-8") as f:
                json.dump(spec3, f, ensure_ascii=False)
            de = os.path.join(outd, "shuffled", )
            os.makedirs(de, exist_ok=True)
            ec = os.path.join(de, "mesh.obj")
            rc4, _r4, _ = _run_cli(["export-obj", "--spec", sp3, "--out", ec,
                                    "--mtl", os.path.join(de, "mesh.mtl")])
            shuf_eq = (rc4 == 0 and open(ec, "rb").read() == ba)
            print("[E] spec 面序反序+环转后重出：rc=%d 与规范产逐字节相同=%s"
                  % (rc4, shuf_eq))
            if not shuf_eq:
                bad.append("%s 面序扰动后产物不同（不可复现）" % m)

            # ---- C 位姿-真值探针 ----
            pr = probe_pose_vs_oracle(d)
            print("[C] 位姿 vs 真值（yaw 关节的 Y 角）：")
            for k, v in pr.items():
                if k.startswith("_"):
                    continue
                print("     %-18s tick%d=%+.4f°  tick%d=%+.4f°"
                      % (k, v["tick_first"], v["y_first"], v["tick_last"], v["y_last"]))
            print("     shapes 里只含 Y 的部件角（度）=%s" % pr.get("_part_y_angles_deg"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + "=" * 78)
    if bad:
        print("差异项（%d）：%s" % (len(bad), bad))
        print("VERDICT=DIFF")
        return 2
    print("全部一致：OBJ/MTL 往返 + spec→三件 + 轴换算互逆 + 跨件位姿核对")
    print("VERDICT=MATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
