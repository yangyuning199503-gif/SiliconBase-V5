/**
 * MessageList - 消息列表组件（支持无限滚动）
 * Phase 2 Week 4 - 前端消息同步实现
 *
 * 功能：
 * - 页面加载时自动拉取历史消息
 * - 滚动到顶部时触发加载更多（游标分页）
 * - 显示加载状态
 * - 与 sessionStore 集成
 */

import { useRef, useEffect, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  User,
  Bot,
  Wrench,
  CheckCircle,
  AlertCircle,
  Loader2,
  ArrowUp,
  Clock,
  Pause,
  X,
  MessageSquareText,
  BrainCircuit,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useSessionStore } from "../stores/sessionStore";
import { parseAIResponse } from "../utils/messageParser";
import { XSSProtection } from "../utils/xssProtection";
import type { Agent } from "../types";
import MemoryAwareness from "./memory/MemoryAwareness";
import { MessageThinkingFlow } from "./MessageThinkingFlow";

interface MessageListProps {
  currentAgent: Agent;
  onSuggestionClick?: (suggestion: string) => void;
  onMemoryClick?: () => void; // 阶段4.1: MemoryAwareness 点击回调
  isProcessing?: boolean; // AI是否正在处理中
}

// 示例建议
const SUGGESTIONS = [
  "打开网易云音乐",
  "截图并保存到桌面",
  "监控CPU使用率，超过80%提醒我",
];

export default function MessageList({
  currentAgent,
  onSuggestionClick,
  isProcessing = false,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isScrolledToTop, setIsScrolledToTop] = useState(false);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // AI思考过程展开状态
  const [expandedThinking, setExpandedThinking] = useState<Set<string>>(
    new Set(),
  );
  const [thinkingFlowOpen, setThinkingFlowOpen] = useState<string | null>(null);

  // 从 sessionStore 获取状态
  const {
    messages,
    currentSession,
    isLoadingMessages,
    hasMoreMessages,
    messagesError,
    loadMoreMessages,
  } = useSessionStore();

  // ═══════════════════════════════════════════════════════════════════
  // 无限滚动检测
  // ═══════════════════════════════════════════════════════════════════
  const handleScroll = useCallback(() => {
    if (!scrollRef.current || isLoadingMessages || !hasMoreMessages) return;

    const { scrollTop } = scrollRef.current;

    // 检测是否滚动到顶部（距离顶部50px内触发）
    if (scrollTop < 50 && hasMoreMessages && !isLoadingMessages) {
      console.log("[MessageList] 触发加载更多消息");
      loadMoreMessages();
    }

    setIsScrolledToTop(scrollTop < 10);
  }, [isLoadingMessages, hasMoreMessages, loadMoreMessages]);

  // 添加滚动监听
  useEffect(() => {
    const scrollEl = scrollRef.current;
    if (scrollEl) {
      scrollEl.addEventListener("scroll", handleScroll);
      return () => scrollEl.removeEventListener("scroll", handleScroll);
    }
  }, [handleScroll]);

  // ═══════════════════════════════════════════════════════════════════
  // 新消息自动滚动到底部
  // ═══════════════════════════════════════════════════════════════════
  const prevMessagesLength = useRef(messages.length);

  useEffect(() => {
    if (scrollRef.current && messages.length > prevMessagesLength.current) {
      // 只有新消息添加时才滚动到底部
      const isNewMessageAdded = messages.length > prevMessagesLength.current;
      if (isNewMessageAdded && !isScrolledToTop) {
        scrollRef.current.scrollTo({
          top: scrollRef.current.scrollHeight,
          behavior: isInitialLoad ? "auto" : "smooth",
        });
      }
    }
    prevMessagesLength.current = messages.length;

    // 首次有消息后结束初始加载状态，后续新消息使用平滑滚动
    if (messages.length > 0 && isInitialLoad) {
      setIsInitialLoad(false);
    }
  }, [messages.length, isScrolledToTop]);

  // ═══════════════════════════════════════════════════════════════════
  // 辅助函数
  // ═══════════════════════════════════════════════════════════════════
  const getMessageIcon = (role: string) => {
    switch (role) {
      case "user":
        return <User className="w-4 h-4" />;
      case "assistant":
        return <Bot className="w-4 h-4" />;
      case "tool":
        return <Wrench className="w-4 h-4" />;
      default:
        return <Bot className="w-4 h-4" />;
    }
  };

  const getMessageStyle = (role: string, isThinking?: boolean) => {
    const baseStyle = "border shadow-lg";

    switch (role) {
      case "user":
        return `${baseStyle} bg-gradient-to-br from-cyan-600/30 to-blue-600/30 border-cyan-500/40 ml-auto rounded-2xl rounded-tr-sm`;
      case "assistant":
        return isThinking
          ? `${baseStyle} bg-gradient-to-br from-blue-600/25 to-purple-600/25 border-blue-500/35 rounded-2xl rounded-tl-sm`
          : `${baseStyle} bg-gradient-to-br from-purple-600/25 to-pink-600/25 border-purple-500/35 rounded-2xl rounded-tl-sm`;
      case "system":
        return `${baseStyle} bg-[#2a2a3a] border-white/15 text-white/70 text-sm rounded-xl mx-auto`;
      case "tool":
        return `${baseStyle} bg-gradient-to-br from-yellow-600/25 to-amber-600/25 border-yellow-500/35 rounded-2xl rounded-tl-sm`;
      default:
        return `${baseStyle} bg-[#2a2a3a] border-white/15 rounded-xl`;
    }
  };

  const parseMessageContent = (content: string | object): string => {
    // parseAIResponse已集成XSS防护，自动清理/转义危险内容
    const parsed = parseAIResponse(content);

    // 双重验证：如果内容包含未被清理的危险模式，进一步转义
    if (!XSSProtection.isSafe(parsed)) {
      console.error("[MessageList] 检测到危险内容，进行强制转义");
      return XSSProtection.escape(parsed);
    }

    return parsed;
  };

  const handleSuggestionClick = (suggestion: string) => {
    if (onSuggestionClick) {
      onSuggestionClick(suggestion);
    }
  };

  // ═══════════════════════════════════════════════════════════════════
  // 【阶段4.1】MemoryAwareness 错误边界组件
  // ═══════════════════════════════════════════════════════════════════
  function MemoryAwarenessErrorBoundary({
    children,
  }: {
    children: React.ReactNode;
  }) {
    const [hasError, setHasError] = useState(false);

    useEffect(() => {
      // 重置错误状态当children变化时
      setHasError(false);
    }, [children]);

    if (hasError) {
      // 静默失败但不完全静默 - 返回null不渲染，但错误已记录
      return null;
    }

    return <ErrorCatcher setHasError={setHasError}>{children}</ErrorCatcher>;
  }

  // 错误捕获包装组件
  function ErrorCatcher({
    children,
    setHasError,
  }: {
    children: React.ReactNode;
    setHasError: (hasError: boolean) => void;
  }) {
    const catcherRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
      const element = catcherRef.current;
      if (!element) return;

      // 监听渲染错误
      const handleError = (event: ErrorEvent) => {
        console.error("[MemoryAwareness] 渲染错误:", event.error);
        setHasError(true);
        // 阻止错误冒泡
        event.preventDefault();
      };

      // 使用 try-catch 包裹渲染
      try {
        window.addEventListener("error", handleError);
        return () => window.removeEventListener("error", handleError);
      } catch (error) {
        console.error("[MemoryAwareness] 错误监听设置失败:", error);
      }
    }, [setHasError]);

    return <div ref={catcherRef}>{children}</div>;
  }

  // ═══════════════════════════════════════════════════════════════════
  // 渲染加载状态
  // ═══════════════════════════════════════════════════════════════════
  if (isInitialLoad && isLoadingMessages) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
          >
            <Loader2 className="w-8 h-8 text-cyan-400" />
          </motion.div>
          <p className="text-sm text-white/50">加载消息中...</p>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════
  // 渲染空状态
  // ═══════════════════════════════════════════════════════════════════
  if (messages.length === 0 && !isLoadingMessages) {
    return (
      <div className="flex-1 flex items-center justify-center overflow-hidden">
        <div className="w-full max-w-lg px-6">
          {/* 中央欢迎区域 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="text-center mb-8"
          >
            {/* 大图标 */}
            <div className="relative inline-block mb-6">
              <motion.div
                animate={{
                  scale: [1, 1.05, 1],
                  rotate: [0, 2, -2, 0],
                }}
                transition={{
                  duration: 4,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
                className="text-7xl mb-4"
              >
                {currentAgent.icon}
              </motion.div>
              {/* 发光背景 */}
              <div
                className="absolute inset-0 blur-3xl opacity-30 -z-10"
                style={{ backgroundColor: currentAgent.color }}
              />
            </div>

            {/* 问候语 */}
            <h2 className="text-2xl font-bold text-white mb-2">
              我是 {currentAgent.name}
            </h2>
            <p className="text-white/50">{currentAgent.description}</p>

            {/* 会话信息 */}
            {currentSession && (
              <p className="text-xs text-white/30 mt-2">
                会话: {currentSession.title}
              </p>
            )}
          </motion.div>

          {/* 快捷建议 */}
          <div className="flex flex-wrap gap-2 justify-center">
            {SUGGESTIONS.map((suggestion, index) => (
              <motion.button
                key={index}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: index * 0.1 }}
                onClick={() => handleSuggestionClick(suggestion)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#2a2a3a] hover:bg-[#353548] text-white/70 hover:text-white/90 text-xs transition-all border border-white/10 hover:border-white/20"
              >
                <Bot className="w-3 h-3" />
                {suggestion}
              </motion.button>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════
  // 渲染消息列表
  // ═══════════════════════════════════════════════════════════════════
  return (
    <div className="flex-1 flex flex-col min-h-0 relative">
      {/* 顶部加载指示器 */}
      <AnimatePresence>
        {isLoadingMessages && hasMoreMessages && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="absolute top-0 left-0 right-0 z-10 flex justify-center pt-2"
          >
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#2a2a3a] border border-white/10 shadow-lg">
              <Loader2 className="w-3.5 h-3.5 animate-spin text-cyan-400" />
              <span className="text-xs text-white/60">加载历史消息...</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 滚动到顶部提示 */}
      <AnimatePresence>
        {!isLoadingMessages && hasMoreMessages && isScrolledToTop && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute top-2 left-1/2 -translate-x-1/2 z-10"
          >
            <button
              onClick={() => loadMoreMessages()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-xs hover:bg-cyan-500/30 transition-colors"
            >
              <ArrowUp className="w-3 h-3" />
              点击加载更多
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 消息列表容器 - 固定高度，避免撑开父容器推动输入框 */}
      <div className="flex-1 min-h-0 overflow-hidden relative">
        <div
          ref={scrollRef}
          className="h-full overflow-y-auto p-5 space-y-5 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent"
        >
          {/* 错误提示 */}
          {messagesError && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mx-auto max-w-md p-3 rounded-xl bg-red-500/10 border border-red-500/30 text-center"
            >
              <p className="text-sm text-red-400">{messagesError}</p>
              <button
                onClick={() => window.location.reload()}
                className="mt-2 text-xs text-cyan-400 hover:text-cyan-300"
              >
                刷新页面重试
              </button>
            </motion.div>
          )}

          {/* 消息列表 - 按时间正序渲染，最新消息在底部 */}
          <div className="flex flex-col">
            {messages
              .filter(
                (message) =>
                  message.role === "user" ||
                  message.role === "assistant" ||
                  message.role === "system",
              )
              .map((message, index) => (
                <motion.div
                  key={message.id || `msg-${index}`}
                  initial={{ opacity: 0, y: 20, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  transition={{
                    duration: 0.3,
                    delay: Math.min(index * 0.03, 0.3),
                  }}
                  className={`flex gap-3 max-w-[85%] mb-5 ${
                    message.role === "user"
                      ? "flex-row-reverse ml-auto"
                      : message.role === "system"
                        ? "justify-center mx-auto max-w-[60%]"
                        : ""
                  }`}
                >
                  {/* 头像 */}
                  <div
                    className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-lg ${
                      message.role === "user"
                        ? "bg-gradient-to-br from-cyan-500 to-blue-500 text-white"
                        : message.role === "system"
                          ? "bg-slate-600 text-white/70"
                          : message.msgType === "task_started"
                            ? "bg-gradient-to-br from-blue-500 to-cyan-400 text-white"
                            : "bg-gradient-to-br from-purple-500 to-pink-500 text-white"
                    }`}
                  >
                    {message.msgType === "task_started"
                      ? "🔄"
                      : getMessageIcon(message.role)}
                  </div>

                  {/* 消息内容 */}
                  <div
                    className={`p-4 ${
                      message.msgType === "task_started"
                        ? "bg-blue-500/10 border-l-4 border-blue-400 rounded-r-xl"
                        : message.msgType === "task_control"
                          ? "bg-slate-500/10 border border-slate-500/20 rounded-xl text-white/60 text-xs"
                          : getMessageStyle(message.role, message.isThinking)
                    } max-w-[85%]`}
                  >
                    {/* 消息头部 */}
                    <div className="flex items-center gap-2 mb-2 text-xs text-white/50">
                      <span className="capitalize font-medium">
                        {message.msgType === "task_started"
                          ? "后台任务"
                          : message.role === "assistant" && message.isThinking
                            ? "思考中"
                            : message.role}
                      </span>
                      {message.round && (
                        <span className="text-cyan-400 bg-cyan-500/10 px-1.5 py-0.5 rounded text-[10px]">
                          第{message.round}轮
                        </span>
                      )}
                      {message.agent && message.agent !== "user" && (
                        <span
                          style={{ color: currentAgent.color }}
                          className="font-medium"
                        >
                          {currentAgent.name}
                        </span>
                      )}
                      {message.timestamp && (
                        <span className="text-white/30 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {new Date(message.timestamp).toLocaleTimeString()}
                        </span>
                      )}
                    </div>

                    {/* 消息正文 */}
                    {(() => {
                      const displayContent = parseMessageContent(
                        message.content,
                      );
                      const isParseError =
                        displayContent.startsWith("[解析错误]");
                      return (
                        <div
                          className={`text-sm leading-relaxed whitespace-pre-wrap ${
                            isParseError
                              ? "text-red-400 bg-red-500/10 p-2 rounded border border-red-500/30"
                              : "text-white/90"
                          }`}
                        >
                          {displayContent}
                        </div>
                      );
                    })()}

                    {/* AI思考过程展示 */}
                    {message.role === "assistant" && message.thinking && (
                      <div className="mt-3">
                        <button
                          onClick={() => {
                            setExpandedThinking((prev) => {
                              const next = new Set(prev);
                              if (next.has(message.id || `msg-${index}`)) {
                                next.delete(message.id || `msg-${index}`);
                              } else {
                                next.add(message.id || `msg-${index}`);
                              }
                              return next;
                            });
                          }}
                          className="flex items-center gap-2 text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
                        >
                          <BrainCircuit className="w-3.5 h-3.5" />
                          <span>思考过程</span>
                          {expandedThinking.has(
                            message.id || `msg-${index}`,
                          ) ? (
                            <ChevronUp className="w-3 h-3" />
                          ) : (
                            <ChevronDown className="w-3 h-3" />
                          )}
                        </button>
                        <AnimatePresence>
                          {expandedThinking.has(
                            message.id || `msg-${index}`,
                          ) && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: "auto", opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              transition={{ duration: 0.2 }}
                              className="overflow-hidden"
                            >
                              <div className="mt-2 p-3 rounded-lg bg-cyan-500/5 border border-cyan-500/20 text-xs text-white/70 whitespace-pre-wrap font-mono leading-relaxed">
                                {message.thinking}
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                    )}

                    {/* AI思维流步骤 */}
                    {message.role === "assistant" &&
                      message.aiSteps &&
                      message.aiSteps.length > 0 && (
                        <div className="mt-2">
                          <button
                            onClick={() =>
                              setThinkingFlowOpen(message.id || `msg-${index}`)
                            }
                            className="flex items-center gap-2 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                          >
                            <BrainCircuit className="w-3.5 h-3.5" />
                            <span>
                              查看思维流 ({message.aiSteps.length} 步)
                            </span>
                          </button>
                          <MessageThinkingFlow
                            steps={message.aiSteps}
                            isOpen={
                              thinkingFlowOpen ===
                              (message.id || `msg-${index}`)
                            }
                            onClose={() => setThinkingFlowOpen(null)}
                          />
                        </div>
                      )}

                    {/* 工具调用展示 */}
                    {message.toolCall && (
                      <div className="mt-3 p-3 rounded-lg bg-black/30 border border-yellow-500/20 text-xs">
                        <div className="flex items-center gap-2 text-yellow-400 font-medium">
                          <Wrench className="w-3.5 h-3.5" />
                          <span>调用: {message.toolCall.tool}</span>
                        </div>
                        <div className="mt-2 text-white/50 font-mono text-[10px] overflow-x-auto">
                          <pre>
                            {JSON.stringify(message.toolCall.params, null, 2)}
                          </pre>
                        </div>
                      </div>
                    )}

                    {/* 工具结果展示 */}
                    {message.toolResult && (
                      <div
                        className={`mt-3 p-2.5 rounded-lg text-xs flex items-center gap-2 border ${
                          message.toolResult.success
                            ? "bg-green-500/10 text-green-400 border-green-500/20"
                            : "bg-red-500/10 text-red-400 border-red-500/20"
                        }`}
                      >
                        {message.toolResult.success ? (
                          <CheckCircle className="w-4 h-4 shrink-0" />
                        ) : (
                          <AlertCircle className="w-4 h-4 shrink-0" />
                        )}
                        <span className="font-medium">
                          {message.toolResult.success ? "执行成功" : "执行失败"}
                        </span>
                      </div>
                    )}

                    {/* 附件展示 */}
                    {message.attachments && message.attachments.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {message.attachments.map((file, fileIndex) => (
                          <div
                            key={fileIndex}
                            className="flex items-center gap-2 px-2 py-1 rounded-lg bg-white/5 border border-white/10 text-xs text-white/60"
                          >
                            <span className="truncate max-w-[150px]">
                              {file.name}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 【阶段4.1】AI消息记忆感知提示 - 带错误边界 */}
                  {message.role === "assistant" && (
                    <div className="mt-2 ml-12">
                      <MemoryAwarenessErrorBoundary>
                        <MemoryAwareness
                          memoryCount={message.memory_count ?? 0}
                          memoryIds={message.memory_ids}
                          relevanceScore={message.relevance_score ?? 0}
                          memoryTypes={message.memory_types}
                          onClick={() => {
                            // TODO: 阶段4.2 接入MemoryPanel
                            console.log(
                              "[MemoryAwareness] 点击记忆提示, memory_ids:",
                              message.memory_ids,
                            );
                          }}
                        />
                      </MemoryAwarenessErrorBoundary>
                    </div>
                  )}
                </motion.div>
              ))}
          </div>

          {/* 底部提示 - 没有更多消息 */}
          {!hasMoreMessages && messages.length > 0 && (
            <div className="text-center py-4">
              <p className="text-xs text-white/30">—— 没有更多历史消息 ——</p>
            </div>
          )}

          {/* 【新增】AI处理中的悬浮控制条 */}
          {isProcessing && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 20 }}
              className="sticky bottom-0 left-0 right-0 mt-4 z-20"
            >
              <div className="bg-[#1e1e2a]/95 backdrop-blur-sm border border-white/10 rounded-2xl p-4 shadow-2xl">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <Loader2 className="w-4 h-4 text-cyan-400 animate-spin" />
                    <span className="text-sm text-white/80">
                      AI正在思考中...
                    </span>
                  </div>
                  <span className="text-xs text-white/40">
                    可随时暂停或调整
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() =>
                      window.dispatchEvent(
                        new CustomEvent("intervention:pause"),
                      )
                    }
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-yellow-500/20 text-yellow-400 text-sm hover:bg-yellow-500/30 transition-colors"
                    title="暂停执行"
                  >
                    <Pause className="w-3.5 h-3.5" />
                    暂停
                  </button>
                  <button
                    onClick={() =>
                      window.dispatchEvent(
                        new CustomEvent("intervention:adjust"),
                      )
                    }
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/20 text-blue-400 text-sm hover:bg-blue-500/30 transition-colors"
                    title="调整方向"
                  >
                    <MessageSquareText className="w-3.5 h-3.5" />
                    调整
                  </button>
                  <button
                    onClick={() =>
                      window.dispatchEvent(
                        new CustomEvent("intervention:cancel"),
                      )
                    }
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/20 text-red-400 text-sm hover:bg-red-500/30 transition-colors"
                    title="取消执行"
                  >
                    <X className="w-3.5 h-3.5" />
                    取消
                  </button>
                </div>
              </div>
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
