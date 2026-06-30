#!/usr/bin/env python3
"""
SiliconBase V5 — 异步高性能状态推断引擎
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
类人生物的中枢神经系统计算核心。

设计约束：
- 核心算法（KF / UKF / PF）为纯同步计算，零 I/O
- AsyncStateEstimator 负责异步并发与线程池隔离
- 只依赖 numpy
"""

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 线性卡尔曼滤波 (KalmanFilter)
# ═══════════════════════════════════════════════════════════════════════════════

class KalmanFilter:
    """
    线性卡尔曼滤波。

    适用场景：内在动机平滑、系统资源估计等状态变化平滑
    且噪声为高斯分布的连续过程。
    """

    def __init__(self, state_dim: int, observation_dim: int):
        self.state_dim = state_dim
        self.obs_dim = observation_dim
        self.X = np.zeros((state_dim, 1))
        self.P = np.eye(state_dim)

    def predict(self, A: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """预测步：先验状态估计与协方差传播。"""
        self.X = A @ self.X
        self.P = A @ self.P @ A.T + Q
        return self.X, self.P

    def update(self, Z: np.ndarray, H: np.ndarray, R: np.ndarray
               ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """更新步：观测残差修正与卡尔曼增益计算。"""
        Y_tilde = Z - H @ self.X
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.X = self.X + K @ Y_tilde
        self.P = (np.eye(self.state_dim) - K @ H) @ self.P
        return self.X, self.P, K

    def get_state(self) -> np.ndarray:
        return self.X.copy()

    def get_covariance(self) -> np.ndarray:
        return self.P.copy()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 无迹卡尔曼滤波 (UnscentedKalmanFilter)
# ═══════════════════════════════════════════════════════════════════════════════

class UnscentedKalmanFilter:
    """
    无迹卡尔曼滤波 (UKF)。

    适用场景：用户意图推断、动机动态变化等具有轻度非线性的连续过程。
    通过 Sigma 点采样精确捕获非线性变换后的均值与协方差。
    """

    def __init__(self, state_dim: int, observation_dim: int,
                 alpha: float = 0.001, beta: float = 2.0, kappa: float = 0.0):
        self.n = state_dim
        self.m = observation_dim
        self.alpha = alpha
        self.beta = beta
        self.kappa = kappa

        self.lambda_ = alpha ** 2 * (self.n + kappa) - self.n

        # 权重初始化
        self.Wm = np.zeros(2 * self.n + 1)
        self.Wc = np.zeros(2 * self.n + 1)
        self.Wm[0] = self.lambda_ / (self.n + self.lambda_)
        self.Wc[0] = self.Wm[0] + (1 - alpha ** 2 + beta)
        for i in range(1, 2 * self.n + 1):
            self.Wm[i] = 1.0 / (2.0 * (self.n + self.lambda_))
            self.Wc[i] = self.Wm[i]

        self.X = np.zeros((self.n, 1))
        self.P = np.eye(self.n)

    def _generate_sigma_points(self) -> np.ndarray:
        """生成 2n+1 个 Sigma 点，返回 (n, 2n+1) 矩阵。"""
        sigma_points = np.zeros((self.n, 2 * self.n + 1))
        sigma_points[:, 0:1] = self.X

        # 矩阵平方根（Cholesky 分解）
        try:
            sqrt_term = np.linalg.cholesky((self.n + self.lambda_) * self.P)
        except np.linalg.LinAlgError:
            # 若 P 非正定，使用特征值分解兜底
            eigvals, eigvecs = np.linalg.eigh(self.P)
            eigvals = np.maximum(eigvals, 1e-10)
            sqrt_term = eigvecs @ np.diag(np.sqrt(eigvals))

        for i in range(self.n):
            sigma_points[:, i + 1] = (self.X + sqrt_term[:, i:i + 1]).flatten()
            sigma_points[:, i + 1 + self.n] = (self.X - sqrt_term[:, i:i + 1]).flatten()

        return sigma_points

    def predict(self, transition_fn: Callable[[np.ndarray], np.ndarray],
                process_noise: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        预测步：将 Sigma 点穿过非线性状态转移函数，重构预测均值和协方差。
        """
        # 数值稳定性保护：协方差矩阵对称化
        self.P = (self.P + self.P.T) / 2.0
        # 防止半正定性丧失
        self.P += np.eye(self.n) * 1e-8

        sigma_points = self._generate_sigma_points()
        n_sigma = sigma_points.shape[1]

        # 传播 Sigma 点
        propagated = np.zeros((self.n, n_sigma))
        for i in range(n_sigma):
            propagated[:, i:i + 1] = transition_fn(sigma_points[:, i:i + 1])

        # 重构均值
        self.X = np.sum(propagated * self.Wm[np.newaxis, :], axis=1, keepdims=True)

        # 重构协方差
        diff = propagated - self.X
        self.P = process_noise.copy()
        for i in range(n_sigma):
            self.P += self.Wc[i] * (diff[:, i:i + 1] @ diff[:, i:i + 1].T)

        # 计算 Sigma 点传播后的线性度指标（LeJEPA 监控）
        propagated_mean = np.sum(propagated * self.Wm[np.newaxis, :], axis=1)
        linear_approx = transition_fn(self.X)
        nonlinearity_score = float(np.linalg.norm(propagated_mean - linear_approx.flatten()))

        if nonlinearity_score > 100.0:
            logger.warning(f"[UKF] 转移函数非线性度较高({nonlinearity_score:.2f})，世界模型可识别性可能下降，当前状态值: {self.X.flatten()}")

        return self.X, self.P

    def update(self, observation: np.ndarray,
               observation_fn: Callable[[np.ndarray], np.ndarray],
               observation_noise: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        更新步：将预测 Sigma 点穿过观测函数，计算卡尔曼增益并更新状态。
        """
        sigma_points = self._generate_sigma_points()
        n_sigma = sigma_points.shape[1]

        # 观测传播
        Z_sigma = np.zeros((self.m, n_sigma))
        for i in range(n_sigma):
            Z_sigma[:, i:i + 1] = observation_fn(sigma_points[:, i:i + 1])

        # 观测均值
        z_pred = np.sum(Z_sigma * self.Wm[np.newaxis, :], axis=1, keepdims=True)

        # 观测协方差
        diff_z = Z_sigma - z_pred
        Pzz = observation_noise.copy()
        for i in range(n_sigma):
            Pzz += self.Wc[i] * (diff_z[:, i:i + 1] @ diff_z[:, i:i + 1].T)

        # 交叉协方差
        diff_x = sigma_points - self.X
        Pxz = np.zeros((self.n, self.m))
        for i in range(n_sigma):
            Pxz += self.Wc[i] * (diff_x[:, i:i + 1] @ diff_z[:, i:i + 1].T)

        # 卡尔曼增益与状态更新
        # 数值稳定性保护：观测协方差矩阵对称化
        Pzz = (Pzz + Pzz.T) / 2.0
        # 防止病态
        Pzz += np.eye(self.m) * 1e-6

        K = Pxz @ np.linalg.inv(Pzz)
        self.X = self.X + K @ (observation - z_pred)
        self.P = self.P - K @ Pzz @ K.T

        # 数值稳定性保护：状态值软裁剪，防止爆炸值继续参与后续计算
        # 正常状态值应在 [0, 1] 之间，允许少量超出（因为 UKF 本身没有硬约束）
        # 这里用较宽的范围 [-1, 2] 做软裁剪，不强行截断正常波动
        self.X = np.clip(self.X, -1.0, 2.0)

        return self.X, self.P

    def get_state(self) -> np.ndarray:
        return self.X.copy()

    def get_covariance(self) -> np.ndarray:
        return self.P.copy()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FFT 频域特征提取（模块级纯函数）
# ═══════════════════════════════════════════════════════════════════════════════

def extract_spectral_features(time_series: np.ndarray,
                                sampling_rate: float = 1.0) -> dict:
    """
    对时间序列做 FFT，提取频域特征。

    Args:
        time_series: 一维时间序列数组 (N,)
        sampling_rate: 采样率（Hz）

    Returns:
        {
            'frequencies': 频率数组,
            'magnitudes': 幅度谱,
            'phases': 相位谱,
            'dominant_freqs': 前5个主要频率,
            'energy_distribution': 低频/中频/高频能量占比,
            'total_energy': 总能量
        }
    """
    N = len(time_series)
    detrended = time_series - np.mean(time_series)
    fft_result = np.fft.fft(detrended)
    frequencies = np.fft.fftfreq(N, d=1.0 / sampling_rate)

    positive_mask = frequencies >= 0
    frequencies = frequencies[positive_mask]
    magnitudes = np.abs(fft_result[positive_mask]) / N
    phases = np.angle(fft_result[positive_mask])

    top_indices = np.argsort(magnitudes)[-5:]
    dominant_freqs = [
        {'frequency': float(frequencies[i]),
         'magnitude': float(magnitudes[i]),
         'phase': float(phases[i])}
        for i in reversed(top_indices)
    ]

    total_energy = np.sum(magnitudes ** 2)
    nyquist = sampling_rate / 2.0
    low_mask = frequencies <= 0.2 * nyquist
    mid_mask = (frequencies > 0.2 * nyquist) & (frequencies <= 0.6 * nyquist)
    high_mask = frequencies > 0.6 * nyquist

    energy_distribution = {
        'low': float(np.sum(magnitudes[low_mask] ** 2) / (total_energy + 1e-300)),
        'mid': float(np.sum(magnitudes[mid_mask] ** 2) / (total_energy + 1e-300)),
        'high': float(np.sum(magnitudes[high_mask] ** 2) / (total_energy + 1e-300))
    }

    return {
        'frequencies': frequencies,
        'magnitudes': magnitudes,
        'phases': phases,
        'dominant_freqs': dominant_freqs,
        'energy_distribution': energy_distribution,
        'total_energy': float(total_energy)
    }


def generate_spectral_scenarios(spectral_features: dict,
                                num_scenarios: int,
                                time_horizon: int) -> np.ndarray:
    """
    基于频谱特征生成随机情景。保持幅度谱不变，随机化相位谱，再逆 FFT 回时域。

    Returns:
        (num_scenarios, time_horizon) 的情景矩阵
    """
    frequencies = spectral_features['frequencies']
    magnitudes = spectral_features['magnitudes']
    N = len(magnitudes)
    scenarios = np.zeros((num_scenarios, time_horizon))

    for i in range(num_scenarios):
        random_phases = np.random.uniform(0, 2 * np.pi, N)
        for dominant in spectral_features['dominant_freqs'][:3]:
            idx = np.argmin(np.abs(frequencies - dominant['frequency']))
            random_phases[idx] = dominant['phase'] + np.random.normal(0, 0.3)

        complex_spectrum = magnitudes * np.exp(1j * random_phases)
        full_spectrum = np.zeros(time_horizon, dtype=complex)
        full_spectrum[:N] = complex_spectrum
        if time_horizon > 2 * N:
            full_spectrum[-(N - 1):] = np.conj(complex_spectrum[1:][::-1])

        time_series = np.fft.ifft(full_spectrum).real[:time_horizon]
        scenarios[i] = time_series

    return scenarios


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 粒子滤波 (ParticleFilter)
# ═══════════════════════════════════════════════════════════════════════════════

class ParticleFilter:
    """
    粒子滤波 (SIS + 多种重采样策略 + 反思修正 + 动态粒子数)。

    适用场景：世界模型多假设预测、多源感知融合、市场状态推断等
    状态可能突变或多峰的复杂过程。
    """

    def __init__(self, num_particles: int, state_dim: int,
                 initial_state_sampler: Callable[[], np.ndarray]):
        self.N = num_particles
        self.state_dim = state_dim
        self.particles = np.zeros((state_dim, self.N))
        for i in range(self.N):
            self.particles[:, i] = initial_state_sampler().flatten()
        self.weights = np.ones(self.N) / self.N

    def predict(self, transition_fn: Callable[[np.ndarray], np.ndarray]):
        """预测步：每个粒子从状态转移分布中采样。"""
        for i in range(self.N):
            self.particles[:, i] = transition_fn(self.particles[:, i]).flatten()

    def update(self, observation: np.ndarray,
               likelihood_fn: Callable[[np.ndarray, np.ndarray], float]):
        """更新步：根据观测似然重新加权粒子。"""
        for i in range(self.N):
            self.weights[i] *= likelihood_fn(self.particles[:, i], observation)

        weight_sum = np.sum(self.weights)
        if weight_sum > 1e-300:
            self.weights /= weight_sum
        else:
            self.weights = np.ones(self.N) / self.N

    # ──────────────────────────────────────────────────────────────────────────
    # 重采样策略集合
    # ──────────────────────────────────────────────────────────────────────────

    def resample(self, method: str = 'residual', correction_hint: dict = None):
        """
        重采样：当有效粒子数低于阈值时执行。

        Args:
            method: 'systematic' | 'multinomial' | 'residual' | 'stratified'
            correction_hint: 反思系统传入的修正信息，可选
        """
        N_eff = 1.0 / np.sum(self.weights ** 2)
        if N_eff >= self.N / 2:
            return

        if method == 'systematic':
            self._systematic_resample()
        elif method == 'multinomial':
            self._multinomial_resample()
        elif method == 'residual':
            self._residual_resample()
        elif method == 'stratified':
            self._stratified_resample()
        else:
            self._residual_resample()

        if correction_hint:
            self._apply_correction(correction_hint)

    def _systematic_resample(self):
        """系统重采样——低方差，适合高频场景。"""
        positions = (np.arange(self.N) + np.random.uniform()) / self.N
        cumsum = np.cumsum(self.weights)
        indices = np.searchsorted(cumsum, positions)
        indices = np.clip(indices, 0, self.N - 1)
        self.particles = self.particles[:, indices]
        self.weights = np.ones(self.N) / self.N

    def _multinomial_resample(self):
        """多项式重采样——按权重独立抽样。"""
        indices = np.random.choice(self.N, size=self.N, p=self.weights)
        self.particles = self.particles[:, indices]
        self.weights = np.ones(self.N) / self.N

    def _residual_resample(self):
        """残差重采样——平衡多样性与效率，默认首选。"""
        residual_counts = (self.weights * self.N).astype(int)
        residual_weights = self.weights * self.N - residual_counts
        residual_weights /= np.sum(residual_weights) + 1e-300

        indices = []
        for i, count in enumerate(residual_counts):
            indices.extend([i] * count)

        remaining = self.N - len(indices)
        if remaining > 0:
            indices.extend(np.random.choice(self.N, size=remaining, p=residual_weights))

        indices = np.array(indices, dtype=int)
        self.particles = self.particles[:, indices]
        self.weights = np.ones(self.N) / self.N

    def _stratified_resample(self):
        """分层重采样——每层内均匀抽样，保证分布均匀性。"""
        positions = (np.random.uniform(0, 1, self.N) + np.arange(self.N)) / self.N
        cumsum = np.cumsum(self.weights)
        indices = np.searchsorted(cumsum, positions)
        indices = np.clip(indices, 0, self.N - 1)
        self.particles = self.particles[:, indices]
        self.weights = np.ones(self.N) / self.N

    def _apply_correction(self, hint: dict):
        """反思驱动修正：在反思建议方向上微调高权重粒子。"""
        bias_direction = hint.get('bias_direction')
        bias_magnitude = hint.get('bias_magnitude', 0.01)
        if bias_direction is None or not isinstance(bias_direction, np.ndarray):
            return
        top_k = max(1, int(self.N * 0.2))
        top_indices = np.argsort(self.weights)[::-1][:top_k]
        for idx in top_indices:
            noise = np.random.randn(self.state_dim) * bias_magnitude
            self.particles[:, idx] += bias_direction.flatten() + noise

        # 高斯正则化（LeJEPA 约束）：对偏离高斯太远的粒子施加拉回力
        mean, cov = self.estimate()
        cov_inv = np.linalg.pinv(cov + 1e-4 * np.eye(self.state_dim))
        for i in range(self.N):
            diff = (self.particles[:, i] - mean.flatten()).reshape(-1, 1)
            mahalanobis = float(diff.T @ cov_inv @ diff)
            if mahalanobis > 3.0:  # 偏离 3 个标准差
                # 向高斯均值拉回 20%
                self.particles[:, i] = 0.8 * self.particles[:, i] + 0.2 * mean.flatten()

    # ──────────────────────────────────────────────────────────────────────────
    # 动态粒子数调整
    # ──────────────────────────────────────────────────────────────────────────

    def adjust_particle_count(self, error_history: list[float]):
        """根据反思系统的误差历史动态调整粒子数。"""
        if len(error_history) < 5:
            return
        avg_error = np.mean(error_history[-5:])
        if avg_error > 0.3:
            new_N = min(self.N * 2, 1000)
            self._resize_particles(new_N)
        elif avg_error < 0.1:
            new_N = max(self.N // 2, 50)
            self._resize_particles(new_N)

    def _resize_particles(self, new_N: int):
        """调整粒子数量（保持高权重粒子，补充新粒子）。"""
        if new_N == self.N:
            return
        top_k = min(new_N, self.N)
        top_indices = np.argsort(self.weights)[::-1][:top_k]
        new_particles = self.particles[:, top_indices].copy()
        new_weights = self.weights[top_indices].copy()
        new_weights /= np.sum(new_weights)

        if new_N > self.N:
            extra = new_N - self.N
            mean_state = np.sum(new_particles * new_weights[np.newaxis, :], axis=1, keepdims=True)
            std_state = np.std(new_particles, axis=1, keepdims=True) + 1e-6
            extra_particles = mean_state + std_state * np.random.randn(self.state_dim, extra)
            new_particles = np.concatenate([new_particles, extra_particles], axis=1)
            new_weights = np.ones(new_N) / new_N

        self.N = new_N
        self.particles = new_particles
        self.weights = new_weights

    # ──────────────────────────────────────────────────────────────────────────
    # 状态估计
    # ──────────────────────────────────────────────────────────────────────────

    def estimate(self) -> tuple[np.ndarray, np.ndarray]:
        """返回加权均值与加权协方差。"""
        X_hat = np.sum(self.particles * self.weights[np.newaxis, :], axis=1, keepdims=True)
        diff = self.particles - X_hat
        P_hat = diff @ np.diag(self.weights) @ diff.T
        return X_hat, P_hat

    def get_particles(self) -> tuple[np.ndarray, np.ndarray]:
        return self.particles.copy(), self.weights.copy()

    def get_neff(self) -> float:
        return 1.0 / np.sum(self.weights ** 2)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 频域感知粒子滤波 (FrequencyAwareParticleFilter)
# ═══════════════════════════════════════════════════════════════════════════════

class FrequencyAwareParticleFilter(ParticleFilter):
    """
    基于频域特征的粒子滤波器。
    粒子转移遵循真实数据的频谱规律，替代简单白噪声扰动。
    """

    def __init__(self, *args, spectral_window: int = 100, **kwargs):
        super().__init__(*args, **kwargs)
        self.spectral_window = spectral_window
        self.observation_history: list[np.ndarray] = []
        self.spectral_features: dict | None = None

    def update_spectral_model(self, new_observation: np.ndarray):
        """更新频谱模型。"""
        self.observation_history.append(new_observation.copy())
        if len(self.observation_history) > self.spectral_window:
            self.observation_history.pop(0)
        if len(self.observation_history) >= 30:
            time_series = np.array([obs.flatten()[0] for obs in self.observation_history])
            self.spectral_features = extract_spectral_features(time_series)

    def predict(self, transition_fn: Callable[[np.ndarray], np.ndarray] = None):
        """
        基于频谱的粒子转移——替代随机扰动。
        若频谱模型未就绪，回退到传入的 transition_fn 或简单随机扰动。
        """
        if self.spectral_features is not None:
            scenarios = generate_spectral_scenarios(
                self.spectral_features,
                num_scenarios=self.N,
                time_horizon=1
            )
            for i in range(self.N):
                self.particles[:, i] += scenarios[i, 0] * np.ones(self.state_dim)
        elif transition_fn is not None:
            super().predict(transition_fn)
        else:
            def _fallback(x):
                return x + np.random.randn(*x.shape) * 0.01
            super().predict(_fallback)

    def predict_with_spectral_transition(self):
        """显式调用基于频谱的粒子转移（兼容旧接口）。"""
        self.predict()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 异步高性能引擎封装 (AsyncStateEstimator)
# ═══════════════════════════════════════════════════════════════════════════════

class AsyncStateEstimator:
    """
    异步高性能状态推断引擎。

    用于多元、动态、毫秒级环境的类人生物中枢神经系统。
    计算与 I/O 分离：核心算法为纯同步计算，引擎负责异步并发调度。
    """

    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="estimator")
        self._estimators: dict[str, Any] = {}

    def register(self, name: str, estimator_type: str, **kwargs):
        """注册一个状态估计器实例。"""
        if estimator_type == 'kalman':
            estimator = KalmanFilter(**kwargs)
        elif estimator_type == 'unscented_kalman':
            estimator = UnscentedKalmanFilter(**kwargs)
        elif estimator_type == 'particle':
            estimator = ParticleFilter(**kwargs)
        elif estimator_type == 'frequency_aware_particle':
            estimator = FrequencyAwareParticleFilter(**kwargs)
        else:
            raise ValueError(f"未知的估计器类型: {estimator_type}")
        self._estimators[name] = estimator

    def get(self, name: str) -> Any:
        """获取已注册的估计器实例。"""
        return self._estimators.get(name)

    def unregister(self, name: str):
        """注销估计器。"""
        self._estimators.pop(name, None)

    def has(self, name: str) -> bool:
        return name in self._estimators

    # ──────────────────────────────────────────────────────────────────────────
    # 异步公共接口
    # ──────────────────────────────────────────────────────────────────────────

    async def predict_async(self, name: str,
                            A_or_transition: Any,
                            Q_or_process_noise: np.ndarray) -> dict:
        """
        异步执行预测步。
        自动将计算密集型任务在线程池中执行，不阻塞事件循环。
        """
        loop = asyncio.get_running_loop()
        estimator = self._estimators[name]

        def _compute():
            if isinstance(estimator, (KalmanFilter, UnscentedKalmanFilter)):
                X, P = estimator.predict(A_or_transition, Q_or_process_noise)
                return {'state': X, 'covariance': P, 'name': name}
            elif isinstance(estimator, ParticleFilter):
                estimator.predict(A_or_transition)
                X, P = estimator.estimate()
                return {'state': X, 'covariance': P, 'neff': estimator.get_neff(), 'name': name}
            else:
                raise TypeError(f"不支持的估计器类型: {type(estimator)}")

        return await loop.run_in_executor(self._executor, _compute)

    async def update_async(self, name: str,
                           observation: np.ndarray,
                           H_or_observation_fn: Any,
                           R_or_observation_noise: np.ndarray) -> dict:
        """异步执行更新步。"""
        loop = asyncio.get_running_loop()
        estimator = self._estimators[name]

        def _compute():
            if isinstance(estimator, KalmanFilter):
                X, P, K = estimator.update(observation, H_or_observation_fn, R_or_observation_noise)
                return {'state': X, 'covariance': P, 'gain': K, 'name': name}
            elif isinstance(estimator, UnscentedKalmanFilter):
                X, P = estimator.update(observation, H_or_observation_fn, R_or_observation_noise)
                return {'state': X, 'covariance': P, 'name': name}
            elif isinstance(estimator, ParticleFilter):
                estimator.update(observation, H_or_observation_fn)
                estimator.resample()
                X, P = estimator.estimate()
                return {'state': X, 'covariance': P, 'neff': estimator.get_neff(), 'name': name}
            else:
                raise TypeError(f"不支持的估计器类型: {type(estimator)}")

        return await loop.run_in_executor(self._executor, _compute)

    async def estimate_async(self, name: str,
                             observation: np.ndarray,
                             predict_args: dict,
                             update_args: dict) -> dict:
        """
        异步完整估计：predict + update 原子执行。
        """
        await self.predict_async(name, **predict_args)
        return await self.update_async(name, observation, **update_args)

    async def batch_estimate(self, tasks: list[dict]) -> list[dict]:
        """
        批量异步估计。可同时运行多个滤波实例
        （如并行处理视觉、市场、语音数据）。
        """
        coros = []
        for task in tasks:
            name = task['name']
            observation = task['observation']
            predict_args = task.get('predict_args', {})
            update_args = task.get('update_args', {})
            coros.append(self.estimate_async(name, observation, predict_args, update_args))
        return await asyncio.gather(*coros, return_exceptions=True)

    async def get_state_async(self, name: str) -> dict:
        """异步获取当前状态估计。"""
        loop = asyncio.get_running_loop()
        estimator = self._estimators[name]

        def _compute():
            if isinstance(estimator, ParticleFilter):
                X, P = estimator.estimate()
                particles, weights = estimator.get_particles()
                return {
                    'state': X,
                    'covariance': P,
                    'particles': particles,
                    'weights': weights,
                    'neff': estimator.get_neff(),
                    'name': name
                }
            else:
                return {
                    'state': estimator.get_state(),
                    'covariance': estimator.get_covariance(),
                    'name': name
                }

        return await loop.run_in_executor(self._executor, _compute)

    def shutdown(self):
        """关闭线程池。"""
        self._executor.shutdown(wait=True)
