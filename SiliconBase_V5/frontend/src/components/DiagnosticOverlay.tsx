import { useState, useEffect, useCallback } from 'react';
import { AlertCircle, X } from 'lucide-react';

interface DiagnosticError {
  timestamp: number;
  message: string;
  stack?: string;
}

interface Bubble {
  id: string;
  message: string;
}

function storeDiagnosticError(error: DiagnosticError) {
  try {
    const raw = localStorage.getItem('diagnostic_errors');
    const errors: DiagnosticError[] = raw ? JSON.parse(raw) : [];

    // Deduplicate: don't add exact same message within 1 second
    const now = Date.now();
    const isDuplicate = errors.some(
      (e) => e.message === error.message && Math.abs(e.timestamp - now) < 1000
    );
    if (isDuplicate) return;

    errors.push(error);
    if (errors.length > 50) errors.shift();
    localStorage.setItem('diagnostic_errors', JSON.stringify(errors));
  } catch {
    // Ignore localStorage errors
  }
}

export function hasRecentErrors(): boolean {
  try {
    const raw = localStorage.getItem('diagnostic_errors');
    if (!raw) return false;
    const list: DiagnosticError[] = JSON.parse(raw);
    const cutoff = Date.now() - 5 * 60 * 1000;
    return list.some((e) => e.timestamp > cutoff);
  } catch {
    return false;
  }
}

export function clearDiagnosticErrors() {
  localStorage.removeItem('diagnostic_errors');
}

export default function DiagnosticOverlay() {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);

  const removeBubble = useCallback((id: string) => {
    setBubbles((prev) => prev.filter((b) => b.id !== id));
  }, []);

  const showBubble = useCallback(
    (message: string) => {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const trimmed = message.length > 120 ? message.slice(0, 120) + '…' : message;

      setBubbles((prev) => [...prev, { id, message: trimmed }]);

      const timeoutId = setTimeout(() => {
        removeBubble(id);
      }, 5000);

      // Store timeout on the DOM node or just let the timeout run;
      // if removed early via click, the timeout will no-op because
      // removeBubble is idempotent.
      return () => clearTimeout(timeoutId);
    },
    [removeBubble]
  );

  useEffect(() => {
    const handleError = (event: ErrorEvent) => {
      const message = event.error?.message || event.message || 'Unknown error';
      const stack = event.error?.stack;
      console.error('[DiagnosticOverlay] 捕获到错误:', event.error || event.message);

      storeDiagnosticError({ timestamp: Date.now(), message, stack });
      showBubble(message);
    };

    const handleRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      const message = reason instanceof Error ? reason.message : String(reason);
      const stack = reason instanceof Error ? reason.stack : undefined;
      console.error('[DiagnosticOverlay] 捕获到未处理的Promise拒绝:', reason);

      storeDiagnosticError({ timestamp: Date.now(), message, stack });
      showBubble(message);
    };

    const handleApiError = (event: Event) => {
      const customEvent = event as CustomEvent;
      const detail = customEvent.detail;
      const message =
        detail?.body?.message ||
        detail?.body?.error ||
        detail?.body?.detail ||
        `API Error ${detail?.status || ''}` ||
        'API请求失败';
      console.error('[DiagnosticOverlay] 捕获到API错误:', detail);

      storeDiagnosticError({
        timestamp: Date.now(),
        message,
        stack: JSON.stringify(detail),
      });
      showBubble(message);
    };

    window.addEventListener('error', handleError);
    window.addEventListener('unhandledrejection', handleRejection);
    window.addEventListener('diagnostic:api-error', handleApiError);

    return () => {
      window.removeEventListener('error', handleError);
      window.removeEventListener('unhandledrejection', handleRejection);
      window.removeEventListener('diagnostic:api-error', handleApiError);
    };
  }, [showBubble]);

  return (
    <div
      className="fixed inset-0 pointer-events-none"
      style={{ zIndex: 9999 }}
    >
      {/* Top-right indicator dot */}
      <div className="absolute top-4 right-4 group pointer-events-auto">
        <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
        <div className="absolute right-0 top-5 hidden group-hover:block">
          <div className="bg-slate-800 text-white text-xs px-2 py-1 rounded shadow-lg whitespace-nowrap border border-slate-700 mt-1">
            诊断模式开启
          </div>
        </div>
      </div>

      {/* Error bubbles - bottom right */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-2 pointer-events-auto">
        {bubbles.map((bubble) => (
          <button
            key={bubble.id}
            onClick={() => removeBubble(bubble.id)}
            className="bg-red-600/90 text-white text-sm px-4 py-3 rounded-lg shadow-lg cursor-pointer flex items-center gap-2 max-w-xs backdrop-blur-sm hover:bg-red-600 transition-colors text-left"
          >
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span className="truncate">{bubble.message}</span>
            <X className="w-3 h-3 shrink-0 ml-1 opacity-70 hover:opacity-100" />
          </button>
        ))}
      </div>
    </div>
  );
}
