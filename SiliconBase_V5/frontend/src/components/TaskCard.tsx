import React, { useState } from "react";
import {
  Play,
  Pause,
  CheckCircle2,
  Clock,
  AlertCircle,
  Loader2,
  Edit3,
  XCircle,
  Archive,
} from "lucide-react";

export interface Task {
  id: string;
  title: string;
  status: "pending" | "running" | "paused" | "completed" | "failed";
  progress: number;
  description?: string;
  priority?: number;
  created_at?: number;
  started_at?: string;
}

interface TaskCardProps {
  task: Task;
  onPause: (taskId: string) => Promise<void>;
  onResume: (taskId: string, newRequirements?: string) => Promise<void>;
  onComplete?: (taskId: string) => Promise<void>;
  onFail?: (taskId: string) => Promise<void>;
  onCompress?: (taskId: string) => Promise<void>;
  onRefresh?: () => void;
}

export const TaskCard: React.FC<TaskCardProps> = ({
  task,
  onPause,
  onResume,
  onComplete,
  onFail,
  onCompress,
  onRefresh,
}) => {
  const [showDialog, setShowDialog] = useState(false);
  const [newRequirements, setNewRequirements] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handlePause = async () => {
    setIsLoading(true);
    try {
      await onPause(task.id);
      setShowDialog(true);
    } catch (error) {
      console.error("暂停任务失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleResume = async () => {
    setIsLoading(true);
    try {
      await onResume(task.id, newRequirements);
      setShowDialog(false);
      setNewRequirements("");
      onRefresh?.();
    } catch (error) {
      console.error("恢复任务失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDirectResume = async () => {
    setIsLoading(true);
    try {
      await onResume(task.id);
      onRefresh?.();
    } catch (error) {
      console.error("恢复任务失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleComplete = async () => {
    if (!onComplete) return;
    setIsLoading(true);
    try {
      await onComplete(task.id);
      onRefresh?.();
    } catch (error) {
      console.error("完成任务失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFail = async () => {
    if (!onFail) return;
    setIsLoading(true);
    try {
      await onFail(task.id);
      onRefresh?.();
    } catch (error) {
      console.error("标记任务失败失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCompress = async () => {
    if (!onCompress) return;
    setIsLoading(true);
    try {
      await onCompress(task.id);
      onRefresh?.();
    } catch (error) {
      console.error("压缩任务失败:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const getStatusIcon = () => {
    switch (task.status) {
      case "running":
        return <Loader2 className="w-4 h-4 animate-spin text-sb-cyan" />;
      case "paused":
        return <Pause className="w-4 h-4 text-yellow-400" />;
      case "completed":
        return <CheckCircle2 className="w-4 h-4 text-green-400" />;
      case "failed":
        return <AlertCircle className="w-4 h-4 text-red-400" />;
      default:
        return <Clock className="w-4 h-4 text-sb-text-secondary" />;
    }
  };

  const getStatusText = () => {
    switch (task.status) {
      case "running":
        return "运行中";
      case "paused":
        return "已暂停";
      case "completed":
        return "已完成";
      case "failed":
        return "失败";
      default:
        return "待处理";
    }
  };

  const getStatusColor = () => {
    switch (task.status) {
      case "running":
        return "text-sb-cyan bg-sb-cyan/10";
      case "paused":
        return "text-yellow-400 bg-yellow-400/10";
      case "completed":
        return "text-green-400 bg-green-400/10";
      case "failed":
        return "text-red-400 bg-red-400/10";
      default:
        return "text-sb-text-secondary bg-sb-text-secondary/10";
    }
  };

  const getProgressColor = () => {
    switch (task.status) {
      case "running":
        return "bg-sb-cyan";
      case "paused":
        return "bg-yellow-400";
      case "completed":
        return "bg-green-400";
      case "failed":
        return "bg-red-400";
      default:
        return "bg-sb-text-secondary";
    }
  };

  return (
    <div className="bg-sb-bg-secondary/50 rounded-lg p-4 border border-white/5 hover:border-white/10 transition-all">
      {/* 头部：标题和状态 */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-white font-medium truncate pr-2">{task.title}</h3>
          {task.description && (
            <p className="text-sb-text-secondary text-sm mt-1 line-clamp-2">
              {task.description}
            </p>
          )}
        </div>
        <div
          className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs ${getStatusColor()}`}
        >
          {getStatusIcon()}
          <span>{getStatusText()}</span>
        </div>
      </div>

      {/* 进度条 */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-sb-text-secondary mb-1">
          <span>进度</span>
          <span>{task.progress}%</span>
        </div>
        <div className="h-2 bg-sb-bg-secondary rounded-full overflow-hidden">
          <div
            className={`h-full ${getProgressColor()} transition-all duration-500`}
            style={{ width: `${task.progress}%` }}
          />
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center justify-between">
        <div className="text-xs text-sb-text-secondary/80">
          ID: {task.id.slice(0, 8)}...
        </div>

        <div className="flex items-center gap-2">
          {(task.status === "running" || task.status === "paused") && (
            <>
              <button
                onClick={handleComplete}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-500/20 hover:bg-green-500/30 text-green-400 rounded-lg text-sm transition-all disabled:opacity-50"
                title="完成任务"
              >
                {isLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                )}
                完成
              </button>
              <button
                onClick={handleFail}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-400 rounded-lg text-sm transition-all disabled:opacity-50"
                title="标记失败"
              >
                {isLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <XCircle className="w-3.5 h-3.5" />
                )}
                失败
              </button>
            </>
          )}

          {task.status === "running" && (
            <button
              onClick={handlePause}
              disabled={isLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-400 rounded-lg text-sm transition-all disabled:opacity-50"
            >
              {isLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Pause className="w-3.5 h-3.5" />
              )}
              暂停
            </button>
          )}

          {task.status === "paused" && (
            <>
              <button
                onClick={() => setShowDialog(true)}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-sb-cyan/20 hover:bg-sb-cyan/30 text-sb-cyan rounded-lg text-sm transition-all disabled:opacity-50"
              >
                <Edit3 className="w-3.5 h-3.5" />
                调整需求
              </button>
              <button
                onClick={handleDirectResume}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-500/20 hover:bg-green-500/30 text-green-400 rounded-lg text-sm transition-all disabled:opacity-50"
              >
                {isLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Play className="w-3.5 h-3.5" />
                )}
                直接恢复
              </button>
            </>
          )}

          {(task.status === "completed" || task.status === "failed") &&
            onCompress && (
              <button
                onClick={handleCompress}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-sb-cyan/20 hover:bg-sb-cyan/30 text-sb-cyan rounded-lg text-sm transition-all disabled:opacity-50"
                title="压缩归档"
              >
                {isLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Archive className="w-3.5 h-3.5" />
                )}
                归档
              </button>
            )}
        </div>
      </div>

      {/* 调整需求对话框 */}
      {showDialog && task.status === "paused" && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setShowDialog(false)}
        >
          <div
            className="bg-sb-bg-secondary rounded-xl border border-white/10 p-6 w-full max-w-md mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h4 className="text-white font-semibold mb-4 flex items-center gap-2">
              <Edit3 className="w-5 h-5 text-sb-cyan" />
              调整任务需求
            </h4>

            <div className="mb-4">
              <label className="block text-sb-text-secondary text-sm mb-2">
                请输入新的需求或调整说明（可选）
              </label>
              <textarea
                value={newRequirements}
                onChange={(e) => setNewRequirements(e.target.value)}
                placeholder="例如：我需要调整一下需求，请把功能改成..."
                className="w-full h-24 bg-sb-bg-primary border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder:text-sb-text-secondary/60 focus:outline-none focus:border-sb-cyan/50 resize-none"
              />
            </div>

            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowDialog(false)}
                className="px-4 py-2 text-sb-text-secondary hover:text-white text-sm transition-all"
              >
                取消
              </button>
              <button
                onClick={handleResume}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-4 py-2 bg-sb-cyan hover:bg-sb-cyan/80 text-white rounded-lg text-sm transition-all disabled:opacity-50"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                提交并恢复
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TaskCard;
