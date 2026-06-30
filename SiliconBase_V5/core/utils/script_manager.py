#!/usr/bin/env python3
"""
脚本管理器 - AI生成/修改脚本（含安全检查）
修复版：AST 检查加固，禁止所有危险操作
2026-02-15 修复：增强AST检查器，全量拦截危险操作
2026-02-16 修复：使用统一AST安全检查器
"""
import importlib.util
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from core.ai.ai_adapter import call_thinker
from core.logger import logger
from core.safety.ast_security_checker import check_code_safety
from core.utils.file_utils import read_json, write_json

BASE_DIR = Path(__file__).parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
GENERATED_DIR = SCRIPTS_DIR / "generated"
BACKUP_DIR = SCRIPTS_DIR / "backups"
REGISTRY_FILE = SCRIPTS_DIR / "registry.json"


@dataclass
class ScriptInfo:
    name: str
    type: str
    path: str
    description: str
    version: str = "1.0.0"
    created_at: str = ""
    updated_at: str = ""
    auto_generated: bool = False
    call_count: int = 0


class ScriptManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:

                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if '_initialized' not in self.__dict__:
            self._initialized = True
            self.scripts: dict[str, ScriptInfo] = {}
            self._ensure_dirs()
            self._load_registry()
            self._discover_scripts()

    def _ensure_dirs(self):
        for d in [SCRIPTS_DIR, GENERATED_DIR, BACKUP_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_registry(self):
        if REGISTRY_FILE.exists():
            try:
                data = read_json(REGISTRY_FILE)
                for name, info in data.items():
                    self.scripts[name] = ScriptInfo(**info)
            except Exception as e:
                logger.error(f"加载注册表失败: {e}")

    def _save_registry(self):
        try:
            data = {name: asdict(info) for name, info in self.scripts.items()}
            write_json(REGISTRY_FILE, data, indent=2)
        except Exception as e:
            logger.error(f"保存注册表失败: {e}")

    def _discover_scripts(self):
        for py_file in GENERATED_DIR.glob("*.py"):
            if py_file.stem not in self.scripts:
                self.scripts[py_file.stem] = ScriptInfo(
                    name=py_file.stem,
                    type="generated",
                    path=str(py_file),
                    description="自动发现脚本",
                    auto_generated=True
                )
        self._save_registry()

    def _check_code_safety(self, code: str) -> bool:
        """静态检查代码是否包含危险操作（使用统一安全检查器）"""
        is_safe, reason = check_code_safety(code)
        if not is_safe:
            logger.warning(f"危险代码被拒绝: {reason}")
            return False
        return True

    def generate_script(self, requirement: str, script_type: str = "generated") -> dict:
        prompt = f"""生成一个Python脚本，功能：{requirement}
要求：
- 包含 run(params=None) 函数作为入口，返回字典 {{"success": True, "data": ...}}
- 仅输出代码，不要解释。
- 禁止使用 os.system, subprocess 等危险操作。
"""
        code = call_thinker([{"role": "user", "content": prompt}])
        if not code:
            return {"success": False, "error": "AI返回空"}
        import re
        match = re.search(r'```python\n(.*?)\n```', code, re.DOTALL)
        if match:
            code = match.group(1)

        if not self._check_code_safety(code):
            return {"success": False, "error": "生成的代码包含危险操作，已拒绝"}

        script_name = f"auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        script_path = GENERATED_DIR / f"{script_name}.py"
        script_path.write_text(code, encoding="utf-8")
        self.scripts[script_name] = ScriptInfo(
            name=script_name,
            type=script_type,
            path=str(script_path),
            description=requirement[:100],
            auto_generated=True
        )
        self._save_registry()
        logger.info(f"脚本生成成功: {script_name}")
        return {"success": True, "script_name": script_name, "path": str(script_path)}

    def modify_script(self, script_name: str, modification: str) -> dict:
        if script_name not in self.scripts:
            return {"success": False, "error": "脚本不存在"}
        script_info = self.scripts[script_name]
        script_path = Path(script_info.path)
        if not script_path.exists():
            return {"success": False, "error": "文件丢失"}
        old_code = script_path.read_text(encoding="utf-8")
        backup = BACKUP_DIR / f"{script_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.py"
        shutil.copy2(script_path, backup)
        prompt = f"""修改以下Python脚本：{modification}\n原始代码：\n{old_code}\n输出修改后的完整代码。"""
        new_code = call_thinker([{"role": "user", "content": prompt}])
        if not new_code:
            return {"success": False, "error": "AI返回空"}
        if not self._check_code_safety(new_code):
            return {"success": False, "error": "修改后的代码包含危险操作，已拒绝"}

        script_path.write_text(new_code, encoding="utf-8")
        script_info.updated_at = datetime.now().isoformat()
        self._save_registry()
        logger.info(f"脚本修改成功: {script_name}")
        return {"success": True, "backup": str(backup)}

    def execute_script(self, script_name: str, params: dict = None) -> dict:
        if script_name not in self.scripts:
            return {"success": False, "error": "脚本不存在"}
        script_info = self.scripts[script_name]
        script_path = Path(script_info.path)
        if not script_path.exists():
            return {"success": False, "error": "文件丢失"}
        try:
            spec = importlib.util.spec_from_file_location(script_name, script_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, 'run'):
                result = module.run(params)
                script_info.call_count += 1
                self._save_registry()
                return {"success": True, "result": result}
            else:
                return {"success": False, "error": "脚本缺少 run 函数"}
        except Exception as e:
            logger.error(f"执行脚本失败: {e}")
            return {"success": False, "error": str(e)}

    def list_scripts(self) -> list[ScriptInfo]:
        return list(self.scripts.values())


def get_script_manager() -> ScriptManager:
    return ScriptManager()
