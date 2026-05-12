"""Tests for memory_node.py — Pydantic data contracts."""


def test_boundary_type_values():
    """BoundaryType 枚举包含全部 4 种类型。"""
    from mem0.ingestion_gate import BoundaryType
    assert len(list(BoundaryType)) == 4
    assert BoundaryType.TOPIC_COMPLETE.value == "topic_complete"
    assert BoundaryType.TIMEOUT.value == "timeout"


def test_memory_node_creation():
    """MemoryNode 可正常创建。"""
    from mem0.ingestion_gate import BoundaryType, MemoryNode
    node = MemoryNode(
        topic_summary="测试",
        messages=[{"role": "user", "content": "hello"}],
        boundary_type=BoundaryType.TOPIC_COMPLETE,
        confidence=0.9,
    )
    assert node.topic_summary == "测试"
    assert node.confidence == 0.9


def test_memory_node_confidence_validation():
    """confidence 超出范围应触发 ValidationError。"""
    import pytest
    from mem0.ingestion_gate import BoundaryType, MemoryNode
    with pytest.raises(Exception):  # ValidationError
        MemoryNode(
            topic_summary="t",
            messages=[],
            boundary_type=BoundaryType.FORCE,
            confidence=1.5,
        )


def test_memory_retrieved_event():
    """MemoryRetrievedEvent 可正常创建并包含检索节点。"""
    from mem0.ingestion_gate import BoundaryType, MemoryNode, MemoryRetrievedEvent
    node = MemoryNode(
        topic_summary="test",
        messages=[],
        boundary_type=BoundaryType.FORCE,
        confidence=1.0,
    )
    ev = MemoryRetrievedEvent(
        query="query",
        retrieved_nodes=[node],
        context_window=[{"role": "user", "content": "q"}],
    )
    assert len(ev.retrieved_nodes) == 1
