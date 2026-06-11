import sys
import os
sys.path.insert(0, os.path.dirname(__file__) + "/..")
import asyncio

print("Test 1: Import streams module...")
from app.streams import InMemoryStream, RedisStreamManager, parse_stream_message
print("  OK")

print("Test 2: InMemoryStream basic operations...")
async def test_in_memory():
    stream = InMemoryStream()
    
    msg_id = await stream.xadd("test_stream", {"key": "value"})
    print(f"  xadd OK: {msg_id}")
    
    await stream.xgroup_create("test_stream", "test_group", mkstream=True)
    print(f"  xgroup_create OK")
    
    for i in range(5):
        await stream.xadd("test_stream", {"data": f"msg_{i}"})
    
    messages = await stream.xreadgroup(
        "test_group", "consumer1", {"test_stream": ">"}, count=3
    )
    print(f"  xreadgroup OK: {len(messages[0][1])} messages")
    
    msg_id = messages[0][1][0][0]
    result = await stream.xack("test_stream", "test_group", msg_id)
    print(f"  xack OK: {result}")

asyncio.run(test_in_memory())
print("  All passed")

print("Test 3: parse_stream_message...")
import json
test_msg = ("123-0", {"type": "test", "data": json.dumps({"x": 1})})
parsed = parse_stream_message(test_msg)
assert parsed["_id"] == "123-0"
assert parsed["type"] == "test"
assert parsed["data"]["x"] == 1
print("  OK")

print("\nAll streams tests passed!")
