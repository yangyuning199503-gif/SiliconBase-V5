/**
 * TaskControlPanel - 任务控制面板组件
 * 
 * 功能：
 * - 显示任务状态（支持轮询同步）
 * - 暂停/恢复任务（支持 failed/interrupted 恢复）
 * - 暂停确认对话框
 * - 状态变更回调
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import { 
  PauseCircleOutlined, 
  PlayCircleOutlined,
  InfoCircleOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
  SyncOutlined
} from '@ant-design/icons';
import { Button, Modal, message, Tag, Tooltip } from 'antd';
import { taskApi, TaskState, type TaskControlPanelProps } from '@/utils/api/task';
import { APIError } from '@/utils/api/core';

// 样式常量
const STYLES = {
  panel: {
    background: 'rgba(30, 41, 59, 0.5)',
    borderRadius: '12px',
    padding: '16px',
    border: '1px solid rgba(255, 255, 255, 0.1)',
  },
  statusSection: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: '16px',
  },
  infoBox: {
    marginTop: '16px',
    padding: '12px 16px',
    background: 'rgba(15, 23, 42, 0.6)',
    borderRadius: '8px',
    border: '1px solid rgba(255, 255, 255, 0.05)',
  },
  infoList: {
    margin: '8px 0 0 0',
    paddingLeft: '20px',
    color: 'rgba(255, 255, 255, 0.6)',
    fontSize: '13px',
    lineHeight: '1.8',
  },
} as const;

/**
 * 获取状态标签配置
 */
const getStatusConfig = (status: TaskState) => {
  const configs: Record<string, { color: string; icon: React.ReactNode; text: string }> = {
    pending: { color: 'default', icon: <InfoCircleOutlined />, text: '待处理' },
    running: { color: 'success', icon: <PlayCircleOutlined />, text: '运行中' },
    paused: { color: 'warning', icon: <PauseCircleOutlined />, text: '已暂停' },
    completed: { color: 'success', icon: <CheckCircleOutlined />, text: '已完成' },
    failed: { color: 'error', icon: <ExclamationCircleOutlined />, text: '失败' },
    cancelled: { color: 'default', icon: <InfoCircleOutlined />, text: '已取消' },
    archived: { color: 'default', icon: <InfoCircleOutlined />, text: '已归档' },
    interrupted: { color: 'warning', icon: <SyncOutlined spin />, text: '已中断' },
    ready: { color: 'processing', icon: <InfoCircleOutlined />, text: '就绪' },
  };
  return configs[status] || configs.pending;
};

export const TaskControlPanel: React.FC<TaskControlPanelProps> = ({
  taskId,
  sessionId,
  initialStatus = 'running',
  onStatusChange,
}) => {
  // 状态
  const [status, setStatus] = useState<TaskState>(initialStatus);
  const [loading, setLoading] = useState(false);
  const [isPauseModalVisible, setIsPauseModalVisible] = useState(false);
  const [isResumeModalVisible, setIsResumeModalVisible] = useState(false);

  // 暂停任务 - 【关键修复】处理checkpoint_id
  const [_checkpointId, setCheckpointId] = useState<string | null>(null);
  
  // 轮询定时器引用
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 同步后端真实状态
  const syncStatus = useCallback(async () => {
    if (!taskId) return;
    try {
      const task = await taskApi.getTask(taskId);
      if (task && task.status) {
        const newStatus = task.status as TaskState;
        if (newStatus !== status) {
          setStatus(newStatus);
          onStatusChange?.(newStatus);
        }
      }
    } catch (error) {
      // 静默失败，不影响用户操作
      console.debug('[TaskControl] 状态同步失败:', error);
    }
  }, [taskId, status, onStatusChange]);

  // 启动/停止轮询
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return;
    pollTimerRef.current = setInterval(() => {
      syncStatus();
    }, 3000);
  }, [syncStatus]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  // 组件挂载时同步一次状态，并根据状态决定是否轮询
  useEffect(() => {
    syncStatus();
  }, [syncStatus]);

  // 状态变化时管理轮询
  useEffect(() => {
    if (status === 'running' || status === 'paused') {
      startPolling();
    } else {
      stopPolling();
    }
    return () => stopPolling();
  }, [status, startPolling, stopPolling]);

  const handlePause = useCallback(async (reason: string = '用户主动暂停') => {
    setLoading(true);
    
    try {
      const result = await taskApi.pauseTask(taskId, { 
        reason,
        session_id: sessionId,
      });
      
      if (result.success) {
        setStatus('paused');
        
        if (result.checkpoint_id) {
          setCheckpointId(result.checkpoint_id);
          console.log('[TaskControl] Checkpoint已保存:', result.checkpoint_id);
        }
        
        const phaseCount = result.phase_count || 0;
        message.success(
          <span>
            任务已暂停
            {phaseCount > 0 && (
              <span style={{ fontSize: '12px', opacity: 0.8, marginLeft: '8px' }}>
                (已保存 {phaseCount} 个阶段锚点)
              </span>
            )}
          </span>
        );
        
        onStatusChange?.('paused');
      } else {
        const errorMsg = result.error || '暂停任务失败';
        message.error(errorMsg);
        console.error('[TaskControl] 暂停任务失败:', errorMsg);
      }
    } catch (error) {
      const errorMessage = error instanceof APIError 
        ? error.message 
        : error instanceof Error 
          ? error.message 
          : '暂停任务失败';
      
      message.error(`暂停任务失败: ${errorMessage}`);
      console.error('[TaskControl] 暂停任务异常:', error);
    } finally {
      setLoading(false);
      setIsPauseModalVisible(false);
    }
  }, [taskId, sessionId, onStatusChange]);

  // 恢复任务
  const handleResume = useCallback(async (aiConfirmation?: string) => {
    setLoading(true);
    
    try {
      const result = await taskApi.resumeTask(taskId, {
        ai_confirmation: aiConfirmation,
        confirmed_understanding: !!aiConfirmation,
        session_id: sessionId,
      });
      
      if (result.success) {
        setStatus('running');
        message.success('任务已恢复');
        onStatusChange?.('running');
      } else {
        const errorMsg = result.error || '恢复任务失败';
        message.error(errorMsg);
        console.error('[TaskControl] 恢复任务失败:', errorMsg);
      }
    } catch (error) {
      const errorMessage = error instanceof APIError 
        ? error.message 
        : error instanceof Error 
          ? error.message 
          : '恢复任务失败';
      
      message.error(`恢复任务失败: ${errorMessage}`);
      console.error('[TaskControl] 恢复任务异常:', error);
    } finally {
      setLoading(false);
      setIsResumeModalVisible(false);
    }
  }, [taskId, onStatusChange]);

  const showPauseModal = useCallback(() => {
    setIsPauseModalVisible(true);
  }, []);

  const showResumeModal = useCallback(() => {
    setIsResumeModalVisible(true);
  }, []);

  const handlePauseCancel = useCallback(() => {
    setIsPauseModalVisible(false);
  }, []);

  const handleResumeCancel = useCallback(() => {
    setIsResumeModalVisible(false);
  }, []);

  const statusConfig = getStatusConfig(status);

  // 判断是否可操作
  const canPause = status === 'running';
  const canResume = ['paused', 'failed', 'interrupted'].includes(status);
  const isCompleted = status === 'completed';
  const isFailedOrInterrupted = status === 'failed' || status === 'interrupted';

  return (
    <div style={STYLES.panel} className="task-control-panel">
      {/* 状态显示 */}
      <div style={STYLES.statusSection}>
        <div className="task-status">
          <span style={{ color: 'rgba(255, 255, 255, 0.6)', marginRight: '8px' }}>
            任务状态:
          </span>
          <Tag 
            color={statusConfig.color}
            icon={statusConfig.icon}
            style={{ fontSize: '13px', padding: '2px 8px' }}
          >
            {statusConfig.text}
          </Tag>
        </div>
        
        {/* 会话ID提示 */}
        <Tooltip title={`会话ID: ${sessionId || '未定义'}`}>
          <span style={{ color: 'rgba(255, 255, 255, 0.4)', fontSize: '12px' }}>
            {(sessionId || 'unknown').slice(0, 8)}...
          </span>
        </Tooltip>
      </div>
      
      {/* 操作按钮 */}
      <div className="task-actions" style={{ display: 'flex', gap: '12px' }}>
        {canPause && (
          <Button
            type="primary"
            danger
            size="large"
            icon={<PauseCircleOutlined />}
            onClick={showPauseModal}
            loading={loading}
            style={{ 
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px'
            }}
          >
            暂停任务
          </Button>
        )}
        
        {canResume && (
          <Button
            type="primary"
            size="large"
            icon={<PlayCircleOutlined />}
            onClick={showResumeModal}
            loading={loading}
            style={{ 
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
              backgroundColor: '#52c41a',
              borderColor: '#52c41a'
            }}
          >
            {isFailedOrInterrupted ? '恢复任务（重试）' : '恢复任务'}
          </Button>
        )}

        {isCompleted && (
          <Button
            type="default"
            size="large"
            disabled
            icon={<CheckCircleOutlined />}
            style={{ flex: 1 }}
          >
            任务已完成
          </Button>
        )}

        {status === 'cancelled' && (
          <Button
            type="default"
            size="large"
            disabled
            icon={<InfoCircleOutlined />}
            style={{ flex: 1 }}
          >
            任务已取消
          </Button>
        )}
      </div>

      {/* 暂停确认对话框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <PauseCircleOutlined style={{ color: '#ff4d4f' }} />
            <span>暂停任务</span>
          </div>
        }
        open={isPauseModalVisible}
        onOk={() => handlePause('用户主动暂停')}
        onCancel={handlePauseCancel}
        confirmLoading={loading}
        okText="确认暂停"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        width={480}
        centered
      >
        <div style={{ padding: '8px 0' }}>
          <p style={{ fontSize: '15px', marginBottom: '12px' }}>
            确定要暂停当前任务吗？
          </p>
          <p style={{ color: 'rgba(0, 0, 0, 0.45)', marginBottom: '16px' }}>
            暂停后可以随时恢复，所有进度都会保存。
          </p>
          
          <div style={{
            padding: '16px',
            background: '#f5f5f5',
            borderRadius: '8px',
            border: '1px solid #e8e8e8'
          }}>
            <strong style={{ color: '#262626' }}>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: '8px' }} />
              暂停后保存的内容：
            </strong>
            <ul style={{
              margin: '12px 0 0 0',
              paddingLeft: '24px',
              color: '#595959',
              lineHeight: '1.8'
            }}>
              <li>已完成的工作步骤</li>
              <li>当前的执行进度</li>
              <li>所有的阶段锚点信息</li>
              <li>工作记忆中的上下文</li>
            </ul>
          </div>
        </div>
      </Modal>

      {/* 恢复任务对话框 */}
      <Modal
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <PlayCircleOutlined style={{ color: '#52c41a' }} />
            <span>恢复任务</span>
          </div>
        }
        open={isResumeModalVisible}
        onOk={() => handleResume()}
        onCancel={handleResumeCancel}
        confirmLoading={loading}
        okText="确认恢复"
        cancelText="取消"
        width={480}
        centered
      >
        <div style={{ padding: '8px 0' }}>
          <p style={{ fontSize: '15px', marginBottom: '12px' }}>
            {isFailedOrInterrupted 
              ? '确定要恢复当前任务吗？将从断点重试。' 
              : '确定要恢复当前任务吗？'}
          </p>
          <p style={{ color: 'rgba(0, 0, 0, 0.45)', marginBottom: '16px' }}>
            任务将从{isFailedOrInterrupted ? '断点' : '暂停前状态'}继续执行。
          </p>
          
          <div style={{
            padding: '16px',
            background: '#f6ffed',
            borderRadius: '8px',
            border: '1px solid #b7eb8f'
          }}>
            <strong style={{ color: '#389e0d' }}>
              <InfoCircleOutlined style={{ marginRight: '8px' }} />
              恢复后任务将：
            </strong>
            <ul style={{
              margin: '12px 0 0 0',
              paddingLeft: '24px',
              color: '#389e0d',
              lineHeight: '1.8'
            }}>
              <li>从断点继续执行</li>
              <li>保留所有已完成的进度</li>
              <li>恢复工作记忆上下文</li>
            </ul>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default TaskControlPanel;
