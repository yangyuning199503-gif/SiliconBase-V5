-- SiliconBase V5 记忆系统数据库性能优化脚本
-- Agent-10: 性能优化工程师
-- 创建时间: 2026-03-06
-- 目标: 查询延迟<100ms

-- ═══════════════════════════════════════════════════════════════════
-- 1. 复合索引优化 - 支持高频查询场景
-- ═══════════════════════════════════════════════════════════════════

-- 1.1 层级+来源复合索引（用于按层级和来源筛选）
CREATE INDEX IF NOT EXISTS idx_memories_layer_source 
ON memories(layer, source);

-- 1.2 场景+时间复合索引（用于按场景和时间范围筛选）
CREATE INDEX IF NOT EXISTS idx_memories_scene_time 
ON memories(scene, created_at DESC);

-- 1.3 用户+层级+时间复合索引（用于用户时间线查询）
CREATE INDEX IF NOT EXISTS idx_memories_user_layer_time 
ON memories(user_id, layer, created_at DESC);

-- 1.4 类型+评分复合索引（用于按类型和质量筛选）
CREATE INDEX IF NOT EXISTS idx_memories_type_rating 
ON memories(mem_type, rating DESC);

-- 1.5 过期时间+用户复合索引（用于过期清理任务）
CREATE INDEX IF NOT EXISTS idx_memories_expire_user 
ON memories(expire_at, user_id) 
WHERE expire_at IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════
-- 2. GIN索引优化 - 支持JSONB高效查询
-- ═══════════════════════════════════════════════════════════════════

-- 2.1 六维评分GIN索引（已存在，验证并优化）
DROP INDEX IF EXISTS idx_value_assessment;
CREATE INDEX IF NOT EXISTS idx_memories_value_assessment 
ON memories USING GIN(value_assessment);

-- 2.2 上下文JSONB GIN索引
CREATE INDEX IF NOT EXISTS idx_memories_context 
ON memories USING GIN(context);

-- 2.3 六维评分子字段索引（用于特定维度查询优化）
CREATE INDEX IF NOT EXISTS idx_memories_overall_score 
ON memories((value_assessment->>'overall')) 
WHERE value_assessment->>'overall' IS NOT NULL;

-- 2.4 等级索引（用于按等级筛选）
CREATE INDEX IF NOT EXISTS idx_memories_grade 
ON memories((value_assessment->>'grade')) 
WHERE value_assessment->>'grade' IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════
-- 3. 部分索引 - 针对特定查询模式优化
-- ═══════════════════════════════════════════════════════════════════

-- 3.1 高评分记忆索引（评分>=5）
CREATE INDEX IF NOT EXISTS idx_memories_high_rating 
ON memories(user_id, layer, created_at DESC) 
WHERE rating >= 5;

-- 3.2 未过期记忆索引
CREATE INDEX IF NOT EXISTS idx_memories_not_expired 
ON memories(user_id, layer, created_at DESC) 
WHERE expire_at IS NULL OR expire_at > CURRENT_TIMESTAMP;

-- 3.3 压缩标记索引（用于压缩任务）
CREATE INDEX IF NOT EXISTS idx_memories_compressed 
ON memories(user_id, created_at) 
WHERE compressed = 0;

-- 3.4 L1/L2工作记忆快速访问索引
CREATE INDEX IF NOT EXISTS idx_memories_working_short 
ON memories(user_id, created_at DESC) 
WHERE layer IN ('working', 'short');

-- ═══════════════════════════════════════════════════════════════════
-- 4. 关联表索引优化
-- ═══════════════════════════════════════════════════════════════════

-- 4.1 记忆关联复合索引
CREATE INDEX IF NOT EXISTS idx_assoc_user_relation 
ON memory_associations(user_id, relation_type, relation_score DESC);

-- 4.2 关联分数索引（用于高质量关联检索）
CREATE INDEX IF NOT EXISTS idx_assoc_high_score 
ON memory_associations(source_mem_id, relation_score DESC) 
WHERE relation_score >= 0.7;

-- 4.3 双向关联快速查询索引
CREATE INDEX IF NOT EXISTS idx_assoc_bidirectional 
ON memory_associations(target_mem_id, source_mem_id, relation_type);

-- ═══════════════════════════════════════════════════════════════════
-- 5. 统计信息更新
-- ═══════════════════════════════════════════════════════════════════

-- 更新所有表的统计信息
ANALYZE memories;
ANALYZE memory_associations;
ANALYZE vital_signs_history;
ANALYZE self_actions;

-- ═══════════════════════════════════════════════════════════════════
-- 6. 查询性能验证
-- ═══════════════════════════════════════════════════════════════════

-- 6.1 查看索引使用情况
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes 
WHERE tablename IN ('memories', 'memory_associations')
ORDER BY idx_scan DESC;

-- 6.2 查看表统计信息
SELECT 
    relname AS table_name,
    n_live_tup AS live_tuples,
    n_dead_tup AS dead_tuples,
    last_vacuum,
    last_autovacuum,
    last_analyze
FROM pg_stat_user_tables
WHERE relname IN ('memories', 'memory_associations', 'vital_signs_history', 'self_actions');
