/**
 * AlignmentDialog 使用示例
 * 
 * 本文件展示如何在实际项目中使用 AlignmentDialog 组件和 useAlignment Hook
 */

import React, { useState } from 'react';
import { AlignmentDialog } from './AlignmentDialog';
import { useAlignment, useAlignmentQueue } from '../hooks/useAlignment';

/**
 * 示例1：基础使用方式（推荐）
 * 使用 useAlignment Hook 监听 WebSocket 事件
 */
export const AlignmentDialogBasicExample: React.FC = () => {
  // 使用 hook 自动处理 WebSocket 事件
  const { 
    dialogProps, 
    sendClarification, 
    sendConfirmation, 
    cancelAlignment,
    pendingCount 
  } = useAlignment();

  return (
    <>
      {/* 在应用中放置对话框 */}
      <AlignmentDialog
        {...dialogProps}
        onConfirm={() => sendConfirmation(true)}
        onClarify={(response) => sendClarification(response)}
        onCancel={cancelAlignment}
      />
      
      {/* 显示待处理数量（可选） */}
      {pendingCount > 0 && (
        <div className="fixed bottom-4 right-4 bg-amber-500 text-white px-3 py-1 rounded-full text-sm">
          待确认: {pendingCount}
        </div>
      )}
    </>
  );
};

/**
 * 示例2：手动控制模式
 * 适用于需要手动触发对话框的场景
 */
export const AlignmentDialogManualExample: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [dialogType, setDialogType] = useState<'clarification' | 'confirmation'>('clarification');

  // 打开澄清对话框
  const openClarification = () => {
    setDialogType('clarification');
    setIsOpen(true);
  };

  // 打开确认对话框
  const openConfirmation = () => {
    setDialogType('confirmation');
    setIsOpen(true);
  };

  const handleClarify = (response: string) => {
    console.log('用户选择:', response);
    setIsOpen(false);
  };

  const handleConfirm = () => {
    console.log('用户确认');
    setIsOpen(false);
  };

  const handleCancel = () => {
    console.log('用户取消');
    setIsOpen(false);
  };

  return (
    <div className="p-6 space-y-4">
      <h2 className="text-xl font-bold text-white">手动控制示例</h2>
      
      <div className="flex gap-4">
        <button
          onClick={openClarification}
          className="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-lg"
        >
          测试澄清对话框
        </button>
        <button
          onClick={openConfirmation}
          className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg"
        >
          测试确认对话框
        </button>
      </div>

      <AlignmentDialog
        type={dialogType}
        question={
          dialogType === 'clarification'
            ? '您想要执行什么操作？'
            : '我理解正确吗？'
        }
        options={
          dialogType === 'clarification'
            ? ['创建文件', '编辑文件', '删除文件', '查看文件']
            : undefined
        }
        confirmMessage={
          dialogType === 'confirmation'
            ? '您想要创建一个名为 "example.txt" 的文件'
            : undefined
        }
        isOpen={isOpen}
        onConfirm={handleConfirm}
        onClarify={handleClarify}
        onCancel={handleCancel}
        timeout={30}
      />
    </div>
  );
};

/**
 * 示例3：使用队列的高级用法
 * Promise 风格的异步请求
 */
export const AlignmentDialogQueueExample: React.FC = () => {
  const { 
    queue, 
    requestClarification, 
    requestConfirmation,
    handleConfirm,
    handleClarify,
    handleCancel,
    hasPending 
  } = useAlignmentQueue();

  // 异步请求澄清
  const askForClarification = async () => {
    try {
      const response = await requestClarification(
        '您想要使用哪种编程语言？',
        ['Python', 'JavaScript', 'TypeScript', 'Java', 'Go'],
        60
      );
      console.log('用户选择了:', response);
      alert(`您选择了: ${response}`);
    } catch (error) {
      console.error('请求失败:', error);
    }
  };

  // 异步请求确认
  const askForConfirmation = async () => {
    try {
      const confirmed = await requestConfirmation(
        '请确认以下操作',
        '删除数据库中的所有记录',
        30
      );
      console.log('用户确认:', confirmed);
      alert(confirmed ? '已确认执行' : '已取消操作');
    } catch (error) {
      console.error('请求失败:', error);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <h2 className="text-xl font-bold text-white">队列示例（Promise风格）</h2>
      
      <div className="flex gap-4">
        <button
          onClick={askForClarification}
          disabled={hasPending}
          className="px-4 py-2 bg-purple-500 hover:bg-purple-600 disabled:opacity-50 
                   text-white rounded-lg transition-colors"
        >
          询问编程语言
        </button>
        <button
          onClick={askForConfirmation}
          disabled={hasPending}
          className="px-4 py-2 bg-red-500 hover:bg-red-600 disabled:opacity-50 
                   text-white rounded-lg transition-colors"
        >
          确认危险操作
        </button>
      </div>

      {/* 队列对话框 */}
      {queue.length > 0 && (
        <AlignmentDialog
          type={queue[0].type}
          question={queue[0].question}
          options={queue[0].options}
          confirmMessage={queue[0].confirmMessage}
          isOpen={true}
          timeout={queue[0].timeout}
          onConfirm={() => handleConfirm(queue[0].id)}
          onClarify={(response) => handleClarify(queue[0].id, response)}
          onCancel={() => handleCancel(queue[0].id)}
        />
      )}
    </div>
  );
};

/**
 * 示例4：与聊天界面集成
 */
export const AlignmentDialogChatIntegration: React.FC = () => {
  const { dialogProps, sendClarification, sendConfirmation, cancelAlignment } = useAlignment();

  return (
    <div className="relative h-screen flex flex-col bg-gray-900">
      {/* 聊天消息区域 */}
      <div className="flex-1 overflow-auto p-4">
        {/* 这里放置聊天消息 */}
        <div className="space-y-4">
          <div className="flex justify-start">
            <div className="bg-gray-800 text-white rounded-lg px-4 py-2 max-w-md">
              您好！有什么可以帮助您的吗？
            </div>
          </div>
        </div>
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t border-gray-800">
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="输入消息..."
            className="flex-1 bg-gray-800 text-white rounded-lg px-4 py-2 
                     focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button className="px-4 py-2 bg-blue-500 hover:bg-blue-600 text-white rounded-lg">
            发送
          </button>
        </div>
      </div>

      {/* 对齐对话框 - 覆盖在聊天界面上 */}
      <AlignmentDialog
        {...dialogProps}
        onConfirm={() => sendConfirmation(true)}
        onClarify={(response) => sendClarification(response)}
        onCancel={cancelAlignment}
      />
    </div>
  );
};

/**
 * 示例5：完整演示页面
 */
export const AlignmentDialogDemo: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'basic' | 'manual' | 'queue' | 'chat'>('basic');

  return (
    <div className="min-h-screen bg-gray-900 p-6">
      <h1 className="text-3xl font-bold text-white mb-8">AlignmentDialog 组件演示</h1>
      
      {/* Tab 切换 */}
      <div className="flex gap-2 mb-6 border-b border-gray-800">
        {(['basic', 'manual', 'queue', 'chat'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm font-medium transition-colors
                      ${activeTab === tab 
                        ? 'text-blue-400 border-b-2 border-blue-400' 
                        : 'text-gray-400 hover:text-gray-300'
                      }`}
          >
            {tab === 'basic' && '基础使用'}
            {tab === 'manual' && '手动控制'}
            {tab === 'queue' && '队列模式'}
            {tab === 'chat' && '聊天集成'}
          </button>
        ))}
      </div>

      {/* 内容区域 */}
      <div className="bg-gray-800/50 rounded-xl p-6">
        {activeTab === 'basic' && <AlignmentDialogBasicExample />}
        {activeTab === 'manual' && <AlignmentDialogManualExample />}
        {activeTab === 'queue' && <AlignmentDialogQueueExample />}
        {activeTab === 'chat' && <AlignmentDialogChatIntegration />}
      </div>
    </div>
  );
};

export default AlignmentDialogDemo;
