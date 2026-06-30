/**
 * 记忆展示组件库
 * Phase 5 Week 9 - 用户体验优化
 */

export { default as MemoryPanel } from './MemoryPanel';
export { default as MemoryCard } from './MemoryCard';
export { default as MemoryAwareness, MemoryAwarenessInline } from './MemoryAwareness';

// 新增组件
export { default as EditableTitle } from '../EditableTitle';
export { default as HighlightText } from '../HighlightText';
export { default as LazyImage, ImageGallery, CachedImage } from '../LazyImage';
export {
  ErrorBoundary,
  GlobalErrorHandler,
  useNetworkStatus,
  OfflineBanner,
  NetworkIndicator,
  APIErrorToast,
  triggerApiError,
  isNetworkError
} from '../ErrorHandler';

// 类型定义
import type { Memory } from '../../utils/api/memory';

export interface MemoryCardProps {
  memory: Memory;
  onDelete?: (id: string) => void;
  onToggleImportant?: (id: string, important: boolean) => void;
  isImportant?: boolean;
  compact?: boolean;
}

export interface MemoryAwarenessProps {
  memoryCount: number;
  memoryIds?: string[] | null;
  onClick?: () => void;
  relevanceScore?: number;
  memoryTypes?: string[] | null;
  className?: string;
}
