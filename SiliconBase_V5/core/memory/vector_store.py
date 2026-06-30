#!/usr/bin/env python3
"""
向量存储（VectorStore）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
白皮书模块：原生异步向量存储（ChromaDB 客户端-服务器模式）
职责：替代 vector_memory.py，提供 async 接口
功能状态：核心公开接口已对齐 vector_memory.py（含批量操作、ID 查询/删除、
         多集合搜索、统计、健康检查、多向量编码、embedder 获取）
约束：
  - add / search / delete 接口为 async def
  - Embedding 计算走 asyncio.to_thread（CPU 密集型，有理由隔离）
  - ChromaDB I/O 通过 AsyncHttpClient 真异步执行，不阻塞事件循环
"""

import asyncio
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.logger import logger
from core.memory.memory_schema import MemoryFilter, MemoryMetadata


@dataclass
class SearchResult:
    """搜索结果——不可变数据契约"""
    id: str
    document: str
    metadata: dict
    distance: float | None = None


class VectorStore:
    """
    向量存储——原生异步接口（ChromaDB 客户端-服务器模式）

    设计说明：
    - 对外接口全 async
    - 内部 Embedding 用 to_thread 隔离 CPU 密集型计算
    - ChromaDB I/O 通过 AsyncHttpClient 真异步执行
    - collections 参数保留向后兼容（旧代码传入不报错），但内部不再使用
    """

    def __init__(
        self,
        embedder: Any,
        collections: dict[str, Any] | None = None,
        host: str = "127.0.0.1",
        port: int = 8000,
    ) -> None:
        """
        Args:
            embedder: Embedding 模型（如 SentenceTransformer）
            collections: 【已废弃】保留向后兼容，传入即忽略
            host: ChromaDB 服务器主机
            port: ChromaDB 服务器端口
        """
        self._embedder = embedder
        self._host = host
        self._port = port
        self._client: Any | None = None
        self._async_collections: dict[str, Any] = {}

    async def _ensure_client(self) -> None:
        """延迟初始化 AsyncHttpClient，支持断线重连"""
        if self._client is not None:
            # 【修复】检测连接是否仍可用，不可用则重置重连
            try:
                await self._client.heartbeat()
                return
            except Exception:
                logger.warning("[VectorStore] ChromaDB 连接已断开，将重新初始化")
                self._client = None
                self._async_collections.clear()
        import chromadb

        self._client = await chromadb.AsyncHttpClient(host=self._host, port=self._port)

    async def _get_or_create_col(self, name: str) -> Any:
        """获取或创建集合（真异步）"""
        if name in self._async_collections:
            return self._async_collections[name]
        await self._ensure_client()
        col = await self._client.get_or_create_collection(name)
        self._async_collections[name] = col
        return col

    async def add(
        self,
        collection: str,
        text: str,
        metadata: Any
    ) -> str:
        """
        添加向量记录

        Args:
            collection: 集合名称（如 "chat", "knowledge", "experience"）
            text: 文本内容
            metadata: MemoryMetadata 实例或兼容的扁平 dict

        Returns:
            str: 记录 ID
        """
        # CPU 密集型推理，使用 to_thread 隔离，不属于 I/O 债务
        embedding = await asyncio.to_thread(self._embed, text)

        mem_id = self._generate_id(text)
        if isinstance(metadata, MemoryMetadata):
            chroma_meta = metadata.to_chroma_metadata()
        elif isinstance(metadata, dict):
            chroma_meta = metadata
        else:
            raise TypeError(f"metadata 必须是 MemoryMetadata 或 dict， got {type(metadata)}")

        col = await self._get_or_create_col(collection)
        await col.upsert(
            documents=[text],
            embeddings=[embedding],
            metadatas=[chroma_meta],
            ids=[mem_id]
        )

        return mem_id

    async def search(
        self,
        collection: str,
        query: str,
        filters: MemoryFilter | None = None,
        limit: int = 5
    ) -> list[SearchResult]:
        """
        语义搜索

        Args:
            collection: 集合名称
            query: 查询文本
            filters: 过滤条件（MemoryFilter）
            limit: 返回数量

        Returns:
            List[SearchResult]: 搜索结果列表
        """
        # CPU 密集型推理，使用 to_thread 隔离，不属于 I/O 债务
        embedding = await asyncio.to_thread(self._embed, query)

        col = await self._get_or_create_col(collection)
        where_clause = filters.to_chroma_where() if filters else None

        results = await col.query(
            query_embeddings=[embedding],
            n_results=limit,
            where=where_clause
        )

        # 解析 ChromaDB 返回格式
        search_results: list[SearchResult] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, mem_id in enumerate(ids):
            search_results.append(SearchResult(
                id=mem_id,
                document=documents[i] if i < len(documents) else "",
                metadata=metadatas[i] if i < len(metadatas) else {},
                distance=distances[i] if i < len(distances) else None
            ))

        return search_results

    async def delete_collection(self, name: str) -> None:
        """删除集合（真异步）"""
        await self._ensure_client()
        await self._client.delete_collection(name)
        self._async_collections.pop(name, None)

    # ═════════════════════════════════════════════════════════════════════════════
    # 1. 批量操作
    # ═════════════════════════════════════════════════════════════════════════════

    async def add_batch(
        self,
        collection: str,
        texts: list[str],
        metadatas: list[MemoryMetadata]
    ) -> list[str]:
        """
        批量添加向量记录

        循环调用 add()，每个调用已经是真异步，不需要额外批处理逻辑。

        Args:
            collection: 集合名称
            texts: 文本列表
            metadatas: 元数据列表（与 texts 一一对应）

        Returns:
            List[str]: 记录 ID 列表
        """
        if len(texts) != len(metadatas):
            raise ValueError(f"texts ({len(texts)}) 与 metadatas ({len(metadatas)}) 长度不一致")

        ids: list[str] = []
        for text, metadata in zip(texts, metadatas, strict=False):
            mem_id = await self.add(collection, text, metadata)
            ids.append(mem_id)
        return ids

    # ═════════════════════════════════════════════════════════════════════════════
    # 2. 按 ID 查询和删除
    # ═════════════════════════════════════════════════════════════════════════════

    async def get(self, collection: str, ids: list[str]) -> list[dict[str, Any]]:
        """
        根据 ID 查询记录

        Args:
            collection: 集合名称
            ids: ID 列表

        Returns:
            List[Dict]: 记录列表，每个记录包含 id, document, metadata
        """
        if not ids:
            return []

        col = await self._get_or_create_col(collection)
        results = await col.get(ids=ids)

        records: list[dict[str, Any]] = []
        result_ids = results.get("ids", [])
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])

        for i, mem_id in enumerate(result_ids):
            records.append({
                "id": mem_id,
                "document": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {}
            })

        return records

    async def delete(self, collection: str, ids: list[str]) -> bool:
        """
        根据 ID 删除记录

        Args:
            collection: 集合名称
            ids: ID 列表

        Returns:
            bool: 是否成功
        """
        if not ids:
            return True

        try:
            col = await self._get_or_create_col(collection)
            await col.delete(ids=ids)
            return True
        except Exception:
            return False

    async def upsert(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: Any
    ) -> str:
        """
        更新或插入记录（指定 ID）

        Args:
            collection: 集合名称
            doc_id: 指定记录 ID
            text: 文本内容
            metadata: MemoryMetadata 实例或兼容的扁平 dict

        Returns:
            str: 记录 ID
        """
        embedding = await asyncio.to_thread(self._embed, text)
        if isinstance(metadata, MemoryMetadata):
            chroma_meta = metadata.to_chroma_metadata()
        elif isinstance(metadata, dict):
            chroma_meta = metadata
        else:
            raise TypeError(f"metadata 必须是 MemoryMetadata 或 dict， got {type(metadata)}")

        col = await self._get_or_create_col(collection)
        await col.upsert(
            documents=[text],
            embeddings=[embedding],
            metadatas=[chroma_meta],
            ids=[doc_id]
        )

        return doc_id

    async def count(self, collection: str) -> int:
        """
        获取集合中的记录数量

        Args:
            collection: 集合名称

        Returns:
            int: 记录数量
        """
        try:
            col = await self._get_or_create_col(collection)
            return await col.count()
        except Exception:
            return 0

    async def get_all(self, collection: str) -> list[dict[str, Any]]:
        """
        获取集合中的所有记录

        Args:
            collection: 集合名称

        Returns:
            List[Dict]: 记录列表，每个记录包含 id, document, metadata
        """
        try:
            col = await self._get_or_create_col(collection)
            results = await col.get()

            records: list[dict[str, Any]] = []
            result_ids = results.get("ids", [])
            documents = results.get("documents", [])
            metadatas = results.get("metadatas", [])

            for i, mem_id in enumerate(result_ids):
                records.append({
                    "id": mem_id,
                    "document": documents[i] if i < len(documents) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {}
                })

            return records
        except Exception:
            return []

    # ═════════════════════════════════════════════════════════════════════════════
    # 3. 多集合搜索（hybrid_search 核心能力）
    # ═════════════════════════════════════════════════════════════════════════════

    async def search_multi(
        self,
        query: str,
        collections: list[str],
        n_results: int = 5
    ) -> dict[str, list[SearchResult]]:
        """
        并发搜索多个集合

        Args:
            query: 查询文本
            collections: 集合名称列表
            n_results: 每个集合返回结果数量

        Returns:
            Dict[str, List[SearchResult]]: 按集合名分组的结果
        """
        tasks = [self.search(coll, query, limit=n_results) for coll in collections]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        grouped: dict[str, list[SearchResult]] = {}
        for coll, res in zip(collections, results_list, strict=False):
            if isinstance(res, Exception):
                grouped[coll] = []
            else:
                grouped[coll] = res

        return grouped

    # ═════════════════════════════════════════════════════════════════════════════
    # 4. 统计接口
    # ═════════════════════════════════════════════════════════════════════════════

    async def get_stats(self) -> dict[str, Any]:
        """
        获取统计信息

        遍历所有已知 collection，统计每个集合的文档数量。

        Returns:
            Dict: 统计信息
        """
        stats: dict[str, Any] = {
            "total_collections": len(self._async_collections),
            "collections": {}
        }

        for name, col in self._async_collections.items():
            try:
                count = await col.count()
                stats["collections"][name] = {"count": count}
            except Exception:
                stats["collections"][name] = {"count": -1}

        return stats

    # ═════════════════════════════════════════════════════════════════════════════
    # 5. 健康检查
    # ═════════════════════════════════════════════════════════════════════════════

    async def is_available(self) -> bool:
        """
        检查 ChromaDB 服务端是否可用。若不可用，触发 _ensure_client 重连。

        Returns:
            bool: True 表示可用
        """
        try:
            await self._ensure_client()
            await self._client.heartbeat()
            return True
        except Exception as e:
            # 失败时重置客户端，下次调用会重连
            logger.warning(f"[VectorStore] ChromaDB 连接检查失败: {type(e).__name__}: {e}")
            self._client = None
            self._async_collections.clear()
            return False

    # ═════════════════════════════════════════════════════════════════════════════
    # 6. 向量表示辅助方法（从 vector_memory.py 迁移）
    # ═════════════════════════════════════════════════════════════════════════════

    def encode_multi_vector(
        self,
        content: str,
        timestamp: str | None = None
    ) -> dict[str, list[float]]:
        """
        生成多向量表示

        为一条记忆生成语义、情感、时间等多个向量表示。

        Args:
            content: 记忆文本内容
            timestamp: 时间戳字符串（ISO 格式），None 表示当前时间

        Returns:
            Dict[str, List[float]]: 多向量字典
                - semantic: 语义向量（全文）
                - emotion: 情感向量
                - temporal: 时间向量（2 维周期特征）
        """
        result: dict[str, list[float]] = {}

        # 1. 语义向量（全文）
        semantic_vec = self._embed(content)
        result["semantic"] = semantic_vec if semantic_vec else [0.0] * 384

        # 2. 情感向量（提取情感关键词后编码）
        emotion_text = self._extract_emotion(content)
        if emotion_text:
            emotion_vec = self._embed(emotion_text)
            result["emotion"] = emotion_vec if emotion_vec else [0.0] * 384
        else:
            result["emotion"] = [0.0] * 384

        # 3. 时间向量（时间戳编码为 2 维周期特征）
        result["temporal"] = self._encode_temporal(timestamp)

        return result

    def _extract_emotion(self, content: str) -> str | None:
        """提取情感关键词，用于生成情感向量"""
        emotion_keywords = [
            "焦虑", "担心", "着急", "开心", "高兴", "难过", "生气",
            "害怕", "恐惧", "兴奋", "失望", "满意", "惊讶", "平静",
            "愉快", "悲伤", "愤怒", "烦恼", "轻松", "紧张"
        ]
        found = [k for k in emotion_keywords if k in content]
        return " ".join(found) if found else None

    def _encode_temporal(self, timestamp: str | None) -> list[float]:
        """将时间戳编码为 2 维周期特征 [sin(hour), cos(hour)]"""
        try:
            if timestamp is None:
                dt = datetime.now()
            elif isinstance(timestamp, str):
                ts_clean = timestamp.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_clean)
            else:
                dt = datetime.now()

            hour = dt.hour
            return [
                float(math.sin(2 * math.pi * hour / 24)),
                float(math.cos(2 * math.pi * hour / 24))
            ]
        except Exception:
            return [0.0, 0.0]

    # ═════════════════════════════════════════════════════════════════════════════
    # 7. embedder 获取接口（替代旧 _embedding_manager.get_embedding_function）
    # ═════════════════════════════════════════════════════════════════════════════

    def get_embedding_function(self) -> Any:
        """
        获取当前使用的嵌入函数/模型

        Returns:
            Any: embedder 实例（如 SentenceTransformer 或 EmbeddingFunction）
        """
        return self._embedder

    def _embed(self, text: str) -> list[float]:
        """CPU 密集型 Embedding 计算（内部同步方法）

        兼容两种 embedder：
        - 原生模型（如 SentenceTransformer）：有 .encode() 方法
        - ChromaDB EmbeddingFunction（如 LocalEmbeddingFunction）：通过 __call__ 调用
        """
        if hasattr(self._embedder, "encode"):
            # 原生模型接口（如 SentenceTransformer）
            result = self._embedder.encode(text)
            if hasattr(result, "tolist"):
                return result.tolist()
            return result if isinstance(result, list) else [result]

        # ChromaDB EmbeddingFunction 兼容接口
        result = self._embedder([text])
        if result and isinstance(result, list) and len(result) > 0:
            first = result[0]
            if isinstance(first, list):
                return first
            return [first]
        return []

    def _generate_id(self, text: str) -> str:
        """确定性 ID 生成"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()
