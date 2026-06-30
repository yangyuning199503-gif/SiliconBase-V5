/**
 * 聊天 API 封装
 * 提供非流式和流式聊天接口
 */

import { fetchAPI, APIError, getAuthToken } from "./core";
import { getApiUrl } from "../../config/ports";

const logger = {
  error: (...args: any[]) => console.error("[ChatAPI]", ...args),
  info: (...args: any[]) => console.info("[ChatAPI]", ...args),
};

/**
 * 聊天请求参数
 */
export interface SendChatParams {
  message: string;
  session_id?: string;
  context?: Array<{ role: string; content: string }>;
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

/**
 * 聊天响应
 */
export interface SendChatResponse {
  success: boolean;
  response: string;
  session_id: string;
  message_id: string;
  usage?: Record<string, any> | null;
  timestamp: number;
}

/**
 * 流式聊天回调
 */
export interface StreamChatCallbacks {
  onMessage?: (chunk: string, fullText: string) => void;
  onComplete?: (fullText: string, sessionId?: string) => void;
  onError?: (error: Error) => void;
}

/**
 * 聊天 API
 */
export const chatApi = {
  /**
   * 非流式聊天
   * @param params - 聊天参数
   * @returns 完整回复
   */
  async sendChat(params: SendChatParams): Promise<SendChatResponse> {
    try {
      logger.info("发送聊天消息", { session_id: params.session_id });

      const response = await fetchAPI<SendChatResponse>("/api/chat", {
        method: "POST",
        body: {
          message: params.message,
          session_id: params.session_id,
          context: params.context,
          model: params.model,
          temperature: params.temperature,
          max_tokens: params.max_tokens,
        },
      });

      if (!response) {
        logger.error("sendChat返回空值");
        throw new Error("发送消息失败：返回空值");
      }

      if (typeof response.success !== "boolean") {
        logger.error("sendChat返回数据格式错误:", response);
        throw new Error("发送消息失败：返回数据格式错误");
      }

      return response;
    } catch (error) {
      logger.error("发送聊天消息异常:", error);
      throw error;
    }
  },

  /**
   * 流式聊天（SSE）
   * @param params - 聊天参数
   * @param callbacks - 流式回调
   * @returns 一个可 await 的 Promise，resolve 时返回完整文本
   */
  async streamChat(
    params: SendChatParams,
    callbacks: StreamChatCallbacks = {},
  ): Promise<string> {
    const url = getApiUrl("/api/chat/stream");

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = getAuthToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    return new Promise<string>((resolve, reject) => {
      let fullText = "";
      let sessionId = params.session_id;

      fetch(url, {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify({
          message: params.message,
          session_id: params.session_id,
          context: params.context,
          model: params.model,
          temperature: params.temperature,
          max_tokens: params.max_tokens,
        }),
      })
        .then(async (response) => {
          if (!response.ok) {
            let message = `请求失败 (${response.status})`;
            try {
              const data = await response.json();
              message = data.detail || data.message || message;
            } catch {
              // ignore
            }
            throw new APIError(message, response.status);
          }

          const reader = response.body?.getReader();
          if (!reader) {
            throw new Error("无法获取响应流");
          }

          const decoder = new TextDecoder("utf-8");
          let buffer = "";

          const processChunk = (): Promise<void> => {
            return reader.read().then(({ done, value }) => {
              if (done) {
                callbacks.onComplete?.(fullText, sessionId);
                resolve(fullText);
                return;
              }

              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              buffer = lines.pop() || "";

              for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed || !trimmed.startsWith("data:")) continue;

                const dataStr = trimmed.slice(5).trim();
                if (dataStr === "[DONE]") continue;

                try {
                  const data = JSON.parse(dataStr);

                  // 会话ID可能从流中返回
                  if (data.session_id && !sessionId) {
                    sessionId = data.session_id;
                  }

                  const chunk =
                    data.content ||
                    data.delta ||
                    data.response ||
                    data.text ||
                    "";
                  if (chunk) {
                    fullText += chunk;
                    callbacks.onMessage?.(chunk, fullText);
                  }

                  if (data.error) {
                    throw new Error(data.error);
                  }
                } catch (e) {
                  // 忽略无法解析的 SSE 数据行
                }
              }

              return processChunk();
            });
          };

          return processChunk();
        })
        .catch((error) => {
          logger.error("流式聊天异常:", error);
          callbacks.onError?.(error instanceof Error ? error : new Error(String(error)));
          reject(error);
        });
    });
  },
};

export default chatApi;
