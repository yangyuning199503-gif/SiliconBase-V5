import { useState, useEffect, useCallback } from "react";
import { fetchAPI, APIError } from "../utils/api/core";
import { Server, Loader2, AlertCircle } from "lucide-react";

interface MCPStatus {
  enabled: boolean;
  servers: string[];
  tools_count: number;
  servers_detail?: Array<{
    name?: string;
    enabled?: boolean;
    tools_count?: number;
    error?: string;
  }>;
}

export function MCPConfigPanel() {
  const [status, setStatus] = useState<MCPStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [toggleLoading, setToggleLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAPI<MCPStatus>("/api/mcp/status");
      setStatus(data);
    } catch (err) {
      const message =
        err instanceof APIError ? err.message : "获取 MCP 状态失败";
      setError(message);
      console.error("[MCPConfigPanel] 获取状态失败:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleToggle = async () => {
    if (!status) return;
    setToggleLoading(true);
    setError(null);
    try {
      const endpoint = status.enabled ? "/api/mcp/disable" : "/api/mcp/enable";
      await fetchAPI<{ success: boolean; message?: string }>(endpoint, {
        method: "POST",
      });
      await fetchStatus();
    } catch (err) {
      const message =
        err instanceof APIError ? err.message : "切换 MCP 状态失败";
      setError(message);
      console.error("[MCPConfigPanel] 切换状态失败:", err);
    } finally {
      setToggleLoading(false);
    }
  };

  const isEnabled = status?.enabled ?? false;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Server className="w-5 h-5 text-sb-cyan" />
          <h3 className="text-white font-medium">MCP 服务</h3>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="p-1.5 text-sb-text-secondary hover:text-white rounded-lg hover:bg-white/5 transition-colors disabled:opacity-50"
          title="刷新状态"
        >
          <Loader2 className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <p className="text-xs text-white/50 mb-4">
        MCP（Model Context Protocol）允许 AI 调用外部工具服务。启用后将从
        config/mcp_servers.yaml 加载服务器配置。
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      <div className="flex items-center justify-between p-4 bg-white/5 rounded-lg">
        <div>
          <div className="text-white text-sm font-medium">
            {isEnabled ? "已启用" : "已禁用"}
          </div>
          <div className="text-sb-text-secondary text-xs mt-1">
            {status
              ? `已连接服务器: ${status.servers?.length || 0} 个 · 工具数: ${status.tools_count || 0}`
              : loading
                ? "加载中..."
                : "未获取到状态"}
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggleLoading || loading}
          className={`relative w-14 h-7 rounded-full transition-colors disabled:opacity-50 ${
            isEnabled ? "bg-green-500" : "bg-gray-600"
          }`}
        >
          <span
            className={`absolute top-1 w-5 h-5 bg-white rounded-full transition-all ${
              isEnabled ? "left-8" : "left-1"
            }`}
          />
          {toggleLoading && (
            <Loader2 className="absolute inset-0 m-auto w-4 h-4 text-white animate-spin" />
          )}
        </button>
      </div>

      {status?.servers_detail && status.servers_detail.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="text-xs text-sb-text-secondary">服务器详情</div>
          {status.servers_detail.map((server, idx) => (
            <div
              key={idx}
              className="flex items-center justify-between p-2 bg-white/5 rounded-lg text-sm"
            >
              <span className="text-white">
                {server.name || `服务器 ${idx + 1}`}
              </span>
              <div className="flex items-center gap-2">
                {server.error ? (
                  <span className="text-red-400 text-xs">{server.error}</span>
                ) : null}
                <span
                  className={`text-xs ${server.enabled ? "text-green-400" : "text-sb-text-secondary"}`}
                >
                  {server.enabled ? "已连接" : "未连接"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
