#!/usr/bin/env python3
"""macOS 全局快捷键：Carbon RegisterEventHotKey。

不依赖 Accessibility 权限；不使用前台 keydown。
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Callable

SIGNATURE = 0x4E48544B                 # 'NHTK'
CONTROL = 0x1000
OPTION = 0x0800
HOT_KEY_CLASS = 0x6B657962             # 'keyb'
HOT_KEY_PRESSED = 5
PARAM_DIRECT = 0x2D2D2D2D              # '----'
TYPE_HOT_KEY_ID = 0x686B6964           # 'hkid'

# Carbon key codes
KEY_LEFT = 123
KEY_RIGHT = 124
KEY_P = 35

BINDINGS = {
    "prev": (KEY_LEFT, CONTROL | OPTION),
    "next": (KEY_RIGHT, CONTROL | OPTION),
    "toggle": (KEY_P, CONTROL | OPTION),
}


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


# 必须保留回调/ref 的强引用，否则 Carbon 会持有悬空指针。
_callback = None
_handler_ref = ctypes.c_void_p()
_hotkey_refs: list[ctypes.c_void_p] = []


def install(callback: Callable[[str], None]) -> bool:
    """注册三个全局热键；成功返回 True，非 macOS/失败返回 False。"""
    global _callback
    if sys.platform != "darwin":
        return False
    path = ctypes.util.find_library("Carbon")
    if not path:
        return False
    try:
        carbon = ctypes.CDLL(path)
        target = carbon.GetApplicationEventTarget
        target.restype = ctypes.c_void_p
        app_target = target()
        if not app_target:
            return False

        handler_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.c_void_p)

        def on_event(_call_ref, event, _user):
            hk = EventHotKeyID()
            size = ctypes.c_ulong(0)
            carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong), ctypes.c_void_p,
            ]
            carbon.GetEventParameter.restype = ctypes.c_int32
            ok = carbon.GetEventParameter(
                event, PARAM_DIRECT, TYPE_HOT_KEY_ID, None,
                ctypes.sizeof(hk), ctypes.byref(size), ctypes.byref(hk))
            if ok == 0 and hk.signature == SIGNATURE:
                # 每个绑定使用 id = 1/2/3；见下方注册顺序。
                name = {1: "prev", 2: "next", 3: "toggle"}.get(hk.id)
                if name:
                    try:
                        callback(name)
                    except Exception:
                        pass
            return 0

        _callback = handler_type(on_event)
        carbon.InstallEventHandler.argtypes = [
            ctypes.c_void_p, handler_type, ctypes.c_ulong,
            ctypes.POINTER(EventTypeSpec), ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.InstallEventHandler.restype = ctypes.c_int32
        spec = EventTypeSpec(HOT_KEY_CLASS, HOT_KEY_PRESSED)
        if carbon.InstallEventHandler(app_target, _callback, 1,
                                      ctypes.byref(spec), None,
                                      ctypes.byref(_handler_ref)) != 0:
            return False

        carbon.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID,
            ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        carbon.RegisterEventHotKey.restype = ctypes.c_int32
        for n, (name, (code, mods)) in enumerate(BINDINGS.items(), 1):
            ref = ctypes.c_void_p()
            if carbon.RegisterEventHotKey(code, mods, EventHotKeyID(SIGNATURE, n),
                                          app_target, 0, ctypes.byref(ref)) != 0:
                return False
            _hotkey_refs.append(ref)
        return True
    except Exception:
        return False
