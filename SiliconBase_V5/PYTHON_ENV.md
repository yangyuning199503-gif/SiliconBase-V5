# Python 环境说明

本项目使用自包含的 Python 环境，所有依赖都在项目目录内。

## 项目内环境位置

| 用途 | 路径 |
|---|---|
| Python 解释器 | `.python/cpython-3.10-windows-x86_64-none/python.exe` |
| 虚拟环境 | `.venv/Scripts/python.exe` |
| 包管理 | `uv`（全局工具） |

## 快速使用

### Windows 命令行（CMD / PowerShell）

在项目根目录 `SiliconBase_V5\SiliconBase_V5\` 下：

```bash
# 使用项目内 Python
python.bat --version

# 使用项目内 pip
pip.bat list

# 或直接激活虚拟环境
.venv\Scripts\activate
python --version
```

### 使用 uv（推荐）

```bash
# 自动使用项目内 .venv
uv run python --version

# 安装依赖
uv pip install -r requirements.txt

# 重新创建虚拟环境
uv venv .venv --python 3.10
```

## 换电脑 / 重新搭建环境

### 方案 A：同平台 Windows（最快）

直接复制整个项目文件夹，包含 `.python` 和 `.venv`：

```
SiliconBase_V5/
├── .python/
├── .venv/
├── pyproject.toml
└── requirements.txt
```

在新电脑上解压后，运行 `python.bat --version` 即可验证。

### 方案 B：跨平台 / 干净重建

1. 安装 `uv`：
   ```bash
   # Windows
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

2. 进入项目目录：
   ```bash
   cd SiliconBase_V5/SiliconBase_V5
   ```

3. 下载 Python 并创建虚拟环境：
   ```bash
   uv venv .venv --python 3.10
   ```

4. 安装依赖：
   ```bash
   uv pip install -r requirements.txt
   ```

5. 验证：
   ```bash
   uv run python --version
   ```

## PyCharm 配置

```
File → Settings → Project → Python Interpreter
→ Add Interpreter → Add Local Interpreter
→ Existing
→ 选择：SiliconBase_V5/SiliconBase_V5/.venv/Scripts/python.exe
```

## 注意事项

- `.python` 目录下的解释器是 **Windows x86_64 专用**，不能跨操作系统使用。
- 如需跨平台，请使用方案 B 在新系统上重建环境。
- 不要随意删除 `.python-version` 文件，它告诉 uv 使用哪个 Python 版本。
