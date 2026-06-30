/**
 * 组件统一导出
 * Phase 4.5: 前端槽位显示增强
 */

// ========== 原始组件导出（向后兼容）==========
export { LongTaskSlotsPanel } from './LongTaskSlotsPanel';

// 聊天区域容器
export { default as ChatArea } from './ChatArea';

// ========== Phase 4.5 新增增强组件 ==========

// 增强版槽位面板
export { 
  EnhancedSlotsPanel, 
  LongTaskSlotsPanel as EnhancedLongTaskSlotsPanel 
} from './EnhancedSlotsPanel';

// 增强版槽位卡片
export { EnhancedSlotCard } from './EnhancedSlotCard';

// 验收面板
export { VerificationPanel } from './VerificationPanel';

// ========== 类型重新导出（方便使用）==========
export type {
  // 增强槽位类型
  EnhancedSlotTask,
  SlotTaskType,
  SlotStatus,
  VerificationState,
  SlotProgress,
  WorkflowInfo,
  SubagentInfo,
  VerificationStatus,
  CheckpointInfo,
  SlotControls,
  VerificationPanelProps,
  EnhancedSlotCardProps,
  // 基础槽位类型（向后兼容）
  SlotTask
} from '../types/slot';
