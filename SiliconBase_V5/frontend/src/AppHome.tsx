import React, { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import MainCanvas from "./components/MainCanvas";
import PulseTimeline from "./components/PulseTimeline";
import ChatArea from "./components/ChatArea";

import { useWebSocket } from "./hooks/useWebSocket";
import { memoryAPI } from "./utils/api/memory";
import { useNotifications } from "./hooks/useNotifications";
import { ObserverIndicator } from "./components/ObserverIndicator";
import { VoiceStateIndicator } from "./components/VoiceStateIndicator";
import { ModeSwitchIndicator } from "./components/ModeSwitchIndicator";
import { PerceptionIndicator } from "./components/PerceptionIndicator";
import {
  Agent,
  Message,
  TaskStatus,
  TaskListItem,
  AIStep,
  AIStatus,
  UploadedFile,
} from "./types";
import { fetchAPI, handleAPIError } from "./utils/api";
import { interventionApi } from "./utils/api/intervention";
import { adaptTaskListItem } from "./utils/api/task";
import { parseAIResponseStructured } from "./utils/messageParser";

import { useSessionStore } from "./stores/sessionStore";

import { ExecutionLog, useExecutionLog } from "./components/ExecutionLog";
import { ScrollText } from "lucide-react";

import MemoryPanel from "./components/memory/MemoryPanel";

const AGENTS: Agent[] = [
  {
    id: "general",
    name: "通用助手",
    icon: "🤖",
    color: "#00d4ff",
    description: "日常对话和任务执行",
  },
];

export default function AppHome() {
  const { showNotification } = useNotifications();
  const [currentAgent, setCurrentAgent] = useState<Agent>(AGENTS[0]);
  const [isRecording, setIsRecording] = useState(false);
  const [agentStatus, setAgentStatus] = useState<AIStatus>("idle");
  const [activeTasks, setActiveTasks] = useState<TaskStatus[]>([]);
  const { sendMessage, lastMessage } = useWebSocket();

  // ═══════════════════════════════════════════════════════════════════
  // Session Store 集成 - 消息同步
  // ═══════════════════════════════════════════════════════════════════
  const {
    currentSessionId,
    messages,
    addMessage,
    createSession,
    switchSession,
  } = useSessionStore();

  // ═══════════════════════════════════════════════════════════════════
  // 会话生命周期初始化（收敛到页面级组件，避免与 MessageList 竞态）
  // ═══════════════════════════════════════════════════════════════════
  useEffect(() => {
    const initializeSession = async () => {
      if (currentSessionId) {
        console.log("[AppHome] 恢复会话:", currentSessionId);
        try {
          await switchSession(currentSessionId);
        } catch (error) {
          console.error("[AppHome] 恢复会话失败，创建新会话:", error);
          await createSession("daily");
        }
      } else {
        console.log("[AppHome] 创建新会话");
        await createSession("daily");
      }
    };

    initializeSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // AI思维流 - 带限流防阻塞
  const [aiSteps, setAISteps] = useState<AIStep[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const stepQueueRef = useRef<AIStep[]>([]);
  const processingRef = useRef(false);

  // 执行日志 hook
  const executionLog = useExecutionLog();
  const [showExecutionLog, setShowExecutionLog] = useState(false);

  // ═══════════════════════════════════════════════════════════════════
  // MemoryPanel 状态管理
  // ═══════════════════════════════════════════════════════════════════
  const [isMemoryPanelOpen, setIsMemoryPanelOpen] = useState(false);
  const [memoryPanelError, setMemoryPanelError] = useState<Error | null>(null);
  const [highlightMemoryId, setHighlightMemoryId] = useState<string | null>(
    null,
  );

  // 用于同步思维流到执行日志的 ref
  const aiStepsRef = useRef<AIStep[]>([]);

  const MAX_AI_STEPS = 50;
  const STORAGE_KEY = "thinking_flow_history";

  // 同步 aiSteps 到 ref
  useEffect(() => {
    aiStepsRef.current = aiSteps;
  }, [aiSteps]);

  // 从 localStorage 加载保存的思维流
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          setAISteps(parsed);
          console.log("[思维流持久化] 已恢复", parsed.length, "条历史记录");
        }
      }
    } catch (error) {
      console.error("[思维流持久化] 加载历史记录失败:", error);
    }
  }, []);

  // 保存思维流到 localStorage（限制最近50条）
  useEffect(() => {
    try {
      const dataToSave = aiSteps.slice(-50);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(dataToSave));
    } catch (error) {
      console.error("[思维流持久化] 保存历史记录失败:", error);
    }
  }, [aiSteps]);

  // 清空思维流历史（暴露到全局供设置页面调用）
  const clearThinkingHistory = useCallback(() => {
    setAISteps([]);
    localStorage.removeItem(STORAGE_KEY);
    executionLog.addInfo("思维流历史已清空");
    showNotification({
      type: "info",
      title: "历史记录",
      message: "思维流历史已清空",
    });
  }, [executionLog, showNotification]);

  // 通过 CustomEvent 暴露清空能力，供设置页面调用
  useEffect(() => {
    const handleClear = () => clearThinkingHistory();
    window.addEventListener("clear:thinking-history", handleClear);
    return () => {
      window.removeEventListener("clear:thinking-history", handleClear);
    };
  }, [clearThinkingHistory]);

  useEffect(() => {
    document.title = "首页 - SiliconBase V5";
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  // 全局通知监听（用于AuthGuard等非组件区域发送通知）
  // ═══════════════════════════════════════════════════════════════════
  useEffect(() => {
    const handleShowNotification = (event: CustomEvent) => {
      const { type, title, message } = event.detail || {};
      if (title && message) {
        showNotification({ type: type || "info", title, message });
      }
    };

    window.addEventListener(
      "show_notification",
      handleShowNotification as EventListener,
    );
    return () => {
      window.removeEventListener(
        "show_notification",
        handleShowNotification as EventListener,
      );
    };
  }, [showNotification]);

  // ═══════════════════════════════════════════════════════════════════
  // 自动保存思维流到短期记忆 (记忆汇聚功能)
  // ═══════════════════════════════════════════════════════════════════
  const saveThinkingFlowToMemory = useCallback(async (steps: AIStep[]) => {
    try {
      if (steps.length === 0) return;

      // 将思维流格式化为文本内容
      const content = steps.map((s) => `[${s.type}] ${s.content}`).join("\n");

      await memoryAPI.createMemory({
        layer: "short",
        mem_type: "thinking_flow",
        content: content,
        scene: "AI思考过程",
        source: "auto_save",
      });

      console.log("[记忆汇聚] 思维流已保存到短期记忆，条数:", steps.length);
    } catch (error) {
      console.error("[记忆汇聚] 保存思维流失败:", error);
    }
  }, []);

  // 当 isProcessing 从 true 变为 false 时，保存思维流
  const prevIsProcessingRef = useRef(isProcessing);
  useEffect(() => {
    // 从处理中变为非处理中，且思维流有内容
    if (prevIsProcessingRef.current && !isProcessing && aiSteps.length > 0) {
      saveThinkingFlowToMemory(aiSteps);
    }
    prevIsProcessingRef.current = isProcessing;
  }, [isProcessing, aiSteps, saveThinkingFlowToMemory]);

  // 保存工具调用记录到记忆
  const saveToolExecutionToMemory = useCallback(
    async (toolName: string, params: Record<string, unknown>, result: string) => {
      try {
        await memoryAPI.createMemory({
          layer: "execution",
          mem_type: "tool_execution",
          content: `工具: ${toolName}\n参数: ${JSON.stringify(params)}\n结果: ${result}`,
          scene: "工具调用",
          source: "auto_save",
        });

        console.log("[记忆汇聚] 工具调用已保存到记忆:", toolName);
      } catch (error) {
        console.error("[记忆汇聚] 保存工具调用失败:", error);
      }
    },
    [],
  );

  const flushStepQueue = useCallback(() => {
    if (processingRef.current || stepQueueRef.current.length === 0) return;
    processingRef.current = true;

    const batch = stepQueueRef.current.splice(0, 10);
    setAISteps((prev) => {
      const combined = [...prev, ...batch];
      return combined.length > MAX_AI_STEPS
        ? combined.slice(-MAX_AI_STEPS)
        : combined;
    });

    processingRef.current = false;
    if (stepQueueRef.current.length > 0) {
      requestAnimationFrame(flushStepQueue);
    }
  }, []);

  const addAIStep = useCallback(
    (step: AIStep) => {
      stepQueueRef.current.push(step);
      if (!processingRef.current) {
        requestAnimationFrame(flushStepQueue);
      }
    },
    [flushStepQueue],
  );

  // 将思维流同步到执行日志（使用 ref 避免依赖循环）
  useEffect(() => {
    const currentSteps = aiStepsRef.current;
    const lastStep = aiSteps[aiSteps.length - 1];

    if (!lastStep) return;
    if (currentSteps.includes(lastStep)) return; // 避免重复处理

    // 同步到执行日志
    switch (lastStep.type) {
      case "thinking":
        executionLog.addThinking(lastStep.content, {
          timestamp: lastStep.timestamp,
        });
        break;
      case "tool":
        executionLog.addTool(lastStep.content, {
          timestamp: lastStep.timestamp,
        });
        break;
      case "result":
        executionLog.addSuccess(lastStep.content, {
          timestamp: lastStep.timestamp,
          screenshot: lastStep.metadata?.screenshot,
        });
        break;
      case "complete":
        if (lastStep.content.includes("错误")) {
          executionLog.addError(lastStep.content, {
            timestamp: lastStep.timestamp,
          });
        } else {
          executionLog.addSuccess(lastStep.content, {
            timestamp: lastStep.timestamp,
          });
        }
        break;
    }

    aiStepsRef.current = [...aiSteps];
  }, [aiSteps, executionLog]);

  // 组件挂载时获取任务列表
  useEffect(() => {
    let failCount = 0;
    let intervalId: ReturnType<typeof setInterval>;

    const fetchTasks = async () => {
      try {
        const data = await fetchAPI<{ tasks: TaskListItem[] }>("/api/tasks");
        failCount = 0; // 成功则重置计数
        if (data?.tasks) {
          const tasks: TaskStatus[] = data.tasks.map(adaptTaskListItem);
          setActiveTasks(tasks);
        }
      } catch (error) {
        // 401 统一由 fetchAPI/core.ts 处理并触发 auth:session_expired，
        // 此处不再自行清理 localStorage 或跳转，避免与全局认证状态竞态。
        // 非401错误：只在前3次失败时打印，避免刷屏
        failCount++;
        if (failCount <= 3) {
          const message = handleAPIError(
            error,
            `获取任务列表失败(${failCount}/3)`,
          );
          console.error(`[App] ${message}`, error);
        }
        // 连续失败5次后延长轮询间隔到30秒
        if (failCount === 5 && intervalId) {
          clearInterval(intervalId);
          intervalId = setInterval(fetchTasks, 30000);
        }
      }
    };

    fetchTasks();
    intervalId = setInterval(fetchTasks, 5000);
    return () => clearInterval(intervalId);
  }, []);

  // ═══════════════════════════════════════════════════════════════════
  // WebSocket 消息处理 - 集成 sessionStore
  // ═══════════════════════════════════════════════════════════════════
  useEffect(() => {
    if (!lastMessage) return;

    console.log("【WebSocket收到消息】", lastMessage);

    switch (lastMessage.type) {
      case "chat_response": {
        const chatContent =
          lastMessage.data?.content || lastMessage.data?.message || "";
        addMessage({
          role: "assistant",
          content: chatContent,
          aiSteps: [...aiStepsRef.current],
        });
        setAISteps([]);
        executionLog.addSuccess("AI 回复完成", {
          preview: chatContent.slice(0, 100),
          timestamp: Date.now(),
        });
        setAgentStatus("idle");
        setIsProcessing(false);
        break;
      }
      // NOTE: 'reply' 和 'completed' 共用同一段处理逻辑是设计意图，
      // 两者均表示 AI 已生成最终回复，仅消息类型标识不同。
      case "reply":
      case "completed": {
        const content = lastMessage.data?.content || lastMessage.data?.answer;

        if (!content || !content.trim() || content === "无内容") {
          console.error("[SILENT_FAILURE_BLOCKED] AI返回空内容:", lastMessage);
          // 添加系统错误消息到 sessionStore
          addMessage({
            id: `error-${Date.now()}`,
            role: "system",
            content: "错误: AI未返回有效内容，请稍后重试",
            timestamp: Date.now(),
          });
          setAgentStatus("error");
          setIsProcessing(false);
          addAIStep({
            id: `error-${Date.now()}`,
            type: "complete",
            content: "错误: AI未返回有效内容",
            timestamp: Date.now(),
          });
          break;
        }

        // 把当前思维流绑定到这条 AI 回复，然后清空全局思维流
        const currentAISteps = [...aiStepsRef.current];

        // 添加AI回复到 sessionStore
        // 【修复】添加记忆元数据字段
        addMessage({
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: content,
          agent: lastMessage.data?.agent || currentAgent.id,
          timestamp: Date.now(),
          memory_count: lastMessage.data?.memory_count ?? null,
          memory_ids: lastMessage.data?.memory_ids ?? null,
          relevance_score: lastMessage.data?.relevance_score ?? null,
          memory_types: lastMessage.data?.memory_types ?? null,
          aiSteps: currentAISteps,
        });
        setAISteps([]);

        // 如果 AI 回复包含结构化思考/行动，同步到执行日志
        const parsed = parseAIResponseStructured(content);
        if (parsed.thinking) {
          executionLog.addThinking(parsed.thinking);
        }
        if (parsed.plan) {
          executionLog.addInfo(`计划：${parsed.plan}`);
        }
        if (parsed.toolCall) {
          executionLog.addTool(`调用 ${parsed.toolCall.tool}`, {
            ...parsed.toolCall.params,
            timestamp: Date.now(),
          });
        }

        setAgentStatus("idle");
        setIsProcessing(false);
        addAIStep({
          id: `complete-${Date.now()}`,
          type: "complete",
          content: content,
          timestamp: Date.now(),
        });
        break;
      }
      case "thinking":
        setAgentStatus("thinking");
        setIsProcessing(true);
        if (lastMessage.data?.content) {
          addAIStep({
            id: `thinking-${Date.now()}-${Math.random()}`,
            type: "thinking",
            content: lastMessage.data.content,
            timestamp: Date.now(),
          });
        }
        break;
      // DEPRECATED: 后端已不再推送此类型，保留以防万一
      case "executing":
      case "tool_call":
        setAgentStatus("executing");
        if (lastMessage.data?.tool) {
          const toolInfo = `调用工具: ${lastMessage.data.tool}\n参数: ${JSON.stringify(lastMessage.data.params || {}, null, 2)}`;
          addAIStep({
            id: `tool-${Date.now()}`,
            type: "tool",
            content: toolInfo,
            timestamp: Date.now(),
          });
          executionLog.addTool(`调用工具: ${lastMessage.data.tool}`, {
            params: lastMessage.data.params || {},
          });
        }
        break;
      case "tool_result":
        {
          const toolName =
            lastMessage.data?.tool || lastMessage.data?.tool_name || "unknown";
          const success = lastMessage.data?.success ?? false;
          const summary =
            lastMessage.data?.summary ||
            lastMessage.data?.message ||
            lastMessage.data?.result ||
            "";
          const error = lastMessage.data?.error;

          // 注入 role: "tool" 消息，让 MessageList 可以渲染增强卡片
          addMessage({
            id: `tool-result-${Date.now()}`,
            role: "tool",
            content: summary,
            toolResult: {
              tool: toolName,
              success,
              data: lastMessage.data?.data,
              error,
              executionTime: lastMessage.data?.execution_time_ms,
              params:
                lastMessage.data?.params || lastMessage.data?.input_params,
              summary,
            },
            timestamp: Date.now(),
          });

          // 保留原有 AIStep（用于思维流）
          const resultContent =
            lastMessage.data?.message ||
            lastMessage.data?.result ||
            JSON.stringify(lastMessage.data || {});
          const stepData: AIStep = {
            id: `result-${Date.now()}`,
            type: "result",
            content: `执行结果:\n${resultContent}`,
            timestamp: Date.now(),
            metadata: {},
          };
          if (lastMessage.data?.path) {
            stepData.metadata = {
              ...stepData.metadata,
              screenshot: lastMessage.data.path,
            };
            stepData.data = lastMessage.data;
          }
          addAIStep(stepData);

          // 写入执行日志
          if (success) {
            executionLog.addSuccess(`工具执行成功: ${toolName}`, {
              summary,
              executionTime: lastMessage.data?.execution_time_ms,
            });
          } else {
            executionLog.addError(`工具执行失败: ${toolName}`, {
              error: error || summary,
            });
          }

          // 自动保存工具调用记录到记忆
          const params =
            (lastMessage.data?.params ||
              lastMessage.data?.input_params ||
              {}) as Record<string, unknown>;
          saveToolExecutionToMemory(toolName, params, resultContent);
        }
        break;
      // DEPRECATED: 后端已不再推送此类型，保留以防万一
      case "learning": {
        const learningTool = lastMessage.data?.tool_id || "未知工具";
        const learningMsg =
          lastMessage.data?.message || `正在学习 ${learningTool} 的用法...`;
        addAIStep({
          id: `learning-${Date.now()}`,
          type: "thinking",
          content: `进入学习模式: ${learningMsg}\n工具: ${learningTool}`,
          timestamp: Date.now(),
        });
        break;
      }
      case "error": {
        const errorContent =
          lastMessage.message || lastMessage.data?.message || "未知错误";
        // 添加错误消息到 sessionStore
        addMessage({
          id: `error-${Date.now()}`,
          role: "system",
          content: `错误: ${errorContent}`,
          timestamp: Date.now(),
        });
        setAgentStatus("idle");
        setIsProcessing(false);
        addAIStep({
          id: `error-${Date.now()}`,
          type: "complete",
          content: `错误: ${errorContent}`,
          timestamp: Date.now(),
        });
        executionLog.addError(`执行错误: ${errorContent}`);
        break;
      }
      case "alignment_started":
        addMessage({ role: "system", content: "AI 正在进行自我对齐..." });
        break;
      case "alignment_result":
        if (lastMessage.data?.content) {
          addMessage({
            id: `alignment-${Date.now()}`,
            role: "assistant",
            content: lastMessage.data.content,
            timestamp: Date.now(),
          });
        }
        break;
      case "input_ack":
        // 用户消息已收到，不做 UI 处理
        break;
      case "intervention_ack":
        addMessage({
          role: "system",
          content: lastMessage.data?.message || "干预指令已提交",
        });
        break;
      case "terminated":
        setActiveTasks((prev) =>
          prev.filter((t) => t.id !== lastMessage.data?.task_id),
        );
        addMessage({ role: "system", content: "任务已终止" });
        break;
      case "execution_complete":
        addAIStep({
          id: `exec-${Date.now()}`,
          type: "execution_complete",
          content:
            lastMessage.data?.content ||
            lastMessage.data?.message ||
            "执行完成",
          timestamp: Date.now(),
        });
        break;
      case "entering_task_loop":
        // 内部状态切换，不做 UI 处理
        break;
      case "task_complete":
        addMessage({ role: "system", content: "任务执行完成" });
        setActiveTasks((prev) =>
          prev.filter((t) => t.id !== lastMessage.data?.task_id),
        );
        executionLog.addSuccess("任务执行完成", {
          task_id: lastMessage.data?.task_id,
        });
        break;
      case "chat_alignment_reply":
        if (lastMessage.data?.content) {
          const msgRole = lastMessage.data?.role || "assistant";
          // 【修复】添加记忆元数据支持
          const message: Message = {
            id: `chat-${Date.now()}`,
            role: msgRole,
            content: lastMessage.data.content,
            timestamp: lastMessage.data?.timestamp || Date.now(),
            // 添加记忆元数据字段
            memory_count: lastMessage.data?.memory_count ?? null,
            memory_ids: lastMessage.data?.memory_ids ?? null,
            relevance_score: lastMessage.data?.relevance_score ?? null,
            memory_types: lastMessage.data?.memory_types ?? null,
          };
          addMessage(message);
        }
        setAgentStatus("idle");
        executionLog.addSuccess("AI 回复完成", {
          type: "chat_alignment",
        });
        break;
      case "quick_chat_reply":
        if (lastMessage.data?.content) {
          addMessage({
            id: `quick-chat-${Date.now()}`,
            role: "assistant",
            content: lastMessage.data.content,
            timestamp: Date.now(),
            msgType: "quick_chat",
          });
          executionLog.addSuccess("AI 快速回复", {
            preview: lastMessage.data.content.slice(0, 100),
          });
        }
        setAgentStatus("idle");
        setIsProcessing(false);
        break;
      case "task_breakdown": {
        const steps = lastMessage.data?.steps || [];
        if (steps.length > 0) {
          addMessage({
            id: `task-breakdown-${Date.now()}`,
            role: "system",
            content: `任务已拆解为 ${steps.length} 个步骤：\n${steps
              .map((s: any, i: number) => `${i + 1}. ${s.name}`)
              .join("\n")}`,
            timestamp: Date.now(),
            msgType: "task_breakdown",
          });
          executionLog.addInfo(`任务已拆解为 ${steps.length} 个步骤`, {
            steps: steps.map((s: any) => s.name),
          });
        }
        break;
      }
      case "task_started": {
        const taskData = lastMessage.data;
        const taskMsg =
          taskData?.content ||
          "任务已启动，我会后台处理。你可以随时问我进度或聊别的。";
        addMessage({
          id: `task-started-${Date.now()}`,
          role: "assistant",
          content: taskMsg,
          timestamp: Date.now(),
          msgType: "task_started",
        });
        executionLog.addInfo("任务已启动", {
          instruction: taskData?.instruction,
          task_id: taskData?.task_id,
        });
        // 将任务加入 activeTasks，让 InputArea 按钮识别到运行中任务
        setActiveTasks((prev) => {
          const taskId = taskData?.task_id || `task-${Date.now()}`;
          if (prev.find((t) => t.id === taskId)) return prev;
          return [
            ...prev,
            {
              id: taskId,
              name: taskData?.instruction || "后台任务",
              description: taskData?.instruction || "",
              status: "running",
              progress: 0,
              startTime: Date.now(),
              elapsedTime: 0,
              type: "user",
              intent: taskData?.instruction || "",
              priority: 5,
              created_at: Date.now(),
            },
          ];
        });
        setAgentStatus("idle");
        setIsProcessing(false);
        break;
      }
      case "task_control_reply": {
        const ctrlData = lastMessage.data;
        const ctrlMsg = ctrlData?.content || "操作已执行";
        const ctrlMode = ctrlData?.mode || "";
        addMessage({
          id: `task-control-${Date.now()}`,
          role: "system",
          content: ctrlMsg,
          timestamp: Date.now(),
          msgType: "task_control",
        });
        executionLog.addAction(`任务控制: ${ctrlMode || "未知操作"}`, {
          mode: ctrlMode,
          content: ctrlMsg,
        });

        // 根据控制类型更新 activeTasks 状态
        if (ctrlMode === "task_paused") {
          setActiveTasks((prev) =>
            prev.map((t) =>
              t.status === "running" ? { ...t, status: "paused" as const } : t,
            ),
          );
          setAgentStatus("idle");
        } else if (ctrlMode === "task_resumed") {
          setActiveTasks((prev) =>
            prev.map((t) =>
              t.status === "paused" ? { ...t, status: "running" as const } : t,
            ),
          );
        } else if (ctrlMode === "task_cancelled" || ctrlMode === "task_retry") {
          setActiveTasks((prev) =>
            prev.filter((t) => t.status !== "running" && t.status !== "paused"),
          );
          setAgentStatus("idle");
          setIsProcessing(false);
        }
        break;
      }
      case "stream_start":
        setStreamingContent("");
        setAgentStatus("thinking");
        break;
      case "stream_chunk":
        setStreamingContent((prev) => prev + (lastMessage.data?.content || ""));
        if (lastMessage.data?.content) {
          addAIStep({
            id: `stream-${Date.now()}-${Math.random()}`,
            type: "thinking",
            content: lastMessage.data.content,
            timestamp: Date.now(),
          });
        }
        break;
      case "stream_end": {
        const finalContent =
          streamingContent || lastMessage.data?.content || "";
        addMessage({
          role: "assistant",
          content: finalContent,
          aiSteps: [...aiStepsRef.current],
        });
        setAISteps([]);
        executionLog.addSuccess("流式响应完成", {
          preview: finalContent.slice(0, 100),
          timestamp: Date.now(),
        });
        setAgentStatus("idle");
        setIsProcessing(false);
        setStreamingContent("");
        break;
      }
      // DEPRECATED: 后端已不再推送此类型，保留以防万一
      case "observer_mode":
        setAgentStatus("observing");
        showNotification({
          type: "info",
          title: "观察者模式",
          message:
            lastMessage.data?.message || "AI进入观察者模式，等待您的需求",
        });
        break;
      // DEPRECATED: 后端已不再推送此类型，保留以防万一
      case "observer_mode_exit":
        setAgentStatus("idle");
        showNotification({
          type: "success",
          title: "观察者模式",
          message: lastMessage.data?.message || "AI已退出观察者模式",
        });
        break;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastMessage, currentAgent.id, addMessage]);

  // ═══════════════════════════════════════════════════════════════════
  // 全局干预事件监听 - 让ChatArea等组件的暂停按钮真正生效
  // ═══════════════════════════════════════════════════════════════════
  const activeTasksRef = useRef(activeTasks);
  useEffect(() => {
    activeTasksRef.current = activeTasks;
  }, [activeTasks]);

  useEffect(() => {
    const handlePause = async () => {
      if (!currentSessionId) return;
      showNotification({
        type: "info",
        title: "正在暂停",
        message: "正在请求中断当前循环...",
      });
      const result = await interventionApi.interruptLoop(
        currentSessionId,
        "用户点击暂停按钮",
      );
      if (result.success) {
        showNotification({
          type: "success",
          title: "已暂停",
          message: result.message,
        });
        setAgentStatus("idle");
        setIsProcessing(false);
      } else {
        showNotification({
          type: "error",
          title: "暂停失败",
          message: result.message,
        });
      }
    };

    const handleCancel = async () => {
      if (!currentSessionId) return;
      showNotification({
        type: "info",
        title: "正在取消",
        message: "正在请求取消当前循环...",
      });
      const result = await interventionApi.interruptLoop(
        currentSessionId,
        "用户点击取消按钮",
        false,
      );
      if (result.success) {
        showNotification({
          type: "success",
          title: "已取消",
          message: result.message,
        });
        setAgentStatus("idle");
        setIsProcessing(false);
      } else {
        showNotification({
          type: "error",
          title: "取消失败",
          message: result.message,
        });
      }
    };

    const handleAdjust = () => {
      // 调整方向：发送一个系统提示，让用户在输入框输入新的方向
      showNotification({
        type: "info",
        title: "调整方向",
        message: "请在输入框中描述您希望调整的方向",
      });
      // 聚焦输入框
      const inputElement = document.querySelector("textarea");
      if (inputElement) {
        inputElement.focus();
      }
    };

    const handleResume = async () => {
      const pausedTask = activeTasksRef.current.find(
        (t) => t.status === "paused",
      );
      if (!pausedTask) {
        showNotification({
          type: "warning",
          title: "无可恢复任务",
          message: "当前没有已暂停的任务",
        });
        return;
      }
      showNotification({
        type: "info",
        title: "正在恢复",
        message: `正在恢复任务: ${pausedTask.name || pausedTask.id}...`,
      });
      const result = await interventionApi.resumeTask(pausedTask.id);
      if (result.success) {
        showNotification({
          type: "success",
          title: "已恢复",
          message: result.message,
        });
        setAgentStatus("executing");
      } else {
        showNotification({
          type: "error",
          title: "恢复失败",
          message: result.message,
        });
      }
    };

    window.addEventListener("intervention:pause", handlePause as EventListener);
    window.addEventListener(
      "intervention:cancel",
      handleCancel as EventListener,
    );
    window.addEventListener(
      "intervention:resume",
      handleResume as EventListener,
    );
    window.addEventListener(
      "intervention:adjust",
      handleAdjust as EventListener,
    );

    return () => {
      window.removeEventListener(
        "intervention:pause",
        handlePause as EventListener,
      );
      window.removeEventListener(
        "intervention:cancel",
        handleCancel as EventListener,
      );
      window.removeEventListener(
        "intervention:resume",
        handleResume as EventListener,
      );
      window.removeEventListener(
        "intervention:adjust",
        handleAdjust as EventListener,
      );
    };
  }, [currentSessionId, showNotification]);

  // ═══════════════════════════════════════════════════════════════════
  // 发送消息处理 - 统一走 WebSocket，避免 REST + WS 双通道重复
  // ═══════════════════════════════════════════════════════════════════
  const handleSendMessage = async (
    content: string,
    type: "text" | "voice" | "chat" | "auto" = "auto",
    files?: UploadedFile[],
  ) => {
    // 确保有当前会话；创建后从 store 实时读取 sessionId，避免闭包过期
    let sessionId = currentSessionId;
    if (!sessionId) {
      try {
        const session = await createSession("daily");
        sessionId = session.id;
      } catch (error) {
        console.error("[App] 创建会话失败:", error);
        showNotification({
          type: "error",
          title: "发送失败",
          message: "无法创建会话，请稍后重试",
        });
        return;
      }
    }
    if (!sessionId) {
      sessionId = useSessionStore.getState().currentSessionId;
    }
    if (!sessionId) {
      showNotification({
        type: "error",
        title: "发送失败",
        message: "会话未建立，无法发送消息",
      });
      return;
    }

    // 乐观更新：本地先添加用户消息，避免发送后界面空白
    addMessage({
      id: `client-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      role: "user",
      content,
      type: type === "auto" ? "text" : type,
      timestamp: Date.now(),
      attachments: files,
      memory_count: null,
      memory_ids: null,
      relevance_score: null,
      memory_types: null,
    });

    // 设置AI状态为思考中
    setAgentStatus("thinking");

    try {
      // 统一走 WebSocket 发送，后端根据 input_type 选择处理模式
      const sent = sendMessage({
        type: "user_input",
        content: content,
        agent: currentAgent.id,
        input_type: type,
        attachments: files,
        session_id: sessionId,
      });

      if (!sent) {
        throw new Error("WebSocket 连接未建立，无法发送消息");
      }
    } catch (error) {
      console.error("[App] 发送消息失败:", error);
      showNotification({
        type: "error",
        title: "发送失败",
        message: error instanceof Error ? error.message : "发送消息失败",
      });
      setAgentStatus("error");
    }
  };

  // 【并发改造】发送任务控制指令（不添加到聊天列表）
  const handleSendControl = (action: string) => {
    if (!currentSessionId) return;
    sendMessage({
      type: "user_input",
      content: action,
      agent: currentAgent.id,
      input_type: "auto",
      session_id: currentSessionId,
    });
    console.log("[App] 发送任务控制指令:", action);
  };

  const handleAgentSwitch = (agent: Agent) => {
    setCurrentAgent(agent);
    addMessage({
      id: `system-${Date.now()}`,
      role: "system",
      content: `已切换到 ${agent.name}`,
      agent: agent.id,
      timestamp: Date.now(),
    });
  };

  // Preserve callback for external compatibility (suppresses TS6133)
  void handleAgentSwitch;

  return (
    <div className="flex-1 min-h-0 overflow-hidden relative grid grid-rows-[128px_48px_1fr]">
      {/* 中央画布区 - 精简高度 */}
      <MainCanvas currentAgent={currentAgent} agentStatus={agentStatus} />

      {/* 脉冲时间轴 */}
      <PulseTimeline messages={messages} />

      {/* 聊天区域 */}
      <ChatArea
        currentAgent={currentAgent}
        onSuggestionClick={handleSendMessage}
        onMemoryClick={(memoryId) => {
          if (memoryId) {
            setHighlightMemoryId(memoryId);
          }
          setIsMemoryPanelOpen(true);
        }}
        isProcessing={isProcessing}
        onSend={handleSendMessage}
        onSendControl={handleSendControl}
        isRecording={isRecording}
        onRecordingChange={setIsRecording}
        agentStatus={agentStatus}
        activeTasks={activeTasks}
        sessionId={currentSessionId || "default"}
      />

      {/* 执行日志面板 */}
      <AnimatePresence>
        {showExecutionLog && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-white/5 bg-slate-950/50 shrink-0"
          >
            <ExecutionLog
              entries={executionLog.entries}
              maxHeight="200px"
              showControls={true}
              onClear={executionLog.clear}
              onExport={executionLog.exportLog}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* 语音状态指示器 */}
      <VoiceStateIndicator />

      {/* 模式切换指示器 */}
      <ModeSwitchIndicator />

      {/* 执行日志切换按钮 - 浮动按钮 */}
      <motion.button
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setShowExecutionLog(!showExecutionLog)}
        className={`fixed bottom-20 right-4 z-40 flex items-center gap-2 px-3 py-2 rounded-lg border shadow-lg transition-all ${
          showExecutionLog
            ? "bg-cyan-500/20 border-cyan-500/30 text-cyan-400"
            : "bg-slate-900/80 border-white/10 text-slate-400 hover:text-white hover:border-white/20"
        }`}
        title={showExecutionLog ? "隐藏执行日志" : "显示执行日志"}
      >
        <ScrollText className="w-4 h-4" />
        <span className="text-xs">
          {showExecutionLog ? "隐藏日志" : "执行日志"}
        </span>
        {executionLog.count > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-700 text-slate-300">
            {executionLog.count}
          </span>
        )}
      </motion.button>

      {/* 观察者模式指示器 */}
      <ObserverIndicator isActive={agentStatus === "observing"} />

      {/* AI感知指示器 */}
      <PerceptionIndicator position="top-right" />

      {/* ═══════════════════════════════════════════════════════════════
          MemoryPanel 侧边栏 - 会话记忆详情
          ═══════════════════════════════════════════════════════════════ */}
      <AnimatePresence>
        {isMemoryPanelOpen && (
          <ErrorBoundary
            fallback={
              <MemoryPanelErrorFallback
                onClose={() => setIsMemoryPanelOpen(false)}
                error={memoryPanelError}
              />
            }
            onError={(error) => {
              console.error("[App] MemoryPanel 加载失败:", error);
              setMemoryPanelError(error);
            }}
          >
            <MemoryPanel
              sessionId={currentSessionId || ""}
              isOpen={isMemoryPanelOpen}
              onClose={() => {
                setIsMemoryPanelOpen(false);
                setHighlightMemoryId(null);
              }}
              highlightMemoryId={highlightMemoryId || undefined}
            />
          </ErrorBoundary>
        )}
      </AnimatePresence>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// ErrorBoundary 组件 - 防止 MemoryPanel 错误阻断主界面
// ═══════════════════════════════════════════════════════════════════
interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback: React.ReactNode;
  onError?: (error: Error) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[App] 组件错误捕获:", error, errorInfo);
    this.props.onError?.(error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

// MemoryPanel 错误回退组件
interface MemoryPanelErrorFallbackProps {
  onClose: () => void;
  error: Error | null;
}

function MemoryPanelErrorFallback({
  onClose,
  error,
}: MemoryPanelErrorFallbackProps) {
  return (
    <>
      {/* 遮罩层 */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40"
      />
      {/* 错误提示面板 */}
      <motion.div
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className="fixed right-0 top-0 h-full w-96 bg-sb-bg-secondary border-l border-white/10 shadow-2xl z-50 flex flex-col"
      >
        <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
          <div className="w-16 h-16 rounded-full bg-red-500/10 flex items-center justify-center mb-4">
            <svg
              className="w-8 h-8 text-red-400"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">
            记忆面板加载失败
          </h3>
          <p className="text-sm text-slate-400 mb-2">
            {error?.message || "组件初始化异常"}
          </p>
          <p className="text-xs text-slate-500 mb-6">
            主界面功能不受影响，请稍后重试或联系管理员
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-white/10 text-white hover:bg-white/20 transition-colors text-sm"
          >
            关闭面板
          </button>
        </div>
      </motion.div>
    </>
  );
}
