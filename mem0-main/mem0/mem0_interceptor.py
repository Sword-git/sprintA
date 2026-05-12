"""Mem0Interceptor — Mem0 Memory.add() 拦截器。

职责：
- 子类化 Memory 覆盖 add() 方法
- 被拦截消息送入 GateController.process()
- 支持 install / uninstall 生命周期管理
"""

import logging
from typing import Any, Dict, List, Optional

from mem0.memory.main import Memory

logger = logging.getLogger(__name__)


class Mem0Interceptor:
    """Mem0 拦截器，控制 Memory.add() 的语义闸门行为。

    用法：
        memory = Memory(...)
        gate = GateController(...)
        interceptor = Mem0Interceptor(gate)
        intercepted_memory = interceptor.install(memory)
        # 使用 intercepted_memory.add(...) 代替原始 memory.add(...)
        interceptor.uninstall()

    Args:
        gate_controller: 闸门控制器实例（GateController）
    """

    def __init__(self, gate_controller):
        self._gate = gate_controller
        self._original_memory: Optional[Memory] = None
        self._intercepted_memory: Optional[InterceptedMemory] = None

    def install(self, memory: Memory) -> "InterceptedMemory":
        """安装拦截器：使用传入的 Memory 实例创建 InterceptedMemory 包装。

        不修改全局 Memory 类，只包装实例。

        Args:
            memory: 原始的 Memory 实例

        Returns:
            InterceptedMemory 实例，可直接用于 add() 调用
        """
        self._original_memory = memory
        self._intercepted_memory = InterceptedMemory(
            gate_controller=self._gate,
            original_memory=memory,
        )
        logger.info("Mem0Interceptor 已安装")
        return self._intercepted_memory

    def uninstall(self) -> Optional[Memory]:
        """卸载拦截器：返回原始 Memory 实例。

        Returns:
            原始的 Memory 实例
        """
        intercepted = self._intercepted_memory
        original = self._original_memory
        self._intercepted_memory = None
        self._original_memory = None
        logger.info("Mem0Interceptor 已卸载")
        return original


class InterceptedMemory(Memory):
    """拦截式 Memory 子类，覆盖 add() 实现语义闸门。

    不修改全局 Memory 类，通过实例包装实现拦截。
    """

    def __init__(self, gate_controller, original_memory: Memory):
        # 跳过 Memory.__init__，手动设置必要属性
        self._gate = gate_controller
        self._original_memory = original_memory
        self.config = original_memory.config
        self.custom_factories = getattr(original_memory, 'custom_factories', {})
        self.llm = getattr(original_memory, 'llm', None)
        self.embedding_model = getattr(original_memory, 'embedding_model', None)
        self.vector_store = getattr(original_memory, 'vector_store', None)
        self.db = getattr(original_memory, 'db', None)
        self.collection_name = getattr(original_memory, 'collection_name', None)
        self.api_version = getattr(original_memory, 'api_version', None)

    def add(
        self,
        messages,
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        infer: bool = True,
        memory_type: Optional[str] = None,
        prompt: Optional[str] = None,
    ):
        """重写 add()：实现语义闸门逻辑。

        逻辑：
        - infer=False 时绕过闸门，直接调用原始 add()
        - infer=True 时逐条送入 GateController.process()
        - process() 返回 True 时自动 flush，调用原始 add() 批量写入
        """
        # 路径 1：不推理，直接放行
        if not infer:
            return self._original_memory.add(
                messages,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                metadata=metadata,
                infer=False,
                memory_type=memory_type,
                prompt=prompt,
            )

        # 路径 2：标准化 messages 为列表
        if isinstance(messages, dict):
            msg_list = [messages]
        else:
            msg_list = list(messages)

        # 路径 3：逐条送入闸门控制器
        for msg in msg_list:
            is_boundary = self._gate.process_message(
                msg,
                user_id=user_id,
                agent_id=agent_id,
                run_id=run_id,
                metadata=metadata,
            )

            if is_boundary:
                # 触发 flush：批量写入累积的记忆
                memory_nodes = self._gate.flush()
                for node in memory_nodes:
                    enriched_metadata = (metadata or {}) | {
                        "topic_summary": node.topic_summary,
                        "boundary_type": node.boundary_type,
                    }
                    self._original_memory.add(
                        node.messages,
                        user_id=user_id,
                        agent_id=agent_id,
                        run_id=run_id,
                        metadata=enriched_metadata,
                        infer=infer,
                        memory_type=memory_type,
                        prompt=prompt,
                    )

        # 返回空列表
        return []