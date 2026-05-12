"""SemanticEventTrigger — LLM 驱动的话题边界判定器。

职责：
- 调用 LLM 分析对话窗口是否出现话题边界
- 解析 LLM JSON 输出为 TriggerResult
- 容错处理异常 JSON 格式
"""

from typing import Dict, Any, List

from mem0.ingestion_gate.gate_controller import TriggerResult


class SemanticEventTrigger:
    """语义事件触发器，基于 LLM 判定话题边界。

    Args:
        llm_client: LLM 客户端实例（OpenAI / Mem0 LlmFactory 等）
        model: 模型名称，默认 gpt-4o
        threshold: 置信度阈值，默认 0.7
    """

    def __init__(self, llm_client, model: str = "gpt-4o", threshold: float = 0.7):
        self._llm = llm_client
        self._model = model
        self._threshold = threshold

    def evaluate(self, messages: List[Dict[str, str]]) -> TriggerResult:
        """分析对话窗口，返回话题边界判定结果。

        流程：构造 Prompt → 调用 LLM → 解析 JSON → 返回 TriggerResult
        """
        # TODO: 实现 LLM 调用和 JSON 解析
        return TriggerResult(
            is_boundary=False,
            confidence=0.0,
            topic_summary="待实现",
            boundary_type="none",
        )
