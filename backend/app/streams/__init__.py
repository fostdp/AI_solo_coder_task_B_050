"""
Redis Stream 工具类
提供微服务间的异步消息通信
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List, Callable
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis_async
    REDIS_AVAILABLE = True
except ImportError:
    try:
        import aioredis as redis_async
        REDIS_AVAILABLE = True
    except ImportError:
        REDIS_AVAILABLE = False
        logger.warning("redis/aioredis not installed, using in-memory fallback")


class InMemoryStream:
    """内存模拟 Redis Stream，用于无 Redis 环境的降级"""

    def __init__(self):
        self._streams: Dict[str, list] = {}
        self._groups: Dict[str, set] = {}
        self._consumers: Dict[str, Dict[str, int]] = {}
        self._counter = 0
        self._lock = asyncio.Lock()

    async def xadd(self, stream: str, fields: Dict, id: str = "*") -> str:
        async with self._lock:
            self._counter += 1
            msg_id = f"{self._counter}-0" if id == "*" else id
            if stream not in self._streams:
                self._streams[stream] = []
            self._streams[stream].append((msg_id, fields))
            return msg_id

    async def xgroup_create(self, stream: str, group: str, id: str = "0", mkstream: bool = False):
        async with self._lock:
            if mkstream and stream not in self._streams:
                self._streams[stream] = []
            key = f"{stream}:{group}"
            if key not in self._groups:
                self._groups[key] = set()
            self._consumers[key] = {}

    async def xreadgroup(
        self, group: str, consumer: str, streams: Dict[str, str],
        count: int = 1, block: Optional[int] = None, noack: bool = False
    ) -> list:
        import time as _time
        async with self._lock:
            results = []
            for stream, start_id in streams.items():
                key = f"{stream}:{group}"
                if stream not in self._streams:
                    continue
                idx = self._consumers.get(key, {}).get(consumer, 0)
                msgs = []
                for i in range(idx, min(idx + count, len(self._streams[stream]))):
                    msg_id, fields = self._streams[stream][i]
                    msgs.append((msg_id, fields))
                    self._consumers.setdefault(key, {})[consumer] = i + 1
                if msgs:
                    results.append((stream, msgs))
            return results

    async def xack(self, stream: str, group: str, *ids: str):
        return len(ids)

    async def close(self):
        pass


class RedisStreamManager:
    """Redis Stream 管理器 - 发布/订阅模式"""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0,
                 use_memory: bool = False, connect_timeout: float = 2.0):
        self.host = host
        self.port = port
        self.db = db
        self._client = None
        self._in_memory = None
        self._connect_timeout = connect_timeout
        self._using_memory = use_memory or not REDIS_AVAILABLE

    async def connect(self) -> bool:
        if self._using_memory:
            self._in_memory = InMemoryStream()
            logger.info("Using in-memory stream")
            return True
        try:
            self._client = redis_async.Redis(
                host=self.host, port=self.port, db=self.db,
                socket_connect_timeout=self._connect_timeout,
                socket_timeout=self._connect_timeout
            )
            await self._client.ping()
            logger.info(f"Connected to Redis Stream at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.warning(f"Redis connection failed, falling back to in-memory: {e}")
            self._in_memory = InMemoryStream()
            self._using_memory = True
            return True

    async def ensure_stream(self, stream_name: str):
        if self._using_memory:
            return
        try:
            exists = await self._client.exists(stream_name)
            if not exists:
                await self._client.xadd(stream_name, {"_init": "1"})
                logger.info(f"Created stream: {stream_name}")
        except Exception as e:
            logger.warning(f"ensure_stream failed: {e}")

    async def ensure_group(self, stream_name: str, group_name: str):
        if self._using_memory:
            await self._in_memory.xgroup_create(stream_name, group_name, mkstream=True)
            return
        try:
            await self._client.xgroup_create(
                stream_name, group_name, id="0", mkstream=True
            )
            logger.info(f"Created consumer group {group_name} on {stream_name}")
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.warning(f"xgroup_create warning: {e}")

    async def publish(self, stream_name: str, data: Dict[str, Any]) -> str:
        fields = {k: json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else str(v)
                  for k, v in data.items()}
        if self._using_memory:
            return await self._in_memory.xadd(stream_name, fields)
        try:
            return await self._client.xadd(stream_name, fields)
        except Exception as e:
            logger.error(f"Publish to {stream_name} failed: {e}")
            return ""

    async def consume_group(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int = 1,
        block_ms: int = 5000
    ) -> List[tuple]:
        streams = {stream_name: ">"}
        if self._using_memory:
            return await self._in_memory.xreadgroup(
                group_name, consumer_name, streams, count=count
            )
        try:
            return await self._client.xreadgroup(
                group_name, consumer_name, streams, count=count, block=block_ms
            )
        except Exception as e:
            logger.error(f"Consume from {stream_name} failed: {e}")
            return []

    async def ack(self, stream_name: str, group_name: str, msg_id: str):
        if self._using_memory:
            await self._in_memory.xack(stream_name, group_name, msg_id)
            return
        try:
            await self._client.xack(stream_name, group_name, msg_id)
        except Exception as e:
            logger.error(f"ACK {msg_id} on {stream_name} failed: {e}")

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None
        if self._in_memory:
            await self._in_memory.close()
            self._in_memory = None


@asynccontextmanager
async def get_stream_manager(host: str, port: int, db: int = 0):
    mgr = RedisStreamManager(host, port, db)
    try:
        await mgr.connect()
        yield mgr
    finally:
        await mgr.close()


def parse_stream_message(msg: tuple) -> Dict[str, Any]:
    """解析 Redis Stream 消息，将字符串值转回 Python 对象"""
    msg_id, fields = msg
    result = {"_id": msg_id}
    for k, v in fields.items():
        if isinstance(v, bytes):
            v = v.decode("utf-8")
        s = str(v)
        try:
            result[k] = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            result[k] = v
    return result
