import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "./index.css";
import { initAuth } from "./utils/auth";
import { GlobalErrorHandler } from "./components/ErrorHandler";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { WebSocketProvider } from "./hooks/useWebSocket";
import { GamificationProvider } from "./hooks/useGamification";
import DiagnosticOverlay, {
  hasRecentErrors,
  clearDiagnosticErrors,
} from "./components/DiagnosticOverlay";
import router from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30,
      refetchOnWindowFocus: false,
    },
  },
});

async function initApplication() {
  const rootElement = document.getElementById("root");
  if (!rootElement) {
    console.error("[Init] 致命错误: 找不到 #root 元素，应用无法渲染");
    document.body.innerHTML = `
      <div style="padding: 40px; text-align: center; font-family: sans-serif;">
        <h1 style="color: #ef4444;">初始化错误</h1>
        <p>找不到应用程序挂载点 (#root)</p>
        <p style="color: #6b7280;">请刷新页面或联系管理员</p>
      </div>
    `;
    return;
  }

  // 【诊断模式】检测近期未处理错误，显示顶部横幅
  if (hasRecentErrors()) {
    const banner = document.createElement("div");
    banner.id = "diagnostic-banner";
    banner.style.cssText =
      "position:fixed;top:0;left:0;width:100%;z-index:10000;background:#dc2626;color:white;padding:8px;text-align:center;font-size:14px;font-family:sans-serif;";
    banner.innerHTML = `
      <span>⚠️ 检测到未处理的错误，请查看控制台或联系开发者</span>
      <button id="diagnostic-clear-btn" style="margin-left:12px;padding:2px 10px;background:white;color:#dc2626;border:none;border-radius:4px;cursor:pointer;font-size:12px;">清除错误</button>
    `;
    document.body.appendChild(banner);
    document
      .getElementById("diagnostic-clear-btn")
      ?.addEventListener("click", () => {
        clearDiagnosticErrors();
        banner.remove();
      });
  }

  console.log("[Init] 正在初始化认证状态...");
  try {
    const isAuth = await initAuth();
    if (isAuth) {
      console.log("[Init] 自动登录成功（token有效）");
    } else {
      console.log("[Init] 未登录或token已过期，显示登录页");
    }
  } catch (error) {
    console.error("[Init] 认证初始化失败:", error);
  }

  try {
    const root = ReactDOM.createRoot(rootElement);
    root.render(
      <QueryClientProvider client={queryClient}>
        <GlobalErrorHandler>
          <WebSocketProvider>
            <GamificationProvider>
              <DiagnosticOverlay />
              <ErrorBoundary>
                <RouterProvider router={router} />
              </ErrorBoundary>
            </GamificationProvider>
          </WebSocketProvider>
        </GlobalErrorHandler>
      </QueryClientProvider>,
    );
    console.log("[Init] 应用渲染成功");
  } catch (error) {
    console.error("[Init] React 渲染失败:", error);
    rootElement.innerHTML = `
      <div style="padding: 40px; text-align: center;">
        <h1 style="color: #ef4444;">渲染错误</h1>
        <p>应用程序启动失败</p>
        <pre style="text-align: left; background: #f3f4f6; padding: 16px; border-radius: 8px;">${
          error instanceof Error ? error.message : String(error)
        }</pre>
      </div>
    `;
  }
}

initApplication().catch((error) => {
  console.error("[Init] 初始化异常:", error);
});
