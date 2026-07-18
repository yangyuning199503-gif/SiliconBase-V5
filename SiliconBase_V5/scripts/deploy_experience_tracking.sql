-- ═══════════════════════════════════════════════════════════════════════════════
-- 【Agent-5】经验量化追踪系统 - 数据库表创建脚本
-- 
-- 部署步骤:
-- 1. 在 PostgreSQL 数据库中执行此脚本
-- 2. 确保数据库用户有创建表的权限
-- 
-- 核心要求:
-- - 记录每次工具执行的经验值
-- - 支持按用户、工具、时间维度查询
-- - 用于游戏化系统和用户成长追踪
-- ═══════════════════════════════════════════════════════════════════════════════

-- 创建经验记录表
CREATE TABLE IF NOT EXISTS experience_records (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    tool_name VARCHAR(255) NOT NULL,
    success BOOLEAN NOT NULL,
    execution_time_ms INTEGER,
    xp_gained INTEGER NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 可选: 添加外键约束(如果需要关联到用户表)
    -- CONSTRAINT fk_user 
    --     FOREIGN KEY (user_id) 
    --     REFERENCES users(id) 
    --     ON DELETE CASCADE
);

-- 创建索引以优化查询性能
CREATE INDEX IF NOT EXISTS idx_experience_user_id 
    ON experience_records(user_id);

CREATE INDEX IF NOT EXISTS idx_experience_tool_name 
    ON experience_records(tool_name);

CREATE INDEX IF NOT EXISTS idx_experience_timestamp 
    ON experience_records(timestamp);

CREATE INDEX IF NOT EXISTS idx_experience_user_tool 
    ON experience_records(user_id, tool_name);

-- 创建复合索引用于常见查询场景
CREATE INDEX IF NOT EXISTS idx_experience_user_time 
    ON experience_records(user_id, timestamp DESC);

-- 添加表注释
COMMENT ON TABLE experience_records IS '工具执行经验值记录表 - 【Agent-5】经验量化追踪系统';
COMMENT ON COLUMN experience_records.user_id IS '用户ID';
COMMENT ON COLUMN experience_records.tool_name IS '工具名称';
COMMENT ON COLUMN experience_records.success IS '工具是否执行成功';
COMMENT ON COLUMN experience_records.execution_time_ms IS '执行耗时(毫秒)';
COMMENT ON COLUMN experience_records.xp_gained IS '获得的经验值';
COMMENT ON COLUMN experience_records.timestamp IS '记录时间';

-- ═══════════════════════════════════════════════════════════════════════════════
-- 常用查询示例
-- ═══════════════════════════════════════════════════════════════════════════════

-- 1. 查询用户的总经验值
-- SELECT user_id, SUM(xp_gained) as total_xp 
-- FROM experience_records 
-- WHERE user_id = 'xxx' 
-- GROUP BY user_id;

-- 2. 查询用户各工具的使用统计
-- SELECT 
--     tool_name, 
--     COUNT(*) as use_count,
--     SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
--     AVG(xp_gained) as avg_xp
-- FROM experience_records 
-- WHERE user_id = 'xxx' 
-- GROUP BY tool_name;

-- 3. 查询今日获得的经验值
-- SELECT SUM(xp_gained) as today_xp 
-- FROM experience_records 
-- WHERE user_id = 'xxx' 
-- AND timestamp >= CURRENT_DATE;

-- 4. 查询用户等级(假设每100XP升一级)
-- SELECT 
--     user_id,
--     SUM(xp_gained) as total_xp,
--     FLOOR(SUM(xp_gained) / 100) + 1 as level
-- FROM experience_records 
-- WHERE user_id = 'xxx'
-- GROUP BY user_id;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 部署验证
-- ═══════════════════════════════════════════════════════════════════════════════

-- 验证表是否创建成功
SELECT 
    table_name, 
    column_name, 
    data_type 
FROM 
    information_schema.columns 
WHERE 
    table_name = 'experience_records' 
ORDER BY 
    ordinal_position;

-- 验证索引是否创建成功
SELECT 
    indexname, 
    indexdef 
FROM 
    pg_indexes 
WHERE 
    tablename = 'experience_records';
