/**
 * TaskControlPanel 集成示例
 * 
 * 展示如何在不同场景中使用 TaskControlPanel 组件
 */

import React, { useState } from 'react';
import { TaskControlPanel } from './TaskControlPanel';
import { TaskState } from '@/utils/api/task';

// 示例1: 基础用法
export const BasicExample: React.FC = () => {
  return (
    <div style={{ padding: '20px', maxWidth: '500px' }}>
      <h3>基础用法</h3>
      <TaskControlPanel
        taskId="task-demo-001"
        sessionId="session-demo-001"
        initialStatus="running"
      />
    </div>
  );
};

// 示例2: 带状态变更回调
export const WithCallbackExample: React.FC = () => {
  const [lastStatus, setLastStatus] = useState<TaskState>('running');

  return (
    <div style={{ padding: '20px', maxWidth: '500px' }}>
      <h3>带状态变更回调</h3>
      <p>上次状态变更: {lastStatus}</p>
      <TaskControlPanel
        taskId="task-demo-002"
        sessionId="session-demo-002"
        initialStatus="running"
        onStatusChange={(status) => {
          setLastStatus(status);
          console.log('任务状态变更为:', status);
        }}
      />
    </div>
  );
};

// 示例3: 不同状态的展示
export const DifferentStatesExample: React.FC = () => {
  return (
    <div style={{ padding: '20px' }}>
      <h3>不同状态展示</h3>
      
      <div style={{ marginBottom: '20px' }}>
        <h4>运行中状态</h4>
        <TaskControlPanel
          taskId="task-running"
          sessionId="session-running"
          initialStatus="running"
        />
      </div>

      <div style={{ marginBottom: '20px' }}>
        <h4>已暂停状态</h4>
        <TaskControlPanel
          taskId="task-paused"
          sessionId="session-paused"
          initialStatus="paused"
        />
      </div>

      <div style={{ marginBottom: '20px' }}>
        <h4>已完成状态</h4>
        <TaskControlPanel
          taskId="task-completed"
          sessionId="session-completed"
          initialStatus="completed"
        />
      </div>

      <div style={{ marginBottom: '20px' }}>
        <h4>失败状态</h4>
        <TaskControlPanel
          taskId="task-failed"
          sessionId="session-failed"
          initialStatus="failed"
        />
      </div>
    </div>
  );
};

// 示例4: 在任务卡片中集成
interface TaskCardWithControlProps {
  task: {
    id: string;
    title: string;
    status: TaskState;
    session_id: string;
  };
  onRefresh?: () => void;
}

export const TaskCardWithControl: React.FC<TaskCardWithControlProps> = ({
  task,
  onRefresh,
}) => {
  return (
    <div
      style={{
        background: 'rgba(30, 41, 59, 0.8)',
        borderRadius: '12px',
        padding: '20px',
        marginBottom: '16px',
        border: '1px solid rgba(255, 255, 255, 0.1)',
      }}
    >
      <div style={{ marginBottom: '16px' }}>
        <h4 style={{ color: '#fff', margin: '0 0 8px 0' }}>{task.title}</h4>
        <p style={{ color: 'rgba(255, 255, 255, 0.6)', fontSize: '13px', margin: 0 }}>
          ID: {task.id}
        </p>
      </div>

      <TaskControlPanel
        taskId={task.id}
        sessionId={task.session_id}
        initialStatus={task.status}
        onStatusChange={(newStatus) => {
          console.log(`任务 ${task.id} 状态变更为 ${newStatus}`);
          onRefresh?.();
        }}
      />
    </div>
  );
};

// 示例5: 完整任务列表示例
export const TaskListExample: React.FC = () => {
  const [tasks, setTasks] = useState([
    {
      id: 'task-001',
      title: '开发新功能模块',
      status: 'running' as TaskState,
      session_id: 'session-001',
    },
    {
      id: 'task-002',
      title: '修复登录Bug',
      status: 'paused' as TaskState,
      session_id: 'session-002',
    },
    {
      id: 'task-003',
      title: '编写API文档',
      status: 'completed' as TaskState,
      session_id: 'session-003',
    },
  ]);

  const handleStatusChange = (taskId: string, newStatus: TaskState) => {
    setTasks((prev) =>
      prev.map((task) =>
        task.id === taskId ? { ...task, status: newStatus } : task
      )
    );
  };

  return (
    <div style={{ padding: '20px', maxWidth: '600px' }}>
      <h3>任务列表示例</h3>
      {tasks.map((task) => (
        <div
          key={task.id}
          style={{
            background: 'rgba(30, 41, 59, 0.8)',
            borderRadius: '12px',
            padding: '20px',
            marginBottom: '16px',
            border: '1px solid rgba(255, 255, 255, 0.1)',
          }}
        >
          <div style={{ marginBottom: '16px' }}>
            <h4 style={{ color: '#fff', margin: '0 0 8px 0' }}>{task.title}</h4>
            <p style={{ color: 'rgba(255, 255, 255, 0.6)', fontSize: '13px', margin: 0 }}>
              ID: {task.id}
            </p>
          </div>

          <TaskControlPanel
            taskId={task.id}
            sessionId={task.session_id}
            initialStatus={task.status}
            onStatusChange={(newStatus) => handleStatusChange(task.id, newStatus)}
          />
        </div>
      ))}
    </div>
  );
};

// 默认导出所有示例
export default {
  BasicExample,
  WithCallbackExample,
  DifferentStatesExample,
  TaskCardWithControl,
  TaskListExample,
};
