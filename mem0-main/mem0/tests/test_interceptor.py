"""Tests for Mem0Interceptor — 拦截器测试（Sprint 2-B）。

测试覆盖：
- B5-001: install/uninstall 行为
- B5-002: 端到端链路 + infer=False 路径
- B6-001: 多轮 add() 一致性
"""

import pytest
from unittest.mock import MagicMock, patch

from mem0.mem0_interceptor import Mem0Interceptor, InterceptedMemory


# ==================== B5-001 ====================

class TestInterceptorInstallUninstall:
    """Mem0Interceptor 安装/卸载测试"""

    def test_install_returns_intercepted_memory(self):
        """install() 返回 InterceptedMemory 实例"""
        mock_gate = MagicMock()
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        result = interceptor.install(mock_memory)

        assert isinstance(result, InterceptedMemory)

    def test_uninstall_returns_original_memory(self):
        """uninstall() 返回原始 Memory 实例"""
        mock_gate = MagicMock()
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        interceptor.install(mock_memory)
        original = interceptor.uninstall()

        assert original is mock_memory

    def test_uninstall_before_install(self):
        """未安装时卸载返回 None"""
        mock_gate = MagicMock()
        interceptor = Mem0Interceptor(mock_gate)
        result = interceptor.uninstall()

        assert result is None


# ==================== B5-002 ====================

class TestEndToEndInferFalse:
    """端到端链路 + infer=False 路径"""

    def test_infer_false_bypasses_gate(self):
        """infer=False 时绕过闸门直接调用原始 add()"""
        mock_gate = MagicMock()
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        intercepted = interceptor.install(mock_memory)

        messages = [{"role": "user", "content": "直接保存"}]
        intercepted.add(messages, user_id="u1", infer=False)

        # 原始 add 被调用，闸门 process_message 未被调用
        mock_memory.add.assert_called_once()
        mock_gate.process_message.assert_not_called()

    def test_infer_true_calls_gate(self):
        """infer=True 时消息进入闸门"""
        mock_gate = MagicMock()
        mock_gate.process_message.return_value = False  # 不触发 flush
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        intercepted = interceptor.install(mock_memory)

        messages = [{"role": "user", "content": "今天天气怎么样？"}]
        intercepted.add(messages, user_id="u1", infer=True)

        # 闸门被调用，原始 add 未被调用（因为未触发 flush）
        mock_gate.process_message.assert_called_once()
        mock_memory.add.assert_not_called()

    def test_boundary_flush_triggers_add(self):
        """process_message 返回 True 时触发 flush + add"""
        mock_gate = MagicMock()
        mock_gate.process_message.return_value = True  # 触发 flush
        mock_gate.flush.return_value = [
            MagicMock(
                messages=[{"role": "user", "content": "聊完了"}],
                topic_summary="天气",
                boundary_type="TOPIC_COMPLETE",
            )
        ]
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        intercepted = interceptor.install(mock_memory)

        messages = [{"role": "user", "content": "好的，再见"}]
        intercepted.add(messages, user_id="u1", infer=True)

        # flush 被调用，原始 add 被调用一次
        mock_gate.flush.assert_called_once()
        mock_memory.add.assert_called_once()


# ==================== B6-001 ====================

class TestMultipleAddConsistency:
    """多轮 add() 调用一致性"""

    def test_three_rounds_no_residual(self):
        """3 轮完整话题循环后状态一致"""
        mock_gate = MagicMock()
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        intercepted = interceptor.install(mock_memory)

        # 第 1 轮：不触发 flush
        mock_gate.process_message.return_value = False
        intercepted.add([{"role": "user", "content": "话题1-A"}], user_id="u1", infer=True)

        # 第 1 轮：触发 flush
        mock_gate.process_message.return_value = True
        mock_gate.flush.return_value = [
            MagicMock(messages=[{"role": "user", "content": "话题1结束"}], topic_summary="话题1", boundary_type="TOPIC_COMPLETE")
        ]
        intercepted.add([{"role": "user", "content": "话题1-B"}], user_id="u1", infer=True)

        # 第 2 轮：不触发 flush
        mock_gate.process_message.return_value = False
        intercepted.add([{"role": "user", "content": "话题2-A"}], user_id="u1", infer=True)

        # 第 2 轮：触发 flush
        mock_gate.process_message.return_value = True
        mock_gate.flush.return_value = [
            MagicMock(messages=[{"role": "user", "content": "话题2结束"}], topic_summary="话题2", boundary_type="TOPIC_COMPLETE")
        ]
        intercepted.add([{"role": "user", "content": "话题2-B"}], user_id="u1", infer=True)

        # 第 3 轮：触发 flush
        mock_gate.process_message.return_value = True
        mock_gate.flush.return_value = [
            MagicMock(messages=[{"role": "user", "content": "话题3"}], topic_summary="话题3", boundary_type="TOPIC_COMPLETE")
        ]
        intercepted.add([{"role": "user", "content": "话题3"}], user_id="u1", infer=True)

        # flush 被调用 3 次（每次边界触发一次）
        assert mock_gate.flush.call_count == 3
        # 原始 add 被调用 3 次（对应 3 次 flush）
        assert mock_memory.add.call_count == 3

    def test_dict_message_normalized(self):
        """dict 格式的 messages 也能正确处理"""
        mock_gate = MagicMock()
        mock_gate.process_message.return_value = False
        mock_memory = MagicMock()
        mock_memory.config = MagicMock()

        interceptor = Mem0Interceptor(mock_gate)
        intercepted = interceptor.install(mock_memory)

        intercepted.add({"role": "user", "content": "单条消息"}, user_id="u1", infer=True)

        mock_gate.process_message.assert_called_once()