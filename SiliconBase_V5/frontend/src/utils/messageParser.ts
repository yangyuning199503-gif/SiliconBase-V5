/**
 * 消息解析工具 - AI响应JSON格式解析（增强XSS防护）
 *
 * 功能：
 * - 解析AI返回的JSON格式响应，提取content/message/response字段
 * - 使用XSS防护工具清理和转义输出内容
 * - 严格遵循异常处理铁律：解析失败时不静默吞异常，必须记录错误
 *
 * 异常处理原则：
 * - 禁止使用 try { ... } catch { return content; } 静默吞异常
 * - 解析失败必须记录 ERROR 日志
 * - JSON中无有效字段时返回友好错误提示
 * - 危险输入拒绝渲染并记录ERROR日志（零静默失败）
 */

import { XSSProtection } from "./xssProtection";

/**
 * 解析AI响应内容
 * 如果是JSON格式，提取content/message/response字段
 * 返回的内容经过XSS安全处理
 *
 * @param content - AI响应内容（字符串或对象）
 * @returns 解析并安全处理后的纯文本内容
 */
export function parseAIResponse(content: string | object): string {
  let parsedContent: string;

  // 如果已经是字符串，尝试解析JSON
  if (typeof content === "string") {
    const trimmed = content.trim();

    // 检查是否是JSON格式（以{开头）
    if (trimmed.startsWith("{")) {
      try {
        const parsed = JSON.parse(trimmed);

        // 提取content字段
        if (parsed.content && typeof parsed.content === "string") {
          parsedContent = parsed.content;
        }

        // 提取message字段
        else if (parsed.message && typeof parsed.message === "string") {
          parsedContent = parsed.message;
        }

        // 提取response字段
        else if (parsed.response && typeof parsed.response === "string") {
          parsedContent = parsed.response;
        }

        // 处理特殊情况：observation + suggestion/insight
        else if (parsed.observation) {
          let result = `观察: ${parsed.observation}`;
          if (parsed.suggestion) {
            result += `\n建议: ${parsed.suggestion}`;
          }
          if (parsed.insight) {
            result += `\n洞察: ${parsed.insight}`;
          }
          parsedContent = result;
        } else {
          // JSON中没有可识别的字段，记录ERROR
          console.error(
            "[MessageParser] JSON中无content/message/response字段:",
            parsed,
          );
          return XSSProtection.escape(
            `[解析错误] AI响应格式异常: ${JSON.stringify(parsed, null, 2)}`,
          );
        }
      } catch (e) {
        // JSON解析失败，记录ERROR
        console.error("[MessageParser] JSON解析失败:", e);
        console.error(
          "[MessageParser] 原始内容前200字符:",
          content.substring(0, 200),
        );
        parsedContent = content;
      }
    } else {
      // 不是JSON，使用原内容
      parsedContent = content;
    }
  } else if (typeof content === "object" && content !== null) {
    // 如果是对象，尝试提取字段
    const obj = content as Record<string, unknown>;

    if (obj.content && typeof obj.content === "string") {
      parsedContent = obj.content;
    } else if (obj.message && typeof obj.message === "string") {
      parsedContent = obj.message;
    } else if (obj.response && typeof obj.response === "string") {
      parsedContent = obj.response;
    } else if (obj.observation) {
      let result = `观察: ${obj.observation}`;
      if (obj.suggestion) result += `\n建议: ${obj.suggestion}`;
      if (obj.insight) result += `\n洞察: ${obj.insight}`;
      parsedContent = result;
    } else {
      console.error(
        "[MessageParser] 对象中无content/message/response字段:",
        obj,
      );
      return XSSProtection.escape(
        `[解析错误] AI响应对象格式异常: ${JSON.stringify(obj, null, 2)}`,
      );
    }
  } else {
    // 未知类型，记录ERROR
    console.error("[MessageParser] 未知内容类型:", typeof content, content);
    return XSSProtection.escape(
      `[解析错误] 无法解析AI响应，类型: ${typeof content}`,
    );
  }

  // 使用XSS防护工具进行安全渲染
  return XSSProtection.safeRender(parsedContent);
}

/**
 * 检查内容是否为JSON格式
 * @param content - 要检查的内容
 * @returns 是否为JSON格式
 */
export function isJSONContent(content: string): boolean {
  if (typeof content !== "string") return false;
  const trimmed = content.trim();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

/**
 * 安全解析JSON（带错误处理）
 * @param content - JSON字符串
 * @returns 解析结果或null
 */
export function safeJSONParse<T>(content: string): T | null {
  try {
    return JSON.parse(content) as T;
  } catch (e) {
    console.error("[MessageParser] JSON解析失败:", e);
    return null;
  }
}

/**
 * 结构化 AI 响应解析结果
 */
export interface ParsedAIResponse {
  content: string;
  thinking?: string;
  plan?: string;
  action?: string;
  toolCall?: { tool: string; params: Record<string, unknown> };
  isStructured: boolean;
}

/**
 * 解析 AI 结构化响应（思考 / 计划 / 行动）
 *
 * 支持的格式：
 *   思考:[分析] ... 计划:[步骤] ... 行动:{"tool":"...","params":{...}}
 *   思考:[分析] ... 行动:{"tool":"...","params":{...}}
 *
 * 解析后：
 *   - thinking / plan / action 放入可折叠的思考过程
 *   - toolCall 提取为工具调用卡片
 *   - content 只保留最终回复；结构化消息如果没有最终回复，正文为空
 */
export function parseAIResponseStructured(
  content: string | object,
): ParsedAIResponse {
  // 统一转成字符串
  let text = "";
  if (typeof content === "string") {
    text = content;
  } else if (content && typeof content === "object") {
    const obj = content as Record<string, unknown>;
    text =
      (typeof obj.content === "string" && obj.content) ||
      (typeof obj.message === "string" && obj.message) ||
      (typeof obj.response === "string" && obj.response) ||
      JSON.stringify(content);
  } else {
    return {
      content: XSSProtection.escape(String(content ?? "")),
      isStructured: false,
    };
  }

  // 没有结构化标记，直接返回
  if (!/思考:|计划:|行动:/.test(text)) {
    return { content: XSSProtection.safeRender(text), isStructured: false };
  }

  // 提取各部分（兼容空格：思考: [分析] 或 思考:[分析]）
  const thinkingMatch = text.match(
    /思考:\s*\[分析\]\s*([\s\S]*?)(?=\s*计划:|\s*行动:|$)/,
  );
  const planMatch = text.match(/计划:\s*\[步骤\]\s*([\s\S]*?)(?=\s*行动:|$)/);
  const actionMatch = text.match(/行动:\s*([\s\S]*)$/);

  const thinking = thinkingMatch ? thinkingMatch[1].trim() : undefined;
  const plan = planMatch ? planMatch[1].trim() : undefined;
  const action = actionMatch ? actionMatch[1].trim() : undefined;

  // 尝试从行动字段解析工具调用 JSON
  let toolCall: ParsedAIResponse["toolCall"];
  if (action) {
    const jsonStr = action.replace(/```json\s*|\s*```/g, "").trim();
    try {
      const parsed = JSON.parse(jsonStr);
      if (parsed.tool || parsed.action) {
        toolCall = {
          tool: String(parsed.tool || parsed.action),
          params: (parsed.params as Record<string, unknown>) || {},
        };
      }
    } catch {
      // 行动不是 JSON，按普通文本在思考过程中展示
    }
  }

  // 结构化响应的正文不再包含 plan/action，避免污染回复。
  // 如果后端在结构化文本后追加 final_answer，则保留。
  const afterAction = actionMatch
    ? text.slice(actionMatch.index! + actionMatch[0].length).trim()
    : "";
  const cleanContent = afterAction || "";

  return {
    content: XSSProtection.safeRender(cleanContent),
    thinking,
    plan,
    action,
    toolCall,
    isStructured: true,
  };
}

// 默认导出
export default parseAIResponse;
