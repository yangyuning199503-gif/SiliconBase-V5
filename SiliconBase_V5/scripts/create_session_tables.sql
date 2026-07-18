-- ═══════════════════════════════════════════════════════════════════════════════
-- SiliconBase V5 - Session Management Tables
-- Phase 1 Week 1 - Task 1: Create sessions and session_messages tables
-- Created: 2026-03-12
-- ═══════════════════════════════════════════════════════════════════════════════

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. sessions table - 会话管理表
-- ═══════════════════════════════════════════════════════════════════════════════

-- Drop table if exists (for clean recreation during development)
DROP TABLE IF EXISTS session_messages CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;

-- Create sessions table
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(64) NOT NULL,
    title VARCHAR(255),
    mode VARCHAR(20) DEFAULT 'daily',
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_message_at TIMESTAMP WITH TIME ZONE,
    message_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Constraints
    CONSTRAINT chk_session_mode CHECK (mode IN ('daily', 'focus', 'analysis', 'debug')),
    CONSTRAINT chk_session_status CHECK (status IN ('active', 'archived', 'deleted'))
);

-- Add table comment
COMMENT ON TABLE sessions IS '会话管理表 - 存储用户会话信息';
COMMENT ON COLUMN sessions.id IS '会话唯一标识 (UUID)';
COMMENT ON COLUMN sessions.user_id IS '用户ID';
COMMENT ON COLUMN sessions.title IS '会话标题';
COMMENT ON COLUMN sessions.mode IS '会话模式: daily(日常)/focus(专注)/analysis(分析)/debug(调试)';
COMMENT ON COLUMN sessions.status IS '会话状态: active(活跃)/archived(归档)/deleted(已删除)';
COMMENT ON COLUMN sessions.created_at IS '创建时间';
COMMENT ON COLUMN sessions.updated_at IS '最后更新时间';
COMMENT ON COLUMN sessions.last_message_at IS '最后消息时间';
COMMENT ON COLUMN sessions.message_count IS '消息数量统计';
COMMENT ON COLUMN sessions.metadata IS '扩展元数据 (JSONB格式)';

-- Create indexes for sessions table
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_updated_at ON sessions(updated_at DESC);
CREATE INDEX idx_sessions_user_status ON sessions(user_id, status);
CREATE INDEX idx_sessions_user_mode ON sessions(user_id, mode);
CREATE INDEX idx_sessions_last_message ON sessions(last_message_at DESC) WHERE last_message_at IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. session_messages table - 会话消息表
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE session_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    content_type VARCHAR(20) DEFAULT 'text',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    memory_id UUID,
    tool_calls JSONB,
    thinking TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    
    -- Constraints
    CONSTRAINT chk_message_role CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    CONSTRAINT chk_content_type CHECK (content_type IN ('text', 'image', 'audio', 'file', 'mixed'))
);

-- Add table comment
COMMENT ON TABLE session_messages IS '会话消息表 - 存储会话中的消息记录';
COMMENT ON COLUMN session_messages.id IS '消息唯一标识 (UUID)';
COMMENT ON COLUMN session_messages.session_id IS '所属会话ID (外键)';
COMMENT ON COLUMN session_messages.role IS '角色: user(用户)/assistant(助手)/system(系统)/tool(工具)';
COMMENT ON COLUMN session_messages.content IS '消息内容';
COMMENT ON COLUMN session_messages.content_type IS '内容类型: text(文本)/image(图片)/audio(音频)/file(文件)/mixed(混合)';
COMMENT ON COLUMN session_messages.created_at IS '创建时间';
COMMENT ON COLUMN session_messages.memory_id IS '关联的L2记忆ID (可选)';
COMMENT ON COLUMN session_messages.tool_calls IS '工具调用信息 (JSONB格式)';
COMMENT ON COLUMN session_messages.thinking IS 'AI思考过程记录';
COMMENT ON COLUMN session_messages.metadata IS '扩展元数据 (JSONB格式)';

-- Create indexes for session_messages table
CREATE INDEX idx_messages_session_created ON session_messages(session_id, created_at DESC);
CREATE INDEX idx_messages_session_role ON session_messages(session_id, role);
CREATE INDEX idx_messages_memory_id ON session_messages(memory_id) WHERE memory_id IS NOT NULL;
CREATE INDEX idx_messages_created_at ON session_messages(created_at DESC);

-- GIN index for JSONB columns (efficient JSON queries)
CREATE INDEX idx_messages_metadata ON session_messages USING GIN(metadata);
CREATE INDEX idx_messages_tool_calls ON session_messages USING GIN(tool_calls) WHERE tool_calls IS NOT NULL;

-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. Create trigger for auto-updating updated_at on sessions
-- ═══════════════════════════════════════════════════════════════════════════════

-- Create function to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger
DROP TRIGGER IF EXISTS update_sessions_updated_at ON sessions;
CREATE TRIGGER update_sessions_updated_at
    BEFORE UPDATE ON sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ═══════════════════════════════════════════════════════════════════════════════
-- 4. Verification Queries (Run manually to verify)
-- ═══════════════════════════════════════════════════════════════════════════════

-- Verify tables created
-- SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('sessions', 'session_messages');

-- Verify columns
-- SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('sessions', 'session_messages') ORDER BY table_name, ordinal_position;

-- Verify indexes
-- SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('sessions', 'session_messages');

-- Verify constraints
-- SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN ('sessions'::regclass, 'session_messages'::regclass);

-- ═══════════════════════════════════════════════════════════════════════════════
-- End of Script
-- ═══════════════════════════════════════════════════════════════════════════════
