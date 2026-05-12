"""Mem0Interceptor — Mem0 Memory.add() 拦截器。

职责：
- 子类化 Memory 覆盖 add() 方法
- 被拦截消息送入 GateController.process()
- 支持 install / uninstall 生命周期管理
"""

from typing import Any, Dict, List, Optional

from mem0.memory.main import Memory


class Mem0Interceptor:
    """Mem0 拦截器，控制 Memory.add() 的语义闸门行为。

    Args:
        gate_controller: 闸门控制器实例
    """

    def __init__(self, gate_controller):
        self._gate = gate_controller
        self._intercepted_memory: Optional[Memory] = None
        self._original_class = Memory

    def install(self) -> None:
        """安装拦截器：将 Memory 替换为 InterceptedMemory。"""
        # TODO: 实现全局替换逻辑
        pass

    def uninstall(self) -> None:
        """卸载拦截器：恢复原生 Memory 行为。"""
        # TODO: 恢复原始 Memory 类引用
        pass


class InterceptedMemory(Memory):
    """拦截式 Memory 子类，覆盖 add() 方法实现语义闸门。

    这是推荐的拦截方案（方案 3），不污染全局状态。
    """

    def __init__(self, gate_controller, **kwargs):
        super().__init__(**kwargs)
        self._gate = gate_controller
        self._original_add = super().add

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
        """重写 add()：语义闸门逻辑。"""
        # TODO: 实现完整的闸门逻辑
        # 1. infer=False 时直接放行
        # 2. infer=True 时逐条送入 GateController
        # 3. process 返回 True 时触发 flush 并调用原始 add
        return self._original_add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            metadata=metadata,
            infer=infer,
            memory_type=memory_type,
            prompt=prompt,
        )
