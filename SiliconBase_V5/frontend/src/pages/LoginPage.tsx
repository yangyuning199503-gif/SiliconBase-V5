/**
 * 登录页面组件
 * 提供用户登录功能，支持用户名/密码认证
 */
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import {
  Lock,
  User,
  LogIn,
  AlertCircle,
  Loader2,
  Shield,
  Eye,
  EyeOff,
  UserPlus,
  X,
  Mail,
} from "lucide-react";
import { login, isAuthenticated, register } from "../utils/auth";

import { useNavigate } from "react-router-dom";

interface LoginPageProps {
  onLoginSuccess?: () => void;
  onRequirePasswordChange?: (username: string) => void;
}

export function LoginPage({
  onLoginSuccess,
  onRequirePasswordChange,
}: LoginPageProps) {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);

  // 注册弹窗状态
  const [showRegister, setShowRegister] = useState(false);
  const [regUsername, setRegUsername] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regLoading, setRegLoading] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);
  const [regSuccess, setRegSuccess] = useState<string | null>(null);
  const [showRegPassword, setShowRegPassword] = useState(false);

  // 检查是否已登录
  useEffect(() => {
    const checkAuth = async () => {
      if (isAuthenticated()) {
        // 使用微任务确保状态更新在下一次渲染周期
        await Promise.resolve();
        if (onLoginSuccess) {
          onLoginSuccess();
        } else {
          navigate("/");
        }
      }
      setIsCheckingAuth(false);
    };
    checkAuth();
  }, [onLoginSuccess]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // 表单验证
    if (!username.trim()) {
      setError("请输入用户名");
      return;
    }
    if (!password.trim()) {
      setError("请输入密码");
      return;
    }

    setIsLoading(true);

    try {
      const result = await login(username.trim(), password.trim());

      if (result.success) {
        // 检查是否需要强制修改密码
        if (result.require_password_change) {
          if (onRequirePasswordChange) {
            onRequirePasswordChange(username.trim());
          } else {
            navigate("/change-password", {
              state: { username: username.trim() },
            });
          }
          return;
        }
        // 确保token已写入localStorage后再触发回调
        setTimeout(() => {
          if (onLoginSuccess) {
            onLoginSuccess();
          } else {
            navigate("/");
          }
        }, 0);
      } else {
        setError(result.message || "登录失败，请检查用户名和密码");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后重试");
    } finally {
      setIsLoading(false);
    }
  };

  // 处理回车键登录
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !isLoading) {
      handleSubmit(e);
    }
  };

  // 处理注册
  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setRegError(null);
    setRegSuccess(null);

    // 表单验证
    if (!regUsername.trim() || regUsername.length < 3) {
      setRegError("用户名至少3个字符");
      return;
    }
    if (!regPassword.trim() || regPassword.length < 6) {
      setRegError("密码至少6个字符");
      return;
    }

    setRegLoading(true);

    try {
      const result = await register(
        regUsername.trim(),
        regPassword.trim(),
        regEmail.trim() || undefined,
      );

      if (result.success) {
        setRegSuccess("注册成功！请使用新账号登录");
        // 清空表单
        setRegUsername("");
        setRegPassword("");
        setRegEmail("");
        // 2秒后关闭弹窗
        setTimeout(() => {
          setShowRegister(false);
          setRegSuccess(null);
        }, 2000);
      } else {
        setRegError(result.message || "注册失败，请重试");
      }
    } catch (err) {
      setRegError(err instanceof Error ? err.message : "注册失败，请稍后重试");
    } finally {
      setRegLoading(false);
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="min-h-screen w-full bg-sb-bg-primary flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex items-center gap-3 text-sb-text-secondary"
        >
          <Loader2 className="w-6 h-6 animate-spin text-sb-cyan" />
          <span>检查登录状态...</span>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-sb-bg-primary flex items-center justify-center p-4">
      {/* 背景装饰 - 提高亮度 */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-sb-cyan/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-sb-cyan/8 rounded-full blur-3xl" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md relative z-10"
      >
        {/* Logo区域 */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.1, duration: 0.5 }}
            className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-sb-cyan to-sb-cyan-dark mb-6 shadow-lg shadow-sb-cyan/20"
          >
            <Shield className="w-10 h-10 text-sb-bg-primary" />
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="text-3xl font-bold text-white mb-2"
          >
            SiliconBase V5
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="text-sb-text-secondary"
          >
            AI 智能体控制中枢
          </motion.p>
        </div>

        {/* 登录表单 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="bg-[#1e1e2a] border border-white/15 rounded-2xl p-8 shadow-2xl"
        >
          <h2 className="text-xl font-semibold text-white mb-6 flex items-center gap-2">
            <Lock className="w-5 h-5 text-sb-cyan" />
            用户登录
          </h2>

          {/* 错误提示 */}
          {error && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl flex items-start gap-3"
            >
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <span className="text-red-400 text-sm">{error}</span>
            </motion.div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* 用户名输入 */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-sb-text-secondary">
                用户名
              </label>
              <div className="relative">
                <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="请输入用户名"
                  disabled={isLoading}
                  className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-4 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                  autoComplete="username"
                  autoFocus
                />
              </div>
            </div>

            {/* 密码输入 */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-sb-text-secondary">
                密码
              </label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="请输入密码"
                  disabled={isLoading}
                  className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-12 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>

            {/* 登录按钮 */}
            <motion.button
              type="submit"
              disabled={isLoading}
              whileHover={{ scale: isLoading ? 1 : 1.02 }}
              whileTap={{ scale: isLoading ? 1 : 0.98 }}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-sb-cyan to-sb-cyan-dark hover:from-sb-cyan-hover hover:to-sb-cyan text-sb-bg-primary font-semibold py-3.5 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-sb-cyan/20"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  登录中...
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5" />
                  登录
                </>
              )}
            </motion.button>
          </form>

          {/* 注册链接 */}
          <div className="mt-6 pt-6 border-t border-white/10 space-y-3">
            <button
              type="button"
              onClick={() => setShowRegister(true)}
              className="w-full flex items-center justify-center gap-2 py-2.5 border border-sb-cyan/30 text-sb-cyan rounded-xl hover:bg-sb-cyan/10 transition-all"
            >
              <UserPlus className="w-4 h-4" />
              注册新账号
            </button>
            <p className="text-xs text-sb-text-secondary text-center">
              首次使用请注册新账号，或联系管理员获取账号
            </p>
          </div>
        </motion.div>

        {/* 底部版权 */}
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="text-center text-sb-text-secondary/50 text-xs mt-8"
        >
          © 2026 SiliconBase V5. All rights reserved.
        </motion.p>
      </motion.div>

      {/* 注册弹窗 */}
      {showRegister && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => !regLoading && setShowRegister(false)}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="relative bg-[#1e1e2a] border border-white/15 rounded-2xl p-8 w-full max-w-md shadow-2xl"
          >
            <button
              onClick={() => !regLoading && setShowRegister(false)}
              disabled={regLoading}
              className="absolute top-4 right-4 text-sb-text-secondary hover:text-white transition-colors disabled:opacity-50"
            >
              <X className="w-5 h-5" />
            </button>

            <h2 className="text-xl font-semibold text-white mb-6 flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-sb-cyan" />
              注册新账号
            </h2>

            {/* 错误/成功提示 */}
            {regError && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg flex items-start gap-2"
              >
                <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
                <span className="text-red-400 text-sm">{regError}</span>
              </motion.div>
            )}
            {regSuccess && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                className="mb-4 p-3 bg-green-500/10 border border-green-500/30 rounded-lg flex items-start gap-2"
              >
                <Shield className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                <span className="text-green-400 text-sm">{regSuccess}</span>
              </motion.div>
            )}

            <form onSubmit={handleRegister} className="space-y-4">
              {/* 用户名 */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-sb-text-secondary">
                  用户名 *
                </label>
                <div className="relative">
                  <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                  <input
                    type="text"
                    value={regUsername}
                    onChange={(e) => setRegUsername(e.target.value)}
                    placeholder="至少3个字符"
                    disabled={regLoading}
                    className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-4 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                    autoComplete="username"
                  />
                </div>
              </div>

              {/* 密码 */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-sb-text-secondary">
                  密码 *
                </label>
                <div className="relative">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                  <input
                    type={showRegPassword ? "text" : "password"}
                    value={regPassword}
                    onChange={(e) => setRegPassword(e.target.value)}
                    placeholder="至少6个字符"
                    disabled={regLoading}
                    className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-12 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowRegPassword(!showRegPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white transition-colors"
                    tabIndex={-1}
                  >
                    {showRegPassword ? (
                      <EyeOff className="w-5 h-5" />
                    ) : (
                      <Eye className="w-5 h-5" />
                    )}
                  </button>
                </div>
              </div>

              {/* 邮箱（可选） */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-sb-text-secondary">
                  邮箱（可选）
                </label>
                <div className="relative">
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                  <input
                    type="email"
                    value={regEmail}
                    onChange={(e) => setRegEmail(e.target.value)}
                    placeholder="用于找回密码"
                    disabled={regLoading}
                    className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-4 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                    autoComplete="email"
                  />
                </div>
              </div>

              {/* 注册按钮 */}
              <motion.button
                type="submit"
                disabled={regLoading}
                whileHover={{ scale: regLoading ? 1 : 1.02 }}
                whileTap={{ scale: regLoading ? 1 : 0.98 }}
                className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-sb-cyan to-sb-cyan-dark hover:from-sb-cyan-hover hover:to-sb-cyan text-sb-bg-primary font-semibold py-3.5 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-sb-cyan/20 mt-6"
              >
                {regLoading ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    注册中...
                  </>
                ) : (
                  <>
                    <UserPlus className="w-5 h-5" />
                    注册
                  </>
                )}
              </motion.button>
            </form>
          </motion.div>
        </div>
      )}
    </div>
  );
}

export default LoginPage;
