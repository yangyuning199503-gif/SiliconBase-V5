/**
 * 修改密码页面组件
 * 首次登录强制修改密码
 */
import { useState } from "react";
import { motion } from "framer-motion";
import {
  Lock,
  AlertCircle,
  Loader2,
  Shield,
  Eye,
  EyeOff,
  CheckCircle2,
  ArrowRight,
} from "lucide-react";
import { fetchAPI } from "../utils/api";

interface ChangePasswordPageProps {
  onPasswordChanged?: () => void;
  username?: string;
}

export function ChangePasswordPage({
  onPasswordChanged,
  username,
}: ChangePasswordPageProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const validatePassword = (password: string): string | null => {
    if (password.length < 8) {
      return "密码长度至少8个字符";
    }
    if (!/[A-Z]/.test(password)) {
      return "密码必须包含至少一个大写字母";
    }
    if (!/[a-z]/.test(password)) {
      return "密码必须包含至少一个小写字母";
    }
    if (!/[0-9]/.test(password)) {
      return "密码必须包含至少一个数字";
    }
    if (!/[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(password)) {
      return "密码必须包含至少一个特殊字符";
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // 验证表单
    if (!currentPassword.trim()) {
      setError("请输入当前密码");
      return;
    }
    if (!newPassword.trim()) {
      setError("请输入新密码");
      return;
    }

    const validationError = validatePassword(newPassword);
    if (validationError) {
      setError(validationError);
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }
    if (newPassword === currentPassword) {
      setError("新密码不能与当前密码相同");
      return;
    }

    setIsLoading(true);

    try {
      const result = await fetchAPI<{ success: boolean; message?: string }>(
        "/api/auth/change-password",
        {
          method: "POST",
          body: {
            current_password: currentPassword,
            new_password: newPassword,
          },
        },
      );

      if (result.success) {
        setSuccess(true);
        setTimeout(() => {
          onPasswordChanged?.();
        }, 1500);
      } else {
        setError(result.message || "修改密码失败");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改密码失败，请稍后重试");
    } finally {
      setIsLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen w-full bg-sb-bg-primary flex items-center justify-center p-4">
        <div className="fixed inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-green-500/10 rounded-full blur-3xl" />
          <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-green-500/8 rounded-full blur-3xl" />
        </div>

        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="w-full max-w-md relative z-10 text-center"
        >
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: "spring" }}
            className="inline-flex items-center justify-center w-24 h-24 rounded-full bg-green-500/20 mb-6"
          >
            <CheckCircle2 className="w-12 h-12 text-green-400" />
          </motion.div>

          <h1 className="text-2xl font-bold text-white mb-4">密码修改成功</h1>
          <p className="text-sb-text-secondary mb-6">
            您的密码已成功修改，正在进入系统...
          </p>

          <div className="flex justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-sb-cyan" />
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full bg-sb-bg-primary flex items-center justify-center p-4">
      {/* 背景装饰 */}
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
            className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-yellow-500 to-orange-600 mb-6 shadow-lg shadow-orange-500/20"
          >
            <Shield className="w-10 h-10 text-white" />
          </motion.div>
          <motion.h1
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="text-3xl font-bold text-white mb-2"
          >
            修改密码
          </motion.h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="text-sb-text-secondary"
          >
            为了您的账户安全，请修改初始密码
          </motion.p>
          {username && (
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="text-sb-cyan mt-2"
            >
              用户: {username}
            </motion.p>
          )}
        </div>

        {/* 修改密码表单 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="bg-[#1e1e2a] border border-white/15 rounded-2xl p-8 shadow-2xl"
        >
          <h2 className="text-xl font-semibold text-white mb-6 flex items-center gap-2">
            <Lock className="w-5 h-5 text-yellow-500" />
            设置新密码
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
            {/* 当前密码 */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-sb-text-secondary">
                当前密码
              </label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                <input
                  type={showCurrentPassword ? "text" : "password"}
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="请输入当前密码"
                  disabled={isLoading}
                  className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-12 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                  autoComplete="current-password"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white transition-colors"
                  tabIndex={-1}
                >
                  {showCurrentPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>

            {/* 新密码 */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-sb-text-secondary">
                新密码
              </label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                <input
                  type={showNewPassword ? "text" : "password"}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="至少8位，包含大小写字母、数字和特殊字符"
                  disabled={isLoading}
                  className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-12 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  onClick={() => setShowNewPassword(!showNewPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white transition-colors"
                  tabIndex={-1}
                >
                  {showNewPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
              <p className="text-xs text-slate-500">
                密码必须包含：8位以上、大写字母、小写字母、数字、特殊字符
              </p>
            </div>

            {/* 确认新密码 */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-sb-text-secondary">
                确认新密码
              </label>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-sb-text-secondary" />
                <input
                  type={showConfirmPassword ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="再次输入新密码"
                  disabled={isLoading}
                  className="w-full bg-sb-bg-primary border border-white/10 rounded-xl pl-12 pr-12 py-3 text-white placeholder:text-sb-text-secondary/50 focus:border-sb-cyan focus:outline-none focus:ring-2 focus:ring-sb-cyan/20 transition-all disabled:opacity-50"
                  autoComplete="new-password"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 text-sb-text-secondary hover:text-white transition-colors"
                  tabIndex={-1}
                >
                  {showConfirmPassword ? (
                    <EyeOff className="w-5 h-5" />
                  ) : (
                    <Eye className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>

            {/* 提交按钮 */}
            <motion.button
              type="submit"
              disabled={isLoading}
              whileHover={{ scale: isLoading ? 1 : 1.02 }}
              whileTap={{ scale: isLoading ? 1 : 0.98 }}
              className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-yellow-500 to-orange-600 hover:from-yellow-400 hover:to-orange-500 text-white font-semibold py-3.5 rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-orange-500/20 mt-6"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  修改中...
                </>
              ) : (
                <>
                  确认修改
                  <ArrowRight className="w-5 h-5" />
                </>
              )}
            </motion.button>
          </form>

          {/* 安全提示 */}
          <div className="mt-6 pt-6 border-t border-white/10">
            <div className="flex items-start gap-3 text-xs text-slate-500">
              <Shield className="w-4 h-4 flex-shrink-0 mt-0.5" />
              <p>
                密码将加密存储。为了账户安全，建议定期更换密码，不要在多个网站使用相同密码。
              </p>
            </div>
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
    </div>
  );
}

export default ChangePasswordPage;
