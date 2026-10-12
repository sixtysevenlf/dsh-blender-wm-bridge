# -*- coding: utf-8 -*-
"""wm_bridge.manifest · SHA-256 清单读写与**严格**核验

对齐灵枢的清单纪律（`tools/verify_manifest.py --strict`：逐项比对被登记的文件，不看总数）：
  · 同时记 **raw**（原始字节）与 **LF 归一**（CRLF→LF）两种哈希——灵枢侧用它对齐跨平台差异；
  · 核验时**缺文件 / 多文件 / 哈希不符**都算失败，各自点名；
  · 清单本身参与哈希（`self` 字段留空写出，避免自指）。

生效条件：build() 给 root 与相对路径列表时返回清单对象；verify() 在清单与盘面逐项一致时 ok=True。
"""
from __future__ import annotations

import hashlib
import json
import os

from . import SCHEMA_MANIFEST

CHUNK = 1 << 20


def raw_sha256(path: str) -> str:
    """文件的原始字节 SHA-256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(CHUNK), b""):
            h.update(blk)
    return h.hexdigest()


def lf_sha256(path: str) -> str:
    """CRLF→LF 归一后的 SHA-256（纯二进制文件按原文算）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()
    h.update(data.replace(b"\r\n", b"\n"))
    return h.hexdigest()


def build(root: str, rels, algorithm_note: str = "") -> dict:
    """给 root 与相对路径列表，产出清单对象（相对路径 → 两种哈希 + 字节数）。"""
    files = {}
    for rel in sorted(rels):
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            raise FileNotFoundError("登记的文件不存在：%s" % rel)
        files[rel] = {
            "raw_sha256": raw_sha256(p),
            "lf_sha256": lf_sha256(p),
            "bytes": os.path.getsize(p),
        }
    return {
        "schema": SCHEMA_MANIFEST,
        "algorithm": "sha256",
        "note": algorithm_note,
        "root_hint": os.path.basename(os.path.normpath(root)),
        "count": len(files),
        "files": files,
        "self": "",          # 清单自身哈希留空写出，读回后由 verify 报告，避免自指
    }


def write(root: str, rels, out_path: str, algorithm_note: str = "") -> dict:
    """建清单并落盘（UTF-8、无 BOM、LF 行尾）。"""
    man = build(root, rels, algorithm_note)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")
    return man


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify(man: dict, root: str, strict: bool = True) -> tuple[bool, list]:
    """核验清单与盘面。

    返回 (ok, problems)。problems 每项为 (kind, rel, detail)：
      missing / changed / extra（strict 时才算 extra）/ malformed
    """
    problems = []
    if not isinstance(man, dict) or man.get("schema") != SCHEMA_MANIFEST:
        return False, [("malformed", "", "清单 schema 不符或不是对象")]
    files = man.get("files")
    if not isinstance(files, dict):
        return False, [("malformed", "", "清单缺 files 对象")]
    if man.get("count") != len(files):
        problems.append(("malformed", "", "count=%r 与 files 条数 %d 不符"
                         % (man.get("count"), len(files))))
    for rel, rec in sorted(files.items()):
        p = os.path.join(root, rel)
        if not os.path.isfile(p):
            problems.append(("missing", rel, "文件不在盘上"))
            continue
        try:
            raw = raw_sha256(p)
            lf = lf_sha256(p)
        except OSError as exc:
            problems.append(("missing", rel, "读失败：%r" % (exc,)))
            continue
        if raw != rec.get("raw_sha256"):
            problems.append(("changed", rel, "raw_sha256 不符：清单 %s / 盘面 %s"
                             % (str(rec.get("raw_sha256"))[:12], raw[:12])))
        if lf != rec.get("lf_sha256"):
            problems.append(("changed", rel, "lf_sha256 不符：清单 %s / 盘面 %s"
                             % (str(rec.get("lf_sha256"))[:12], lf[:12])))
        if rec.get("bytes") != os.path.getsize(p):
            problems.append(("changed", rel, "字节数不符：清单 %r / 盘面 %d"
                             % (rec.get("bytes"), os.path.getsize(p))))
    if strict:
        # 全量面：登记面之外不得多也不能少（调用方自己给根）
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                if rel.replace(os.sep, "/") not in files:
                    problems.append(("extra", rel, "未登记文件（strict 下算失败）"))
    ok = not problems
    return ok, problems
