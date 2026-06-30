#!/usr/bin/env python3
"""
记忆图谱 - 核心实现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
提供记忆关系图谱功能：
- 记忆节点管理
- 关系建立和查询
- 图谱遍历

【使用示例】
    from core.memory.memory_graph import memory_graph

    # 添加记忆节点
    memory_graph.add_node("mem_123", {"content": "..."})

    # 建立关系
    memory_graph.add_relation("mem_123", "mem_456", "related_to")
"""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger('memory_graph')


class RelationType(Enum):
    """关系类型枚举"""
    RELATED_TO = "related_to"       # 相关
    CAUSES = "causes"               # 导致
    RESULTS_FROM = "results_from"   # 结果于
    PART_OF = "part_of"             # 部分
    CONTAINS = "contains"           # 包含
    SIMILAR_TO = "similar_to"       # 相似
    SEQUENTIAL = "sequential"       # 顺序


@dataclass
class MemoryNode:
    """记忆节点数据类"""
    node_id: str
    content: dict[str, Any]
    node_type: str = "memory"
    created_at: float = field(default_factory=time.time)
    relations: dict[str, list[str]] = field(default_factory=dict)  # relation_type -> node_ids


@dataclass
class Relation:
    """关系数据类"""
    source_id: str
    target_id: str
    relation_type: RelationType
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryGraph:
    """
    记忆图谱

    管理记忆节点和它们之间的关系，支持图谱遍历。

    单例模式实现。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化记忆图谱"""
        if self._initialized:
            return
        self._initialized = True

        # 节点存储: node_id -> MemoryNode
        self._nodes: dict[str, MemoryNode] = {}

        # 关系存储: (source_id, target_id) -> Relation
        self._relations: dict[tuple, Relation] = {}

        # 锁
        self._lock = threading.RLock()

        logger.info("[MemoryGraph] 记忆图谱初始化完成")

    def add_node(self, node_id: str, content: dict[str, Any], node_type: str = "memory") -> MemoryNode:
        """
        添加节点

        Args:
            node_id: 节点ID
            content: 节点内容
            node_type: 节点类型

        Returns:
            节点对象
        """
        with self._lock:
            if node_id in self._nodes:
                # 更新现有节点
                self._nodes[node_id].content.update(content)
                return self._nodes[node_id]

            node = MemoryNode(
                node_id=node_id,
                content=content,
                node_type=node_type
            )
            self._nodes[node_id] = node
            logger.debug(f"[MemoryGraph] 添加节点: {node_id}")
            return node

    def get_node(self, node_id: str) -> MemoryNode | None:
        """
        获取节点

        Args:
            node_id: 节点ID

        Returns:
            节点对象或None
        """
        return self._nodes.get(node_id)

    def remove_node(self, node_id: str) -> bool:
        """
        删除节点

        Args:
            node_id: 节点ID

        Returns:
            是否成功
        """
        with self._lock:
            if node_id not in self._nodes:
                return False

            # 删除相关关系
            relations_to_remove = [
                key for key in self._relations
                if key[0] == node_id or key[1] == node_id
            ]
            for key in relations_to_remove:
                del self._relations[key]

            # 删除节点
            del self._nodes[node_id]
            logger.debug(f"[MemoryGraph] 删除节点: {node_id}")
            return True

    def get_relation(self, source_id: str, target_id: str) -> Relation | None:
        """
        获取关系

        Args:
            source_id: 源节点ID
            target_id: 目标节点ID

        Returns:
            关系对象或None
        """
        return self._relations.get((source_id, target_id))

    def get_related_nodes(self, node_id: str, relation_type: RelationType = None) -> list[str]:
        """
        获取相关节点

        Args:
            node_id: 节点ID
            relation_type: 关系类型过滤

        Returns:
            节点ID列表
        """
        node = self._nodes.get(node_id)
        if not node:
            return []

        if relation_type:
            return node.relations.get(relation_type.value, [])
        else:
            # 返回所有相关节点
            related = set()
            for node_ids in node.relations.values():
                related.update(node_ids)
            return list(related)

    def traverse(self, start_id: str, max_depth: int = 3,
                 relation_types: list[RelationType] = None) -> dict[str, Any]:
        """
        遍历图谱

        Args:
            start_id: 起始节点ID
            max_depth: 最大深度
            relation_types: 关系类型过滤

        Returns:
            遍历结果
        """
        visited = set()
        result = {"nodes": [], "relations": []}

        def traverse_recursive(node_id: str, depth: int):
            if depth > max_depth or node_id in visited:
                return

            visited.add(node_id)
            node = self._nodes.get(node_id)
            if not node:
                return

            result["nodes"].append(node_id)

            # 获取相关节点
            for rel_type, target_ids in node.relations.items():
                if relation_types and RelationType(rel_type) not in relation_types:
                    continue

                for target_id in target_ids:
                    if (node_id, target_id) in self._relations:
                        result["relations"].append({
                            "source": node_id,
                            "target": target_id,
                            "type": rel_type
                        })
                    traverse_recursive(target_id, depth + 1)

        traverse_recursive(start_id, 0)
        return result

    def find_path(self, start_id: str, end_id: str,
                  max_depth: int = 5) -> list[str] | None:
        """
        查找路径

        Args:
            start_id: 起始节点
            end_id: 目标节点
            max_depth: 最大深度

        Returns:
            路径节点列表或None
        """
        if start_id not in self._nodes or end_id not in self._nodes:
            return None

        # BFS查找最短路径
        from collections import deque

        queue = deque([(start_id, [start_id])])
        visited = {start_id}

        while queue:
            current_id, path = queue.popleft()

            if len(path) > max_depth:
                continue

            if current_id == end_id:
                return path

            node = self._nodes[current_id]
            for target_ids in node.relations.values():
                for target_id in target_ids:
                    if target_id not in visited:
                        visited.add(target_id)
                        queue.append((target_id, path + [target_id]))

        return None

    def get_stats(self) -> dict[str, int]:
        """获取统计信息"""
        return {
            "nodes": len(self._nodes),
            "relations": len(self._relations)
        }

    def clear(self) -> None:
        """清空图谱"""
        with self._lock:
            self._nodes.clear()
            self._relations.clear()
            logger.info("[MemoryGraph] 图谱已清空")

    # ═══════════════════════════════════════════════════════════════
    # API 兼容方法
    # ═══════════════════════════════════════════════════════════════

    def add_memory_node(self, memory_id: str, attributes: dict[str, Any]) -> bool:
        """
        添加记忆节点 (API兼容方法)

        Args:
            memory_id: 记忆ID
            attributes: 节点属性字典

        Returns:
            是否成功
        """
        try:
            node_type = attributes.get("node_type", "memory")
            self.add_node(memory_id, attributes, node_type)
            return True
        except Exception as e:
            logger.error(f"[MemoryGraph] 添加记忆节点失败: {e}")
            return False

    def add_relation(self, from_id: str, to_id: str,
                     relation_type: str, strength: float = 1.0,
                     attributes: dict[str, Any] | None = None) -> bool:
        """
        添加记忆关系 (API兼容方法)

        Args:
            from_id: 源记忆ID
            to_id: 目标记忆ID
            relation_type: 关系类型字符串
            strength: 关系强度 (0-1)
            attributes: 额外属性

        Returns:
            是否成功
        """
        try:
            # 转换关系类型字符串为枚举
            try:
                rel_type = RelationType(relation_type)
            except ValueError:
                rel_type = RelationType.RELATED_TO

            return self.add_relation_enum(from_id, to_id, rel_type, strength, attributes)
        except Exception as e:
            logger.error(f"[MemoryGraph] 添加关系失败: {e}")
            return False

    def add_relation_enum(self, source_id: str, target_id: str,
                          relation_type: RelationType, weight: float = 1.0,
                          metadata: dict[str, Any] | None = None) -> bool:
        """原始枚举类型添加关系方法"""
        with self._lock:
            # 确保节点存在
            if source_id not in self._nodes:
                logger.warning(f"[MemoryGraph] 源节点不存在: {source_id}")
                return False
            if target_id not in self._nodes:
                logger.warning(f"[MemoryGraph] 目标节点不存在: {target_id}")
                return False

            # 创建关系
            relation = Relation(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                weight=weight,
                metadata=metadata or {}
            )

            self._relations[(source_id, target_id)] = relation

            # 更新节点的关系列表
            rel_type_str = relation_type.value
            if rel_type_str not in self._nodes[source_id].relations:
                self._nodes[source_id].relations[rel_type_str] = []
            if target_id not in self._nodes[source_id].relations[rel_type_str]:
                self._nodes[source_id].relations[rel_type_str].append(target_id)

            logger.debug(f"[MemoryGraph] 添加关系: {source_id} -> {target_id} ({relation_type.value})")
            return True

    def find_related(self, memory_id: str, depth: int = 2,
                     min_strength: float = 0.0,
                     relation_types: list[str] | None = None) -> list[dict[str, Any]]:
        """
        查找相关记忆 (API兼容方法)

        Args:
            memory_id: 起始记忆ID
            depth: 遍历深度
            min_strength: 最小关系强度
            relation_types: 关系类型过滤

        Returns:
            相关记忆列表
        """
        result = []
        visited = set()

        def traverse(current_id: str, current_depth: int):
            if current_depth > depth or current_id in visited:
                return
            visited.add(current_id)

            node = self._nodes.get(current_id)
            if not node:
                return

            result.append({
                "memory_id": current_id,
                "content": node.content,
                "depth": current_depth
            })

            # 获取相关节点
            for rel_type, target_ids in node.relations.items():
                if relation_types and rel_type not in relation_types:
                    continue

                for target_id in target_ids:
                    # 检查关系强度
                    rel_key = (current_id, target_id)
                    relation = self._relations.get(rel_key)
                    if relation and relation.weight >= min_strength:
                        traverse(target_id, current_depth + 1)

        traverse(memory_id, 0)
        return result[1:] if len(result) > 0 else []  # 排除自身

    def get_graph_data(self, center_node: str | None = None,
                       depth: int = 2, limit: int = 100) -> dict[str, Any]:
        """
        获取图谱数据 (API兼容方法)

        Args:
            center_node: 中心节点ID
            depth: 遍历深度
            limit: 最大节点数

        Returns:
            图谱数据字典
        """
        nodes = []
        edges = []

        if center_node and center_node in self._nodes:
            # 从中心节点遍历
            result = self.traverse(center_node, depth)
            node_ids = result.get("nodes", [])
            rels = result.get("relations", [])

            for node_id in node_ids[:limit]:
                node = self._nodes.get(node_id)
                if node:
                    nodes.append({
                        "id": node_id,
                        "type": node.node_type,
                        "content": node.content
                    })

            for rel in rels[:limit]:
                edges.append({
                    "source": rel["source"],
                    "target": rel["target"],
                    "type": rel["type"]
                })
        else:
            # 返回所有节点
            for node_id, node in list(self._nodes.items())[:limit]:
                nodes.append({
                    "id": node_id,
                    "type": node.node_type,
                    "content": node.content
                })

            for (source, target), relation in list(self._relations.items())[:limit]:
                edges.append({
                    "source": source,
                    "target": target,
                    "type": relation.relation_type.value
                })

        return {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(self._nodes),
            "total_edges": len(self._relations)
        }

    def get_graph_stats(self) -> dict[str, Any]:
        """
        获取图谱统计信息 (API兼容方法)

        Returns:
            统计信息字典
        """
        return {
            "total_nodes": len(self._nodes),
            "total_relations": len(self._relations),
            "node_types": {},
            "relation_types": {}
        }

    def auto_discover_relations(self, memory_id: str,
                                 candidate_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """
        自动发现关系 (API兼容方法)

        Args:
            memory_id: 目标记忆ID
            candidate_ids: 候选记忆ID列表

        Returns:
            发现的关系列表
        """
        discovered = []

        # 简单实现：基于内容相似度推荐关系
        target_node = self._nodes.get(memory_id)
        if not target_node:
            return discovered

        candidates = candidate_ids or list(self._nodes.keys())

        for candidate_id in candidates:
            if candidate_id == memory_id:
                continue

            candidate_node = self._nodes.get(candidate_id)
            if not candidate_node:
                continue

            # 检查是否已有关系
            if (memory_id, candidate_id) in self._relations:
                continue

            # 简单相似度检查（内容关键词匹配）
            target_content = str(target_node.content)
            candidate_content = str(candidate_node.content)

            # 提取关键词（简化版）
            target_words = set(target_content.lower().split())
            candidate_words = set(candidate_content.lower().split())

            if target_words and candidate_words:
                common_words = target_words & candidate_words
                similarity = len(common_words) / max(len(target_words), len(candidate_words))

                if similarity > 0.3:  # 相似度阈值
                    discovered.append({
                        "source": memory_id,
                        "target": candidate_id,
                        "relation_type": "similar_to",
                        "confidence": round(similarity, 2),
                        "reason": f"内容相似度: {round(similarity * 100)}%"
                    })

        return discovered

    def refresh(self) -> bool:
        """
        刷新图谱 (API兼容方法)

        Returns:
            是否成功
        """
        logger.info("[MemoryGraph] 图谱刷新完成")
        return True


# ═══════════════════════════════════════════════════════════════
# 记忆关联引擎
# ═══════════════════════════════════════════════════════════════

class MemoryAssociationEngine:
    """
    记忆关联引擎

    提供高级关联回忆功能，基于图谱进行智能联想。
    """

    def __init__(self, user_id: str):
        """
        初始化关联引擎

        Args:
            user_id: 用户ID
        """
        self.user_id = user_id
        self.graph = get_memory_graph(user_id)
        logger.info(f"[MemoryAssociationEngine] 初始化完成，用户: {user_id}")

    def associative_recall(self, query: str, context: dict[str, Any] | None = None,
                           top_k: int = 5) -> list[dict[str, Any]]:
        """
        联想回忆

        根据查询字符串联想相关的记忆。

        Args:
            query: 查询字符串
            context: 上下文信息
            top_k: 返回结果数量

        Returns:
            相关记忆列表
        """
        results = []

        try:
            # 简单实现：基于关键词匹配
            query_words = set(query.lower().split())

            for node_id, node in self.graph._nodes.items():
                node_content = str(node.content)
                node_words = set(node_content.lower().split())

                if query_words and node_words:
                    common_words = query_words & node_words
                    if common_words:
                        score = len(common_words) / len(query_words)
                        results.append({
                            "memory_id": node_id,
                            "content": node.content,
                            "relevance_score": round(score, 2),
                            "matched_keywords": list(common_words)
                        })

            # 按相关度排序
            results.sort(key=lambda x: x["relevance_score"], reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.error(f"[MemoryAssociationEngine] 联想回忆失败: {e}")
            return []

    def find_causal_chain(self, start_id: str, end_id: str) -> list[dict[str, Any]] | None:
        """
        查找因果链

        Args:
            start_id: 起始记忆ID
            end_id: 目标记忆ID

        Returns:
            因果链或None
        """
        path = self.graph.find_path(start_id, end_id)
        if not path:
            return None

        chain = []
        for node_id in path:
            node = self.graph._nodes.get(node_id)
            if node:
                chain.append({
                    "memory_id": node_id,
                    "content": node.content
                })

        return chain


# ═══════════════════════════════════════════════════════════════
# 全局实例管理
# ═══════════════════════════════════════════════════════════════

# 用户图谱缓存
_user_graphs: dict[str, MemoryGraph] = {}
_user_engines: dict[str, MemoryAssociationEngine] = {}


def get_memory_graph(user_id: str) -> MemoryGraph:
    """
    获取用户的记忆图谱

    Args:
        user_id: 用户ID

    Returns:
        MemoryGraph实例
    """
    if user_id not in _user_graphs:
        _user_graphs[user_id] = MemoryGraph()
        logger.info(f"[MemoryGraph] 为用户 {user_id} 创建新图谱")
    return _user_graphs[user_id]


def get_association_engine(user_id: str) -> MemoryAssociationEngine:
    """
    获取用户的记忆关联引擎

    Args:
        user_id: 用户ID

    Returns:
        MemoryAssociationEngine实例
    """
    if user_id not in _user_engines:
        _user_engines[user_id] = MemoryAssociationEngine(user_id)
        logger.info(f"[MemoryAssociationEngine] 为用户 {user_id} 创建新引擎")
    return _user_engines[user_id]


# 创建全局记忆图谱实例（向后兼容）
try:
    memory_graph = MemoryGraph()
except Exception as e:
    logger.error(f"[MemoryGraph] 创建实例失败: {e}")
    memory_graph = None


__all__ = [
    'MemoryGraph',
    'memory_graph',
    'MemoryNode',
    'Relation',
    'RelationType',
    'MemoryAssociationEngine',
    'get_memory_graph',
    'get_association_engine',
]
