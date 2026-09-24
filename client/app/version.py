# -*- coding: utf-8 -*-
"""客户端版本号单一来源。

使用方：
- ``api_client`` 心跳上报（CLIENT_VERSION 引用 APP_VERSION）；
- ``updater`` 与服务端发布版本比对，判断是否需要更新；
- ``build.py`` 读取此处命名 zip 产物，并写入包内 update_manifest.json。

不变量：发布更新时 APP_VERSION 必须与 build.py 产出的
update_manifest.json 的 version 一致（build.py 自动保证）。
"""

from __future__ import annotations

#: 当前客户端版本号（语义化：主.次.修订）
APP_VERSION = "1.1.0"
