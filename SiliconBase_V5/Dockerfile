# SiliconBase V5 Docker镜像
# 支持Python 3.10 + AI/ML全栈

FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/app/.cache/huggingface \
    TORCH_HOME=/app/.cache/torch

# 安装系统依赖
# 包括：编译工具、音频处理、OCR依赖、网络工具等
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 编译工具
    gcc \
    g++ \
    make \
    cmake \
    # Python开发头文件
    python3-dev \
    # 音频处理
    libsndfile1 \
    libsndfile1-dev \
    portaudio19-dev \
    libasound2-dev \
    # OCR依赖
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    tesseract-ocr-eng \
    libtesseract-dev \
    # 图像处理
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    # 网络工具
    curl \
    wget \
    # 其他工具
    git \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 创建缓存目录
RUN mkdir -p /app/.cache/huggingface /app/.cache/torch /app/data /app/models /app/logs

# 首先复制requirements.txt并安装依赖（利用Docker缓存层）
COPY requirements.txt requirements.docker.txt ./

# 安装Python依赖
# 分步安装以优化层缓存
RUN pip install --upgrade pip setuptools wheel && \
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt && \
    pip install fastapi uvicorn[standard] python-multipart pydantic-settings

# 安装额外的Docker特定依赖
RUN pip install redis hiredis

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p /app/data/state /app/data/user_configs /app/config /app/tools /app/plugins

# 复制默认配置（如果不存在）
COPY config/ /app/config/

# 设置启动脚本权限
RUN chmod +x docker-entrypoint.sh 2>/dev/null || true

# 暴露端口
# 8000: API服务
# 8502: 状态服务器
# 8503: WebSocket服务器
EXPOSE 8600

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8600/api/health || exit 1

# 设置入口点
ENTRYPOINT ["python"]

# 默认启动命令
CMD ["api/run.py", "--host", "0.0.0.0", "--port", "8600"]
