"""GateController — 语义闸门控制器（具体实现）。

职责：
- 编排消息追加 → trigger 判定 → flush 流程
- 超时强制刷写
- 状态查询
"""

import time
from typing import Dict, Any, List, Optional

from mem0.ingestion_gate.memory_node import MemoryNode, BoundaryType
from mem0.ingestion_gate.gate_controller import MemoryIngestionGate
from mem0.ingestion_gate.gate_controller import TriggerResult
from mem0.memory_buffer import ActiveStreamBuffer


class GateController(MemoryIngestionGate):
    """语义闸门控制器的具体实现。

    将 ActiveStreamBuffer 和语义触发器绑定，实现完整的闸门逻辑。

    Args:
        buffer: 消息缓冲区实例
        trigger: 语义事件触发器实例（待 Sprint 1-B 实现后可注入）
    """

    def __init__(self, buffer: ActiveStreamBuffer, trigger=None):
        self._buffer = buffer
        self._trigger = trigger
        self._last_boundary_type: str = "none"
        self._is_flushed: bool = False
        self._user_id: Optional[str] = None
        self._agent_id: Optional[str] = None
        self._run_id: Optional[str] = None
        self._metadata: Optional[Dict[str, Any]] = None

    def process(
        self,
        message: Dict[str, str],
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """处理单条消息：追加到缓冲区 → 语义判定 → 返回是否触发 flush。"""
        self._user_id = user_id
        self._agent_id = agent_id
        self._run_id = run_id
        self._metadata = metadata

        # 追加消息到缓冲区
        self._buffer.append_sync(message)

        # 语义触发器判定
        if self._trigger:
            result = self._trigger.evaluate(self._buffer.get_window())
            if result.is_boundary:
                self._last_boundary_type = result.boundary_type
                return True
        return False

    def check_timeout(self) -> bool:
        """缓冲区中是否有消息已过期。"""
        return self._buffer.has_expired()

    def force_flush(self, boundary_type: str = "force") -> List[MemoryNode]:
        """强制刷写当前缓冲区，无视 trigger 判定。"""
        self._last_boundary_type = boundary_type
        node = self._build_node(boundary_type)
        self._buffer.clear()
        self._is_flushed = True
        return [node]

    def flush(self) -> List[MemoryNode]:
        """导出当前缓冲区的全部消息为一个 MemoryNode 并清空缓冲区。"""
        return self.force_flush(boundary_type=self._last_boundary_type)

    def _build_node(self, boundary_type: str) -> MemoryNode:
        """根据当前缓冲区和元数据构建 MemoryNode。"""
        return MemoryNode(
            topic_summary="待 LLM 生成",
            messages=self._buffer.get_window(),
            boundary_type=BoundaryType[boundary_type.upper()],
            confidence=1.0,
            user_id=self._user_id,
            agent_id=self._agent_id,
            run_id=self._run_id,
            metadata=self._metadata,
        )

    def get_state(self) -> Dict[str, Any]:
        """返回闸门当前状态。"""
        ttl_remaining = 0
        if self._buffer.size() > 0:
            oldest = min(
                (m.get("_received_at", 0) for m in self._buffer._buffer),
                default=0,
            )
            elapsed = time.time() - oldest if oldest else 0
            ttl_remaining = max(0, int(self._buffer._ttl_seconds - elapsed))
        return {
            "buffer_size": self._buffer.size(),
            "last_boundary_type": self._last_boundary_type,
            "is_flushed": self._is_flushed,
            "ttl_remaining": ttl_remaining,
        }

    def reset(self) -> None:
        """重置闸门到初始状态。"""
        self._buffer.clear()
        self._last_boundary_type = "none"
        self._is_flushed = False
        self._user_id = None
        self._agent_id = None
        self._run_id = None
        self._metadata = None
