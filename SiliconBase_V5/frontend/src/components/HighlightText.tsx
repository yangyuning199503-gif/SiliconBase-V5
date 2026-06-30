/**
 * HighlightText - 高亮文本组件
 * Phase 5 Week 9 - 用户体验优化
 * 
 * 功能：
 * - 根据搜索关键词高亮显示文本
 * - 支持多个关键词
 * - 自定义高亮样式
 */

import { memo } from 'react';

interface HighlightTextProps {
  text: string;
  keywords: string | string[];
  className?: string;
  highlightClassName?: string;
  caseSensitive?: boolean;
}

function HighlightText({
  text,
  keywords,
  className = '',
  highlightClassName = 'bg-yellow-500/30 text-yellow-200 px-0.5 rounded',
  caseSensitive = false
}: HighlightTextProps) {
  // 如果没有关键词，直接返回原文本
  if (!keywords || (Array.isArray(keywords) && keywords.length === 0) || 
      (typeof keywords === 'string' && !keywords.trim())) {
    return <span className={className}>{text}</span>;
  }

  // 标准化关键词
  const normalizedKeywords = Array.isArray(keywords) 
    ? keywords.filter(k => k.trim()).map(k => caseSensitive ? k : k.toLowerCase())
    : [caseSensitive ? keywords : keywords.toLowerCase()];

  if (normalizedKeywords.length === 0) {
    return <span className={className}>{text}</span>;
  }

  // 构建正则表达式，按长度降序排序以避免部分匹配问题
  const sortedKeywords = [...normalizedKeywords].sort((a, b) => b.length - a.length);
  const escapedKeywords = sortedKeywords.map(k => 
    k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  );
  
  const pattern = new RegExp(`(${escapedKeywords.join('|')})`, caseSensitive ? 'g' : 'gi');
  
  // 分割文本
  const parts = text.split(pattern);
  
  return (
    <span className={className}>
      {parts.map((part, index) => {
        const isMatch = caseSensitive 
          ? normalizedKeywords.includes(part)
          : normalizedKeywords.includes(part.toLowerCase());
        
        if (isMatch) {
          return (
            <mark
              key={index}
              className={highlightClassName}
            >
              {part}
            </mark>
          );
        }
        return <span key={index}>{part}</span>;
      })}
    </span>
  );
}

// 使用memo优化性能
export default memo(HighlightText, (prevProps, nextProps) => {
  return prevProps.text === nextProps.text && 
         JSON.stringify(prevProps.keywords) === JSON.stringify(nextProps.keywords);
});
