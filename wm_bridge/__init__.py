# -*- coding: utf-8 -*-
"""wm_bridge · 灵枢世界模型 × Blender 桥 —— 本 fork 相对原版插件的全部新增面。

设计契约见 DESIGN.md。三条硬边界（违反即失败）：
  B1 不改 lingshu 的 world/
  B2 不把 bpy 带进 lingshu
  B3 原版插件零改动

本包**不 import bpy**：所有需要 Blender 的动作都经进程外通道（见 probe.py / 待实现的 oracle.py），
因此本包可以在没有 Blender、没有 DSH、没有插件的机器上单独跑自测。
"""
__version__ = "0.1.0"

SCHEMA_ORACLE = "wm_bridge.oracle/1"   # 真值导出记录的 schema 标识
SCHEMA_MANIFEST = "wm_bridge.manifest/1"
