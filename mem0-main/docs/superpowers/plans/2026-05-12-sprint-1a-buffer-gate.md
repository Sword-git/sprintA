# Sprint 1-A: ActiveStreamBuffer + GateController Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the message buffer (ActiveStreamBuffer) and gate controller (GateController) for the Mem0 semantic ingestion pipeline, enabling sliding-window buffering with TTL expiration and trigger-based flush decisions.

**Architecture:** `ActiveStreamBuffer` is a low-level async-safe message buffer with sliding window, TTL expiry, and FIFO eviction. `GateController` wraps it, delegates boundary decisions to an injected `trigger` callable, and implements the `MemoryIngestionGate` ABC. Both classes live in `mem0/memory/buffer_gate.py`.

**Tech Stack:** Python 3.10+, asyncio, pytest + pytest-asyncio, Pydantic (for MemoryNode)

**Dependencies:** A2-001 depends on B1-001 (SemanticEventTrigger). GateController accepts trigger as a callable via DI, so it composes with any trigger later.

---

### Task 1: ActiveStreamBuffer — append, get_window, size, FIFO eviction (A1-001 core)

**Files:**
- Create: `mem0/memory/buffer_gate.py`
- Modify: `mem0/tests/test_buffer.py`

- [ ] **Step 1: Write failing test for append + get_window + size**

```python
"""Tests for ActiveStreamBuffer — 消息缓冲区。"""
import asyncio
import time
import pytest
from mem0.memory.buffer_gate import ActiveStreamBuffer


def test_append_and_get_window():
    """append 追加消息，get_window 返回全部消息，含 _received_at 和 _seq。"""
    buf = ActiveStreamBuffer(window_size=10)
    asyncio.run(buf.append({"role": "user", "content": "hello"}))
    asyncio.run(buf.append({"role": "assistant", "content": "hi"}))

    window = buf.get_window()
    assert len(window) == 2
    assert window[0]["role"] == "user"
    assert window[0]["content"] == "hello"
    assert "_received_at" in window[0]
    assert "_seq" in window[0]
    assert window[1]["role"] == "assistant"
    assert window[1]["_seq"] == 1
    assert buf.size() == 2


def test_fifo_eviction_on_full_window():
    """满窗口时新消息挤入，最旧消息移出。"""
    buf = ActiveStreamBuffer(window_size=3)

    async def fill():
        for i in range(5):
            await buf.append({"role": "user", "content": f"msg{i}"})

    asyncio.run(fill())
    assert buf.size() == 3
    window = buf.get_window()
    assert window[0]["content"] == "msg2"
    assert window[1]["content"] == "msg3"
    assert window[2]["content"] == "msg4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_append_and_get_window mem0/tests/test_buffer.py::test_fifo_eviction_on_full_window -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mem0.memory.buffer_gate'`

- [ ] **Step 3: Write minimal ActiveStreamBuffer implementation**

```python
"""ActiveStreamBuffer + GateController — 消息缓冲区与闸门控制。

Sprint 1-A: 滑动窗口缓冲区 + TTL 过期 + 闸门触发判定。
"""
import asyncio
import time
from typing import Dict, List, Optional


class ActiveStreamBuffer:
    """消息缓冲区 —— 支持滑动窗口、TTL 过期清理、FIFO 挤出。

    对齐 Mem0 原生消息格式：{"role": str, "content": str}
    内部附加 _received_at (float timestamp) 和 _seq (int) 字段。
    """

    def __init__(self, window_size: int = 100, ttl_seconds: Optional[float] = None):
        self._messages: List[Dict] = []
        self._window_size = window_size
        self._ttl_seconds = ttl_seconds
        self._seq = 0
        self._lock = asyncio.Lock()

    async def append(self, message: Dict[str, str]) -> None:
        """追加消息到缓冲区，自动附加 _received_at 和 _seq。

        Args:
            message: 格式 {"role": str, "content": str}，对齐 Mem0.add() 的 messages 参数。
        """
        async with self._lock:
            enriched = {
                "role": message["role"],
                "content": message["content"],
                "_received_at": time.time(),
                "_seq": self._seq,
            }
            self._seq += 1
            self._messages.append(enriched)
            while len(self._messages) > self._window_size:
                self._messages.pop(0)
            if self._ttl_seconds is not None:
                self._cleanup_expired_locked()

    def get_window(self) -> List[Dict]:
        """返回当前窗口内全部消息的副本。"""
        return list(self._messages)

    def size(self) -> int:
        """返回当前缓冲区消息数量。"""
        return len(self._messages)

    def _cleanup_expired_locked(self) -> int:
        """内部方法：在持有锁的情况下剔除过期消息，返回剔除数量。"""
        if self._ttl_seconds is None:
            return 0
        before = len(self._messages)
        now = time.time()
        self._messages = [
            m for m in self._messages
            if (now - m["_received_at"]) <= self._ttl_seconds
        ]
        return before - len(self._messages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_append_and_get_window mem0/tests/test_buffer.py::test_fifo_eviction_on_full_window -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write failing test for slide()**

```python
def test_slide_pops_oldest_messages():
    """slide(count) 弹出指定数量的最旧消息。"""
    buf = ActiveStreamBuffer(window_size=10)

    async def fill():
        for i in range(5):
            await buf.append({"role": "user", "content": f"msg{i}"})

    asyncio.run(fill())
    removed = asyncio.run(buf.slide(3))
    assert len(removed) == 3
    assert removed[0]["content"] == "msg0"
    assert removed[1]["content"] == "msg1"
    assert removed[2]["content"] == "msg2"
    assert buf.size() == 2
    assert buf.get_window()[0]["content"] == "msg3"


def test_slide_count_exceeds_buffer():
    """slide 数量超过缓冲区大小时只弹出实际数量。"""
    buf = ActiveStreamBuffer(window_size=10)

    async def fill():
        await buf.append({"role": "user", "content": "a"})

    asyncio.run(fill())
    removed = asyncio.run(buf.slide(10))
    assert len(removed) == 1
    assert buf.size() == 0
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_slide_pops_oldest_messages mem0/tests/test_buffer.py::test_slide_count_exceeds_buffer -v`
Expected: FAIL with `AttributeError: 'ActiveStreamBuffer' object has no attribute 'slide'`

- [ ] **Step 7: Implement slide()**

Add to `ActiveStreamBuffer` in `buffer_gate.py`:

```python
    async def slide(self, count: int) -> List[Dict]:
        """弹出指定数量的最旧消息并返回。

        Args:
            count: 要弹出的消息数量。若超过缓冲区大小，则弹出全部。

        Returns:
            被弹出的消息列表（按从旧到新排列）。
        """
        async with self._lock:
            count = min(count, len(self._messages))
            removed = self._messages[:count]
            self._messages = self._messages[count:]
            return removed
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_slide_pops_oldest_messages mem0/tests/test_buffer.py::test_slide_count_exceeds_buffer -v`
Expected: PASS

- [ ] **Step 9: Write failing test for concurrent safety**

```python
def test_concurrent_safety():
    """并发写入安全性验证 —— 多协程同时 append 不会丢失或损坏消息。"""
    buf = ActiveStreamBuffer(window_size=200)

    async def writer(start: int, n: int):
        for i in range(start, start + n):
            await buf.append({"role": "user", "content": f"msg{i}"})

    async def run():
        tasks = [
            writer(0, 50),
            writer(50, 50),
            writer(100, 50),
            writer(150, 50),
        ]
        await asyncio.gather(*tasks)

    asyncio.run(run())
    assert buf.size() == 200
    seqs = [m["_seq"] for m in buf.get_window()]
    assert sorted(seqs) == list(range(200))
```

- [ ] **Step 10: Run test to verify concurrent safety**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_concurrent_safety -v`
Expected: PASS

---

### Task 2: TTL 过期清理 (A1-002)

**Files:**
- Modify: `mem0/memory/buffer_gate.py`
- Modify: `mem0/tests/test_buffer.py`

- [ ] **Step 1: Write failing test for is_expired**

```python
def test_is_expired():
    """is_expired 基于 _received_at + ttl_seconds 正确判断过期。"""
    buf = ActiveStreamBuffer(ttl_seconds=1.0)
    now = time.time()
    assert buf.is_expired({"_received_at": now - 2.0}) is True
    assert buf.is_expired({"_received_at": now - 0.5}) is False
    assert buf.is_expired({"_received_at": now}) is False


def test_is_expired_no_ttl():
    """无 TTL 时 is_expired 永远返回 False。"""
    buf = ActiveStreamBuffer(ttl_seconds=None)
    assert buf.is_expired({"_received_at": time.time() - 99999}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_is_expired mem0/tests/test_buffer.py::test_is_expired_no_ttl -v`
Expected: FAIL with `AttributeError: 'ActiveStreamBuffer' object has no attribute 'is_expired'`

- [ ] **Step 3: Implement is_expired()**

Add to `ActiveStreamBuffer` in `buffer_gate.py`:

```python
    def is_expired(self, message: Dict) -> bool:
        """判断单条消息是否已过期。

        Args:
            message: 含 _received_at 字段的消息字典。

        Returns:
            True 如果消息已超过 TTL 存活时间。
        """
        if self._ttl_seconds is None:
            return False
        return (time.time() - message["_received_at"]) > self._ttl_seconds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_is_expired mem0/tests/test_buffer.py::test_is_expired_no_ttl -v`
Expected: PASS

- [ ] **Step 5: Write failing test for cleanup_expired**

```python
def test_cleanup_expired():
    """cleanup_expired 批量剔除过期消息并返回剔除数量。"""
    buf = ActiveStreamBuffer(ttl_seconds=0.5)

    async def add_expired():
        # Manually insert an expired message
        buf._messages.append({
            "role": "user", "content": "old",
            "_received_at": time.time() - 10.0,
            "_seq": 0,
        })
        # Add fresh messages
        for i in range(3):
            await buf.append({"role": "user", "content": f"fresh{i}"})

    asyncio.run(add_expired())
    assert buf.size() == 4
    removed = asyncio.run(buf.cleanup_expired())
    assert removed == 1
    assert buf.size() == 3
    for m in buf.get_window():
        assert m["content"] != "old"


def test_cleanup_expired_no_ttl():
    """无 TTL 时 cleanup_expired 返回 0。"""
    buf = ActiveStreamBuffer(ttl_seconds=None)

    async def add():
        await buf.append({"role": "user", "content": "a"})

    asyncio.run(add())
    removed = asyncio.run(buf.cleanup_expired())
    assert removed == 0
    assert buf.size() == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_cleanup_expired mem0/tests/test_buffer.py::test_cleanup_expired_no_ttl -v`
Expected: FAIL with `AttributeError: 'ActiveStreamBuffer' object has no attribute 'cleanup_expired'`

- [ ] **Step 7: Implement cleanup_expired()**

Add to `ActiveStreamBuffer` in `buffer_gate.py`:

```python
    async def cleanup_expired(self) -> int:
        """批量剔除过期消息，返回剔除数量。"""
        async with self._lock:
            return self._cleanup_expired_locked()
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_cleanup_expired mem0/tests/test_buffer.py::test_cleanup_expired_no_ttl -v`
Expected: PASS

- [ ] **Step 9: Write test for auto-cleanup on append**

```python
def test_ttl_auto_cleanup_on_append():
    """每次 append 自动触发过期扫描。"""
    buf = ActiveStreamBuffer(window_size=10, ttl_seconds=0.1)

    async def add_and_wait():
        await buf.append({"role": "user", "content": "will_expire"})
        # Wait for TTL to expire
        await asyncio.sleep(0.2)
        # This append should trigger cleanup of the first message
        await buf.append({"role": "user", "content": "fresh"})

    asyncio.run(add_and_wait())
    assert buf.size() == 1
    assert buf.get_window()[0]["content"] == "fresh"
```

- [ ] **Step 10: Run test to verify auto-cleanup passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_ttl_auto_cleanup_on_append -v`
Expected: PASS (auto-cleanup already implemented in Step 1 append)

---

### Task 3: 边界条件处理 (A1-003)

**Files:**
- Modify: `mem0/memory/buffer_gate.py`
- Modify: `mem0/tests/test_buffer.py`

- [ ] **Step 1: Write failing test for clear()**

```python
def test_clear():
    """clear() 返回全部消息且缓冲区归零。"""
    buf = ActiveStreamBuffer(window_size=10)

    async def add():
        for i in range(3):
            await buf.append({"role": "user", "content": f"msg{i}"})

    asyncio.run(add())
    assert buf.size() == 3
    removed = asyncio.run(buf.clear())
    assert len(removed) == 3
    assert removed[0]["content"] == "msg0"
    assert buf.size() == 0
    assert buf.get_window() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_clear -v`
Expected: FAIL with `AttributeError: 'ActiveStreamBuffer' object has no attribute 'clear'`

- [ ] **Step 3: Implement clear()**

Add to `ActiveStreamBuffer` in `buffer_gate.py`:

```python
    async def clear(self) -> List[Dict]:
        """清空缓冲区并返回全部消息。"""
        async with self._lock:
            removed = list(self._messages)
            self._messages.clear()
            self._seq = 0
            return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_clear -v`
Expected: PASS

- [ ] **Step 5: Write test for empty buffer edge cases**

```python
def test_empty_buffer():
    """空缓冲区边界条件 —— 所有操作不报错。"""
    buf = ActiveStreamBuffer(window_size=10)
    assert buf.size() == 0
    assert buf.get_window() == []
    removed = asyncio.run(buf.slide(5))
    assert removed == []
    removed = asyncio.run(buf.clear())
    assert removed == []
    removed = asyncio.run(buf.cleanup_expired())
    assert removed == 0
    assert buf.is_expired({"_received_at": time.time()}) is False
```

- [ ] **Step 6: Run test to verify empty buffer passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py::test_empty_buffer -v`
Expected: PASS

- [ ] **Step 7: Run all buffer tests to verify complete**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py -v`
Expected: PASS (all 10 tests)

---

### Task 4: GateController 核心逻辑 (A2-001)

**Files:**
- Modify: `mem0/memory/buffer_gate.py`
- Modify: `mem0/tests/test_gate.py`
- Reference: `mem0/ingestion_gate/gate_controller.py` (MemoryIngestionGate ABC)
- Reference: `mem0/ingestion_gate/memory_node.py` (TriggerResult, BoundaryType, MemoryNode)

- [ ] **Step 1: Write failing test — trigger returns True → process returns True**

```python
"""Tests for GateController — 闸门控制。"""
import asyncio
import pytest
from mem0.memory.buffer_gate import ActiveStreamBuffer, GateController
from mem0.ingestion_gate import BoundaryType, TriggerResult


def test_process_returns_true_triggers_flush():
    """trigger 返回 is_boundary=True 时 process 返回 True。"""
    buf = ActiveStreamBuffer(window_size=10)

    def always_trigger(messages):
        return TriggerResult(
            is_boundary=True,
            confidence=0.9,
            topic_summary="test topic",
            boundary_type=BoundaryType.TOPIC_COMPLETE,
        )

    gate = GateController(buffer=buf, trigger=always_trigger)
    result = asyncio.run(
        gate.process({"role": "user", "content": "hello"})
    )
    assert result is True
    assert buf.size() == 1  # message appended before trigger check


def test_process_returns_false_accumulates():
    """trigger 返回 is_boundary=False 时消息仅累积，process 返回 False。"""
    buf = ActiveStreamBuffer(window_size=10)

    def never_trigger(messages):
        return TriggerResult(
            is_boundary=False,
            confidence=0.1,
            topic_summary="",
            boundary_type="none",
        )

    gate = GateController(buffer=buf, trigger=never_trigger)
    result = asyncio.run(
        gate.process({"role": "user", "content": "msg1"})
    )
    assert result is False
    asyncio.run(gate.process({"role": "user", "content": "msg2"}))
    assert buf.size() == 2  # messages accumulate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py::test_process_returns_true_triggers_flush mem0/tests/test_gate.py::test_process_returns_false_accumulates -v`
Expected: FAIL with `ImportError: cannot import name 'GateController'`

- [ ] **Step 3: Implement GateController**

Add to `buffer_gate.py` after `ActiveStreamBuffer`:

```python
import time as _time_module  # already imported at top

from mem0.ingestion_gate import BoundaryType, MemoryNode, TriggerResult


class GateController:
    """闸门控制器 —— 追加消息 → 调用 trigger 判定 → 返回 is_boundary。

    实现 MemoryIngestionGate 抽象接口。
    """

    def __init__(self, *, buffer: ActiveStreamBuffer, trigger, timeout_seconds: Optional[float] = None):
        self._buffer = buffer
        self._trigger = trigger
        self._timeout_seconds = timeout_seconds
        self._last_boundary_type: Optional[str] = None
        self._is_flushed = False
        self._last_message_time: Optional[float] = None

    async def process(
        self,
        message: Dict[str, str],
        *,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """处理单条消息：追加到缓冲区 → 调用语义判定 → 返回是否触发 flush。

        Args:
            message: 格式 {"role": str, "content": str}
            user_id: 用户标识（预留，对齐 Mem0.add()）
            agent_id: Agent 标识（预留，对齐 Mem0.add()）
            run_id: 运行标识（预留，对齐 Mem0.add()）
            metadata: 扩展元数据（预留）

        Returns:
            True = trigger 判定为边界，应执行 flush
            False = 继续累积
        """
        await self._buffer.append(message)
        self._last_message_time = time.time()

        window = self._buffer.get_window()
        result = self._trigger(window)

        if result.is_boundary:
            self._last_boundary_type = result.boundary_type
            return True
        return False

    def check_timeout(self) -> bool:
        """检查距最后一条消息的时间是否已超过 timeout_seconds。

        Returns:
            True 如果超时到期。
        """
        if self._timeout_seconds is None or self._last_message_time is None:
            return False
        return (time.time() - self._last_message_time) > self._timeout_seconds

    def force_flush(self) -> List:
        """强制刷写，无论 trigger 判定结果如何。

        Returns:
            MemoryNode 列表，含当前缓冲区全部消息。
        """
        self._last_boundary_type = BoundaryType.FORCE
        return self.flush()

    def flush(self) -> List:
        """导出当前缓冲区全部消息为 MemoryNode 并清空缓冲区。

        Returns:
            话题级记忆节点列表。
        """
        messages = self._buffer.get_window()
        if not messages:
            return []
        # sync clear — flush is called from sync context, internal clear is safe
        self._buffer._messages.clear()
        self._buffer._seq = 0
        self._is_flushed = True

        node = MemoryNode(
            topic_summary=self._last_boundary_type or "flush",
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            boundary_type=BoundaryType(self._last_boundary_type) if self._last_boundary_type in [e.value for e in BoundaryType] else BoundaryType.FORCE,
            confidence=1.0,
        )
        return [node]

    def get_state(self) -> Dict[str, Any]:
        """查询闸门当前状态。

        Returns:
            {"buffer_size", "last_boundary_type", "ttl_remaining", "is_flushed"}
        """
        ttl_remaining = None
        if self._timeout_seconds is not None and self._last_message_time is not None:
            elapsed = time.time() - self._last_message_time
            ttl_remaining = max(0.0, self._timeout_seconds - elapsed)

        return {
            "buffer_size": self._buffer.size(),
            "last_boundary_type": self._last_boundary_type,
            "ttl_remaining": ttl_remaining,
            "is_flushed": self._is_flushed,
        }

    def reset(self) -> None:
        """重置闸门到初始状态。"""
        self._buffer._messages.clear()
        self._buffer._seq = 0
        self._last_boundary_type = None
        self._is_flushed = False
        self._last_message_time = None
```

- [ ] **Step 4: Run test to verify GateController core passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py::test_process_returns_true_triggers_flush mem0/tests/test_gate.py::test_process_returns_false_accumulates -v`
Expected: PASS

- [ ] **Step 5: Write test for continuous process calls**

```python
def test_continuous_calls():
    """连续 process 调用后 buffer 状态正确。"""
    buf = ActiveStreamBuffer(window_size=5)
    trigger_count = [0]

    def trigger_every_3(messages):
        trigger_count[0] += 1
        is_boundary = len(messages) >= 3
        return TriggerResult(
            is_boundary=is_boundary,
            confidence=0.8 if is_boundary else 0.2,
            topic_summary="batch" if is_boundary else "",
            boundary_type=BoundaryType.TOPIC_COMPLETE if is_boundary else "none",
        )

    gate = GateController(buffer=buf, trigger=trigger_every_3)

    async def run():
        results = []
        for i in range(5):
            r = await gate.process({"role": "user", "content": f"msg{i}"})
            results.append(r)
        return results

    results = asyncio.run(run())
    # First 2 should be False (accumulate), 3rd True, 4th False, 5th False
    assert results == [False, False, True, False, False]
    assert buf.size() == 5
```

- [ ] **Step 6: Run test for continuous calls**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py::test_continuous_calls -v`
Expected: PASS

---

### Task 5: GateController 超时强制刷写 + 状态查询 (A2-002)

**Files:**
- Modify: `mem0/memory/buffer_gate.py`
- Modify: `mem0/tests/test_gate.py`

- [ ] **Step 1: Write failing test for timeout force flush**

```python
def test_timeout_force_flush():
    """TTL 到期后 check_timeout 返回 True，force_flush 清空缓冲区。"""
    buf = ActiveStreamBuffer(window_size=10)
    gate = GateController(
        buffer=buf,
        trigger=lambda msgs: TriggerResult(False, 0.0, "", "none"),
        timeout_seconds=0.1,
    )

    async def run():
        await gate.process({"role": "user", "content": "hello"})

    asyncio.run(run())
    assert gate.check_timeout() is False
    # Wait for timeout
    import time as _time
    _time.sleep(0.15)
    assert gate.check_timeout() is True

    nodes = gate.force_flush()
    assert len(nodes) == 1
    assert nodes[0].boundary_type == BoundaryType.FORCE
    assert buf.size() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py::test_timeout_force_flush -v`
Expected: FAIL (GateController already has these methods from Step 1 of Task 4, but let's verify)

Expected: PASS (methods already implemented in Task 4 Step 3)

- [ ] **Step 3: Write test for get_state**

```python
def test_get_state():
    """get_state() 返回正确的状态字典。"""
    buf = ActiveStreamBuffer(window_size=10)

    def trigger(messages):
        return TriggerResult(True, 0.9, "summary", BoundaryType.TOPIC_COMPLETE)

    gate = GateController(buffer=buf, trigger=trigger, timeout_seconds=5.0)

    async def run():
        await gate.process({"role": "user", "content": "msg"})

    asyncio.run(run())

    state = gate.get_state()
    assert state["buffer_size"] == 1
    assert state["last_boundary_type"] == BoundaryType.TOPIC_COMPLETE
    assert state["is_flushed"] is False
    assert isinstance(state["ttl_remaining"], float)
    assert state["ttl_remaining"] <= 5.0
```

- [ ] **Step 4: Run test to verify get_state passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py::test_get_state -v`
Expected: PASS

- [ ] **Step 5: Write test for reset**

```python
def test_reset():
    """reset() 后闸门回到初始状态。"""
    buf = ActiveStreamBuffer(window_size=10)
    gate = GateController(
        buffer=buf,
        trigger=lambda msgs: TriggerResult(False, 0.0, "", "none"),
    )

    async def run():
        await gate.process({"role": "user", "content": "msg"})

    asyncio.run(run())
    assert buf.size() == 1

    gate.reset()
    assert buf.size() == 0
    state = gate.get_state()
    assert state["buffer_size"] == 0
    assert state["last_boundary_type"] is None
    assert state["is_flushed"] is False
```

- [ ] **Step 6: Run test to verify reset passes**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py::test_reset -v`
Expected: PASS

- [ ] **Step 7: Run all gate tests to verify complete**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_gate.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Run full Sprint 1-A test suite**

Run: `cd "g:\ai agent\first-team-main\first-team-main\mem0-main" && python -m pytest mem0/tests/test_buffer.py mem0/tests/test_gate.py -v`
Expected: PASS (16 tests)
