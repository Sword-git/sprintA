"""Gate Controller — 语义闸门的核心抽象。

负责：
1. MemoryIngestionGate 抽象接口定义
2. 消息追加 → trigger 判定 → flush 流程编排
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

from mem0.ingestion_gate.memory_node import MemoryNode


class TriggerResult:
    """语义触发器判定结果。

    作为 `MemoryIngestionGate.evaluate()` 的返回值，
    将 LLM 的边界判定结果结构化传递给闸门控制器。
    """

    def __init__(
        self,
        is_boundary: bool,
        confidence: float,
        topic_summary: str,
        boundary_type: str = "none",
    ):
        self.is_boundary = is_boundary
        self.confidence = confidence
        self.topic_summary = topic_summary
        self.boundary_type = boundary_type

    def __repr__(self) -> str:
        return (
            f"TriggerResult(is_boundary={self.is_boundary}, "
            f"confidence={self.confidence:.2f}, "
            f"boundary_type={self.boundary_type})"
        )


class MemoryIngestionGate(ABC):
    """语义闸门抽象接口。

    所有实现必须提供以下四个方法：
    - process(): 接收单条消息，追加到缓冲区后调用语义判定
    - flush(): 导出当前累积的完整记忆并清空缓冲区
    - get_state(): 查询闸门当前状态
    - reset(): 重置到初始状态

    典型实现见后续 GateController。
    """

    @abstractmethod
    def process(
        self,
        message: Dict[str, str],
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """处理单条消息。

        流程：消息追加到缓冲区 → 调用语义判定 → 返回是否触发 flush。

        Args:
            message: 单条对话消息，格式 {"role": "user"|"assistant", "content": "..."}
            user_id: 用户标识（对齐 Mem0.add()）
            agent_id: Agent 标识（对齐 Mem0.add()）
            run_id: 运行标识（对齐 Mem0.add()）
            metadata: 扩展元数据

        Returns:
            True = 语义判定为边界，应执行 flush
            False = 继续累积，不触发写入
        """
        ...

    @abstractmethod
    def flush(self) -> List[MemoryNode]:
        """导出当前缓冲区中累积的记忆并清空缓冲区。

        Returns:
            话题级记忆节点列表，每个节点含完整对话窗口和语义元信息。
        """
        ...

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """查询闸门当前状态。

        Returns:
            状态字典，至少包含：
            - buffer_size: 当前缓冲区内消息数量
            - last_boundary_type: 最后一次触发的边界类型
            - is_flushed: 是否已被 flush 过
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """重置闸门到初始状态。"""
        ...
