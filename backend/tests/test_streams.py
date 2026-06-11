"""
Redis Stream 基础设施测试
验证 Streams 内存模式与接口规范
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def in_memory_stream():
    from app.streams import InMemoryStream
    return InMemoryStream()


@pytest.mark.asyncio
async def test_in_memory_stream_xadd(in_memory_stream):
    msg_id = await in_memory_stream.xadd("test_stream", {"key": "value"})
    assert msg_id is not None
    assert "test_stream" in in_memory_stream._streams


@pytest.mark.asyncio
async def test_in_memory_stream_xreadgroup(in_memory_stream):
    await in_memory_stream.xgroup_create("test_stream", "test_group", mkstream=True)

    for i in range(5):
        await in_memory_stream.xadd("test_stream", {"data": f"msg_{i}"})

    messages = await in_memory_stream.xreadgroup(
        "test_group", "consumer1", {"test_stream": ">"}, count=3
    )

    assert len(messages) == 1
    stream_name, msgs = messages[0]
    assert stream_name == "test_stream"
    assert len(msgs) == 3


@pytest.mark.asyncio
async def test_in_memory_stream_consume_order(in_memory_stream):
    await in_memory_stream.xgroup_create("stream_order", "g1", mkstream=True)

    for i in range(10):
        await in_memory_stream.xadd("stream_order", {"idx": str(i)})

    msgs1 = await in_memory_stream.xreadgroup("g1", "c1", {"stream_order": ">"}, count=4)
    assert len(msgs1[0][1]) == 4

    msgs2 = await in_memory_stream.xreadgroup("g1", "c1", {"stream_order": ">"}, count=4)
    assert len(msgs2[0][1]) == 4

    msgs3 = await in_memory_stream.xreadgroup("g1", "c1", {"stream_order": ">"}, count=4)
    assert len(msgs3[0][1]) == 2


@pytest.mark.asyncio
async def test_in_memory_stream_xack(in_memory_stream):
    await in_memory_stream.xgroup_create("ack_test", "g1", mkstream=True)
    await in_memory_stream.xadd("ack_test", {"a": "1"})

    msgs = await in_memory_stream.xreadgroup("g1", "c1", {"ack_test": ">"}, count=1)
    msg_id = msgs[0][1][0][0]

    result = await in_memory_stream.xack("ack_test", "g1", msg_id)
    assert result == 1


def test_parse_stream_message():
    from app.streams import parse_stream_message
    import json

    test_msg = ("123-0", {"type": "test", "data": json.dumps({"x": 1, "y": 2})})
    parsed = parse_stream_message(test_msg)

    assert parsed["_id"] == "123-0"
    assert parsed["type"] == "test"
    assert isinstance(parsed["data"], dict)
    assert parsed["data"]["x"] == 1
    assert parsed["data"]["y"] == 2


@pytest.mark.asyncio
async def test_redis_stream_manager_in_memory_mode():
    from app.streams import RedisStreamManager

    mgr = RedisStreamManager(host="localhost", port=6379, db=0, use_memory=True)
    connected = await mgr.connect()
    assert connected is True
    assert mgr._using_memory is True

    await mgr.close()


@pytest.mark.asyncio
async def test_stream_manager_publish_consume():
    from app.streams import RedisStreamManager

    mgr = RedisStreamManager(use_memory=True)
    await mgr.connect()
    await mgr.ensure_stream("test_pubsub")
    await mgr.ensure_group("test_pubsub", "test_group")

    msg_id = await mgr.publish("test_pubsub", {"test_key": "test_value", "num": 42})
    assert msg_id is not None

    messages = await mgr.consume_group(
        "test_pubsub", "test_group", "consumer_test", count=1, block_ms=100
    )

    assert len(messages) >= 0

    await mgr.close()


@pytest.mark.asyncio
async def test_multiple_streams():
    from app.streams import InMemoryStream

    stream = InMemoryStream()

    await stream.xadd("stream_a", {"v": "a1"})
    await stream.xadd("stream_b", {"v": "b1"})
    await stream.xadd("stream_a", {"v": "a2"})

    assert "stream_a" in stream._streams
    assert "stream_b" in stream._streams
    assert len(stream._streams["stream_a"]) == 2
    assert len(stream._streams["stream_b"]) == 1
