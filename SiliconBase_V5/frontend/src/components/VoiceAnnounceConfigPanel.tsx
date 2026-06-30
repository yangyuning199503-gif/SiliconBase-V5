import { useState, useEffect, useCallback } from "react";
import { fetchAPI, APIError } from "../utils/api/core";
import { Volume2, Loader2, AlertCircle } from "lucide-react";

interface VoiceAnnounceConfig {
  enabled: boolean;
  ai_output: boolean;
  process?: Record<string, any>;
  priority?: Record<string, any>;
}

export function VoiceAnnounceConfigPanel() {
  const [config, setConfig] = useState<VoiceAnnounceConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAPI<VoiceAnnounceConfig>(
        "/api/voice/announce/config",
      );
      setConfig(data);
    } catch (err) {
      const message =
        err instanceof APIError ? err.message : "获取语音播报配置失败";
      setError(message);
      console.error("[VoiceAnnounceConfigPanel] 获取配置失败:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = async (updates: Partial<VoiceAnnounceConfig>) => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      const newConfig = { ...config, ...updates };
      await fetchAPI<{ status: string; config: VoiceAnnounceConfig }>(
        "/api/voice/announce/config",
        {
          method: "POST",
          body: newConfig,
        },
      );
      setConfig(newConfig);
    } catch (err) {
      const message =
        err instanceof APIError ? err.message : "保存语音播报配置失败";
      setError(message);
      console.error("[VoiceAnnounceConfigPanel] 保存配置失败:", err);
    } finally {
      setSaving(false);
    }
  };

  const current = config ?? { enabled: true, ai_output: true };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Volume2 className="w-5 h-5 text-sb-cyan" />
          <h3 className="text-white font-medium">语音播报</h3>
        </div>
        <button
          onClick={fetchConfig}
          disabled={loading}
          className="p-1.5 text-sb-text-secondary hover:text-white rounded-lg hover:bg-white/5 transition-colors disabled:opacity-50"
          title="刷新配置"
        >
          <Loader2 className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <p className="text-xs text-white/50 mb-4">
        控制 AI 是否通过语音主动播报关键信息（如任务状态、执行结果）。
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      <div className="space-y-3">
        <ToggleRow
          label="启用语音播报"
          description="AI 主动通过语音播报关键事件"
          checked={current.enabled}
          onChange={(enabled) => handleSave({ enabled })}
          loading={saving}
        />
        <ToggleRow
          label="播报 AI 输出"
          description="朗读 AI 的重要回复内容"
          checked={current.ai_output}
          onChange={(ai_output) => handleSave({ ai_output })}
          loading={saving}
        />
      </div>
    </div>
  );
}

interface ToggleRowProps {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  loading: boolean;
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  loading,
}: ToggleRowProps) {
  return (
    <div className="flex items-center justify-between p-4 bg-white/5 rounded-lg">
      <div>
        <div className="text-white text-sm font-medium">{label}</div>
        <div className="text-sb-text-secondary text-xs mt-1">{description}</div>
      </div>
      <button
        onClick={() => onChange(!checked)}
        disabled={loading}
        className={`relative w-14 h-7 rounded-full transition-colors disabled:opacity-50 ${
          checked ? "bg-green-500" : "bg-gray-600"
        }`}
      >
        <span
          className={`absolute top-1 w-5 h-5 bg-white rounded-full transition-all ${
            checked ? "left-8" : "left-1"
          }`}
        />
      </button>
    </div>
  );
}
