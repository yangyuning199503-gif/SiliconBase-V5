# SiliconBase V5 本地自包含环境配置说明

> 生成时间：2026-06-25  
> 目标：让项目主要依赖和模型文件都在工作目录内，方便打包和迁移。

---

## 一、已完成的改动

### 1. Python 解释器内置化
- **复制来源**：`C:\Users\yang\AppData\Roaming\uv\python\cpython-3.10-windows-x86_64-none`
- **复制到**：`SiliconBase_V5/.python/cpython-3.10-windows-x86_64-none`
- **大小**：约 71MB

这样 `.venv` 的 base interpreter 指向项目内部，换机器时只要修复路径即可。

### 2. 重建虚拟环境 `.venv`
使用项目内的 Python 解释器重新创建 `.venv`，并补齐核心与可选依赖：

| 依赖 | 作用 | 状态 |
|---|---|---|
| `requirements-core.txt` | Web、DB、异步等基础 | 已装 |
| `bcrypt`、`passlib`、`aiofiles` | 登录密码/JWT | 已装 |
| `apscheduler`、`prometheus-client` | 定时任务、监控 | 已装 |
| `pyaudio`、`vosk`、`pyttsx3`、`edge-tts` | 语音 ASR/TTS | 已装 |
| `torch` (CPU) | 世界模型、embedding | 已装 |
| `transformers`、`sentence-transformers` | HuggingFace 模型推理 | 已装 |
| `chromadb` | 向量记忆存储 | 已装 |

已删除损坏/冗余的：
- `.venv.broken.20260625_122017`（7.1GB，核心编译文件缺失，无法修复）
- `.venv.old`（旧环境，指向外部 Python）

### 3. 语音系统已修复
根因是 `.venv` 缺少 `pyaudio`，导致 `voice.interface` 导不进来。

现在：
- `VoiceInterface` 正常导入、实例化。
- Vosk 模型从 `assets/models/vosk-model-cn-0.22` 加载。
- 唤醒词 `元旦 / 你好元旦 / 小助手` 已生效。
- Piper TTS 缺少 `piper` 包，当前使用 `pyttsx3` 备用中文语音。

### 4. 向量记忆 + 世界模型已就绪
- ChromaDB 服务器启动成功，端口 8000。
- HuggingFace `all-MiniLM-L6-v2` 模型加载成功。
- 世界模型在 CPU 上初始化成功。

### 5. HuggingFace 模型内置化
- **复制到**：`SiliconBase_V5/checkpoints/hf_cache/`
- 已保留：
  - `sentence-transformers/all-MiniLM-L6-v2`（约 175MB）
  - `uer/roberta-base-finetuned-jd-binary-chinese`（约 1.5GB）
- 已移除语音/TTS 大模型（当前 Piper 未启用，避免 5GB+ 冗余）。

### 6. 启动脚本 `start_local.bat`
位于项目根目录 `E:\SiliconBase_V5\start_local.bat`：

```bat
set HF_HOME=%PROJECT_DIR%\checkpoints\hf_cache
set SENTENCE_TRANSFORMERS_HOME=%PROJECT_DIR%\checkpoints\hf_cache
set TRANSFORMERS_OFFLINE=1
set OLLAMA_MODELS=E:\.ollama\models
set AUTO_ENABLE_MCP=false
```

**不再禁用语音、不再强制关闭诊断模式。**

### 7. 迁移修复脚本
- `SiliconBase_V5/tools/repair_venv.py`
- `E:\SiliconBase_V5\repair_venv.bat`

打包移动到别的目录后，先运行 `repair_venv.bat` 修复 `.venv` 路径。

### 8. 依赖文件更新
- `requirements-core.txt` 补全 `passlib`、`aiofiles`、`bcrypt`、`apscheduler`、`prometheus-client`。
- 新增 `requirements-voice.txt`（语音依赖）。
- `requirements-full.txt` 引入 `requirements-voice.txt`。

### 9. `.gitignore` 更新
忽略 `.venv/`、`.venv.old/`、`.venv.broken*/`、`.python/`、`checkpoints/`、`.env` 等。

---

## 二、现在怎么启动

直接双击：

```
E:\SiliconBase_V5\start_local.bat
```

启动项：
- Redis（`tools/redis/redis-server.exe`）
- Ollama（如果已安装），模型使用 `E:\.ollama\models`
- 后端：`http://localhost:8600`
- 前端：`http://localhost:5173`

---

## 三、验证结果

已验证后端正常启动：

```text
[ChromaDB] 服务器就绪，端口 8000
[ChromaDB] 向量存储后端已就绪
[MemoryService] VectorStore 嵌入模型加载成功
[WorldModel] 世界模型已初始化
[Unified] ✅ 系统启动完成！所有功能已就绪
[语音] 备用 TTS 引擎初始化成功
[唤醒词] 最终唤醒词配置: ['元旦', '你好元旦', '小助手']
[Warmup] 文本模型 qwen3:8b 预热成功
[Warmup] 视觉模型 qwen3-vl:2b 预热成功
```

登录/Token 也已验证通过。

---

## 四、关于“为什么不直接改位置继续用”

| 东西 | 处理方式 | 原因 |
|---|---|---|
| Ollama 模型 | 不复制，改 `OLLAMA_MODELS` 指向 `E:\.ollama\models` | 6.7GB，没必要 duplicate |
| HF 小模型 | 复制到项目内 | 代码通过 `HF_HOME` 找本地模型；方便打包 |
| Python 解释器 | 复制到项目内 | `.venv` 必须指向 base interpreter；外部路径打包后失效 |
| 损坏旧 `.venv` | 删除重建 | `torch/_C.pyd` 已缺失，搬过来也跑不了 |
| `E:\index-tts`（17GB） | 暂时不处理 | Piper 未启用，语音用 pyttsx3 备用引擎；启用 Piper 时再接入 |

---

## 五、打包迁移注意事项

1. 移动目录后先运行 `repair_venv.bat`。
2. `checkpoints/`、`assets/models/` 大模型不要进 Git，打包时单独处理。
3. 目标机器若没有 Ollama 模型，迁移 `E:\.ollama\models` 或重新 `ollama pull`。

---

## 六、已修复的非阻塞日志

- **MCP 初始化超时**：`start_local.bat` 与 `.env` 已默认设置 `AUTO_ENABLE_MCP=false`，不会再因未安装 node MCP 服务器而等待 60 秒超时。
- **软件信息库写入失败**：已执行 `scripts/migrate_software_info_columns.py`，将 `software_info.id` / `user_id` 从 `VARCHAR(64)` 扩展到 `VARCHAR(255)`，GlobalView 扫描注册表不再因字段超长而报错。

## 七、仍存在的可选增强

- **Piper TTS**：`piper` Python 包尚未安装，当前使用 `pyttsx3` 备用引擎。Piper 模型文件已放在 `assets/models/piper/`，需要时可启用。
- **Ollama 模型在外部**：`OLLAMA_MODELS=E:\.ollama\models`，打包迁移时需一并处理。

---

*文档结束。*
