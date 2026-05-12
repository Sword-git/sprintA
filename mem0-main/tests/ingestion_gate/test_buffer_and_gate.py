"""Sprint 2-A: Buffer + GateController tests.

A3-001: Sliding window + TTL expiry
A3-002: Concurrency safety
A4-001: GateController decision paths
A4-002: GateController consecutive calls + reset
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time

from mem0.memory_buffer import ActiveStreamBuffer
from mem0.gate_controller import GateController
from mem0.ingestion_gate.gate_controller import MemoryIngestionGate, TriggerResult
from mem0.ingestion_gate.memory_node import MemoryNode, BoundaryType


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def buffer():
    """Fresh buffer with default window=15, ttl=300."""
    return ActiveStreamBuffer(max_window_size=15, ttl_seconds=300)


@pytest.fixture
def large_buffer():
    """Buffer sized to hold 100 messages for concurrency testing."""
    return ActiveStreamBuffer(max_window_size=100, ttl_seconds=300)


@pytest.fixture
def mock_trigger():
    """A mock semantic trigger whose evaluate() return value can be configured per-test."""
    trigger = MagicMock()
    trigger.evaluate.return_value = TriggerResult(
        is_boundary=False,
        confidence=0.0,
        topic_summary="",
        boundary_type="none",
    )
    return trigger


def make_message(role="user", content="test message"):
    return {"role": role, "content": content}


# ═══════════════════════════════════════════════════════════════════════════════
# A3-001: Sliding Window + TTL Expiry
# ═══════════════════════════════════════════════════════════════════════════════

class TestWindowSliding:
    """A3-001-1: Window sliding — 15 messages then 16th pushes 1st out."""

    @pytest.mark.asyncio
    async def test_15_messages_all_kept(self, buffer):
        """After 15 messages, all 15 remain in window."""
        for i in range(15):
            await buffer.append(make_message(content=f"msg-{i}"))

        assert buffer.size() == 15

    @pytest.mark.asyncio
    async def test_16th_pushes_1st_out(self, buffer):
        """16th message slides window: size stays 15, 1st removed, 16th present."""
        for i in range(16):
            await buffer.append(make_message(content=f"msg-{i}"))

        assert buffer.size() == 15

        window = buffer.get_window()
        contents = [m["content"] for m in window]

        assert "msg-0" not in contents, "1st message should be evicted"
        assert "msg-15" in contents, "16th message should be present"

    @pytest.mark.asyncio
    async def test_slide_method_removes_oldest(self, buffer):
        """slide() pops N oldest messages and returns them."""
        for i in range(10):
            await buffer.append(make_message(content=f"msg-{i}"))

        popped = buffer.slide(3)

        assert len(popped) == 3
        assert popped[0]["content"] == "msg-0"
        assert popped[1]["content"] == "msg-1"
        assert popped[2]["content"] == "msg-2"
        assert buffer.size() == 7

    @pytest.mark.asyncio
    async def test_get_window_excludes_internal_fields(self, buffer):
        """get_window() returns only role + content, not _received_at or _seq."""
        await buffer.append(make_message(content="hello"))

        window = buffer.get_window()

        assert len(window) == 1
        assert window[0] == {"role": "user", "content": "hello"}
        assert "_received_at" not in window[0]
        assert "_seq" not in window[0]

    @pytest.mark.asyncio
    async def test_fifo_ordering_preserved(self, buffer):
        """Messages maintain FIFO order after multiple appends."""
        for i in range(20):
            await buffer.append(make_message(content=f"msg-{i}"))

        window = buffer.get_window()
        contents = [m["content"] for m in window]

        # window should contain msg-5 through msg-19 (15 most recent)
        expected = [f"msg-{i}" for i in range(5, 20)]
        assert contents == expected
        assert len(contents) == 15


class TestTTLExpiry:
    """A3-001-2: TTL — expired messages auto-removed; non-expired retained."""

    @pytest.mark.asyncio
    async def test_expired_messages_auto_removed_on_append(self, buffer):
        """When a new message triggers cleanup, expired messages are removed."""
        with patch.object(buffer, "_cleanup_expired_sync") as mock_cleanup:
            await buffer.append(make_message())
            assert mock_cleanup.called

    @pytest.mark.asyncio
    async def test_expired_messages_removed_non_expired_kept(self, buffer):
        """Messages past TTL are removed; those within TTL stay."""
        with freeze_time("2026-05-12 10:00:00") as frozen:
            for i in range(5):
                await buffer.append(make_message(content=f"fresh-{i}"))
            assert buffer.size() == 5

            # Advance past TTL: all 5 become expired
            frozen.move_to("2026-05-12 10:06:00")  # +6 minutes > 300s TTL

            await buffer.append(make_message(content="trigger-cleanup"))

            # Only the just-appended message remains
            assert buffer.size() == 1
            window = buffer.get_window()
            assert window[0]["content"] == "trigger-cleanup"

    @pytest.mark.asyncio
    async def test_partial_expiry_mixed_window(self, buffer):
        """Only messages past TTL are evicted; recent ones survive."""
        with freeze_time("2026-05-12 10:00:00") as frozen:
            for i in range(3):
                await buffer.append(make_message(content=f"old-{i}"))

            # +100s: insert 2 more
            frozen.move_to("2026-05-12 10:01:40")
            for i in range(2):
                await buffer.append(make_message(content=f"mid-{i}"))
            assert buffer.size() == 5

            # +301s from start: old-* expired (>300s), mid-* at 201s still fresh
            frozen.move_to("2026-05-12 10:05:01")
            await buffer.append(make_message(content="trigger"))

            window = buffer.get_window()
            contents = [m["content"] for m in window]

            assert "trigger" in contents
            assert "mid-0" in contents
            assert "mid-1" in contents
            assert "old-0" not in contents
            assert "old-1" not in contents
            assert "old-2" not in contents

    @pytest.mark.asyncio
    async def test_is_expired_returns_true_for_expired(self, buffer):
        """is_expired() returns True when TTL exceeded."""
        with freeze_time("2026-05-12 10:06:00"):
            msg = {"role": "user", "content": "old", "_received_at": datetime(2026, 5, 12, 10, 0, 0).timestamp()}
            assert buffer.is_expired(msg) is True

    @pytest.mark.asyncio
    async def test_is_expired_returns_false_for_fresh(self, buffer):
        """is_expired() returns False when within TTL."""
        with freeze_time("2026-05-12 10:02:00"):
            msg = {"role": "user", "content": "fresh", "_received_at": datetime(2026, 5, 12, 10, 0, 0).timestamp()}
            assert buffer.is_expired(msg) is False

    @pytest.mark.asyncio
    async def test_is_expired_missing_received_at(self, buffer):
        """is_expired() returns True for messages without _received_at."""
        with freeze_time("2026-05-12 10:00:00"):
            msg = {"role": "user", "content": "no timestamp"}
            assert buffer.is_expired(msg) is True

    @pytest.mark.asyncio
    async def test_cleanup_expired_returns_removed_count(self, buffer):
        """cleanup_expired() returns the number of messages removed."""
        with freeze_time("2026-05-12 10:00:00") as frozen:
            for i in range(5):
                await buffer.append(make_message(content=f"msg-{i}"))

            frozen.move_to("2026-05-12 10:06:00")  # past TTL

            removed = buffer.cleanup_expired()
            assert removed == 5
            assert buffer.size() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# A3-002: Concurrency Safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrencySafety:
    """A3-002: 100 concurrent writes — no data loss or duplicates."""

    @pytest.mark.asyncio
    async def test_100_concurrent_writes_size_equals_100(self, large_buffer):
        """100 concurrent appends → size() == 100, no data loss."""
        async def append_one(i: int):
            await large_buffer.append(make_message(content=f"concurrent-msg-{i}"))

        tasks = [append_one(i) for i in range(100)]
        await asyncio.gather(*tasks)

        assert large_buffer.size() == 100

    @pytest.mark.asyncio
    async def test_100_concurrent_writes_no_duplicate_seq(self, large_buffer):
        """Every message must have a unique _seq number."""
        async def append_one(i: int):
            await large_buffer.append(make_message(content=f"concurrent-msg-{i}"))

        tasks = [append_one(i) for i in range(100)]
        await asyncio.gather(*tasks)

        # Access internal buffer to check _seq uniqueness
        seqs = [m["_seq"] for m in large_buffer._buffer]
        assert len(seqs) == len(set(seqs)), "Duplicate _seq values found"
        assert len(seqs) == 100

    @pytest.mark.asyncio
    async def test_100_concurrent_writes_all_contents_present(self, large_buffer):
        """All 100 messages appear in window."""
        async def append_one(i: int):
            await large_buffer.append(make_message(content=f"concurrent-msg-{i}"))

        tasks = [append_one(i) for i in range(100)]
        await asyncio.gather(*tasks)

        window_contents = {m["content"] for m in large_buffer.get_window()}
        expected = {f"concurrent-msg-{i}" for i in range(100)}
        assert window_contents == expected

    @pytest.mark.asyncio
    async def test_concurrent_writes_respect_window_limit(self, buffer):
        """With default window=15, 100 concurrent writes → size() == 15."""
        async def append_one(i: int):
            await buffer.append(make_message(content=f"msg-{i}"))

        tasks = [append_one(i) for i in range(100)]
        await asyncio.gather(*tasks)

        assert buffer.size() == 15, "Window should cap at max_window_size"

    @pytest.mark.asyncio
    async def test_concurrent_writes_fifo_integrity(self, large_buffer):
        """Under concurrent load, _seq ordering reflects insertion order roughly."""
        async def append_one(i: int):
            await large_buffer.append(make_message(content=f"msg-{i}"))

        tasks = [append_one(i) for i in range(100)]
        await asyncio.gather(*tasks)

        seqs = [m["_seq"] for m in large_buffer._buffer]

        # All seq values 0-99 must be present (completeness)
        assert sorted(seqs) == list(range(100)), (
            "All seq numbers 0-99 should be present"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# A4-001: GateController Decision Paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestGateControllerDecisionPaths:
    """A4-001: trigger True → flush; trigger False → accumulate; TTL → force_flush."""

    def test_trigger_true_returns_true(self, buffer, mock_trigger):
        """When trigger.evaluate() returns is_boundary=True, process() returns True."""
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=True,
            confidence=0.95,
            topic_summary="topic complete",
            boundary_type="topic_complete",
        )
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        result = gate.process(make_message(content="final message"))

        assert result is True

    def test_trigger_false_returns_false_accumulates(self, buffer, mock_trigger):
        """When trigger.evaluate() returns is_boundary=False, process() returns False."""
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=False,
            confidence=0.3,
            topic_summary="",
            boundary_type="none",
        )
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        result = gate.process(make_message(content="mid conversation"))

        assert result is False

    def test_process_stores_user_agent_metadata(self, buffer, mock_trigger):
        """process() stores user_id, agent_id, run_id, metadata on the controller."""
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        gate.process(
            make_message(),
            user_id="u1",
            agent_id="a1",
            run_id="r1",
            metadata={"key": "val"},
        )

        assert gate._user_id == "u1"
        assert gate._agent_id == "a1"
        assert gate._run_id == "r1"
        assert gate._metadata == {"key": "val"}

    def test_flush_creates_memory_node_with_correct_fields(self, buffer):
        """flush() returns a MemoryNode wrapping all buffered messages."""
        # Pre-fill buffer synchronously via internal append path
        now = time.time()
        for i in range(3):
            buffer._buffer.append({
                "role": "user",
                "content": f"msg-{i}",
                "_received_at": now,
                "_seq": i,
            })

        gate = GateController(buffer=buffer)
        gate._user_id = "u1"
        gate._agent_id = "a1"
        gate._run_id = "r1"
        gate._metadata = {"meta": "data"}
        gate._last_boundary_type = "topic_complete"

        nodes = gate.flush()

        assert len(nodes) == 1
        node = nodes[0]
        assert isinstance(node, MemoryNode)
        assert len(node.messages) == 3
        assert node.user_id == "u1"
        assert node.agent_id == "a1"
        assert node.run_id == "r1"
        assert node.metadata == {"meta": "data"}
        assert node.boundary_type == BoundaryType.TOPIC_COMPLETE

    def test_flush_clears_buffer(self, buffer):
        """After flush(), buffer size is 0 and is_flushed is True."""
        now = time.time()
        for i in range(3):
            buffer._buffer.append({
                "role": "user",
                "content": f"msg-{i}",
                "_received_at": now,
                "_seq": i,
            })

        gate = GateController(buffer=buffer)

        gate.flush()

        assert buffer.size() == 0
        assert gate._is_flushed is True

    def test_ttl_force_flush_when_expired(self, buffer):
        """TTL expiry → force_flush is executed."""
        with freeze_time("2026-05-12 10:00:00") as frozen:
            for i in range(3):
                buffer._buffer.append({
                    "role": "user",
                    "content": f"msg-{i}",
                    "_received_at": time.time(),
                    "_seq": i,
                })

            gate = GateController(buffer=buffer)
            gate._user_id = "u1"
            gate._last_boundary_type = "timeout"

            # Advance past 300s TTL
            frozen.move_to("2026-05-12 10:06:00")

            removed = buffer.cleanup_expired()
            assert removed == 3

            nodes = gate.flush()
            node = nodes[0]
            assert node.boundary_type == BoundaryType.TIMEOUT


# ═══════════════════════════════════════════════════════════════════════════════
# A4-002: GateController Consecutive Calls + Reset
# ═══════════════════════════════════════════════════════════════════════════════

class TestGateControllerConsecutiveAndReset:
    """A4-002: 5 consecutive calls state; reset() restores initial values."""

    def test_five_consecutive_process_calls_state(self, buffer, mock_trigger):
        """5 consecutive process calls → buffer state tracked correctly."""
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=False,
            confidence=0.0,
            topic_summary="",
            boundary_type="none",
        )
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        for i in range(5):
            gate.process(
                make_message(content=f"msg-{i}"),
                user_id="u1",
                agent_id="a1",
            )

        # get_state reflects accumulated metadata from last call
        state = gate.get_state()
        assert state["last_boundary_type"] == "none"
        assert state["is_flushed"] is False

        # Process state values from last call
        assert gate._user_id == "u1"
        assert gate._agent_id == "a1"

    def test_reset_restores_initial_state(self, buffer, mock_trigger):
        """After operations, reset() returns all fields to initial values."""
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=True,
            confidence=0.9,
            topic_summary="done",
            boundary_type="topic_complete",
        )
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        # Perform operations that mutate state
        gate.process(
            make_message(content="hello"),
            user_id="u1",
            agent_id="a1",
            run_id="r1",
            metadata={"k": "v"},
        )
        gate._last_boundary_type = "topic_complete"

        # Pre-fill buffer
        buffer._buffer.append({
            "role": "user", "content": "hello",
            "_received_at": time.time(), "_seq": 0,
        })

        gate.flush()

        assert gate._is_flushed is True
        assert buffer.size() == 0

        # RESET
        gate.reset()

        state = gate.get_state()
        assert state["buffer_size"] == 0
        assert state["last_boundary_type"] == "none"
        assert state["is_flushed"] is False
        assert gate._user_id is None
        assert gate._agent_id is None
        assert gate._run_id is None
        assert gate._metadata is None

    def test_reset_clears_buffer(self, buffer):
        """reset() clears buffer when it contains messages."""
        buffer._buffer.append({
            "role": "user", "content": "persistent",
            "_received_at": time.time(), "_seq": 0,
        })
        gate = GateController(buffer=buffer)

        assert buffer.size() == 1

        gate.reset()

        assert buffer.size() == 0

    def test_get_state_after_reset_matches_initial(self, buffer):
        """get_state() after reset() matches state from fresh GateController."""
        gate = GateController(buffer=buffer)

        # Mutate
        gate._last_boundary_type = "topic_complete"
        gate._is_flushed = True
        gate._user_id = "u1"

        gate.reset()

        # Compare reset state to a new controller
        fresh_gate = GateController(buffer=ActiveStreamBuffer())
        fresh_state = fresh_gate.get_state()
        reset_state = gate.get_state()

        assert reset_state == fresh_state

    def test_get_state_initial_values(self, buffer):
        """Fresh GateController has correct initial get_state() values."""
        gate = GateController(buffer=buffer)

        state = gate.get_state()

        assert state == {
            "buffer_size": 0,
            "last_boundary_type": "none",
            "is_flushed": False,
            "ttl_remaining": 0,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: GateController + ActiveStreamBuffer end-to-end
# ═══════════════════════════════════════════════════════════════════════════════

class TestGateControllerBufferIntegration:
    """End-to-end: GateController orchestrating buffer + trigger + flush."""

    def test_full_lifecycle_accumulate_then_flush(self, buffer, mock_trigger):
        """Full lifecycle: accumulate messages, trigger hits boundary, flush."""
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=True,
            confidence=0.95,
            topic_summary="discussed topic A fully",
            boundary_type="topic_complete",
        )
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        # process with trigger returning True
        result = gate.process(
            make_message(content="last message on topic A"),
            user_id="u1",
            agent_id="a1",
            run_id="r1",
        )

        assert result is True

        # Flush creates node with correct metadata
        nodes = gate.flush()
        assert len(nodes) == 1
        assert nodes[0].user_id == "u1"
        assert nodes[0].boundary_type == BoundaryType.TOPIC_COMPLETE

    def test_process_trigger_false_then_true_sequence(self, buffer, mock_trigger):
        """Accumulate on False, then flush on True."""
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        # First two calls: no boundary
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=False, confidence=0.2,
            topic_summary="", boundary_type="none",
        )
        assert gate.process(make_message(content="msg-1")) is False
        assert gate.process(make_message(content="msg-2")) is False

        # Third call: boundary detected
        mock_trigger.evaluate.return_value = TriggerResult(
            is_boundary=True, confidence=0.9,
            topic_summary="topic ended", boundary_type="topic_complete",
        )
        assert gate.process(make_message(content="msg-3")) is True

    def test_multiple_flush_cycles(self, buffer, mock_trigger):
        """Multiple accumulate→flush cycles produce distinct MemoryNodes."""
        gate = GateController(buffer=buffer, trigger=mock_trigger)

        for cycle in range(3):
            mock_trigger.evaluate.return_value = TriggerResult(
                is_boundary=True,
                confidence=0.9,
                topic_summary=f"topic {cycle}",
                boundary_type="topic_complete",
            )
            gate.process(
                make_message(content=f"cycle-{cycle}"),
                user_id="u1",
                run_id=f"r{cycle}",
            )

            nodes = gate.flush()
            assert len(nodes) == 1
            assert nodes[0].run_id == f"r{cycle}"

            # reset for next cycle (simulating continuation)
            gate._is_flushed = False
