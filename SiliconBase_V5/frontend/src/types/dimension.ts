/**
 * 维度筛选类型定义
 * Dimension Filter Types
 */

// 六维价值评估维度
export type DimensionKey = 
  | 'emotional_temperature'  // 情感温度
  | 'ethical_safety'         // 伦理安全
  | 'self_growth'            // 自我成长
  | 'execution_effectiveness' // 执行成效
  | 'sustainability'         // 存续保障
  | 'inspiration_innovation'; // 灵感创新

// 维度信息
export interface DimensionInfo {
  key: DimensionKey;
  label: string;
  icon: string;
  weight: string;
  weightValue: number; // 权重数值 (0-1)
}

// 维度配置
export const DIMENSIONS_CONFIG: DimensionInfo[] = [
  { key: 'emotional_temperature', label: '情感温度', icon: '🤗', weight: '25%', weightValue: 0.25 },
  { key: 'ethical_safety', label: '伦理安全', icon: '⚖️', weight: '20%', weightValue: 0.20 },
  { key: 'self_growth', label: '自我成长', icon: '🌱', weight: '20%', weightValue: 0.20 },
  { key: 'execution_effectiveness', label: '执行成效', icon: '✅', weight: '15%', weightValue: 0.15 },
  { key: 'sustainability', label: '存续保障', icon: '🛡️', weight: '15%', weightValue: 0.15 },
  { key: 'inspiration_innovation', label: '灵感创新', icon: '💫', weight: '5%', weightValue: 0.05 }
];

// 等级类型
export type Grade = 'S' | 'A' | 'B' | 'C' | 'D';

// 等级配置
export const GRADES_CONFIG: Grade[] = ['S', 'A', 'B', 'C', 'D'];

// 等级颜色映射
export const GRADE_COLORS: Record<Grade, { bg: string; text: string; border: string }> = {
  S: { bg: 'bg-yellow-500', text: 'text-yellow-400', border: 'border-yellow-500/30' },
  A: { bg: 'bg-green-500', text: 'text-green-400', border: 'border-green-500/30' },
  B: { bg: 'bg-blue-500', text: 'text-blue-400', border: 'border-blue-500/30' },
  C: { bg: 'bg-gray-500', text: 'text-gray-400', border: 'border-gray-500/30' },
  D: { bg: 'bg-red-500', text: 'text-red-400', border: 'border-red-500/30' }
};

// 维度筛选状态
export interface DimensionFilterState {
  selectedDimensions: DimensionKey[];
  minScores: Record<DimensionKey, number>;
}

// 维度筛选参数 (用于API请求)
export interface DimensionFilterParams {
  dimension_weights?: Record<DimensionKey, number>;
  min_dimension_scores?: Partial<Record<DimensionKey, number>>;
  grades?: Grade[];
}

// 维度筛选组件Props
export interface DimensionFilterProps {
  selectedDimensions: DimensionKey[];
  minScores: Partial<Record<DimensionKey, number>>;
  onDimensionToggle: (dimension: DimensionKey) => void;
  onMinScoreChange: (dimension: DimensionKey, score: number) => void;
  onApply: () => void;
  onReset: () => void;
  isOpen: boolean;
  onClose: () => void;
}

// 等级筛选组件Props
export interface GradeFilterProps {
  selectedGrades: Grade[];
  onChange: (grades: Grade[]) => void;
}

// 价值评估V2
export interface ValueAssessmentV2 {
  overall_score: number;
  overall_grade: Grade;
  dimension_scores: Record<string, number>;
  will_affect_behavior: boolean;
  emotional_impact?: Record<string, number>;
  suggested_reflection?: string;
  growth_insights?: string[];
  ethical_notes?: string[];
}

// 维度分数范围
export const DIMENSION_SCORE_MIN = 1;
export const DIMENSION_SCORE_MAX = 5;
export const DIMENSION_SCORE_STEP = 0.5;
export const DIMENSION_SCORE_DEFAULT = 3;

// 获取维度标签
export function getDimensionLabel(key: DimensionKey): string {
  const dim = DIMENSIONS_CONFIG.find(d => d.key === key);
  return dim?.label || key;
}

// 获取维度图标
export function getDimensionIcon(key: DimensionKey): string {
  const dim = DIMENSIONS_CONFIG.find(d => d.key === key);
  return dim?.icon || '📊';
}

// 获取维度权重
export function getDimensionWeight(key: DimensionKey): string {
  const dim = DIMENSIONS_CONFIG.find(d => d.key === key);
  return dim?.weight || '0%';
}

// 验证分数是否在有效范围内
export function isValidDimensionScore(score: number): boolean {
  return score >= DIMENSION_SCORE_MIN && 
         score <= DIMENSION_SCORE_MAX && 
         (score * 2) % 1 === 0; // 确保是0.5的倍数
}

// 格式化分数显示
export function formatDimensionScore(score: number): string {
  return score.toFixed(1);
}
