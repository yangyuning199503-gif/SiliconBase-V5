/**
 * 认证工具函数
 * 处理用户登录、登出、token管理等
 */

// Token存储键名
const TOKEN_KEY = "silicon_token";
const USER_KEY = "silicon_user";
const TOKEN_EXPIRY_KEY = "silicon_token_expiry";

// 【修复】标签页隔离：使用 sessionStorage 存储标签页ID和当前用户ID
const TAB_ID_KEY = "silicon_tab_id";
const TAB_USER_KEY = "silicon_tab_user";

// 生成唯一标签页ID
function getTabId(): string {
  let tabId = sessionStorage.getItem(TAB_ID_KEY);
  if (!tabId) {
    tabId = `tab_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
    sessionStorage.setItem(TAB_ID_KEY, tabId);
  }
  return tabId;
}

// 初始化标签页ID
const currentTabId = getTabId();
console.log("[Auth] 当前标签页ID:", currentTabId);

// 导入API配置
import { buildApiUrl } from "../config/api";

/**
 * 用户信息接口
 */
export interface UserInfo {
  user_id: string;
  username: string;
  email?: string;
  avatar?: string;
  role?: string;
}

/**
 * 登录结果接口（扁平化，与后端 LoginResponse 一致）
 */
export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_id: string;
  username: string;
  require_password_change: boolean;
}

/**
 * login() 内部返回类型，在后端字段基础上保留 success/message 供调用方判断
 * 失败时仅返回 success=false 与 message
 */
export interface LoginAttemptResult {
  success: boolean;
  message?: string;
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  user_id?: string;
  username?: string;
  require_password_change?: boolean;
}

// 认证状态变更监听器
type AuthStateListener = (isAuthenticated: boolean) => void;
const authStateListeners: AuthStateListener[] = [];

// 是否正在处理登出（防止并发请求导致多次触发）
let isLoggingOut = false;

/**
 * 注册认证状态变更监听器
 * @param listener 监听器函数
 * @returns 取消注册的函数
 */
export function onAuthStateChange(listener: AuthStateListener): () => void {
  authStateListeners.push(listener);
  return () => {
    const index = authStateListeners.indexOf(listener);
    if (index > -1) {
      authStateListeners.splice(index, 1);
    }
  };
}

/**
 * 通知认证状态变更
 * @param authenticated 是否已认证
 */
function notifyAuthStateChange(authenticated: boolean): void {
  authStateListeners.forEach((listener) => {
    try {
      listener(authenticated);
    } catch (error) {
      console.error("[Auth] 认证状态监听器执行失败:", error);
    }
  });
}

/**
 * 用户登录
 * 调用后端登录API，成功后保存token
 * @param username 用户名
 * @param password 密码
 * @returns 登录结果
 */
export async function login(
  username: string,
  password: string,
): Promise<LoginAttemptResult> {
  try {
    const url = buildApiUrl("/api/auth/login");
    console.log("[Login] Request URL:", url);

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });

    // 先获取文本，避免JSON解析错误
    const responseText = await response.text();
    console.log(
      "[Login] Response:",
      response.status,
      responseText.substring(0, 200),
    );

    // 如果响应为空
    if (!responseText) {
      return {
        success: false,
        message: "后端返回空响应，请检查后端服务是否正常运行",
      };
    }

    // 尝试解析JSON
    let data;
    try {
      data = JSON.parse(responseText);
    } catch (parseError) {
      return {
        success: false,
        message: `后端返回格式错误: ${responseText.substring(0, 100)}`,
      };
    }

    if (!response.ok) {
      // 根据状态码和错误类型提供友好的中文提示
      let errorMessage: string;

      switch (response.status) {
        case 401:
          // 401 可能是用户名不存在或密码错误
          if (
            data.detail?.includes("password") ||
            data.message?.includes("password")
          ) {
            errorMessage = "密码错误，请重新输入";
          } else if (
            data.detail?.includes("user") ||
            data.message?.includes("user")
          ) {
            errorMessage = "用户名不存在，请检查或注册新账号";
          } else {
            errorMessage = "用户名或密码错误";
          }
          break;
        case 403:
          errorMessage = "账号已被禁用，请联系管理员";
          break;
        case 404:
          errorMessage = "用户不存在，请先注册账号";
          break;
        case 409:
          errorMessage = "该用户名已被注册";
          break;
        case 422:
          errorMessage = "输入格式不正确，请检查用户名和密码";
          break;
        case 429:
          errorMessage = "登录尝试次数过多，请稍后再试";
          break;
        case 500:
        case 502:
        case 503:
        case 504:
          errorMessage = "服务器暂时不可用，请稍后重试";
          break;
        default: {
          // 尝试使用后端返回的具体错误，或提供通用提示
          const backendMsg = data.detail || data.message;
          if (backendMsg) {
            // 翻译常见的后端英文错误
            if (backendMsg.toLowerCase().includes("invalid")) {
              errorMessage = "用户名或密码错误";
            } else if (backendMsg.toLowerCase().includes("not found")) {
              errorMessage = "用户不存在，请先注册";
            } else if (backendMsg.toLowerCase().includes("disabled")) {
              errorMessage = "账号已被禁用";
            } else {
              errorMessage = backendMsg;
            }
          } else {
            errorMessage = `登录失败 (错误码: ${response.status})`;
          }
        }
      }

      return {
        success: false,
        message: errorMessage,
      };
    }

    if (data.access_token) {
      // 【修复】登录前先清除可能残留的旧的 session storage
      // 防止新用户访问到之前用户的会话
      localStorage.removeItem("siliconbase-session-storage");
      console.log("[Login] 已清除残留的 session storage");

      // 保存token
      setAuthToken(data.access_token, data.expires_in);
      // 保存用户信息
      setAuthUser({
        user_id: data.user_id || "",
        username: data.username || username,
      });
      // 通知认证状态变更
      notifyAuthStateChange(true);
      // 触发登录成功全局事件，供WebSocket等组件监听
      window.dispatchEvent(
        new CustomEvent("auth:login_success", {
          detail: { user_id: data.user_id, username: data.username },
        }),
      );
      return {
        success: true,
        access_token: data.access_token,
        token_type: data.token_type,
        expires_in: data.expires_in,
        user_id: data.user_id,
        username: data.username,
        require_password_change: data.require_password_change,
      };
    }

    return {
      success: false,
      message: "登录响应缺少access_token",
    };
  } catch (error) {
    console.error("[Login] Error:", error);
    let errorMsg = "网络错误";

    if (error instanceof Error) {
      if (error.message.includes("Failed to fetch")) {
        errorMsg =
          "无法连接到后端服务。请检查:\n1. 后端是否已启动 (看黑色窗口)\n2. 端口 8600 是否正常\n3. 刷新页面重试";
      } else if (error.message.includes("NetworkError")) {
        errorMsg = "网络错误，请检查网络连接";
      } else {
        errorMsg = error.message;
      }
    }

    return {
      success: false,
      message: errorMsg,
    };
  }
}

/**
 * 用户登出
 * 清除本地存储的token和用户信息
 * @param callApi 是否调用后端登出API（可选）
 * @param force 是否强制登出（绕过isLoggingOut检查）
 */
export async function logout(
  callApi: boolean = false,
  force: boolean = false,
): Promise<void> {
  // 防止并发调用导致的重复登出
  if (!force && isLoggingOut) {
    console.log("[Auth] 登出操作正在进行中，跳过重复调用");
    return;
  }

  isLoggingOut = true;

  try {
    if (callApi) {
      try {
        const token = getAuthToken();
        if (token) {
          await fetch(buildApiUrl("/api/auth/logout"), {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
            },
          });
        }
      } catch (error) {
        console.error("Logout API call failed:", error);
      }
    }

    // 清除本地存储
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(TOKEN_EXPIRY_KEY);

    // 【修复】清除 session storage 中的 currentSessionId
    // 防止用户切换后访问到不属于当前用户的会话
    localStorage.removeItem("siliconbase-session-storage");

    // 【修复】清除标签页关联的用户ID
    sessionStorage.removeItem(TAB_USER_KEY);

    // 通知认证状态变更
    notifyAuthStateChange(false);

    // 触发登出全局事件
    window.dispatchEvent(new CustomEvent("auth:logout"));

    console.log("[Auth] 用户已登出，本地存储已清除");
  } finally {
    isLoggingOut = false;
  }
}

/**
 * 获取存储的认证token
 * @returns token字符串或null
 */
export function getAuthToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY);

  // 检查token是否过期
  if (token) {
    const expiry = localStorage.getItem(TOKEN_EXPIRY_KEY);
    if (expiry) {
      const expiryTime = parseInt(expiry, 10);
      if (Date.now() > expiryTime) {
        console.log("[Auth] Token已过期，自动清除");
        logout(false, true); // 强制登出，不调用API
        return null;
      }
    }
  }

  return token;
}

/**
 * 获取认证请求头
 * @returns 包含Authorization头的对象
 */
export function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * 设置认证token
 * @param token JWT token字符串
 * @param expiresIn 过期时间（秒），可选
 */
export function setAuthToken(token: string, expiresIn?: number): void {
  localStorage.setItem(TOKEN_KEY, token);

  // 如果提供了过期时间，计算并存储过期时间点
  if (expiresIn && expiresIn > 0) {
    const expiryTime = Date.now() + expiresIn * 1000;
    localStorage.setItem(TOKEN_EXPIRY_KEY, expiryTime.toString());
  } else {
    // 默认7天过期
    const defaultExpiry = Date.now() + 7 * 24 * 60 * 60 * 1000;
    localStorage.setItem(TOKEN_EXPIRY_KEY, defaultExpiry.toString());
  }
}

/**
 * 获取存储的用户信息
 * @returns 用户信息对象或null
 */
export function getAuthUser(): UserInfo | null {
  const userStr = localStorage.getItem(USER_KEY);
  if (!userStr) return null;

  try {
    const user = JSON.parse(userStr) as UserInfo;

    // 【修复】标签页隔离验证：检查当前标签页是否与此用户关联
    const tabUserId = sessionStorage.getItem(TAB_USER_KEY);
    if (tabUserId && tabUserId !== user.user_id) {
      // 当前标签页关联的用户与 localStorage 中的用户不一致
      // 说明用户在另一个标签页切换了账号
      console.warn(
        "[Auth] 标签页用户不一致，当前标签页用户:",
        tabUserId,
        "存储用户:",
        user.user_id,
      );
      return null;
    }

    return user;
  } catch (error) {
    console.error("[Auth] 解析用户信息失败:", error);
    return null;
  }
}

/**
 * 设置用户信息
 * @param user 用户信息对象
 */
export function setAuthUser(user: UserInfo): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  // 【修复】同时设置标签页关联的用户ID
  sessionStorage.setItem(TAB_USER_KEY, user.user_id);
  console.log("[Auth] 设置标签页关联用户:", user.user_id);
}

/**
 * 获取当前登录用户ID
 * @returns 用户ID或null
 */
export function getCurrentUserId(): string | null {
  const user = getAuthUser();
  return user?.user_id || null;
}

/**
 * 检查用户是否已登录
 * @returns 是否已登录
 */
export function isAuthenticated(): boolean {
  return !!getAuthToken();
}

/**
 * 检查token是否即将过期（1小时内）
 * @returns 是否即将过期
 */
export function isTokenExpiringSoon(): boolean {
  const expiry = localStorage.getItem(TOKEN_EXPIRY_KEY);
  if (!expiry) return true;

  const expiryTime = parseInt(expiry, 10);
  const oneHour = 60 * 60 * 1000;
  return Date.now() > expiryTime - oneHour;
}

/**
 * 修改密码
 * @param currentPassword 当前密码
 * @param newPassword 新密码
 * @returns 修改结果
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<{ success: boolean; message?: string }> {
  try {
    const token = getAuthToken();
    if (!token) {
      return { success: false, message: "未登录" };
    }

    const response = await fetch(buildApiUrl("/api/auth/change-password"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });

    let data;
    try {
      data = await response.json();
    } catch (parseErr) {
      return {
        success: false,
        message: "响应格式错误：无法解析JSON数据",
      };
    }

    if (!response.ok) {
      return {
        success: false,
        message: data?.detail || data?.message || "修改密码失败",
      };
    }

    return { success: true, message: "密码修改成功" };
  } catch (error) {
    console.error("Change password error:", error);
    return {
      success: false,
      message: error instanceof Error ? error.message : "修改密码失败",
    };
  }
}

/**
 * 获取当前登录用户信息（从后端API）
 * 此函数用于验证token有效性并同步前后端认证状态
 * @returns 用户信息
 */
export async function fetchCurrentUser(): Promise<UserInfo | null> {
  try {
    const token = getAuthToken();
    if (!token) {
      console.log("[Auth] 没有token，用户未登录");
      return null;
    }

    console.log("[Auth] 正在验证当前用户...");
    const response = await fetch(buildApiUrl("/api/auth/me"), {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      console.error(`[Auth] 获取用户信息失败: HTTP ${response.status}`);

      if (response.status === 401) {
        console.log("[Auth] Token无效或已过期，清除登录状态");
        // Token无效，强制清除登录状态
        await logout(false, true);

        // 触发全局认证失效事件，让UI层可以响应（如跳转到登录页）
        window.dispatchEvent(
          new CustomEvent("auth:session_expired", {
            detail: { message: "登录已过期，请重新登录" },
          }),
        );
      }
      return null;
    }

    let data;
    try {
      data = await response.json();
    } catch (parseErr) {
      console.error("[Auth] 解析用户信息响应失败");
      return null;
    }

    // 更新本地存储的用户信息
    const userInfo: UserInfo = {
      user_id: data.user_id,
      username: data.username,
      email: data.email,
      avatar: data.avatar,
      role: data.role,
    };
    setAuthUser(userInfo);

    console.log("[Auth] 用户信息验证成功:", userInfo.username);
    return userInfo;
  } catch (error) {
    console.error("[Auth] 获取当前用户错误:", error);
    return null;
  }
}

/**
 * 刷新访问令牌
 * 调用后端 /api/auth/refresh 获取新 token
 * @returns 是否刷新成功
 */
export async function refreshAuthToken(): Promise<boolean> {
  try {
    const token = getAuthToken();
    if (!token) {
      console.log("[Auth] 没有token，无法刷新");
      return false;
    }

    console.log("[Auth] 正在刷新访问令牌...");
    const response = await fetch(buildApiUrl("/api/auth/refresh"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      console.error(`[Auth] 刷新令牌失败: HTTP ${response.status}`);
      return false;
    }

    const data = await response.json();
    if (!data.access_token) {
      console.error("[Auth] 刷新令牌响应缺少access_token");
      return false;
    }

    // 保存新token
    setAuthToken(data.access_token, data.expires_in);
    console.log("[Auth] 访问令牌刷新成功");
    return true;
  } catch (error) {
    console.error("[Auth] 刷新令牌请求失败:", error);
    return false;
  }
}

/**
 * 初始化认证状态
 * 应用启动时调用，验证本地token是否有效
 * @returns 是否已认证
 */
export async function initAuth(): Promise<boolean> {
  const token = getAuthToken();
  if (!token) {
    console.log("[Auth] 初始化: 未找到token");
    return false;
  }

  console.log("[Auth] 初始化: 发现token，正在验证...");
  const user = await fetchCurrentUser();
  if (user) {
    console.log("[Auth] 初始化: 认证有效");
    notifyAuthStateChange(true);
    return true;
  } else {
    console.log("[Auth] 初始化: 认证已失效");
    return false;
  }
}

/**
 * 强制刷新认证状态
 * 用于手动触发认证状态验证
 */
export async function refreshAuthState(): Promise<boolean> {
  const user = await fetchCurrentUser();
  notifyAuthStateChange(!!user);
  return !!user;
}

/**
 * 用户注册结果接口
 */
export interface RegisterResult {
  success: boolean;
  message?: string;
  user_id?: string;
  username?: string;
}

/**
 * 用户注册
 * 调用后端注册API创建新账号
 * @param username 用户名
 * @param password 密码
 * @param email 邮箱（可选）
 * @returns 注册结果
 */
export async function register(
  username: string,
  password: string,
  email?: string,
): Promise<RegisterResult> {
  try {
    const url = buildApiUrl("/api/auth/register");
    console.log("[Register] Request URL:", url);

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password, email }),
    });

    // 先获取文本，避免JSON解析错误
    const responseText = await response.text();
    console.log(
      "[Register] Response:",
      response.status,
      responseText.substring(0, 200),
    );

    // 如果响应为空
    if (!responseText) {
      return {
        success: false,
        message: "后端返回空响应，请检查后端服务是否正常运行",
      };
    }

    // 尝试解析JSON
    let data;
    try {
      data = JSON.parse(responseText);
    } catch (parseError) {
      return {
        success: false,
        message: `后端返回格式错误: ${responseText.substring(0, 100)}`,
      };
    }

    if (!response.ok) {
      // 处理 409 Conflict（用户名已存在）
      if (response.status === 409) {
        return {
          success: false,
          message: "用户名已存在，请选择其他用户名",
        };
      }
      return {
        success: false,
        message:
          data.detail || data.message || `注册失败 (HTTP ${response.status})`,
      };
    }

    if (data.success) {
      return {
        success: true,
        user_id: data.user_id,
        username: data.username,
        message: data.message || "注册成功",
      };
    }

    return {
      success: false,
      message: data.message || "注册失败",
    };
  } catch (error) {
    console.error("[Register] Error:", error);
    let errorMsg = "网络错误";

    if (error instanceof Error) {
      if (error.message.includes("Failed to fetch")) {
        errorMsg =
          "无法连接到后端服务。请检查:\n1. 后端是否已启动\n2. 端口 8600 是否正常\n3. 刷新页面重试";
      } else if (error.message.includes("NetworkError")) {
        errorMsg = "网络错误，请检查网络连接";
      } else {
        errorMsg = error.message;
      }
    }

    return {
      success: false,
      message: errorMsg,
    };
  }
}
