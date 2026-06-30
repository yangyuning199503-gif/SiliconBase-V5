/**
 * XSS防护工具 - 增强前端安全防护
 * 
 * 功能：
 * - 使用DOMPurify清理HTML内容
 * - 转义纯文本内容
 * - 验证输入是否包含危险模式
 * - 零静默失败：危险输入拒绝渲染并记录ERROR日志
 */

import DOMPurify from 'dompurify';

/**
 * XSS防护配置选项
 */
export interface XSSProtectionOptions {
  /** 允许的HTML标签 */
  allowedTags?: string[];
  /** 允许的HTML属性 */
  allowedAttr?: string[];
  /** 是否允许危险协议（如javascript:） */
  allowDangerousProtocols?: boolean;
}

/**
 * 默认允许的HTML标签（极简安全白名单）
 */
const DEFAULT_ALLOWED_TAGS = ['b', 'i', 'em', 'strong', 'p', 'br', 'code', 'pre'];

/**
 * 默认允许的HTML属性（空数组，不允任何属性）
 */
const DEFAULT_ALLOWED_ATTR: string[] = [];

/**
 * 危险的XSS模式正则表达式
 */
const DANGEROUS_PATTERNS = [
  // script标签（包括未闭合的）
  /<script\b/gi,
  /<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi,
  // javascript:协议
  /javascript:/gi,
  // 事件处理器属性
  /on\w+\s*=/gi,
  // data:协议（可能导致XSS）
  /data:(?:text\/html|image\/svg\+xml)/gi,
  // iframe标签
  /<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi,
  // object/embed标签
  /<object\b[^<]*(?:(?!<\/object>)<[^<]*)*<\/object>/gi,
  /<embed\b[^<]*(?:\/)?>/gi,
  // 表达式（IE）
  /expression\s*\(/gi,
  // 行为（IE）
  /behavior\s*:/gi,
  // mhtml:协议
  /mhtml:/gi,
  // vbscript:协议
  /vbscript:/gi,
];

/**
 * XSS检测结果
 */
export interface XSSDetectionResult {
  /** 是否安全 */
  isSafe: boolean;
  /** 检测到的危险模式 */
  detectedPatterns: string[];
  /** 原始输入 */
  originalInput: string;
}

/**
 * XSS防护工具类
 */
export const XSSProtection = {
  /**
   * 清理HTML内容
   * 使用DOMPurify移除危险标签和属性
   * 
   * @param html - 需要清理的HTML字符串
   * @param options - 清理选项
   * @returns 清理后的安全HTML
   */
  sanitize(html: string, options?: XSSProtectionOptions): string {
    if (typeof html !== 'string') {
      console.error('[XSSProtection] sanitize: 输入必须是字符串类型', typeof html);
      return '';
    }

    const allowedTags = options?.allowedTags ?? DEFAULT_ALLOWED_TAGS;
    const allowedAttr = options?.allowedAttr ?? DEFAULT_ALLOWED_ATTR;

    try {
      const sanitized = String(DOMPurify.sanitize(html, {
        ALLOWED_TAGS: allowedTags,
        ALLOWED_ATTR: allowedAttr,
        FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick'],
        KEEP_CONTENT: false,
        SANITIZE_DOM: true,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any));
      
      // 如果清理前后的内容不一致，记录警告
      if (sanitized !== html.trim()) {
        console.warn('[XSSProtection] HTML内容被清理，可能存在安全风险');
        console.warn('[XSSProtection] 原始长度:', html.length, '清理后长度:', sanitized.length);
      }

      return sanitized;
    } catch (error) {
      console.error('[XSSProtection] HTML清理失败:', error);
      // 零静默失败：清理失败时返回空字符串
      return '';
    }
  },

  /**
   * 转义纯文本内容
   * 将特殊HTML字符转换为实体编码
   * 
   * @param text - 需要转义的文本
   * @returns 转义后的安全文本
   */
  escape(text: string): string {
    if (typeof text !== 'string') {
      console.error('[XSSProtection] escape: 输入必须是字符串类型', typeof text);
      return '';
    }

    // 使用textContent进行安全转义
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * 验证输入是否包含危险模式
   * 用于预防性检查，不清理内容
   * 
   * @param input - 需要验证的输入
   * @returns 验证结果
   */
  validateInput(input: string): XSSDetectionResult {
    if (typeof input !== 'string') {
      console.error('[XSSProtection] validateInput: 输入必须是字符串类型', typeof input);
      return {
        isSafe: false,
        detectedPatterns: ['非字符串输入'],
        originalInput: String(input)
      };
    }

    const detectedPatterns: string[] = [];

    // 检查危险模式
    for (const pattern of DANGEROUS_PATTERNS) {
      if (pattern.test(input)) {
        detectedPatterns.push(pattern.source.substring(0, 50) + '...');
      }
      // 重置正则表达式lastIndex
      pattern.lastIndex = 0;
    }

    const isSafe = detectedPatterns.length === 0;

    if (!isSafe) {
      console.error('[XSSProtection] 检测到危险输入模式:', detectedPatterns);
      console.error('[XSSProtection] 可疑输入前100字符:', input.substring(0, 100));
    }

    return {
      isSafe,
      detectedPatterns,
      originalInput: input
    };
  },

  /**
   * 快速安全检查
   * 返回布尔值表示是否安全
   * 
   * @param input - 需要验证的输入
   * @returns 是否安全
   */
  isSafe(input: string): boolean {
    return this.validateInput(input).isSafe;
  },

  /**
   * 安全渲染消息内容
   * 根据内容类型自动选择转义或清理策略
   * 
   * @param content - 消息内容
   * @returns 安全处理后的内容
   */
  safeRender(content: string | object): string {
    // 处理对象类型
    if (typeof content === 'object') {
      try {
        content = JSON.stringify(content);
      } catch (e) {
        console.error('[XSSProtection] 对象序列化失败:', e);
        return '[内容格式错误]';
      }
    }

    if (typeof content !== 'string') {
      console.error('[XSSProtection] safeRender: 不支持的类型', typeof content);
      return '[内容格式错误]';
    }

    // 验证输入安全性（仅用于日志记录）
    const validation = this.validateInput(content);
    if (!validation.isSafe) {
      console.error('[XSSProtection] 检测到危险内容模式:', validation.detectedPatterns);
    }

    // 如果内容包含允许的安全HTML标签，则进行清理；否则直接转义
    const allowedTagPattern = new RegExp(
      `<\\/?(?:${DEFAULT_ALLOWED_TAGS.join('|')})\\b`,
      'i'
    );
    if (allowedTagPattern.test(content)) {
      return this.sanitize(content);
    }

    // 纯文本或不允许的HTML标签，进行转义
    return this.escape(content);
  },

  /**
   * 安全渲染Markdown（基础支持）
   * 清理HTML并保留安全的Markdown格式
   * 
   * @param markdown - Markdown内容
   * @returns 安全处理后的HTML
   */
  safeMarkdownRender(markdown: string): string {
    if (typeof markdown !== 'string') {
      console.error('[XSSProtection] safeMarkdownRender: 输入必须是字符串类型');
      return '';
    }

    // 先验证输入安全性
    const validation = this.validateInput(markdown);
    if (!validation.isSafe) {
      console.error('[XSSProtection] Markdown内容包含危险模式，拒绝渲染');
      return this.escape(markdown);
    }

    // 使用更宽松的标签白名单
    return this.sanitize(markdown, {
      allowedTags: [
        'b', 'i', 'em', 'strong', 'p', 'br', 'code', 'pre',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'blockquote'
      ],
      allowedAttr: []
    });
  }
};

/**
 * 便捷函数：清理HTML
 */
export const sanitize = (html: string, options?: XSSProtectionOptions): string => 
  XSSProtection.sanitize(html, options);

/**
 * 便捷函数：转义文本
 */
export const escape = (text: string): string => 
  XSSProtection.escape(text);

/**
 * 便捷函数：验证输入
 */
export const validateInput = (input: string): XSSDetectionResult => 
  XSSProtection.validateInput(input);

/**
 * 便捷函数：安全渲染
 */
export const safeRender = (content: string | object): string => 
  XSSProtection.safeRender(content);

// 默认导出
export default XSSProtection;
