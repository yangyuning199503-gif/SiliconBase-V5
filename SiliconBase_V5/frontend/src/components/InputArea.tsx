import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Send,
  Paperclip,
  Mic,
  Command,
  Pause,
  Square,
  Play,
  X,
  FileText,
  Image,
  File,
  AlertTriangle,
} from "lucide-react";
import { fetchAPI } from "../utils/api";
import { TaskStatus } from "../types";

interface UploadedFile {
  id: string;
  name: string;
  type: string;
  size: number;
  url?: string;
}

interface InputAreaProps {
  onSend: (
    content: string,
    type?: "text" | "voice" | "chat" | "auto",
    files?: UploadedFile[],
  ) => void;
  onSendControl?: (action: string) => void; // 新增：发送任务控制指令（不显示在聊天区）
  isRecording: boolean;
  onRecordingChange: (recording: boolean) => void;
  agentStatus: string;
  activeTasks?: TaskStatus[];
  sessionId?: string; // 新增：当前会话ID
}

export default function InputArea({
  onSend,
  onSendControl,
  isRecording,
  onRecordingChange,
  agentStatus,
  activeTasks = [],
  sessionId = "default",
}: InputAreaProps) {
  const [input, setInput] = useState("");
  const [showCommands, setShowCommands] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showPauseConfirm, setShowPauseConfirm] = useState(false); // 新增：暂停确认弹窗
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  // 统一错误通知
  const notifyError = useCallback((message: string) => {
    window.dispatchEvent(
      new CustomEvent("show_error_notification", {
        detail: { message },
      }),
    );
  }, []);

  // 【hold-to-talk】录音状态
  const [isHolding, setIsHolding] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const commands = [
    { id: "remember", label: "/remember", desc: "保存到长期记忆" },
    { id: "mode", label: "/mode", desc: "切换工作模式" },
    { id: "agent", label: "/agent", desc: "切换Agent" },
    { id: "status", label: "/status", desc: "查看系统状态" },
  ];

  // 获取正在运行的任务
  const runningTask = activeTasks.find((t) => t.status === "running");
  const pausedTask = activeTasks.find((t) => t.status === "paused");

  // 【新增】ESC键暂停循环
  const handleInterruptLoop = async () => {
    if (!sessionId) return;

    setIsLoading(true);
    try {
      // 统一走 fetchAPI，自动携带 token 并处理 401
      await fetchAPI(`/api/sessions/${sessionId}/interrupt`, {
        method: "POST",
        body: {
          reason: "用户按下ESC键请求中断循环",
          graceful: true, // 优雅退出，等待当前工具完成
        },
      });

      console.log("[InputArea] 循环中断请求已发送:", sessionId);
      // 触发自定义事件通知ChatArea
      window.dispatchEvent(
        new CustomEvent("loop_interrupted", {
          detail: { sessionId, reason: "用户中断" },
        }),
      );
    } catch (error) {
      console.error("[SILENT_FAILURE_BLOCKED] 中断循环请求失败:", error);
      notifyError(
        `中断循环请求失败: ${error instanceof Error ? error.message : "网络错误"}`,
      );
    } finally {
      setIsLoading(false);
      setShowPauseConfirm(false);
    }
  };

  // 暂停任务/循环
  const handlePauseTask = async () => {
    setIsLoading(true);
    try {
      if (runningTask) {
        // 有具体任务ID时走REST API
        await fetchAPI(`/api/tasks/${runningTask.id}/pause`, {
          method: "POST",
          body: { reason: "用户暂停", new_requirements: "" },
        });
        console.log("[InputArea] 任务已暂停:", runningTask.id);
      } else if (
        agentStatus === "running" ||
        agentStatus === "thinking" ||
        agentStatus === "executing"
      ) {
        // 【修复】统一走中断API，确保能真正终止AgentLoop
        if (sessionId) {
          await fetchAPI(`/api/sessions/${sessionId}/interrupt`, {
            method: "POST",
            body: {
              reason: "用户点击暂停按钮",
              graceful: true,
            },
          });
          console.log("[InputArea] 循环中断请求已发送:", sessionId);
          window.dispatchEvent(
            new CustomEvent("loop_interrupted", {
              detail: { sessionId, reason: "用户暂停" },
            }),
          );
        }
      }
    } catch (error) {
      console.error("[SILENT_FAILURE_BLOCKED] 暂停请求失败:", error);
      notifyError(
        `暂停请求失败: ${error instanceof Error ? error.message : "网络错误"}`,
      );
    } finally {
      setIsLoading(false);
    }
  };

  // 恢复任务
  const handleResumeTask = async () => {
    if (!pausedTask) {
      // 【并发改造】没有具体 pausedTask 时，通过 WebSocket 发送恢复指令
      if (onSendControl) {
        setIsLoading(true);
        try {
          onSendControl("继续");
          console.log("[InputArea] 通过 WebSocket 发送恢复指令");
        } finally {
          setIsLoading(false);
        }
      }
      return;
    }
    setIsLoading(true);
    try {
      await fetchAPI(`/api/tasks/${pausedTask.id}/resume`, {
        method: "POST",
        body: {
          ai_confirmation: "用户要求恢复任务",
          confirmed_understanding: true,
        },
      });
      console.log("[InputArea] 任务已恢复:", pausedTask.id);
    } catch (error) {
      console.error("[SILENT_FAILURE_BLOCKED] 恢复任务请求失败:", error);
      notifyError(
        `恢复任务请求失败: ${error instanceof Error ? error.message : "网络错误"}`,
      );
    } finally {
      setIsLoading(false);
    }
  };

  // 结束任务/循环
  const handleCancelTask = async () => {
    setIsLoading(true);
    try {
      if (runningTask || pausedTask) {
        const task = runningTask || pausedTask;
        if (!task) return;
        await fetchAPI(`/api/tasks/${task.id}/cancel`, {
          method: "POST",
          body: { reason: "用户取消" },
        });
        console.log("[InputArea] 任务已取消:", task.id);
      } else if (
        agentStatus === "running" ||
        agentStatus === "thinking" ||
        agentStatus === "executing"
      ) {
        // 【修复】统一走中断API，确保能真正终止AgentLoop
        if (sessionId) {
          await fetchAPI(`/api/sessions/${sessionId}/interrupt`, {
            method: "POST",
            body: {
              reason: "用户点击取消按钮",
              graceful: false,
            },
          });
          console.log("[InputArea] 循环取消请求已发送:", sessionId);
          window.dispatchEvent(
            new CustomEvent("loop_interrupted", {
              detail: { sessionId, reason: "用户取消" },
            }),
          );
        }
      }
    } catch (error) {
      console.error("[SILENT_FAILURE_BLOCKED] 取消请求失败:", error);
      notifyError(
        `取消请求失败: ${error instanceof Error ? error.message : "网络错误"}`,
      );
    } finally {
      setIsLoading(false);
    }
  };

  const adjustTextareaHeight = () => {
    const textarea = inputRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      const newHeight = Math.min(Math.max(textarea.scrollHeight, 24), 120);
      textarea.style.height = `${newHeight}px`;
    }
  };

  useEffect(() => {
    adjustTextareaHeight();
  }, [input]);

  const handleSend = async () => {
    if (!input.trim() && selectedFiles.length === 0) return;

    let filesToSend: UploadedFile[] = [];
    if (selectedFiles.length > 0) {
      setIsUploading(true);
      try {
        filesToSend = await uploadFiles();
      } catch (error) {
        console.error("[InputArea] 文件上传失败:", error);
        window.dispatchEvent(
          new CustomEvent("show_error_notification", {
            detail: {
              message: `文件上传失败: ${error instanceof Error ? error.message : "未知错误"}`,
            },
          }),
        );
        setIsUploading(false);
        return;
      } finally {
        setIsUploading(false);
      }
    }

    const sendType = "auto";
    onSend(input, sendType, filesToSend.length > 0 ? filesToSend : undefined);

    setInput("");
    setShowCommands(false);
    setSelectedFiles([]);

    if (inputRef.current) {
      inputRef.current.style.height = "24px";
    }
  };

  // 【修改】ESC键处理：有循环运行时弹出确认框
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === "Escape") {
      // 如果有命令提示框，先关闭
      if (showCommands) {
        setShowCommands(false);
        return;
      }

      // 如果有输入内容，先清空
      if (input.trim()) {
        setInput("");
        inputRef.current?.blur();
        return;
      }

      // 【新增】如果有运行中的循环（agentStatus 为 thinking/executing），弹出暂停确认
      if (agentStatus === "thinking" || agentStatus === "executing") {
        setShowPauseConfirm(true);
        return;
      }

      inputRef.current?.blur();
    }
  };

  useEffect(() => {
    if (input.startsWith("/")) {
      setShowCommands(true);
    } else {
      setShowCommands(false);
    }
  }, [input]);

  // 【新增】全局ESC键监听 - 无论焦点在哪里都能暂停
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === "Escape" &&
        (agentStatus === "thinking" || agentStatus === "executing") &&
        !showPauseConfirm
      ) {
        e.preventDefault();
        setShowPauseConfirm(true);
      }
    };

    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, [agentStatus, showPauseConfirm]);

  const applyCommand = (cmd: string) => {
    setInput(cmd + " ");
    inputRef.current?.focus();
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      setSelectedFiles((prev) => [...prev, ...Array.from(files)]);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const removeSelectedFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const uploadFiles = async (): Promise<UploadedFile[]> => {
    const uploaded: UploadedFile[] = [];

    for (const file of selectedFiles) {
      const formData = new FormData();
      formData.append("file", file);

      try {
        // 统一走 fetchAPI，自动携带 token；FormData 由 fetchAPI 原样传递
        const result = await fetchAPI<{
          id?: string;
          url?: string;
          path?: string;
          filename?: string;
        }>("/api/upload", {
          method: "POST",
          body: formData,
        });

        uploaded.push({
          id: result.id || `${Date.now()}_${file.name}`,
          name: file.name,
          type: file.type,
          size: file.size,
          url: result.url || result.path,
        });
      } catch (error) {
        console.error(`[InputArea] 上传文件 ${file.name} 失败:`, error);
        throw error;
      }
    }

    return uploaded;
  };

  const getFileIcon = (fileType: string) => {
    if (fileType.startsWith("image/")) {
      return <Image className="w-4 h-4" />;
    } else if (fileType.includes("text") || fileType.includes("pdf")) {
      return <FileText className="w-4 h-4" />;
    }
    return <File className="w-4 h-4" />;
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  return (
    <div className="p-5 border-t border-white/10 bg-gradient-to-t from-black/20 to-transparent relative flex-shrink-0 transition-all duration-200 min-h-[120px]">
      {/* 【新增】ESC暂停确认弹窗 */}
      <AnimatePresence>
        {showPauseConfirm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center"
            onClick={() => setShowPauseConfirm(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-[#1e1e2a] border border-white/20 rounded-2xl p-6 max-w-md w-full mx-4 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start gap-4">
                <div className="p-3 rounded-xl bg-yellow-500/20 text-yellow-400">
                  <AlertTriangle className="w-6 h-6" />
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-white mb-2">
                    是否暂停当前循环？
                  </h3>
                  <p className="text-sm text-white/60 mb-4">
                    AI正在思考中。选择暂停方式：
                  </p>

                  <div className="space-y-2">
                    {/* 第一个选项：停止循环（不可恢复） */}
                    <button
                      onClick={handleInterruptLoop}
                      disabled={isLoading}
                      className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-all disabled:opacity-50 text-left"
                    >
                      <Square className="w-5 h-5" />
                      <div>
                        <div className="font-medium">停止循环</div>
                        <div className="text-xs text-red-400/70">
                          等待当前操作完成后停止（不可恢复）
                        </div>
                      </div>
                    </button>

                    {/* 第二个选项：暂停任务（可恢复） */}
                    {runningTask && (
                      <button
                        onClick={handlePauseTask}
                        disabled={isLoading}
                        className="w-full flex items-center gap-3 px-4 py-3 rounded-xl bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500/30 transition-all disabled:opacity-50 text-left"
                      >
                        <Pause className="w-5 h-5" />
                        <div>
                          <div className="font-medium">暂停任务</div>
                          <div className="text-xs text-yellow-400/70">
                            立即暂停，稍后可以从暂停点继续
                          </div>
                        </div>
                      </button>
                    )}

                    <button
                      onClick={() => setShowPauseConfirm(false)}
                      className="w-full px-4 py-2 rounded-xl bg-white/5 text-white/60 hover:bg-white/10 transition-all text-sm"
                    >
                      取消，继续运行
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 任务控制按钮 */}
      {(runningTask || pausedTask) && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-3 flex items-center gap-2"
        >
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#2a2a3a] border border-white/15">
            <div
              className={`w-2 h-2 rounded-full ${
                runningTask ? "bg-yellow-400 animate-pulse" : "bg-blue-400"
              }`}
            />
            <span className="text-xs text-white/70">
              {runningTask
                ? `任务执行中: ${runningTask.name}`
                : `任务已暂停: ${pausedTask?.name}`}
            </span>
          </div>

          {runningTask ? (
            <button
              onClick={handlePauseTask}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500/30 transition-all disabled:opacity-50"
              title="暂停任务"
            >
              <Pause className="w-3.5 h-3.5" />
              <span className="text-xs">暂停</span>
            </button>
          ) : (
            <button
              onClick={handleResumeTask}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30 transition-all disabled:opacity-50"
              title="恢复任务"
            >
              <Play className="w-3.5 h-3.5" />
              <span className="text-xs">恢复</span>
            </button>
          )}

          <button
            onClick={handleCancelTask}
            disabled={isLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-all disabled:opacity-50"
            title="取消任务"
          >
            <Square className="w-3.5 h-3.5" />
            <span className="text-xs">取消</span>
          </button>
        </motion.div>
      )}

      {/* 已选文件列表 */}
      {selectedFiles.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-3 flex flex-wrap gap-2"
        >
          {selectedFiles.map((file, index) => (
            <div
              key={`${file.name}_${index}`}
              className="flex items-center gap-2 px-2 py-1 rounded-lg bg-[#2a2a3a] border border-white/15 text-xs text-white/70"
            >
              {getFileIcon(file.type)}
              <span className="max-w-[150px] truncate">{file.name}</span>
              <span className="text-white/40">
                ({formatFileSize(file.size)})
              </span>
              <button
                onClick={() => removeSelectedFile(index)}
                className="p-0.5 rounded hover:bg-white/10 text-white/50 hover:text-white/70 transition-colors"
                disabled={isUploading}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </motion.div>
      )}

      <div className="relative">
        {/* 命令提示框 */}
        {showCommands && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98 }}
            className="absolute bottom-full mb-3 left-0 right-0 bg-[#232330] p-2 rounded-xl z-30 border border-white/15 shadow-2xl"
          >
            {commands.map((cmd) => (
              <button
                key={cmd.id}
                onClick={() => applyCommand(cmd.label)}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors text-left group"
              >
                <code className="text-cyan-400 font-mono text-sm group-hover:text-cyan-300">
                  {cmd.label}
                </code>
                <span className="text-sm text-white/50 group-hover:text-white/70">
                  {cmd.desc}
                </span>
              </button>
            ))}
          </motion.div>
        )}

        {/* 输入框容器 */}
        <div className="flex items-center gap-2 bg-[#232330] p-2 rounded-2xl border border-white/15 focus-within:border-cyan-500/40 focus-within:shadow-lg focus-within:shadow-cyan-500/10 transition-all duration-200">
          {/* 附件按钮 */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={isRecording || isUploading}
            className="p-2.5 rounded-xl hover:bg-white/5 transition-all duration-200 text-white/50 hover:text-white/70 disabled:opacity-50 disabled:cursor-not-allowed"
            title="上传文件"
          >
            <Paperclip className="w-5 h-5" />
          </button>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            disabled={isRecording || isUploading}
          />

          {/* 输入框 */}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isRecording
                ? "正在聆听..."
                : "输入内容，AI 自主判断是聊天还是任务..."
            }
            className="flex-1 bg-transparent border-none outline-none text-white placeholder-white/30 text-sm resize-none overflow-y-auto py-1.5"
            disabled={isRecording || isUploading}
            style={{
              minHeight: "24px",
              maxHeight: "120px",
              height: "24px",
              transition: "height 0.15s ease-out",
            }}
            rows={1}
          />

          {!input && (
            <div className="hidden md:flex items-center gap-1.5 text-xs text-white/50 bg-[#2a2a3a] px-2 py-1 rounded-lg">
              <Command className="w-3 h-3" />
              <span>/ 快捷命令</span>
            </div>
          )}

          {/* 语音按钮 —— hold-to-talk 按住说话 */}
          <button
            onMouseDown={async () => {
              setIsHolding(true);
              onRecordingChange(true);
              audioChunksRef.current = [];
              try {
                const stream = await navigator.mediaDevices.getUserMedia({
                  audio: true,
                });
                const recorder = new MediaRecorder(stream, {
                  mimeType: "audio/webm",
                });
                mediaRecorderRef.current = recorder;
                recorder.ondataavailable = (e) => {
                  if (e.data.size > 0) audioChunksRef.current.push(e.data);
                };
                recorder.onstop = async () => {
                  stream.getTracks().forEach((t) => t.stop());
                  const audioBlob = new Blob(audioChunksRef.current, {
                    type: "audio/webm",
                  });
                  if (audioBlob.size < 1000) return; // 太短忽略
                  const formData = new FormData();
                  formData.append("audio", audioBlob, "recording.webm");
                  try {
                    const result = await fetchAPI<{ text?: string }>(
                      "/api/voice/stt",
                      {
                        method: "POST",
                        body: formData,
                      },
                    );
                    if (result.text) {
                      onSend(result.text, "voice");
                    }
                  } catch (err) {
                    console.error("[InputArea] STT请求失败:", err);
                    window.dispatchEvent(
                      new CustomEvent("show_error_notification", {
                        detail: {
                          message: `语音识别失败: ${err instanceof Error ? err.message : "未知错误"}`,
                        },
                      }),
                    );
                  }
                };
                recorder.start(100);
                holdTimerRef.current = setTimeout(() => {
                  if (recorder.state === "recording") recorder.stop();
                  setIsHolding(false);
                  onRecordingChange(false);
                }, 30000); // 最大30秒
              } catch (err) {
                console.error("[InputArea] 麦克风启动失败:", err);
                setIsHolding(false);
                onRecordingChange(false);
                window.dispatchEvent(
                  new CustomEvent("show_error_notification", {
                    detail: { message: "无法访问麦克风，请检查权限设置" },
                  }),
                );
              }
            }}
            onMouseUp={() => {
              if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
              setIsHolding(false);
              onRecordingChange(false);
              if (mediaRecorderRef.current?.state === "recording") {
                mediaRecorderRef.current.stop();
              }
            }}
            onMouseLeave={() => {
              if (isHolding) {
                if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
                setIsHolding(false);
                onRecordingChange(false);
                if (mediaRecorderRef.current?.state === "recording") {
                  mediaRecorderRef.current.stop();
                }
              }
            }}
            onTouchStart={async (e) => {
              e.preventDefault();
              setIsHolding(true);
              onRecordingChange(true);
              audioChunksRef.current = [];
              try {
                const stream = await navigator.mediaDevices.getUserMedia({
                  audio: true,
                });
                const recorder = new MediaRecorder(stream, {
                  mimeType: "audio/webm",
                });
                mediaRecorderRef.current = recorder;
                recorder.ondataavailable = (ev) => {
                  if (ev.data.size > 0) audioChunksRef.current.push(ev.data);
                };
                recorder.onstop = async () => {
                  stream.getTracks().forEach((t) => t.stop());
                  const audioBlob = new Blob(audioChunksRef.current, {
                    type: "audio/webm",
                  });
                  if (audioBlob.size < 1000) return;
                  const formData = new FormData();
                  formData.append("audio", audioBlob, "recording.webm");
                  try {
                    const result = await fetchAPI<{ text?: string }>(
                      "/api/voice/stt",
                      {
                        method: "POST",
                        body: formData,
                      },
                    );
                    if (result.text) onSend(result.text, "voice");
                  } catch (err) {
                    console.error("[InputArea] STT请求失败:", err);
                    window.dispatchEvent(
                      new CustomEvent("show_error_notification", {
                        detail: {
                          message: `语音识别失败: ${err instanceof Error ? err.message : "未知错误"}`,
                        },
                      }),
                    );
                  }
                };
                recorder.start(100);
                holdTimerRef.current = setTimeout(() => {
                  if (recorder.state === "recording") recorder.stop();
                  setIsHolding(false);
                  onRecordingChange(false);
                }, 30000);
              } catch (err) {
                console.error("[InputArea] 麦克风启动失败:", err);
                setIsHolding(false);
                onRecordingChange(false);
                window.dispatchEvent(
                  new CustomEvent("show_error_notification", {
                    detail: { message: "无法访问麦克风，请检查权限设置" },
                  }),
                );
              }
            }}
            onTouchEnd={() => {
              if (holdTimerRef.current) clearTimeout(holdTimerRef.current);
              setIsHolding(false);
              onRecordingChange(false);
              if (mediaRecorderRef.current?.state === "recording") {
                mediaRecorderRef.current.stop();
              }
            }}
            className={`p-2.5 rounded-xl transition-all duration-200 select-none ${
              isHolding || isRecording
                ? "bg-red-500/30 text-red-400 border border-red-500/40 shadow-lg shadow-red-500/20"
                : "hover:bg-white/5 text-white/50 hover:text-white/70"
            } ${isHolding ? "animate-pulse" : ""}`}
            title={isHolding ? "松开结束录音" : "按住说话"}
          >
            <Mic className={`w-5 h-5 ${isHolding ? "animate-bounce" : ""}`} />
          </button>

          {/* 暂停任务按钮 - 常驻 */}
          <button
            onClick={handlePauseTask}
            disabled={
              isLoading ||
              (!runningTask &&
                agentStatus !== "running" &&
                agentStatus !== "thinking" &&
                agentStatus !== "executing")
            }
            className="p-2.5 rounded-xl bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            title="暂停任务/循环"
          >
            <Pause className="w-5 h-5" />
          </button>

          {/* 恢复任务按钮 - 常驻 */}
          <button
            onClick={handleResumeTask}
            disabled={isLoading || !pausedTask}
            className="p-2.5 rounded-xl bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            title="恢复任务"
          >
            <Play className="w-5 h-5" />
          </button>

          {/* 结束任务按钮 - 常驻 */}
          <button
            onClick={handleCancelTask}
            disabled={
              isLoading ||
              (!(runningTask || pausedTask) &&
                agentStatus !== "running" &&
                agentStatus !== "thinking" &&
                agentStatus !== "executing")
            }
            className="p-2.5 rounded-xl bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            title="结束任务/循环"
          >
            <Square className="w-5 h-5" />
          </button>

          {/* 发送按钮 */}
          <button
            onClick={handleSend}
            disabled={
              (!input.trim() && selectedFiles.length === 0) ||
              isRecording ||
              isUploading
            }
            className="p-2.5 rounded-xl text-white disabled:opacity-30 disabled:cursor-not-allowed hover:brightness-110 hover:scale-105 active:scale-95 transition-all duration-200 shadow-lg bg-gradient-to-r from-cyan-500 to-blue-500 shadow-cyan-500/20"
          >
            {isUploading ? (
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
              >
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full" />
              </motion.div>
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>

      {/* 底部提示 */}
      <div className="flex items-center justify-between mt-3 text-xs">
        <div className="flex items-center gap-4 text-white/50">
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded bg-[#2a2a3a] text-white/70 font-mono text-[10px]">
              Enter
            </kbd>
            发送
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded bg-[#2a2a3a] text-white/70 font-mono text-[10px]">
              Shift + Enter
            </kbd>
            换行
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 rounded bg-[#2a2a3a] text-white/70 font-mono text-[10px]">
              Esc
            </kbd>
            {agentStatus === "running" ? "暂停循环" : "取消"}
          </span>
          <span className="flex items-center gap-1.5 text-cyan-400">
            AI 自主判断模式
          </span>
        </div>
        <div className="flex items-center gap-2 text-white/50">
          <div
            className={`w-2 h-2 rounded-full ${
              agentStatus === "idle"
                ? "bg-green-400 shadow-lg shadow-green-400/50"
                : "bg-yellow-400 animate-pulse shadow-lg shadow-yellow-400/50"
            }`}
          />
          <span className="capitalize font-medium">{agentStatus}</span>
        </div>
      </div>
    </div>
  );
}
