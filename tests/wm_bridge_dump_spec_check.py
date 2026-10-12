# -*- coding: utf-8 -*-
"""正向端到端核对：**Blender 侧 `bpy_dump` 的 spec → 桥的三件产物 × 既有产物**

这是 task-12 的「正向端到端」门（对照脚本 `wm_bridge_artifact_compare.py` 走的是**反演**
路线：从既有产物反推 spec 再导出）。本脚本吃的是 **Blender 真跑出来的 spec**：

    Blender 内：  python -m wm_bridge.bpy_dump --out spec/<m>.spec.json \
                      --collection <COLL> --name <m> --frame 0 --frames N --tick-hz 24
    无 Blender：  python tests/wm_bridge_dump_spec_check.py

对每个模型比四样：
  · OBJ/MTL：与 **f0（同帧参照）** 逐字节（signed-zero 归一；原始字节差另行打印）。
    旧 `wmtest/` 只作诊断参照：它是**取帧泄漏期**的产物，`arm` 的 75.5% 顶点
    位姿就是错的（max 1.5 m），故不能当几何基准。
  · 真值：共同实体的逐 tick 位置最大偏差、四元数（按旋转等价 ±q 同解）
  · 部件：**件数 + 图元分布逐类求和后必须相等**（类别名可以不同：
    本桥按 **link（关节）** 出类别，Lead 的临时脚本按**整机一个类别**出 —— 前者才是
    关节级预测需要的形态，故字节不同是预期，语义必须相等）
  · 跨件守卫：`export-shapes` 的 `crosscheck.ok` 必须为 True

退出码：0 全一致；2 有差异；3 夹具/spec 目录不存在（**显式 SKIP**，不算通过）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FORK = os.path.dirname(HERE)
sys.path.insert(0, FORK)

from wm_bridge import geom as G               # noqa: E402

MODELS = ("lamp", "turret", "arm")
DEF_SPEC = "/mnt/d/DSH/blender/out/wmtest/spec"     # bpy_dump 产物
DEF_REF = "/mnt/d/DSH/blender/out/wmtest"          # 既有三件（旧口径）
DEF_F0 = "/mnt/d/DSH/blender/out/wmtest/f0"        # Lead 独立生成的同帧产物


def _run_cli(args):
    p = subprocess.run([sys.executable, "-X", "utf8", "-m", "wm_bridge.cli"] + args,
                       cwd=FORK, capture_output=True, text=True)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, {"_raw": p.stdout[-300:], "_err": p.stderr[-300:]}


def _sigzero_eq(a, b):
    return a.replace("-0.000000", "0.000000") == b.replace("-0.000000", "0.000000")


def _raw_diff_lines(a, b):
    la, lb = a.split("\n"), b.split("\n")
    if len(la) != len(lb):
        return None
    return sum(1 for x, y in zip(la, lb) if x != y)


def _oracle_cmp(src_path, new_path):
    """共同实体的逐 tick 偏差 → (max_pos_dev, n_sign_only_quat, n_bad, n_tracks)。"""
    def load(p):
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        head, tracks = rows[0], rows[1:]
        return {t["entity"] for t in tracks}, {(t["entity"], t["tick"]): t for t in tracks}

    ents_a, a = load(src_path)
    ents_b, b = load(new_path)
    common = sorted(ents_a & ents_b)
    mx, sign_only, bad = 0.0, 0, 0
    for key in sorted(set(a) & set(b)):
        if key[0] not in common:
            continue
        ra, rb = a[key], b[key]
        for ax in ("x", "y", "z"):
            mx = max(mx, abs(float(ra["pos"][ax]) - float(rb["pos"][ax])))
        qa, qb = ra.get("rot_quat"), rb.get("rot_quat")
        if qa and qb:
            d = max(abs(u - v) for u, v in zip(qa, qb))
            d2 = max(abs(u + v) for u, v in zip(qa, qb))
            if min(d, d2) > G.DATA_TOL:
                bad += 1
            elif d2 < d:
                sign_only += 1
    n = sum(1 for k in set(a) & set(b) if k[0] in common)
    return mx, sign_only, bad, n, len(common), sorted(ents_a ^ ents_b)


def _vert_dev(a_path, b_path):
    """两份 OBJ 的逐顶点偏差 → (n_verts, n_moved, max_dev, 面集合相同?)。
    只在**同名同序**的组之间比（组名/顺序不同就返回 None）。"""
    a = G.parse_obj(open(a_path, encoding="utf-8").read())
    b = G.parse_obj(open(b_path, encoding="utf-8").read())
    if [x["name"] for x in a["meshes"]] != [x["name"] for x in b["meshes"]]:
        return None
    n = moved = 0
    mx = 0.0
    faceeq = True
    for ga, gb in zip(a["meshes"], b["meshes"]):
        if len(ga["verts"]) != len(gb["verts"]):
            return None
        for va, vb in zip(ga["verts"], gb["verts"]):
            d = max(abs(va[i] - vb[i]) for i in range(3))
            n += 1
            if d > 1e-9:
                moved += 1
            mx = max(mx, d)
        if sorted(G.canonical_tris(ga["tris"])) != sorted(G.canonical_tris(gb["tris"])):
            faceeq = False
    return n, moved, mx, faceeq


def _kind_hist(doc):
    hist = {}
    for parts in (doc.get("shapes") or {}).values():
        for p in parts:
            hist[p["kind"]] = hist.get(p["kind"], 0) + 1
    return sum(len(v) for v in (doc.get("shapes") or {}).values()), hist


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec-dir", default=DEF_SPEC)
    ap.add_argument("--ref-dir", default=DEF_REF)
    ap.add_argument("--f0-dir", default=DEF_F0)
    args = ap.parse_args(argv)
    if not os.path.isdir(args.spec_dir):
        print("SKIP: spec 目录不存在：%s（先在 Blender 里跑 `python -m wm_bridge.bpy_dump`）"
              "—— 本核对**未执行**，不是通过" % args.spec_dir)
        return 3
    print("spec（Blender 抽出）：%s" % args.spec_dir)
    print("既有产物（旧口径）  ：%s" % args.ref_dir)
    print("同帧独立产物（f0）  ：%s" % (args.f0_dir if os.path.isdir(args.f0_dir) else "（无）"))
    tmp = tempfile.mkdtemp(prefix="wmb_e2e_")
    bad = []
    print("\n%-7s %-22s %-10s %-26s %-16s %s" % (
        "模型", "OBJ 逐字节(原始差行)", "MTL", "真值(共同实体/最大位置偏差)",
        "四元数", "部件(件数/图元分布)"))
    print("-" * 108)
    try:
        for m in MODELS:
            sp = os.path.join(args.spec_dir, m + ".spec.json")
            ref = os.path.join(args.ref_dir, m)
            if not (os.path.exists(sp) and os.path.isdir(ref)):
                print("%-7s SKIP（缺 spec 或既有产物）" % m)
                continue
            out = os.path.join(tmp, m)
            os.makedirs(out, exist_ok=True)
            o, mtl = os.path.join(out, "mesh.obj"), os.path.join(out, "mesh.mtl")
            rc_o, r_o = _run_cli(["export-obj", "--spec", sp, "--out", o, "--mtl", mtl])
            txt_ref = open(os.path.join(ref, "mesh.obj"), encoding="utf-8").read()
            txt_new = open(o, encoding="utf-8").read()
            # 主参照是 **f0**（Lead 在修好取帧之后独立生成的同帧产物）；
            # 旧 `wmtest/` 是**取帧泄漏期**的产物，只能作诊断参照（见下方 vert_dev）。
            f0o = os.path.join(args.f0_dir, m, "mesh.obj") if os.path.isdir(args.f0_dir) else ""
            ref_primary = f0o if (f0o and os.path.exists(f0o)) else os.path.join(ref, "mesh.obj")
            eq = _sigzero_eq(open(ref_primary, encoding="utf-8").read(), txt_new)
            raw = _raw_diff_lines(open(ref_primary, encoding="utf-8").read(), txt_new)
            vd = _vert_dev(os.path.join(ref, "mesh.obj"), ref_primary) \
                if ref_primary != os.path.join(ref, "mesh.obj") else None
            mtl_eq = _sigzero_eq(open(os.path.join(ref, "mesh.mtl"), encoding="utf-8").read(),
                                 open(mtl, encoding="utf-8").read())
            so, sh = os.path.join(out, "shapes.json"), os.path.join(out, "oracle.jsonl")
            rc_s, r_s = _run_cli(["export-shapes", "--spec", sp, "--out", so])
            rc_r, r_r = _run_cli(["export-oracle", "--spec", sp, "--out", sh])
            mx, sign_only, nb, ncmp, nent, only = _oracle_cmp(
                os.path.join(ref, "oracle.jsonl"), sh)
            mine = json.load(open(so, encoding="utf-8"))
            refsh = json.load(open(os.path.join(ref, "shapes.json"), encoding="utf-8"))
            n_mine, h_mine = _kind_hist(mine)
            n_ref, h_ref = _kind_hist(refsh)
            groups = sorted(k.split("/")[-1] for k in mine["shapes"])
            print("%-7s %-22s %-10s %-26s %-16s %s" % (
                m,
                "%s (raw差 %s)" % ("✅" if eq else "❌", raw),
                "✅" if mtl_eq else "❌",
                "%d 实体/%d 条  max=%.3e" % (nent, ncmp, mx),
                "±q:%d 超差:%d" % (sign_only, nb),
                "%d==%d %s" % (n_mine, n_ref, "✅" if h_mine == h_ref else "❌ %s vs %s"
                               % (h_mine, h_ref))))
            print("        link 分组=%s｜crosscheck ok=%s(问题 %d)｜oracle rc=%s cov=%s"
                  % (groups, (r_s.get("crosscheck") or {}).get("ok"),
                     (r_s.get("crosscheck") or {}).get("n_problems", -1),
                     rc_r, r_r.get("frame_coverage_problem")))
            if vd:
                print("        诊断：旧 wmtest/mesh.obj vs f0 ⇒ 顶点 %d 个，位移 %d 个(%.1f%%)，"
                      "max|Δ|=%.6f m，面集合相同=%s"
                      % (vd[0], vd[1], 100.0 * vd[1] / vd[0], vd[2], vd[3]))
            if not (rc_o == 0 and rc_s == 0 and rc_r == 0 and eq and mtl_eq
                    and nb == 0 and h_mine == h_ref
                    and (r_s.get("crosscheck") or {}).get("ok")):
                bad.append(m)
            if vd and vd[1] and vd[2] > G.DATA_TOL:
                print("        ⇒ 旧件在这 %d 个顶点上**姿态就不同**（不是格式差异）："
                      "正是本桥要挡的取帧泄漏" % vd[1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 108)
    if bad:
        print("差异：%s" % bad)
        print("VERDICT=DIFF")
        return 2
    print("VERDICT=MATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
