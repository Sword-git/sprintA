"""Pydantic data contracts for the Semantic Ingestion Gate."""

import uuid
from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field


class BoundaryType(str, Enum):
    """触发闸门放行的边界类型。"""

    TOPIC_COMPLETE = "topic_complete"  # 当前话题已充分讨论
    TOPIC_SWITCH = "topic_switch"      # 用户切换到新话题
    TIMEOUT = "timeout"                # 对话超时，系统强制刷写
    FORCE = "force"                    # 外部强制刷新


class MemoryNode(BaseModel):
    """话题级记忆单元 —— 闸门放行后交付给存储层的最小结构。

    对齐 Mem0 原生 `MemoryItem` 风格（mem0-main/mem0/configs/base.py:16），
    新增 topic 维度的语义字段。
    """

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="唯一标识符",
    )
    topic_summary: str = Field(
        ...,
        description="话题摘要，由 LLM 在边界判定时生成",
    )
    messages: List[Dict[str, str]] = Field(
        ...,
        description="原始对话窗口内容，格式为 [{\"role\": \"user\"|\"assistant\", \"content\": \"...\"}]",
    )
    boundary_type: BoundaryType = Field(
        ...,
        description="触发写入的边界类型",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="边界判定的置信度（0.0-1.0）",
    )
    user_id: Optional[str] = Field(
        None,
        description="对齐 Mem0.add() 的 user_id 参数",
    )
    agent_id: Optional[str] = Field(
        None,
        description="对齐 Mem0.add() 的 agent_id 参数",
    )
    run_id: Optional[str] = Field(
        None,
        description="对齐 Mem0.add() 的 run_id 参数",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="扩展元数据，对齐 MemoryItem.metadata",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="记忆创建时间戳（UTC）",
    )


class MemoryRetrievedEvent(BaseModel):
    """检索事件 —— 记录本次检索的上下文，供后续话题连续性判定。"""

    query: str = Field(
        ...,
        description="用户查询内容",
    )
    retrieved_nodes: List[MemoryNode] = Field(
        default_factory=list,
        description="检索到的记忆节点列表",
    )
    context_window: List[Dict[str, str]] = Field(
        default_factory=list,
        description="当前对话窗口，用于上下文连续性判断",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="检索事件时间戳（UTC）",
    )
