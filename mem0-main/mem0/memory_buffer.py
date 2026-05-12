"""ActiveStreamBuffer — 话题消息滑动窗口缓冲区。

职责：
- 累积对话消息到可配置大小的滑动窗口
- 基于 TTL 的自动过期清理
- FIFO 挤出（满窗口时移除最旧消息）
- asyncio.Lock 并发安全
"""

import asyncio
import time
from typing import Dict, Any, List, Optional


class ActiveStreamBuffer:
    """话题级消息缓冲区，支持滑动窗口和 TTL 过期。

    Args:
        max_window_size: 窗口最大消息数，默认 15
        ttl_seconds: 消息过期时间（秒），默认 300
    """

    def __init__(self, max_window_size: int = 15, ttl_seconds: int = 300):
        self._max_window_size = max_window_size
        self._ttl_seconds = ttl_seconds
        self._buffer: List[Dict[str, Any]] = []
        self._seq: int = 0
        self._lock = asyncio.Lock()

    async def append(self, message: Dict[str, str]) -> None:
        """追加消息到缓冲区。

        消息结构：{"role": str, "content": str, "_received_at": float, "_seq": int}
        满窗口时 FIFO 挤出最旧消息。
        """
        async with self._lock:
            entry = {
                "role": message["role"],
                "content": message["content"],
                "_received_at": time.time(),
                "_seq": self._seq,
            }
            self._seq += 1
            self._buffer.append(entry)
            # 满窗口时挤出最旧
            if len(self._buffer) > self._max_window_size:
                self._buffer.pop(0)
            # 自动触发过期扫描
            self._cleanup_expired_sync()

    def get_window(self) -> List[Dict[str, Any]]:
        """返回当前窗口内全部消息（不含内部字段 _received_at/_seq）。"""
        return [
            {"role": m["role"], "content": m["content"]}
            for m in self._buffer
        ]

    def slide(self, count: int) -> List[Dict[str, Any]]:
        """弹出指定数量的最旧消息并返回。"""
        result = self._buffer[:count]
        self._buffer = self._buffer[count:]
        return result

    def clear(self) -> List[Dict[str, Any]]:
        """清空缓冲区并返回全部消息。"""
        result = list(self._buffer)
        self._buffer.clear()
        return result

    def is_expired(self, message: Dict[str, Any]) -> bool:
        """判断单条消息是否过期。"""
        received_at = message.get("_received_at")
        if received_at is None:
            return True
        return (time.time() - received_at) > self._ttl_seconds

    def size(self) -> int:
        """返回当前缓冲区内消息数量。"""
        return len(self._buffer)

    def cleanup_expired(self) -> int:
        """批量剔除过期消息，返回剔除数量。"""
        before = len(self._buffer)
        self._cleanup_expired_sync()
        return before - len(self._buffer)

    def _cleanup_expired_sync(self) -> None:
        now = time.time()
        cutoff = now - self._ttl_seconds
        self._buffer = [m for m in self._buffer if m.get("_received_at", 0) > cutoff]
