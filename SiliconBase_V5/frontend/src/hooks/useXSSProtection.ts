/**
 * XSS防护Hook - React组件中使用XSS防护
 * 
 * 功能：
 * - 提供便捷的方法来保护组件免受XSS攻击
 * - 零静默失败：危险输入自动转义
 * - 支持HTML清理、文本转义和安全渲染
 */

import { useCallback } from 'react';
import { XSSProtection, XSSProtectionOptions } from '../utils/xssProtection';

/**
 * XSS防护Hook返回类型
 */
export interface UseXSSProtectionReturn {
  /** 清理HTML内容 */
  sanitize: (html: string, options?: XSSProtectionOptions) => string;
  /** 转义纯文本内容 */
  escape: (text: string) => string;
  /** 安全渲染（自动选择策略） */
  safeRender: (content: string | object) => string;
  /** 验证输入安全性 */
  isSafe: (input: string) => boolean;
  /** 安全设置innerHTML */
  setDangerouslySetInnerHTML: (html: string, options?: XSSProtectionOptions) => { __html: string };
}

/**
 * XSS防护Hook
 * 在React组件中使用XSS防护功能
 * 
 * @example
 * ```tsx
 * function MessageComponent({ content }: { content: string }) {
 *   const { safeRender } = useXSSProtection();
 *   
 *   // 安全渲染消息内容
 *   const safeContent = safeRender(content);
 *   
 *   return <div>{safeContent}</div>;
 * }
 * ```
 */
export function useXSSProtection(): UseXSSProtectionReturn {
  /**
   * 清理HTML内容
   */
  const sanitize = useCallback((html: string, options?: XSSProtectionOptions): string => {
    return XSSProtection.sanitize(html, options);
  }, []);

  /**
   * 转义纯文本内容
   */
  const escape = useCallback((text: string): string => {
    return XSSProtection.escape(text);
  }, []);

  /**
   * 安全渲染内容（自动选择清理或转义策略）
   */
  const safeRender = useCallback((content: string | object): string => {
    return XSSProtection.safeRender(content);
  }, []);

  /**
   * 验证输入安全性
   */
  const isSafe = useCallback((input: string): boolean => {
    return XSSProtection.isSafe(input);
  }, []);

  /**
   * 安全设置dangerouslySetInnerHTML
   * 先清理HTML，再包装为React所需的格式
   */
  const setDangerouslySetInnerHTML = useCallback(
    (html: string, options?: XSSProtectionOptions): { __html: string } => {
      const sanitized = XSSProtection.sanitize(html, options);
      return { __html: sanitized };
    },
    []
  );

  return {
    sanitize,
    escape,
    safeRender,
    isSafe,
    setDangerouslySetInnerHTML,
  };
}

export default useXSSProtection;
