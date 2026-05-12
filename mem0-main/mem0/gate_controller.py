"""GateController — 语义闸门控制器（具体实现）。

职责：
- 编排消息追加 → trigger 判定 → flush 流程
- 超时强制刷写
- 状态查询
"""

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
        # TODO: 待 Sprint 1-B 实现 SemanticEventTrigger 后启用
        # if self._trigger:
        #     result = self._trigger.evaluate(self._buffer.get_window())
        #     if result.is_boundary:
        #         return True
        return False

    def flush(self) -> List[MemoryNode]:
        """导出当前缓冲区的全部消息为一个 MemoryNode 并清空缓冲区。"""
        messages = self._buffer.get_window()
        node = MemoryNode(
            topic_summary="待 LLM 生成",
            messages=messages,
            boundary_type=BoundaryType[self._last_boundary_type.upper()],
            confidence=1.0,
        )
        self._buffer.clear()
        self._is_flushed = True
        return [node]

    def get_state(self) -> Dict[str, Any]:
        """返回闸门当前状态。"""
        return {
            "buffer_size": self._buffer.size(),
            "last_boundary_type": self._last_boundary_type,
            "is_flushed": self._is_flushed,
            "ttl_remaining": 0,  # TODO: 计算 TTL 剩余时间
        }

    def reset(self) -> None:
        """重置闸门到初始状态。"""
        self._buffer.clear()
        self._last_boundary_type = "none"
        self._is_flushed = False
