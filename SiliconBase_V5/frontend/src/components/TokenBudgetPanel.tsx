/**
 * Token 预算可视化面板
 * SiliconBase V5 - Token Budget Panel
 * 
 * 功能：
 *   ✓ 显示8大类别预算使用情况
 *   ✓ 超出预算时红色警告
 *   ✓ 点击类别查看详细截断信息
 *   ✓ 实时总预算进度条
 */

import React, { useState } from 'react';
import { 
  Wallet, 
  AlertTriangle, 
  CheckCircle, 
  Info, 
  ChevronDown, 
  ChevronUp,
  BarChart3,
  Scissors
} from 'lucide-react';
import { BudgetCategory, TokenBudgetReport } from '../types/prompt';

interface TokenBudgetPanelProps {
  categories: Record<string, BudgetCategory>;
  totalBudget: number;
  totalUsed: number;
  isOverBudget: boolean;
  budgetReport?: TokenBudgetReport;
  className?: string;
}

export const TokenBudgetPanel: React.FC<TokenBudgetPanelProps> = ({
  categories,
  totalBudget,
  totalUsed,
  isOverBudget,
  budgetReport,
  className = ''
}) => {
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);

  // 计算使用率
  const usagePercent = Math.min(100, Math.round((totalUsed / totalBudget) * 100));
  
  // 获取状态颜色
  const getStatusColor = (used: number, budget: number) => {
    const ratio = used / budget;
    if (ratio > 1) return 'text-red-400 bg-red-500';
    if (ratio > 0.9) return 'text-amber-400 bg-amber-500';
    if (ratio > 0.7) return 'text-yellow-400 bg-yellow-500';
    return 'text-green-400 bg-green-500';
  };

  const getStatusText = (used: number, budget: number) => {
    const ratio = used / budget;
    if (ratio > 1) return '超预算';
    if (ratio > 0.9) return '警告';
    if (ratio > 0.7) return '偏高';
    return '正常';
  };

  // 分类列表
  const categoryList = Object.values(categories).sort((a, b) => {
    // 按使用率降序排列
    return (b.used / b.budget) - (a.used / a.budget);
  });

  return (
    <div className={`bg-sb-bg-secondary border border-white/10 rounded-xl overflow-hidden ${className}`}>
      {/* 头部 - 总预算概览 */}
      <div className={`px-4 py-4 border-b border-white/10 ${
        isOverBudget ? 'bg-red-500/10' : 'bg-white/5'
      }`}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Wallet className={`w-5 h-5 ${isOverBudget ? 'text-red-400' : 'text-sb-cyan'}`} />
            <span className="font-medium text-sb-text-primary">Token 预算总览</span>
          </div>
          
          {isOverBudget && (
            <div className="flex items-center gap-1.5 text-red-400">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">超出预算!</span>
            </div>
          )}
          
          {!isOverBudget && usagePercent > 90 && (
            <div className="flex items-center gap-1.5 text-amber-400">
              <AlertTriangle className="w-4 h-4" />
              <span className="text-sm font-medium">接近上限</span>
            </div>
          )}
          
          {!isOverBudget && usagePercent <= 90 && (
            <div className="flex items-center gap-1.5 text-green-400">
              <CheckCircle className="w-4 h-4" />
              <span className="text-sm font-medium">预算充足</span>
            </div>
          )}
        </div>

        {/* 总进度条 */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-sb-text-secondary">
              已使用: <span className={isOverBudget ? 'text-red-400' : 'text-sb-cyan'}>
                {totalUsed.toLocaleString()}
              </span> / {totalBudget.toLocaleString()} tokens
            </span>
            <span className={`font-medium ${
              isOverBudget ? 'text-red-400' : usagePercent > 90 ? 'text-amber-400' : 'text-sb-text-primary'
            }`}>
              {usagePercent}%
            </span>
          </div>
          
          <div className="h-3 bg-white/10 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                isOverBudget 
                  ? 'bg-red-500' 
                  : usagePercent > 90 
                    ? 'bg-amber-500' 
                    : usagePercent > 70 
                      ? 'bg-yellow-500' 
                      : 'bg-green-500'
              }`}
              style={{ width: `${Math.min(100, usagePercent)}%` }}
            />
          </div>
        </div>

        {/* 截断警告 */}
        {budgetReport && budgetReport.allocations.some(a => a.wasTruncated) && (
          <div className="mt-3 p-2 bg-amber-500/10 border border-amber-500/30 rounded-lg">
            <div className="flex items-center gap-2 text-amber-400">
              <Scissors className="w-4 h-4" />
              <span className="text-sm">
                有 {budgetReport.allocations.filter(a => a.wasTruncated).length} 个类别内容被截断
              </span>
            </div>
          </div>
        )}
      </div>

      {/* 分类详情 */}
      <div className="divide-y divide-white/5">
        {categoryList.map((category) => {
          const usageRatio = category.used / category.budget;
          const isExpanded = expandedCategory === category.name;
          const statusColor = getStatusColor(category.used, category.budget);
          const statusText = getStatusText(category.used, category.budget);
          
          // 查找该分类的截断信息
          const allocation = budgetReport?.allocations.find(
            a => a.category === category.name
          );

          return (
            <div key={category.name} className="bg-white/5">
              {/* 分类头部（可点击展开） */}
              <button
                onClick={() => setExpandedCategory(isExpanded ? null : category.name)}
                className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/5 transition-colors"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-sb-text-primary">
                      {category.name}
                    </span>
                    
                    {/* 状态标签 */}
                    <span className={`px-2 py-0.5 text-xs rounded ${statusColor.replace('bg-', 'bg-').replace('text-', 'text-')}/20 ${statusColor.split(' ')[0]}`}>
                      {statusText}
                    </span>
                    
                    {/* 截断标记 */}
                    {category.truncated && (
                      <span className="flex items-center gap-1 px-2 py-0.5 text-xs bg-amber-500/20 text-amber-400 rounded">
                        <Scissors className="w-3 h-3" />
                        已截断
                      </span>
                    )}
                  </div>

                  {/* 进度条 */}
                  <div className="mt-2 flex items-center gap-3">
                    <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${statusColor.split(' ')[1]}`}
                        style={{ width: `${Math.min(100, usageRatio * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-sb-text-secondary min-w-[80px] text-right">
                      {Math.round(category.used).toLocaleString()} / {category.budget.toLocaleString()}
                    </span>
                  </div>
                </div>

                {/* 展开图标 */}
                <div className="ml-3 text-sb-text-secondary">
                  {isExpanded ? (
                    <ChevronUp className="w-4 h-4" />
                  ) : (
                    <ChevronDown className="w-4 h-4" />
                  )}
                </div>
              </button>

              {/* 展开详情 */}
              {isExpanded && (
                <div className="px-4 pb-4 bg-black/20">
                  {/* 详细统计 */}
                  <div className="grid grid-cols-2 gap-3 mt-2">
                    <div className="p-2 bg-white/5 rounded">
                      <p className="text-xs text-sb-text-secondary">预算</p>
                      <p className="text-sm font-medium">{category.budget.toLocaleString()} tokens</p>
                    </div>
                    <div className="p-2 bg-white/5 rounded">
                      <p className="text-xs text-sb-text-secondary">已使用</p>
                      <p className={`text-sm font-medium ${usageRatio > 1 ? 'text-red-400' : ''}`}>
                        {Math.round(category.used).toLocaleString()} tokens
                      </p>
                    </div>
                  </div>

                  {/* 截断详情 */}
                  {allocation?.wasTruncated && (
                    <div className="mt-3 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                      <div className="flex items-center gap-2 text-amber-400 mb-2">
                        <Scissors className="w-4 h-4" />
                        <span className="text-sm font-medium">内容被截断</span>
                      </div>
                      <div className="space-y-1 text-xs text-sb-text-secondary">
                        <p>原始长度: {allocation.originalLength.toLocaleString()} tokens</p>
                        <p>截断后: {allocation.truncatedLength.toLocaleString()} tokens</p>
                        <p>保留率: {((allocation.truncatedLength / allocation.originalLength) * 100).toFixed(1)}%</p>
                      </div>
                    </div>
                  )}

                  {/* 优化建议 */}
                  {usageRatio > 0.9 && !category.truncated && (
                    <div className="mt-3 p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                      <div className="flex items-center gap-2 text-blue-400">
                        <Info className="w-4 h-4" />
                        <span className="text-sm">
                          建议：考虑使用精简版变体以减少Token使用
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 底部提示 */}
      <div className="px-4 py-3 bg-white/5 border-t border-white/10">
        <p className="text-xs text-sb-text-secondary">
          <BarChart3 className="w-3.5 h-3.5 inline mr-1" />
          Token数基于字符长度估算（字符数/4），实际可能略有差异
        </p>
      </div>
    </div>
  );
};

export default TokenBudgetPanel;
