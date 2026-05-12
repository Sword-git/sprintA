"""Tests for SemanticEventTrigger — 语义触发器测试（Sprint 2-B）。

测试覆盖：
- B4-001: mock LLM 正常/异常 JSON 解析
- B4-002: threshold 参数 + 边界类型映射
"""

import pytest
from unittest.mock import MagicMock
from mem0.semantic_trigger import SemanticEventTrigger, extract_json
from mem0.ingestion_gate.gate_controller import TriggerResult


# ==================== B4-001 ====================

class TestMockLLMNormalJSON:
    """mock 返回正常 JSON 时正确解析 TriggerResult"""

    def test_boundary_true(self):
        """LLM 返回 is_boundary=true 时正确解析"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"is_boundary": true, "confidence": 0.9, "topic_summary": "讨论晚饭", "boundary_type": "TOPIC_COMPLETE"}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "今晚吃什么？"},
            {"role": "assistant", "content": "吃火锅吧"},
            {"role": "user", "content": "好的，走吧"},
        ])

        assert result.is_boundary is True
        assert result.confidence == 0.9
        assert result.topic_summary == "讨论晚饭"
        assert result.boundary_type == "TOPIC_COMPLETE"

    def test_boundary_false(self):
        """LLM 返回 is_boundary=false 时正确解析"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"is_boundary": false, "confidence": 0.3, "topic_summary": "", "boundary_type": "NONE"}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你的？"},
        ])

        assert result.is_boundary is False
        assert result.topic_summary == ""


class TestMockLLMMalformedJSON:
    """mock 返回异常 JSON 时触发容错路径 (B1-002 / B4-001)"""

    def test_plain_text_instead_of_json(self):
        """LLM 返回纯文本而非 JSON"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="我觉得这里的话题还没结束"))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "继续聊"},
        ])

        assert result.is_boundary is False
        assert result.confidence == 0.0
        assert result.boundary_type == "NONE"

    def test_json_in_code_block(self):
        """LLM 返回 ```json ``` 代码块"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='```json\n{"is_boundary": true, "confidence": 0.85, "topic_summary": "天气话题结束", "boundary_type": "TOPIC_SWITCH"}\n```'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "今天天气怎么样？"},
            {"role": "assistant", "content": "挺好的"},
            {"role": "user", "content": "那我们聊聊别的吧"},
        ])

        assert result.is_boundary is True
        assert result.boundary_type == "TOPIC_SWITCH"

    def test_llm_call_failure(self):
        """LLM 调用本身抛出异常"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.side_effect = Exception("网络错误")

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "测试"},
        ])

        assert result.is_boundary is False
        assert result.confidence == 0.0

    def test_empty_response(self):
        """LLM 返回空字符串"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content=""))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "测试"},
        ])

        assert result.is_boundary is False


# ==================== B4-002 ====================

class TestThresholdParameter:
    """threshold 参数影响判定结果"""

    def test_below_threshold(self):
        """confidence < threshold 时 is_boundary=False"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"is_boundary": true, "confidence": 0.6, "topic_summary": "不太确定的话题", "boundary_type": "TOPIC_COMPLETE"}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "嗯"},
            {"role": "assistant", "content": "哦"},
        ])

        assert result.is_boundary is False  # 0.6 < 0.7

    def test_above_threshold(self):
        """confidence >= threshold 时 is_boundary=True"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"is_boundary": true, "confidence": 0.8, "topic_summary": "确定的话题结束", "boundary_type": "TOPIC_COMPLETE"}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "好的，今天就到这里"},
        ])

        assert result.is_boundary is True  # 0.8 >= 0.7

    def test_exactly_at_threshold(self):
        """confidence == threshold 时 is_boundary=True"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"is_boundary": true, "confidence": 0.7, "topic_summary": "刚好阈值", "boundary_type": "TOPIC_COMPLETE"}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "刚好到达阈值"},
        ])

        assert result.is_boundary is True  # 0.7 >= 0.7


class TestBoundaryTypeMapping:
    """BoundaryType 枚举值与返回 JSON 的映射"""

    @pytest.mark.parametrize("boundary_type", [
        "TOPIC_COMPLETE",
        "TOPIC_SWITCH",
        "TIMEOUT",
        "NONE",
    ])
    def test_valid_boundary_types(self, boundary_type):
        """所有合法边界类型都能正确映射"""
        mock_llm = MagicMock()
        is_boundary = boundary_type != "NONE"
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content=f'{{"is_boundary": {str(is_boundary).lower()}, "confidence": 0.9, "topic_summary": "测试", "boundary_type": "{boundary_type}"}}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "测试映射"},
        ])

        assert result.boundary_type == boundary_type

    def test_invalid_boundary_type_fallback(self):
        """非法 boundary_type 使用默认值"""
        mock_llm = MagicMock()
        mock_llm.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content='{"is_boundary": true, "confidence": 0.9, "topic_summary": "测试", "boundary_type": "INVALID_TYPE"}'))
        ]

        trigger = SemanticEventTrigger(mock_llm, threshold=0.7)
        result = trigger.evaluate([
            {"role": "user", "content": "测试非法类型"},
        ])

        # 非法类型被修正为 TOPIC_COMPLETE
        assert result.boundary_type in ("TOPIC_COMPLETE", "TOPIC_SWITCH", "TIMEOUT", "NONE")


# ==================== B4-001 补充 ====================

class TestEmptyWindow:
    """空消息窗口的边界行为"""

    def test_empty_messages(self):
        """空列表直接返无边界"""
        mock_llm = MagicMock()
        trigger = SemanticEventTrigger(mock_llm)
        result = trigger.evaluate([])
        assert result.is_boundary is False


# ==================== extract_json 单元测试 ====================

class TestExtractJson:
    """extract_json 工具函数测试（B1-002 容错解析）"""

    def test_normal_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_json_with_code_block(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_generic_code_block(self):
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_json_embedded_in_text(self):
        assert extract_json('这是结果: {"a": 1}，请查看') == {"a": 1}

    def test_invalid_text(self):
        assert extract_json("这不是 JSON") is None

    def test_empty_text(self):
        assert extract_json("") is None