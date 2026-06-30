/**
 * TradingModeSelector.tsx
 * 交易模式选择器组件
 * 
 * 支持三种模式切换：
 * - 全自动量化 (auto): 专业策略，24/7自动运行
 * - AI辅助交易 (ai): AI实时决策，消息驱动
 * - 手动交易 (manual): K线分析，自主决策
 */

import React from 'react';
import { Bot, Brain, MousePointer, TrendingUp } from 'lucide-react';

export type TradingMode = 'auto' | 'ai' | 'manual';

export interface TradingModeInfo {
  id: TradingMode;
  label: string;
  description: string;
  icon: React.ElementType;
  color: 'blue' | 'purple' | 'green';
  suitable: string;
  features: string[];
  riskLevel: 'high' | 'medium' | 'low';
}

interface TradingModeSelectorProps {
  currentMode: TradingMode;
  onModeChange: (mode: TradingMode) => void;
  disabled?: boolean;
}

export const TRADING_MODES: TradingModeInfo[] = [
  {
    id: 'auto',
    label: '机器人自动交易',
    description: '24小时自动买卖，无需盯盘',
    icon: Bot,
    color: 'blue',
    suitable: 'BTC、ETH等主流合约',
    features: ['自动执行', '严格风控', '全天候运行'],
    riskLevel: 'medium',
  },
  {
    id: 'ai',
    label: 'AI给出建议，你来决定',
    description: 'AI分析市场并推荐操作，你确认后才执行',
    icon: Brain,
    color: 'purple',
    suitable: 'DOGE、SHIB等Meme币',
    features: ['AI分析', '看新闻判市场', '每一步可解释'],
    riskLevel: 'high',
  },
  {
    id: 'manual',
    label: '手动交易',
    description: '自己看K线，自己决定买卖',
    icon: MousePointer,
    color: 'green',
    suitable: '任意币种',
    features: ['技术分析', '完全控制', '实时下单'],
    riskLevel: 'low',
  },
];

const getRiskBadge = (riskLevel: 'high' | 'medium' | 'low') => {
  const configs = {
    high: { color: 'text-red-400', bg: 'bg-red-500/10', text: '高风险' },
    medium: { color: 'text-yellow-400', bg: 'bg-yellow-500/10', text: '中风险' },
    low: { color: 'text-green-400', bg: 'bg-green-500/10', text: '低风险' },
  };
  const config = configs[riskLevel];
  return (
    <span className={`px-2 py-0.5 rounded text-xs ${config.color} ${config.bg}`}>
      {config.text}
    </span>
  );
};

export const TradingModeSelector: React.FC<TradingModeSelectorProps> = ({
  currentMode,
  onModeChange,
  disabled = false,
}) => {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {TRADING_MODES.map((mode) => {
        const Icon = mode.icon;
        const isActive = currentMode === mode.id;
        const isDisabled = disabled && !isActive;
        
        const colorClasses = {
          blue: {
            active: 'bg-blue-500/10 border-blue-500',
            inactive: 'bg-gray-800 border-gray-700 hover:border-blue-500/50',
            icon: 'text-blue-400',
          },
          purple: {
            active: 'bg-purple-500/10 border-purple-500',
            inactive: 'bg-gray-800 border-gray-700 hover:border-purple-500/50',
            icon: 'text-purple-400',
          },
          green: {
            active: 'bg-green-500/10 border-green-500',
            inactive: 'bg-gray-800 border-gray-700 hover:border-green-500/50',
            icon: 'text-green-400',
          },
        }[mode.color];
        
        return (
          <button
            key={mode.id}
            onClick={() => !isDisabled && onModeChange(mode.id)}
            disabled={isDisabled}
            className={`
              relative p-5 rounded-xl border-2 transition-all text-left group
              ${isActive ? colorClasses.active : colorClasses.inactive}
              ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
            `}
          >
            {/* 选中标记 */}
            {isActive && (
              <div className="absolute top-3 right-3">
                <div className={`w-3 h-3 rounded-full bg-${mode.color}-500`} />
              </div>
            )}
            
            {/* 图标和标题 */}
            <div className="flex items-center gap-3 mb-3">
              <div className={`
                p-2.5 rounded-lg transition-colors
                ${isActive ? `bg-${mode.color}-500/20` : 'bg-gray-700 group-hover:bg-gray-600'}
              `}>
                <Icon className={`w-6 h-6 ${colorClasses.icon}`} />
              </div>
              <div>
                <h3 className={`font-semibold ${isActive ? 'text-white' : 'text-gray-300'}`}>
                  {mode.label}
                </h3>
                {getRiskBadge(mode.riskLevel)}
              </div>
            </div>
            
            {/* 描述 */}
            <p className="text-sm text-gray-400 mb-3">
              {mode.description}
            </p>
            
            {/* 特性列表 */}
            <div className="flex flex-wrap gap-1.5 mb-3">
              {mode.features.map((feature, idx) => (
                <span
                  key={idx}
                  className={`
                    px-2 py-0.5 rounded text-xs
                    ${isActive 
                      ? `bg-${mode.color}-500/20 text-${mode.color}-300` 
                      : 'bg-gray-700/50 text-gray-400'}
                  `}
                >
                  {feature}
                </span>
              ))}
            </div>
            
            {/* 适合币种 */}
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <TrendingUp className="w-3.5 h-3.5" />
              <span>适合: {mode.suitable}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
};

export default TradingModeSelector;
