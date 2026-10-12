# -*- coding: utf-8 -*-
"""wm_bridge.probe · 通道探针（fail-closed）

判据与插件自身的诊断词汇对齐：**跑不起来永远不等于通过**。
本件只做"能不能连上"的判定，不做任何写操作、不启动任何进程。

生效条件：probe() 返回 dict，kind ∈ {ok, blender-unreachable, backend-unreachable,
degraded, config-error}；kind != "ok" 时 ok 为 False 且给出 fix 提示。**绝不返回"未知但算过"**。
"""
from __future__ import annotations

import json
import os
import socket

#: 本 fork 的隔离端口（原版 9876/9877/9878）
DEFAULT_ADDON_PORT = 9886
DEFAULT_HTTP_PORT = 9887
PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_NAME = "dsh-blender-wm.config.json"


def load_ports(config_path: str | None = None) -> tuple[int, int, str]:
    """解析端口：env（DSH_BLENDER_WM_ADDON_PORT / _HTTP_PORT）→ 配置文件 → 内置默认。"""
    addon = os.environ.get("DSH_BLENDER_WM_ADDON_PORT")
    http = os.environ.get("DSH_BLENDER_WM_HTTP_PORT")
    src = "default"
    if addon is None or http is None:
        p = config_path or os.path.join(PKG_ROOT, CONFIG_NAME)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
                if addon is None and cfg.get("addonPort"):
                    addon, src = cfg["addonPort"], "config:%s" % os.path.basename(p)
                if http is None and cfg.get("httpPort"):
                    http, src = cfg["httpPort"], "config:%s" % os.path.basename(p)
            except (OSError, ValueError):
                src = "config-unreadable"
    try:
        return int(addon or DEFAULT_ADDON_PORT), int(http or DEFAULT_HTTP_PORT), src
    except (TypeError, ValueError):
        return DEFAULT_ADDON_PORT, DEFAULT_HTTP_PORT, "config-invalid→default"


def tcp_alive(host: str, port: int, timeout: float = 1.5) -> bool:
    """生效条件：在 timeout 内建立到 host:port 的 TCP 连接成功返回 True，否则 False。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe(host: str = "127.0.0.1", config_path: str | None = None) -> dict:
    """探通道。返回 dict（ok/kind/summary/fix/ports）。"""
    addon_port, http_port, src = load_ports(config_path)
    a = tcp_alive(host, addon_port)
    b = tcp_alive(host, http_port)
    ports = {"addon": addon_port, "http": http_port, "source": src}
    if a and b:
        return {"ok": True, "kind": "ok",
                "summary": "addon 与后端都在监听（%d / %d）" % (addon_port, http_port),
                "fix": "", "ports": ports}
    if not a and not b:
        return {"ok": False, "kind": "blender-unreachable",
                "summary": "%d 与 %d 都没人监听 —— Blender 没跑，或 addon 没 Connect，后端也没起"
                           % (addon_port, http_port),
                "fix": "blender_viewport(op=\"launch\") 一键拉起并自动 Connect；"
                       "或人工：Blender → N 面板 → Connect",
                "ports": ports}
    if not a:
        return {"ok": False, "kind": "blender-unreachable",
                "summary": "后端在（%d），但 addon 端口 %d 没监听 —— Blender 没跑或没 Connect"
                           % (http_port, addon_port),
                "fix": "blender_viewport(op=\"launch\")；或人工在 Blender 里按 N → Connect",
                "ports": ports}
    return {"ok": False, "kind": "backend-unreachable",
            "summary": "addon 在（%d），但后端端口 %d 没监听" % (addon_port, http_port),
            "fix": "blender_viewport(op=\"start\") 起后端；仍不通看 workDir 是否可写",
            "ports": ports}
