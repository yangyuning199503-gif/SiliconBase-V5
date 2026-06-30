/**
 * 提示词变体选择器
 * SiliconBase V5 - Variant Selector Component
 * 
 * 功能：
 *   ✓ 显示当前模块的所有变体
 *   ✓ 一键切换变体
 *   ✓ 显示各变体的Token数和失败率
 *   ✓ 智能推荐最优变体
 */

import React, { useMemo } from 'react';
import { GitBranch, Check, AlertTriangle, Zap, BarChart3 } from 'lucide-react';
import { PromptVariant } from '../types/prompt';

interface VariantSelectorProps {
  variants: PromptVariant[];
  selectedVariantId: string;
  onChange: (variantId: string) => void;
  currentTokenCount?: number;
  budgetLimit?: number;
  className?: string;
}

export const VariantSelector: React.FC<VariantSelectorProps> = ({
  variants,
  selectedVariantId,
  onChange,
  currentTokenCount: _currentTokenCount,
  budgetLimit = 1500,
  className = ''
}) => {
  // 按推荐程度排序变体
  const sortedVariants = useMemo(() => {
    return [...variants].sort((a, b) => {
      // 默认变体排前面
      if (a.isDefault !== b.isDefault) return a.isDefault ? -1 : 1;
      // 失败率低的排前面
      return a.failureRate - b.failureRate;
    });
  }, [variants]);

  // 找出最优变体（Pareto最优：失败率最低且token适中）
  const optimalVariant = useMemo(() => {
    const validVariants = variants.filter(v => v.tokenCount <= budgetLimit);
    if (validVariants.length === 0) return variants.reduce((min, v) => 
      v.tokenCount < min.tokenCount ? v : min
    );
    
    return validVariants.reduce((best, v) => 
      v.failureRate < best.failureRate ? v : best
    );
  }, [variants, budgetLimit]);

  // 判断是否超预算
  const isOverBudget = (variant: PromptVariant) => {
    return variant.tokenCount > budgetLimit;
  };

  return (
    <div className={`bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden ${className}`}>
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 bg-white/5">
        <div className="flex items-center gap-2">
          <GitBranch className="w-5 h-5 text-sb-cyan" />
          <span className="font-medium text-sb-text-primary">提示词变体</span>
        </div>
        
        {/* 智能推荐提示 */}
        {optimalVariant && optimalVariant.id !== selectedVariantId && (
          <button
            onClick={() => onChange(optimalVariant.id)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-500/20 text-green-400 rounded-lg hover:bg-green-500/30 transition-colors"
          >
            <Zap className="w-4 h-4" />
            <span>推荐: {optimalVariant.name}</span>
          </button>
        )}
      </div>

      {/* 变体列表 */}
      <div className="divide-y divide-white/5">
        {sortedVariants.map((variant) => {
          const isSelected = variant.id === selectedVariantId;
          const overBudget = isOverBudget(variant);
          const hasHighFailureRate = variant.failureRate > 0.1;

          return (
            <button
              key={variant.id}
              onClick={() => onChange(variant.id)}
              className={`w-full text-left p-4 transition-all ${
                isSelected 
                  ? 'bg-sb-cyan/10 border-l-4 border-l-sb-cyan' 
                  : 'hover:bg-white/5 border-l-4 border-l-transparent'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  {/* 变体名称和标签 */}
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sb-text-primary">
                      {variant.name}
                    </span>
                    
                    {variant.isDefault && (
                      <span className="px-1.5 py-0.5 text-xs bg-blue-500/20 text-blue-400 rounded">
                        默认
                      </span>
                    )}
                    
                    {isSelected && (
                      <Check className="w-4 h-4 text-green-400" />
                    )}
                  </div>

                  {/* 描述 */}
                  <p className="text-sm text-sb-text-secondary mb-2">
                    {variant.description}
                  </p>

                  {/* 指标 */}
                  <div className="flex items-center gap-4 text-xs">
                    {/* Token数 */}
                    <div className={`flex items-center gap-1 ${
                      overBudget ? 'text-red-400' : 'text-sb-text-secondary'
                    }`}>
                      <BarChart3 className="w-3.5 h-3.5" />
                      <span>Token: {variant.tokenCount.toLocaleString()}</span>
                      {overBudget && (
                        <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                      )}
                    </div>

                    {/* 失败率 */}
                    <div className={`flex items-center gap-1 ${
                      hasHighFailureRate ? 'text-amber-400' : 'text-sb-text-secondary'
                    }`}>
                      <span>失败率: {(variant.failureRate * 100).toFixed(1)}%</span>
                    </div>

                    {/* 使用统计 */}
                    {variant.stats && (
                      <span className="text-sb-text-secondary">
                        使用: {variant.stats.usageCount}次
                      </span>
                    )}
                  </div>
                </div>

                {/* 右侧状态指示 */}
                <div className="flex flex-col items-end gap-1">
                  {overBudget && (
                    <span className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 rounded">
                      超预算
                    </span>
                  )}
                  {hasHighFailureRate && !overBudget && (
                    <span className="px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded">
                      高失败率
                    </span>
                  )}
                  {!overBudget && !hasHighFailureRate && (
                    <span className="px-2 py-0.5 text-xs bg-green-500/20 text-green-400 rounded">
                      推荐
                    </span>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* 底部说明 */}
      <div className="px-4 py-3 bg-white/5 border-t border-white/10">
        <p className="text-xs text-sb-text-secondary">
          <span className="text-sb-cyan">💡 提示：</span>
          系统会根据Token预算和失败率自动推荐最优变体
        </p>
      </div>
    </div>
  );
};

export default VariantSelector;
