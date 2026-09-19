# -*- coding: utf-8 -*-
"""单实例锁（阶段 2）。

策略（按优先级）：
1. QLocalSocket 连接测试：已存在监听实例 → 向对方发送 ``show`` 消息，
   返回 ``is_primary=False``；
2. QLocalServer 监听：无实例时建立命名管道；listen 失败（名字被占 /
   残留管道）时先 ``removeServer`` 再重试一次；
3. QSharedMemory 兜底：``attach`` 探测已有实例，失败则 ``create(1)`` 占位。

Windows 注意事项：QLocalServer 在 Windows 使用命名管道，名字不允许出现
反斜杠等字符，因此 key 固定为安全字符串（默认为 ``HomeworkTime_SingleInstance``），
本模块内部还会再做一次非法字符清洗。

作为 principal 方（is_primary=True）收到新连接时，将其内容经 ``new_message``
信号发出（AppController 可轮询属性 ``messages`` 或直接连接信号）。
"""

from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import QObject, QSharedMemory, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

#: 默认实例 key（Windows 命名管道名，不能含反斜杠）
DEFAULT_KEY = "HomeworkTime_SingleInstance"
#: key 中禁止出现的字符（安全清洗）
_BAD_CHARS = '\\/:*?"<>| '

_LOGGER_NAME = "app.single_instance"


def _safe_key(key: str) -> str:
    """清洗 key，确保可用于 Windows 命名管道与共享内存命名。"""
    cleaned = "".join(c for c in key if c not in _BAD_CHARS).strip()
    return cleaned or DEFAULT_KEY


class SingleInstance(QObject):
    """客户端单实例守卫。

    用法::

        si = SingleInstance()
        if not si.is_primary:
            si.notify("show")     # 唤醒已有实例后退出本进程
            si.destroy()
            return
        # ... 正常启动业务 ...
        si.destroy()              # 退出时释放

    消息回传:
        principal 实例将 ``new_message`` 信号对外广播收到的文本
        （多条消息时按顺序累积在 ``messages`` 列表中，供轮询）。
    """

    new_message = pyqtSignal(str)

    def __init__(self, key: str = DEFAULT_KEY, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._key = _safe_key(key)
        self._server: Optional[QLocalServer] = None
        self._memory: Optional[QSharedMemory] = None
        #: 收到的过期消息列表（principal 实例）
        self.messages: List[str] = []
        #: 未断开的客户端连接（保持 Python 引用，避免被 GC 提前销毁）
        self._clients: List[QLocalSocket] = []
        self._primary = self._acquire()
        if self._primary and self._server is not None:
            self._server.newConnection.connect(self._on_new_connection)

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    @property
    def is_primary(self) -> bool:
        """本进程是否为唯一主实例。"""
        return self._primary

    # ------------------------------------------------------------------
    # 实例获取
    # ------------------------------------------------------------------
    def _acquire(self) -> bool:
        """按「连接测试 → QLocalServer → QSharedMemory」顺序判断归属。"""
        # 1) 已有监听实例？
        if self._try_notify_existing("show"):
            return False

        # 2) QLocalServer 监听（先清理可能残留的管道）
        server = QLocalServer(self)
        QLocalServer.removeServer(self._key)
        if server.listen(self._key):
            self._server = server
            self._guard_memory()
            return True
        # 监听失败：名字可能刚被其它进程抢占，removeServer 后重试一次
        QLocalServer.removeServer(self._key)
        if server.listen(self._key):
            self._server = server
            self._guard_memory()
            return True

        # 3) QSharedMemory 兜底
        memory = QSharedMemory(self._key, self)
        if memory.attach():
            return False                     # 确有其它实例存活
        if not memory.create(1):
            return False                     # 正在被其它进程创建/持有
        self._memory = memory
        return True

    def _guard_memory(self) -> None:
        """已抢占 QLocalServer 时，再用 QSharedMemory 占位加固。"""
        memory = QSharedMemory(self._key, self)
        if memory.attach():
            # 极端情况：server 抢到了但 shm 被别人占着 —— 以本实例为准
            return
        try:
            if not memory.create(1):
                return
        except Exception:
            return
        self._memory = memory

    # ------------------------------------------------------------------
    # 通知已有实例
    # ------------------------------------------------------------------
    def _try_notify_existing(self, message: str) -> bool:
        """尝试连接已有实例并发送消息；返回是否连接成功。"""
        socket = QLocalSocket(self)
        socket.connectToServer(self._key)
        if not socket.waitForConnected(800):
            socket.close()
            return False
        try:
            socket.write(message.encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(800)
        except Exception:
            pass
        finally:
            try:
                socket.disconnectFromServer()
            except Exception:
                pass
            socket.close()
        return True

    def notify(self, message: str = "show") -> bool:
        """主动通知当前监听实例（本实例非 principal 时唤醒对方使用）。"""
        return self._try_notify_existing(message)

    # ------------------------------------------------------------------
    # 服务器侧接收
    # ------------------------------------------------------------------
    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        while self._server.hasPendingConnections():
            conn = self._server.nextPendingConnection()
            if conn is None:
                continue
            conn.readyRead.connect(lambda c=conn: self._read_client(c))
            conn.disconnected.connect(lambda c=conn: self._drop_client(c))
            self._clients.append(conn)

    def _read_client(self, conn: QLocalSocket) -> None:
        data = bytes(conn.readAll()).decode("utf-8", "replace")
        if not data:
            return
        self.messages.append(data)
        self.new_message.emit(data)

    def _drop_client(self, conn: QLocalSocket) -> None:
        if conn in self._clients:
            self._clients.remove(conn)
        try:
            conn.deleteLater()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 释放
    # ------------------------------------------------------------------
    def destroy(self) -> None:
        """释放监听与共享内存占位。非 principal 调用为无副作用的安全操作。"""
        if self._server is not None:
            try:
                self._server.close()
                self._server.deleteLater()
            except Exception:
                pass
            self._server = None
        if self._memory is not None:
            try:
                self._memory.detach()
            except Exception:
                pass
            self._memory = None
        for conn in list(self._clients):
            try:
                conn.abort()
                conn.deleteLater()
            except Exception:
                pass
        self._clients = []