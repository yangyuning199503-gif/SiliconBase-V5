import React, { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

/**
 * 路由级错误边界
 * 捕获子组件渲染错误，防止单个页面崩溃导致整站白屏
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("[ErrorBoundary] 页面渲染错误:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-900 text-white p-6">
          <div className="max-w-md w-full bg-slate-800/50 border border-white/10 rounded-2xl p-8 text-center">
            <h1 className="text-2xl font-bold mb-4 text-red-400">
              页面渲染出错
            </h1>
            <p className="text-slate-300 mb-6">
              当前页面发生不可恢复的错误，请刷新或返回首页重试。
            </p>
            {this.state.error && (
              <pre className="text-left text-xs text-slate-400 bg-slate-900/80 rounded-lg p-4 mb-6 overflow-auto max-h-40">
                {this.state.error.message}
              </pre>
            )}
            <div className="flex gap-3 justify-center">
              <button
                onClick={() => window.location.reload()}
                className="px-4 py-2 rounded-lg bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 hover:bg-cyan-500/30"
              >
                刷新页面
              </button>
              <button
                onClick={() => (window.location.href = "/")}
                className="px-4 py-2 rounded-lg bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10"
              >
                返回首页
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
