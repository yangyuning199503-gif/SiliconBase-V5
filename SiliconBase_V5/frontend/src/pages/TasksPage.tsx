import React, { useState, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { TaskCard, Task } from "../components/TaskCard";
import { LongTaskSlotsPanel, SlotTask } from "../components/LongTaskSlotsPanel";
import {
  Loader2,
  RefreshCw,
  Plus,
  ListFilter,
  CheckCircle2,
  Play,
  Pause,
  AlertCircle,
  Clock,
  X,
  ChevronDown,
  ChevronUp,
  Save,
  Rocket,
  Inbox,
} from "lucide-react";
import { taskApi } from "@/utils/api/task";
import { slotAPI } from "@/utils/api/slots";
import { useNotifications } from "@/hooks/useNotifications";
import { motion, AnimatePresence } from "framer-motion";

type FilterStatus =
  | "all"
  | "pending"
  | "running"
  | "paused"
  | "completed"
  | "failed";

type CreateMode = "execute" | "backlog";

// 创建任务对话框组件
interface CreateTaskDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: {
    mode: CreateMode;
    slotId: number | null;
    taskName: string;
    taskType: string;
    requirements: string;
    priority: string;
  }) => void;
  isLoading: boolean;
  slots: SlotTask[];
}

const TASK_TYPES = [
  "开发任务",
  "研究任务",
  "数据分析",
  "文档编写",
  "代码审查",
  "其他",
];

const PRIORITIES = [
  { value: "urgent", label: "紧急" },
  { value: "high", label: "高" },
  { value: "normal", label: "普通" },
  { value: "low", label: "低" },
];

const CreateTaskDialog: React.FC<CreateTaskDialogProps> = ({
  isOpen,
  onClose,
  onSubmit,
  isLoading,
  slots,
}) => {
  const [taskName, setTaskName] = useState("");
  const [taskType, setTaskType] = useState(TASK_TYPES[0]);
  const [requirements, setRequirements] = useState("");
  const [priority, setPriority] = useState("normal");
  const [mode, setMode] = useState<CreateMode>("execute");
  const [selectedSlotId, setSelectedSlotId] = useState<number | null>(null);

  useEffect(() => {
    if (!isOpen) {
      setTaskName("");
      setRequirements("");
      setPriority("normal");
      setMode("execute");
      setSelectedSlotId(null);
    } else {
      const idleSlot = slots.find((s) => s.status === "idle");
      setSelectedSlotId(idleSlot ? idleSlot.slot_id : null);
    }
  }, [isOpen, slots]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskName.trim()) return;
    onSubmit({
      mode,
      slotId: selectedSlotId,
      taskName: taskName.trim(),
      taskType,
      requirements: requirements.trim(),
      priority,
    });
  };

  const idleSlots = slots.filter((s) => s.status === "idle");
  const canExecute = idleSlots.length > 0 || selectedSlotId !== null;

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="bg-sb-bg-secondary rounded-xl border border-sb-cyan/30 p-6 w-full max-w-lg shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          {/* 标题 */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-sb-cyan/20 flex items-center justify-center">
                <Plus className="w-5 h-5 text-sb-cyan" />
              </div>
              <div>
                <h4 className="text-white font-semibold">新建任务</h4>
                <p className="text-sb-text-secondary text-sm">
                  选择让 AI 立即执行，或仅记录到待办清单
                </p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-sb-text-secondary hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <form onSubmit={handleSubmit}>
            {/* 模式选择 */}
            <div className="mb-4">
              <label className="block text-sb-text-primary text-sm mb-2">
                创建方式
              </label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setMode("execute")}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-all ${
                    mode === "execute"
                      ? "bg-sb-cyan/20 border-sb-cyan/50 text-sb-cyan"
                      : "bg-sb-bg-primary border-white/10 text-sb-text-secondary hover:text-white"
                  }`}
                >
                  <Rocket className="w-4 h-4" />
                  让 AI 执行
                </button>
                <button
                  type="button"
                  onClick={() => setMode("backlog")}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-all ${
                    mode === "backlog"
                      ? "bg-sb-cyan/20 border-sb-cyan/50 text-sb-cyan"
                      : "bg-sb-bg-primary border-white/10 text-sb-text-secondary hover:text-white"
                  }`}
                >
                  <Inbox className="w-4 h-4" />
                  添加到待办
                </button>
              </div>
              {mode === "execute" && !canExecute && (
                <p className="mt-2 text-xs text-yellow-400 flex items-center gap-1">
                  <AlertCircle className="w-3 h-3" />
                  当前没有空闲槽位，请先停止或完成现有任务
                </p>
              )}
            </div>

            {/* 槽位选择（仅执行模式） */}
            {mode === "execute" && (
              <div className="mb-4">
                <label className="block text-sb-text-primary text-sm mb-2">
                  执行槽位
                </label>
                <select
                  value={selectedSlotId ?? ""}
                  onChange={(e) =>
                    setSelectedSlotId(Number(e.target.value) || null)
                  }
                  className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-sb-cyan/50"
                >
                  {slots.map((slot) => (
                    <option key={slot.slot_id} value={slot.slot_id}>
                      槽位 {slot.slot_id} -{" "}
                      {slot.status === "idle"
                        ? "空闲"
                        : slot.task_name || slot.status}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* 任务名称 */}
            <div className="mb-4">
              <label className="block text-sb-text-primary text-sm mb-2">
                任务名称 <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={taskName}
                onChange={(e) => setTaskName(e.target.value)}
                placeholder="输入任务名称..."
                className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-sb-text-secondary focus:outline-none focus:border-sb-cyan/50"
                required
              />
            </div>

            {/* 任务类型 */}
            <div className="mb-4">
              <label className="block text-sb-text-primary text-sm mb-2">
                任务类型
              </label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-sb-cyan/50"
              >
                {TASK_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>

            {/* 优先级 */}
            <div className="mb-4">
              <label className="block text-sb-text-primary text-sm mb-2">
                优先级
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
                className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-sb-cyan/50"
              >
                {PRIORITIES.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>

            {/* 需求描述 */}
            <div className="mb-4">
              <label className="block text-sb-text-primary text-sm mb-2">
                需求描述
              </label>
              <textarea
                value={requirements}
                onChange={(e) => setRequirements(e.target.value)}
                placeholder="描述任务的具体需求和目标..."
                rows={4}
                className="w-full bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-sb-text-secondary focus:outline-none focus:border-sb-cyan/50 resize-none"
              />
            </div>

            {/* 按钮 */}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-sb-text-secondary hover:text-white text-sm transition-all"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={isLoading || !taskName.trim() || (mode === "execute" && !canExecute)}
                className="flex items-center gap-1.5 px-4 py-2 bg-sb-cyan hover:bg-sb-cyan/80 disabled:bg-sb-bg-secondary/60 disabled:cursor-not-allowed text-white font-medium rounded-lg text-sm transition-all"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    创建中...
                  </>
                ) : mode === "execute" ? (
                  <>
                    <Rocket className="w-4 h-4" />
                    创建并执行
                  </>
                ) : (
                  <>
                    <Inbox className="w-4 h-4" />
                    添加到待办
                  </>
                )}
              </button>
            </div>
          </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export const TasksPage: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const { showNotification } = useNotifications();

  // 3槽位长任务状态
  const [slots, setSlots] = useState<SlotTask[]>([
    { slot_id: 1, status: "idle", progress: 0 },
    { slot_id: 2, status: "idle", progress: 0 },
    { slot_id: 3, status: "idle", progress: 0 },
  ]);
  const [slotsLoading, setSlotsLoading] = useState(false);

  // 创建任务对话框状态
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createTaskLoading, setCreateTaskLoading] = useState(false);

  // 检查点管理状态
  const [showCheckpointsPanel, setShowCheckpointsPanel] = useState(false);
  const [checkpointsMap, setCheckpointsMap] = useState<Record<string, any[]>>(
    {},
  );
  const [checkpointsLoading, setCheckpointsLoading] = useState(false);
  const [checkpointError, setCheckpointError] = useState<string | null>(null);

  // Pure data fetchers for react-query
  const fetchTasksData = useCallback(async (): Promise<Task[]> => {
    try {
      const data = await taskApi.listTasks({ limit: 100 });

      if (data.tasks) {
        const formattedTasks: Task[] = data.tasks.map((t: any) => ({
          id: t.id,
          title: t.title || t.intent || "未命名任务",
          description: t.description || t.intent || "",
          status:
            t.status === "running"
              ? "running"
              : t.status === "completed"
                ? "completed"
                : t.status === "failed"
                  ? "failed"
                  : t.status === "paused"
                    ? "paused"
                    : "pending",
          progress: t.progress || 0,
          priority: t.priority,
          created_at: t.created_at
            ? new Date(t.created_at).getTime()
            : Date.now(),
          started_at: t.started_at,
        }));

        const statusOrder = {
          running: 0,
          paused: 1,
          pending: 2,
          failed: 3,
          completed: 4,
        };
        formattedTasks.sort(
          (a, b) => statusOrder[a.status] - statusOrder[b.status],
        );

        return formattedTasks;
      }
      return [];
    } catch (e: any) {
      console.error("获取任务列表失败:", e);
      throw e;
    }
  }, []);

  const fetchSlotsData = useCallback(async (): Promise<SlotTask[]> => {
    try {
      const data = await slotAPI.getSlots();
      if (data) {
        return data;
      }
    } catch (e: any) {
      console.error("获取槽位状态失败:", e);
    }
    return [
      { slot_id: 1, status: "idle", progress: 0 },
      { slot_id: 2, status: "idle", progress: 0 },
      { slot_id: 3, status: "idle", progress: 0 },
    ];
  }, []);

  const {
    data: tasksData,
    isFetching: tasksFetching,
    error: tasksError,
    refetch: refetchTasks,
  } = useQuery({
    queryKey: ["tasks"],
    queryFn: fetchTasksData,
    refetchInterval: 5000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const {
    data: slotsData,
    isFetching: slotsFetching,
    refetch: refetchSlots,
  } = useQuery({
    queryKey: ["taskSlots"],
    queryFn: fetchSlotsData,
    refetchInterval: 5000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  // Sync query state to local state
  useEffect(() => {
    if (tasksFetching) {
      setError(null);
    } else if (tasksError) {
      setError(
        tasksError instanceof Error ? tasksError.message : "获取任务列表失败",
      );
    }
  }, [tasksFetching, tasksError]);

  useEffect(() => {
    if (!tasksFetching && tasksData !== undefined) {
      setTasks(tasksData);
      setLastRefresh(new Date());
    }
  }, [tasksFetching, tasksData]);

  useEffect(() => {
    if (!slotsFetching && slotsData !== undefined) {
      setSlots(slotsData);
    }
  }, [slotsFetching, slotsData]);

  useEffect(() => {
    setIsLoading(tasksFetching);
  }, [tasksFetching]);

  useEffect(() => {
    setSlotsLoading(slotsFetching);
  }, [slotsFetching]);

  // Manual refresh callbacks
  const fetchTasks = useCallback(async () => {
    await refetchTasks();
  }, [refetchTasks]);

  const fetchSlots = useCallback(async () => {
    await refetchSlots();
  }, [refetchSlots]);

  // 暂停任务
  const handlePause = async (taskId: string) => {
    try {
      await taskApi.pauseTask(taskId, { reason: "用户手动暂停" });
      showNotification({
        type: "success",
        title: "任务已暂停",
        message: `任务 ${taskId.slice(0, 8)} 已暂停`,
      });
      await fetchTasks();
    } catch (err) {
      console.error("[TasksPage] 暂停任务失败:", err, "taskId:", taskId);
      setError(err instanceof Error ? err.message : "暂停任务失败");
      showNotification({
        type: "error",
        title: "暂停失败",
        message: err instanceof Error ? err.message : "暂停任务失败",
      });
    }
  };

  // 恢复任务
  const handleResume = async (taskId: string, newRequirements?: string) => {
    try {
      const result = await taskApi.resumeTask(taskId, {
        ai_confirmation: newRequirements,
        confirmed_understanding: !!newRequirements,
      });

      if (result.requires_ai_confirmation) {
        console.log("需要AI确认理解新需求");
      }

      showNotification({
        type: "success",
        title: "任务已恢复",
        message: `任务 ${taskId.slice(0, 8)} 已恢复执行`,
      });
      await fetchTasks();
    } catch (err) {
      console.error("[TasksPage] 恢复任务失败:", err, "taskId:", taskId);
      setError(err instanceof Error ? err.message : "恢复任务失败");
      showNotification({
        type: "error",
        title: "恢复失败",
        message: err instanceof Error ? err.message : "恢复任务失败",
      });
    }
  };

  // 完成任务
  const handleComplete = async (taskId: string) => {
    try {
      await taskApi.completeTask(taskId);
      showNotification({
        type: "success",
        title: "任务已完成",
        message: `任务 ${taskId.slice(0, 8)} 已标记完成`,
      });
      await fetchTasks();
    } catch (err) {
      console.error("[TasksPage] 完成任务失败:", err, "taskId:", taskId);
      setError(err instanceof Error ? err.message : "完成任务失败");
      showNotification({
        type: "error",
        title: "完成失败",
        message: err instanceof Error ? err.message : "完成任务失败",
      });
    }
  };

  // 标记任务失败
  const handleFail = async (taskId: string) => {
    try {
      await taskApi.failTask(taskId);
      showNotification({
        type: "warning",
        title: "任务已标记失败",
        message: `任务 ${taskId.slice(0, 8)} 已标记为失败`,
      });
      await fetchTasks();
    } catch (err) {
      console.error("[TasksPage] 标记任务失败失败:", err, "taskId:", taskId);
      setError(err instanceof Error ? err.message : "标记任务失败失败");
      showNotification({
        type: "error",
        title: "标记失败",
        message: err instanceof Error ? err.message : "标记任务失败失败",
      });
    }
  };

  // 压缩归档任务
  const handleCompress = async (taskId: string) => {
    try {
      await taskApi.compressTask(taskId);
      showNotification({
        type: "success",
        title: "任务已压缩",
        message: `任务 ${taskId.slice(0, 8)} 已语义压缩`,
      });
      await fetchTasks();
    } catch (err) {
      console.error("[TasksPage] 压缩任务失败:", err, "taskId:", taskId);
      setError(err instanceof Error ? err.message : "压缩任务失败");
      showNotification({
        type: "error",
        title: "压缩失败",
        message: err instanceof Error ? err.message : "压缩任务失败",
      });
    }
  };

  // 3槽位长任务操作处理
  const handleSlotPause = async (slotId: number) => {
    try {
      setSlotsLoading(true);
      await slotAPI.pause(slotId, "用户手动暂停");
      showNotification({
        type: "success",
        title: "槽位已暂停",
        message: `槽位 ${slotId} 任务已暂停`,
      });
      await fetchSlots();
    } catch (error) {
      console.error(`暂停槽位 ${slotId} 失败:`, error);
      showNotification({
        type: "error",
        title: "暂停失败",
        message: error instanceof Error ? error.message : "暂停槽位失败",
      });
    } finally {
      setSlotsLoading(false);
    }
  };

  const handleSlotResume = async (slotId: number, aiConfirmation: string) => {
    try {
      setSlotsLoading(true);
      await slotAPI.resume(slotId, aiConfirmation);
      showNotification({
        type: "success",
        title: "槽位已恢复",
        message: `槽位 ${slotId} 任务已恢复`,
      });
      await fetchSlots();
    } catch (error) {
      console.error(`恢复槽位 ${slotId} 失败:`, error);
      showNotification({
        type: "error",
        title: "恢复失败",
        message: error instanceof Error ? error.message : "恢复槽位失败",
      });
    } finally {
      setSlotsLoading(false);
    }
  };

  const handleSlotStop = async (slotId: number) => {
    try {
      setSlotsLoading(true);
      await slotAPI.stop(slotId);
      showNotification({
        type: "success",
        title: "槽位已停止",
        message: `槽位 ${slotId} 任务已停止`,
      });
      await fetchSlots();
    } catch (error) {
      console.error(`停止槽位 ${slotId} 失败:`, error);
      showNotification({
        type: "error",
        title: "停止失败",
        message: error instanceof Error ? error.message : "停止槽位失败",
      });
    } finally {
      setSlotsLoading(false);
    }
  };

  // 提交创建任务
  const handleCreateTaskSubmit = async (data: {
    mode: CreateMode;
    slotId: number | null;
    taskName: string;
    taskType: string;
    requirements: string;
    priority: string;
  }) => {
    try {
      setCreateTaskLoading(true);

      if (data.mode === "execute") {
        const targetSlotId =
          data.slotId || slots.find((s) => s.status === "idle")?.slot_id;

        if (!targetSlotId) {
          showNotification({
            type: "warning",
            title: "没有空闲槽位",
            message: "请先停止或完成一个现有任务",
          });
          return;
        }

        const response = await slotAPI.createTask(targetSlotId, {
          task_name: data.taskName,
          task_type: data.taskType,
          params: { priority: data.priority },
          user_requirements: data.requirements,
          metadata: { priority: data.priority },
        });

        if (response.success) {
          showNotification({
            type: "success",
            title: "任务已创建并开始执行",
            message: `任务 "${data.taskName}" 已放入槽位 ${targetSlotId}`,
          });
          setCreateDialogOpen(false);
          await fetchTasks();
          await fetchSlots();
        } else {
          throw new Error(response.message || "创建槽位任务失败");
        }
      } else {
        const response = await taskApi.createTask({
          title: data.taskName,
          description: data.requirements,
          priority: data.priority as any,
          task_type: data.taskType,
          metadata: {},
        });

        if (response.id) {
          showNotification({
            type: "success",
            title: "已添加到待办",
            message: `任务 "${data.taskName}" 已记录`,
          });
          setCreateDialogOpen(false);
          await fetchTasks();
        } else {
          throw new Error("创建任务失败");
        }
      }
    } catch (error) {
      console.error("创建任务出错:", error);
      showNotification({
        type: "error",
        title: "创建失败",
        message: error instanceof Error ? error.message : "创建任务失败",
      });
    } finally {
      setCreateTaskLoading(false);
    }
  };

  // 加载任务检查点
  const fetchCheckpoints = useCallback(async (taskId: string) => {
    try {
      setCheckpointsLoading(true);
      setCheckpointError(null);
      const data = await taskApi.getCheckpoints(taskId);
      setCheckpointsMap((prev) => ({
        ...prev,
        [taskId]: data || [],
      }));
    } catch (err: any) {
      console.error(`[TasksPage] 加载检查点失败: ${taskId}`, err);
      setCheckpointError(err.message || "加载检查点失败");
    } finally {
      setCheckpointsLoading(false);
    }
  }, []);

  // 手动保存检查点
  const handleCreateCheckpoint = async (taskId: string, name: string) => {
    try {
      await taskApi.createCheckpoint(taskId, { name });
      showNotification({
        type: "success",
        title: "检查点已保存",
        message: `任务 ${taskId.slice(0, 8)} 的检查点已保存`,
      });
      await fetchCheckpoints(taskId);
    } catch (err: any) {
      console.error(`[TasksPage] 保存检查点失败: ${taskId}`, err);
      setCheckpointError(err.message || "保存检查点失败");
      showNotification({
        type: "error",
        title: "保存失败",
        message: err.message || "保存检查点失败",
      });
    }
  };

  // 过滤任务
  const filteredTasks =
    filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  // 统计各状态任务数量
  const stats = {
    all: tasks.length,
    pending: tasks.filter((t) => t.status === "pending").length,
    running: tasks.filter((t) => t.status === "running").length,
    paused: tasks.filter((t) => t.status === "paused").length,
    completed: tasks.filter((t) => t.status === "completed").length,
    failed: tasks.filter((t) => t.status === "failed").length,
  };

  const getFilterButtonClass = (status: FilterStatus) => {
    const baseClass =
      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-all";
    const isActive = filter === status;

    if (isActive) {
      return `${baseClass} bg-sb-cyan/20 text-sb-cyan border border-sb-cyan/30`;
    }
    return `${baseClass} text-sb-text-secondary hover:text-white hover:bg-white/5`;
  };

  const getStatusIcon = (status: FilterStatus) => {
    switch (status) {
      case "running":
        return <Play className="w-3.5 h-3.5" />;
      case "paused":
        return <Pause className="w-3.5 h-3.5" />;
      case "completed":
        return <CheckCircle2 className="w-3.5 h-3.5" />;
      case "failed":
        return <AlertCircle className="w-3.5 h-3.5" />;
      case "pending":
        return <Clock className="w-3.5 h-3.5" />;
      default:
        return <ListFilter className="w-3.5 h-3.5" />;
    }
  };

  const getFilterLabel = (status: FilterStatus) => {
    const labels: Record<FilterStatus, string> = {
      all: "全部",
      pending: "待处理",
      running: "运行中",
      paused: "已暂停",
      completed: "已完成",
      failed: "失败",
    };
    return labels[status];
  };

  return (
    <div className="h-full flex flex-col bg-sb-bg-primary">
      {/* 头部 */}
      <div className="p-6 border-b border-white/5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              <ListFilter className="w-6 h-6 text-sb-cyan" />
              任务管理
            </h1>
            <p className="text-sb-text-secondary text-sm mt-1">
              管理长期任务与待办清单，支持暂停、恢复和检查点
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sb-text-secondary/80 text-xs">
              上次刷新: {lastRefresh.toLocaleTimeString()}
            </span>
            <button
              onClick={() => {
                fetchTasks();
                fetchSlots();
              }}
              disabled={isLoading || slotsLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 text-sb-text-primary rounded-lg text-sm transition-all disabled:opacity-50"
            >
              <RefreshCw
                className={`w-4 h-4 ${isLoading || slotsLoading ? "animate-spin" : ""}`}
              />
              刷新
            </button>
            <button
              className="flex items-center gap-1.5 px-3 py-1.5 bg-sb-cyan hover:bg-sb-cyan/80 text-white rounded-lg text-sm transition-all"
              onClick={() => setCreateDialogOpen(true)}
            >
              <Plus className="w-4 h-4" />
              新建任务
            </button>
          </div>
        </div>

        {/* 状态过滤器 */}
        <div className="flex items-center gap-2 flex-wrap">
          {(
            [
              "all",
              "pending",
              "running",
              "paused",
              "completed",
              "failed",
            ] as FilterStatus[]
          ).map((status) => (
            <button
              key={status}
              onClick={() => setFilter(status)}
              className={getFilterButtonClass(status)}
            >
              {getStatusIcon(status)}
              {getFilterLabel(status)}
              <span className="ml-1 text-xs opacity-60">({stats[status]})</span>
            </button>
          ))}
        </div>
      </div>

      {/* 任务面板内容 */}
      <div className="flex-1 overflow-auto p-6">
        {/* 3槽位长任务面板 */}
        <div className="mb-8">
          <LongTaskSlotsPanel
            slots={slots}
            onPause={handleSlotPause}
            onResume={handleSlotResume}
            onStop={handleSlotStop}
            onCreateTask={() => {
              setCreateDialogOpen(true);
            }}
            loading={slotsLoading}
          />
        </div>

        {/* 原有任务列表 */}
        <div className="mb-4">
          <h3 className="text-white font-medium mb-4 flex items-center gap-2">
            <ListFilter className="w-4 h-4 text-sb-text-secondary" />
            全部任务列表
          </h3>
        </div>
        {isLoading && tasks.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="w-8 h-8 animate-spin text-sb-cyan" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-full text-sb-text-secondary">
            <AlertCircle className="w-12 h-12 mb-4 text-red-400" />
            <p>{error}</p>
            <button
              onClick={fetchTasks}
              className="mt-4 px-4 py-2 bg-sb-cyan/20 text-sb-cyan rounded-lg text-sm hover:bg-sb-cyan/30 transition-all"
            >
              重试
            </button>
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-sb-text-secondary">
            <ListFilter className="w-12 h-12 mb-4" />
            <p>暂无{filter !== "all" ? getFilterLabel(filter) : ""}任务</p>
            {filter !== "all" && (
              <button
                onClick={() => setFilter("all")}
                className="mt-4 text-sb-cyan hover:text-sb-cyan/80 text-sm"
              >
                查看全部任务
              </button>
            )}
          </div>
        ) : (
          <div className="grid gap-4 max-w-4xl">
            {filteredTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onPause={handlePause}
                onResume={handleResume}
                onComplete={handleComplete}
                onFail={handleFail}
                onCompress={handleCompress}
                onRefresh={fetchTasks}
              />
            ))}
          </div>
        )}

        {/* 检查点管理面板 */}
        <div className="mt-8 max-w-4xl">
          <button
            onClick={() => setShowCheckpointsPanel(!showCheckpointsPanel)}
            className="flex items-center gap-2 text-white font-medium mb-4 hover:text-sb-cyan transition-colors"
          >
            {showCheckpointsPanel ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
            检查点管理
            <span className="text-xs text-sb-text-secondary font-normal">
              （点击展开）
            </span>
          </button>
          <AnimatePresence>
            {showCheckpointsPanel && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="bg-sb-bg-secondary/30 rounded-lg border border-white/5 p-4 space-y-4">
                  {checkpointError && (
                    <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
                      <AlertCircle className="w-4 h-4" />
                      {checkpointError}
                    </div>
                  )}
                  {tasks.filter(
                    (t) => t.status === "running" || t.status === "paused",
                  ).length === 0 ? (
                    <p className="text-sb-text-secondary text-sm">
                      没有运行中或暂停的任务，无法管理检查点。
                    </p>
                  ) : (
                    tasks
                      .filter(
                        (t) => t.status === "running" || t.status === "paused",
                      )
                      .map((task) => {
                        const checkpoints = checkpointsMap[task.id] || [];
                        return (
                          <div
                            key={task.id}
                            className="border border-white/5 rounded-lg p-4"
                          >
                            <div className="flex items-center justify-between mb-3">
                              <div>
                                <h4 className="text-white font-medium text-sm">
                                  {task.title}
                                </h4>
                                <div className="flex items-center gap-2 mt-1">
                                  <span className="text-xs text-sb-text-secondary">
                                    进度: {task.progress}%
                                  </span>
                                  <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden">
                                    <div
                                      className="h-full bg-sb-cyan rounded-full transition-all"
                                      style={{ width: `${task.progress}%` }}
                                    />
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                <button
                                  onClick={() => fetchCheckpoints(task.id)}
                                  className="text-xs text-sb-cyan hover:text-sb-cyan-hover transition-colors"
                                >
                                  刷新检查点
                                </button>
                                <button
                                  onClick={() =>
                                    handleCreateCheckpoint(
                                      task.id,
                                      `手动检查点-${new Date().toLocaleTimeString()}`,
                                    )
                                  }
                                  className="flex items-center gap-1 px-2 py-1 text-xs bg-sb-cyan/20 text-sb-cyan rounded hover:bg-sb-cyan/30 transition-colors"
                                >
                                  <Save className="w-3 h-3" />
                                  保存检查点
                                </button>
                              </div>
                            </div>
                            {checkpointsLoading && !checkpointsMap[task.id] ? (
                              <div className="flex items-center gap-2 text-sb-text-secondary text-sm">
                                <Loader2 className="w-4 h-4 animate-spin" />
                                加载检查点...
                              </div>
                            ) : checkpoints.length === 0 ? (
                              <p className="text-sb-text-secondary text-xs">
                                暂无检查点记录
                              </p>
                            ) : (
                              <div className="space-y-2">
                                {checkpoints.map((cp: any, idx: number) => (
                                  <div
                                    key={idx}
                                    className="flex items-center justify-between bg-white/5 rounded px-3 py-2 text-sm"
                                  >
                                    <div className="flex items-center gap-2">
                                      <span className="text-sb-cyan text-xs">
                                        #{idx + 1}
                                      </span>
                                      <span className="text-white">
                                        {cp.name || cp.step || "未命名检查点"}
                                      </span>
                                    </div>
                                    <span className="text-sb-text-secondary text-xs">
                                      {cp.created_at
                                        ? new Date(
                                            cp.created_at,
                                          ).toLocaleString("zh-CN")
                                        : "-"}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* 创建任务对话框 */}
      <CreateTaskDialog
        isOpen={createDialogOpen}
        onClose={() => setCreateDialogOpen(false)}
        onSubmit={handleCreateTaskSubmit}
        isLoading={createTaskLoading}
        slots={slots}
      />
    </div>
  );
};

export default TasksPage;
