"""SemanticEventTrigger — LLM 驱动的话题边界判定器。

职责：
- 调用 LLM 分析对话窗口是否出现话题边界
- 解析 LLM JSON 输出为 TriggerResult
- 容错处理异常 JSON 格式
"""

import json
import logging
from typing import Dict, Any, List, Optional

from mem0.ingestion_gate.gate_controller import TriggerResult

logger = logging.getLogger(__name__)

# B2-001：话题边界判定的 Prompt 模板
BOUNDARY_DETECTION_PROMPT = """你是一个对话话题边界检测器。分析以下对话消息，判断是否出现了话题边界。

话题边界的定义：
1. TOPIC_COMPLETE: 当前话题的讨论已经自然结束
2. TOPIC_SWITCH: 对话明显转向了一个新的话题
3. TIMEOUT: 长时间没有新消息，话题已冷却
4. NONE: 当前话题仍在继续，没有边界

消息列表：
{messages}

请严格返回以下 JSON 格式（不要包含其他文字）：
{{
    "is_boundary": true或false,
    "confidence": 0.0到1.0之间的数值,
    "topic_summary": "当前话题的简短总结，如果is_boundary为false则为空字符串",
    "boundary_type": "TOPIC_COMPLETE" / "TOPIC_SWITCH" / "TIMEOUT" / "NONE"
}}
"""


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 返回的文本中提取 JSON 对象。

    对齐 mem0-main/mem0/memory/utils.py 中的 extract_json 函数风格。
    支持从代码块（```json ```）、普通文本中提取 JSON。
    """
    if not text:
        return None

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass

    if "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass

    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        if end > start:
            try:
                return json.loads(text[start:end].strip())
            except json.JSONDecodeError:
                pass

    return None


class SemanticEventTrigger:
    """语义事件触发器，基于 LLM 判定话题边界。

    Args:
        llm_client: LLM 客户端实例
        model: 模型名称，默认 gpt-4o
        threshold: 置信度阈值，默认 0.7
    """

    def __init__(self, llm_client, model: str = "gpt-4o", threshold: float = 0.7):
        self._llm = llm_client
        self._model = model
        self._threshold = threshold

    def _build_prompt(self, messages: List[Dict[str, str]]) -> str:
        """构造发送给 LLM 的 Prompt。"""
        formatted_messages = []
        for i, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            formatted_messages.append(f"[{i}] {role}: {content}")
        return BOUNDARY_DETECTION_PROMPT.format(messages="\n".join(formatted_messages))

    def _parse_response(self, response_text: str) -> TriggerResult:
        """解析 LLM 响应，容错处理异常格式。"""
        parsed = extract_json(response_text)

        if parsed is None:
            logger.warning(f"无法解析 LLM 响应: {response_text[:200]}")
            return TriggerResult(is_boundary=False, confidence=0.0, topic_summary="", boundary_type="NONE")

        is_boundary = parsed.get("is_boundary", False)
        confidence = parsed.get("confidence", 0.0)
        topic_summary = parsed.get("topic_summary", "")
        boundary_type = parsed.get("boundary_type", "NONE")

        valid_types = {"TOPIC_COMPLETE", "TOPIC_SWITCH", "TIMEOUT", "NONE"}
        if boundary_type not in valid_types:
            boundary_type = "TOPIC_COMPLETE"

        if is_boundary and confidence >= self._threshold:
            return TriggerResult(is_boundary=True, confidence=confidence, topic_summary=topic_summary, boundary_type=boundary_type)
        else:
            return TriggerResult(is_boundary=False, confidence=confidence, topic_summary="", boundary_type="NONE")

    def evaluate(self, messages: List[Dict[str, str]]) -> TriggerResult:
        """分析对话窗口，返回话题边界判定结果。"""
        if not messages:
            return TriggerResult(is_boundary=False, confidence=0.0, topic_summary="", boundary_type="NONE")

        prompt = self._build_prompt(messages)

        try:
            response = self._llm.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "你是一个严格输出 JSON 的对话分析助手。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            response_text = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return TriggerResult(is_boundary=False, confidence=0.0, topic_summary="", boundary_type="NONE")

        return self._parse_response(response_text)
