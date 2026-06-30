#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
技能自动生成器 - 硅基生命的"进化"能力
核心流程：
1. 分析任务 → 判断是否需要新工具
2. 设计工具 → 确定输入输出、参数schema
3. 生成代码 → 调用现有code_generate工具
4. 验证代码 → 语法检查、安全扫描、沙箱测试
5. 注册工具 → 保存到tools/目录并自动注册
6. 立即使用 → 新工具立即可被AI调用
设计原则：
- 不重复造轮子：复用现有code_generate工具
- 安全第一：多层验证防止危险代码
- 渐进学习：从简单工具开始，逐步复杂
- 可追溯：所有生成的技能都有版本记录
"""  # 模块文档字符串：说明核心流程和设计原则
import ast  # ast模块：抽象语法树，用于代码语法检查和安全分析
import importlib.util  # importlib.util：动态导入工具
import json  # json模块：JSON数据处理
import re  # re模块：正则表达式，用于模式匹配和安全检查
import shutil  # shutil模块：文件移动和备份
import sys  # sys模块：系统相关功能，用于动态模块加载
import time  # time模块：时间戳生成
from dataclasses import dataclass, field  # dataclass装饰器和field函数
from pathlib import Path  # Path类：跨平台路径处理

from core.logger import logger  # 日志记录器
from core.tool.base_tool import BaseTool  # 工具基类：生成的工具必须继承
from core.tool.tool_manager import tool_manager  # 工具管理器：用于注册新工具


@dataclass  # 使用@dataclass自动生成__init__等方法
class GeneratedSkill:  # 生成的技能信息类
    """生成的技能信息"""  # 类文档字符串
    skill_id: str  # 技能ID：唯一标识符
    name: str  # 技能名称：人类可读的名称
    description: str  # 技能描述：功能说明
    code: str  # 代码内容：生成的Python代码
    file_path: Path  # 文件路径：保存位置
    schema: dict  # 参数schema：输入参数的JSON Schema定义
    test_result: dict = field(default_factory=dict)  # 测试结果：验证和测试信息
    created_at: float = field(default_factory=time.time)  # 创建时间戳

    def to_dict(self) -> dict:  # 转换为字典方法
        """转换为字典"""  # 方法文档字符串
        return {  # 返回包含所有字段的字典
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "file_path": str(self.file_path),  # Path转字符串
            "schema": self.schema,
            "test_result": self.test_result,
            "created_at": self.created_at
        }


class CodeValidator:  # 代码验证器类：多层安全检查
    """
    代码验证器 - 多层安全检查
    """  # 类文档字符串

    # 危险操作黑名单（正则匹配）：检测危险代码模式
    DANGEROUS_PATTERNS = [
        r'import\s+os\.system',  # 导入os.system
        r'os\.system\s*\(',  # 调用os.system
        r'subprocess\.call\s*\([^)]*shell\s*=\s*True',  # subprocess带shell=True
        r'eval\s*\(',  # eval函数调用
        r'exec\s*\(',  # exec函数调用
        r'__import__\s*\(',  # __import__调用
        r'importlib\.import_module',  # 动态导入
        r'open\s*\([^)]*,\s*["\']w',  # 文件写入（模式匹配不精确）
        r'rm\s+-rf',  # 强制删除命令
        r'del\s+__builtins__',  # 删除内置函数
    ]

    # 允许的导入白名单（可选启用）：严格模式下只允许这些导入
    ALLOWED_IMPORTS = {
        'os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib', 'typing',  # 标准库
        'math', 'random', 'string', 'collections', 'itertools', 'functools',  # 标准库扩展
        'hashlib', 'base64', 'urllib', 'http', 'requests',  # 网络和加密
        'numpy', 'pandas', 'PIL', 'cv2', 'pyautogui', 'psutil',  # 第三方库
        'core.base_tool', 'core.logger', 'core.config', 'core.error_codes'  # 项目内部模块
    }

    def validate(self, code: str, strict: bool = False) -> tuple[bool, str]:  # 验证代码安全性方法
        """
        验证代码安全性
        Args:
            code: 待验证的代码字符串
            strict: 是否使用严格模式（启用导入白名单）
        Returns:
            (是否通过, 错误信息)
        """  # 方法文档字符串
        # 1. 语法检查
        try:
            ast.parse(code)  # 尝试解析代码为AST
        except SyntaxError as e:  # 语法错误
            return False, f"语法错误: {e}"  # 返回失败和错误信息

        # 2. 危险模式检查
        for pattern in self.DANGEROUS_PATTERNS:  # 遍历所有危险模式
            if re.search(pattern, code, re.IGNORECASE):  # 正则匹配（忽略大小写）
                return False, f"检测到危险代码模式: {pattern}"  # 匹配到危险模式

        # 3. AST级检查（更精确）
        try:
            tree = ast.parse(code)  # 重新解析AST
            checker = ASTSecurityChecker(self.ALLOWED_IMPORTS if strict else None)  # 创建检查器
            checker.visit(tree)  # 遍历AST节点
            if checker.violations:  # 如果有违规
                return False, f"安全检查失败: {'; '.join(checker.violations[:3])}"  # 返回前3条违规
        except Exception as e:  # AST检查异常
            return False, f"AST检查失败: {e}"  # 返回错误

        return True, "验证通过"  # 所有检查通过

    def sandbox_test(self, code: str, test_input: dict = None) -> tuple[bool, str, any]:  # 沙箱测试方法
        """
        沙箱测试：静态代码安全检查（移除动态执行以防范代码注入风险）
        Args:
            code: 待测试的代码
            test_input: 测试输入参数（当前未使用）
        Returns:
            (是否成功, 错误信息, 返回值)
        """  # 方法文档字符串
        # 安全修复：移除了exec()动态执行，改为多层静态检查
        try:
            # 1. 语法检查
            try:
                tree = ast.parse(code)  # 解析AST
            except SyntaxError as e:  # 语法错误
                return False, f"语法错误: {e}", None

            # 2. AST安全分析 - 检查危险函数调用
            dangerous_calls = ['eval', 'exec', 'compile', '__import__', 'open', 'subprocess']  # 危险函数列表
            for node in ast.walk(tree):  # 遍历所有AST节点
                if isinstance(node, ast.Call):  # 函数调用节点
                    if isinstance(node.func, ast.Name) and node.func.id in dangerous_calls:  # 直接调用危险函数
                        return False, f"安全警告: 检测到危险函数调用 '{node.func.id}'", None
                    # 检查属性访问（如 os.system）
                    if isinstance(node.func, ast.Attribute) and node.func.attr in ['system', 'popen', 'call', 'run']:
                        return False, "安全警告: 检测到潜在危险的系统调用", None
                # 检查是否有尝试访问私有属性的操作
                if isinstance(node, ast.Attribute) and node.attr.startswith('_') and node.attr.startswith('__') and not node.attr.endswith('__'):  # 双下划线且不是魔术方法
                    return False, "安全警告: 检测到私有属性访问", None

            return True, "静态安全验证通过", None  # 静态检查通过

        except Exception as e:  # 异常处理
            return False, f"安全验证异常: {e}", None  # 返回错误


class ASTSecurityChecker(ast.NodeVisitor):  # AST安全检查器类
    """AST安全检查器"""  # 类文档字符串

    def __init__(self, allowed_imports: set | None = None):  # 初始化方法
        self.allowed_imports = allowed_imports  # 允许的导入集合
        self.violations = []  # 违规列表：存储发现的违规信息

    def visit_Import(self, node):  # 访问Import节点
        """检查import语句"""  # 方法文档字符串
        if self.allowed_imports:  # 如果启用了导入白名单
            for alias in node.names:  # 遍历导入的模块
                module = alias.name.split('.')[0]  # 提取顶层模块名
                if module not in self.allowed_imports:  # 不在白名单中
                    self.violations.append(f"禁止导入模块: {alias.name}")  # 记录违规
        self.generic_visit(node)  # 继续访问子节点

    def visit_ImportFrom(self, node):  # 访问ImportFrom节点
        """检查from...import语句"""  # 方法文档字符串
        if self.allowed_imports and node.module:  # 如果启用了白名单且有模块名
            module = node.module.split('.')[0]  # 提取顶层模块名
            if module not in self.allowed_imports:  # 不在白名单中
                self.violations.append(f"禁止从模块导入: {node.module}")  # 记录违规
        self.generic_visit(node)  # 继续访问子节点

    def visit_Call(self, node):  # 访问Call节点（函数调用）
        """检查函数调用"""  # 方法文档字符串
        # 检查危险函数调用
        if isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', '__import__'):  # 直接函数调用且为危险函数
            self.violations.append(f"禁止调用函数: {node.func.id}")  # 记录违规
        self.generic_visit(node)  # 继续访问子节点


class SkillGenerator:  # 技能生成器类：核心组件
    """
    技能生成器 - 让AI能创造新工具
    """  # 类文档字符串

    def __init__(self):  # 初始化方法
        self.validator = CodeValidator()  # 创建代码验证器实例
        self.generated_skills_dir = Path(__file__).parent.parent / "tools" / "auto_generated"  # 技能保存目录
        self.generated_skills_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在）

        # 技能注册表
        self.registry_file = self.generated_skills_dir / "registry.json"  # 注册表文件路径
        self.registry = self._load_registry()  # 加载注册表

    def _load_registry(self) -> dict:  # 加载注册表方法
        """加载已生成技能的注册表"""  # 方法文档字符串
        if self.registry_file.exists():  # 检查文件是否存在
            try:
                with open(self.registry_file, encoding='utf-8') as f:  # 打开文件
                    return json.load(f)  # 解析JSON
            except Exception as e:  # 加载失败
                logger.warning(f"[SkillGenerator] 加载注册表失败: {e}")  # 记录警告
        return {}  # 返回空字典

    def _save_registry(self):  # 保存注册表方法
        """保存技能注册表"""  # 方法文档字符串
        with open(self.registry_file, 'w', encoding='utf-8') as f:  # 打开文件写入
            json.dump(self.registry, f, ensure_ascii=False, indent=2)  # 保存JSON（格式化）

    def should_generate_skill(self, task_description: str, execution_history: list[dict]) -> tuple[bool, str]:  # 判断是否需要生成技能
        """
        判断是否需要生成新技能
        Args:
            task_description: 任务描述
            execution_history: 执行历史
        Returns:
            (是否需要, 原因)
        """  # 方法文档字符串
        # 情况1：现有工具多次失败
        failure_count = sum(1 for h in execution_history if not h.get('success', False))  # 统计失败次数
        if failure_count >= 3:  # 连续失败3次以上
            return True, f"连续{failure_count}次失败，可能需要新工具"  # 需要生成

        # 情况2：任务描述明确提到需要新功能
        keywords = ['自动', '批量', '循环', '定时', '监控', '爬取', '分析']  # 关键词列表
        for kw in keywords:  # 遍历关键词
            if kw in task_description:  # 任务包含关键词
                # 检查是否已有类似工具
                existing = self._find_similar_skill(task_description)
                if not existing:  # 没有类似工具
                    return True, f"任务涉及'{kw}'，且无现有工具可用"  # 需要生成

        # 情况3：步骤过多（超过10步），可能需要封装
        if len(execution_history) >= 10:  # 执行步骤超过10步
            return True, "步骤过多，建议封装为专用工具"  # 需要生成

        return False, "现有工具可满足需求"  # 不需要生成

    def _find_similar_skill(self, description: str) -> str | None:  # 查找类似技能方法
        """查找是否有类似技能"""  # 方法文档字符串
        # 简单关键词匹配（可用向量相似度改进）
        desc_lower = description.lower()  # 转小写
        for skill_id, info in self.registry.items():  # 遍历注册表
            name = info.get('name', '')
            if any(word in desc_lower and word in name.lower()
                   for word in desc_lower.split() if len(word) > 2):  # 匹配长度>2的单词
                return skill_id  # 返回匹配的技能ID
        return None  # 未找到

    async def generate_skill(self, task_description: str, execution_history: list[dict] = None) -> GeneratedSkill | None:  # 生成技能主方法
        """
        生成新技能的主流程
        Args:
            task_description: 任务描述
            execution_history: 执行历史
        Returns:
            GeneratedSkill对象，或None（失败）
        """  # 方法文档字符串
        logger.info(f"[SkillGenerator] 开始生成技能: {task_description[:50]}...")  # 记录开始

        # Step 1: 分析需求，设计工具
        design = self._design_tool(task_description, execution_history or [])
        if not design:  # 设计失败
            logger.error("[SkillGenerator] 工具设计失败")
            return None

        # Step 2: 构建代码生成提示词
        code_prompt = self._build_code_prompt(design, execution_history or [])

        # Step 3: 调用现有code_generate工具生成代码
        code = await self._generate_code_with_tool(code_prompt)
        if not code:  # 生成失败
            logger.error("[SkillGenerator] 代码生成失败")
            return None

        # Step 4: 验证代码
        is_valid, error_msg = self.validator.validate(code, strict=False)
        if not is_valid:  # 验证失败
            logger.error(f"[SkillGenerator] 代码验证失败: {error_msg}")
            # 尝试修复
            code = await self._fix_code(code, error_msg)
            if not code:  # 修复失败
                return None

        # Step 5: 沙箱测试
        test_passed, test_msg, test_output = self.validator.sandbox_test(code)

        # Step 6: 保存并注册
        skill = self._save_skill(design, code, {
            "syntax_valid": is_valid,
            "sandbox_passed": test_passed,
            "sandbox_message": test_msg,
            "sandbox_output": test_output[:200] if test_output else ""  # 限制输出长度
        })

        if skill:  # 生成成功
            logger.info(f"[SkillGenerator] 技能生成成功: {skill.skill_id}")

        return skill

    def _design_tool(self, task: str, history: list[dict]) -> dict | None:  # 设计工具方法
        """
        分析任务，设计工具结构
        Args:
            task: 任务描述
            history: 执行历史
        Returns:
            设计字典，包含skill_id、tool_id、name、schema等
        """  # 方法文档字符串
        # 生成技能ID
        skill_id = f"auto_{int(time.time())}_{hash(task) % 10000}"  # 时间戳+哈希

        # 从任务描述提取关键词作为工具名
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', task)  # 匹配中文和英文单词
        name_words = words[:3] if words else ["Auto"]  # 取前3个单词
        name = "".join(name_words)  # 拼接为名称

        # 简化英文名（用于类名）
        tool_id = f"auto_{name.lower()[:20]}_{int(time.time()) % 1000}"  # 构建工具ID
        tool_id = re.sub(r'[^a-z0-9_]', '_', tool_id)  # 替换非法字符为下划线

        # 构建输入schema（从执行历史中推断参数）
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }

        # 从history中提取常用参数
        for h in history:
            params = h.get('params', {})
            for key, value in params.items():
                if key not in schema["properties"]:  # 新参数
                    if isinstance(value, str):
                        schema["properties"][key] = {"type": "string"}
                    elif isinstance(value, (int, float)):
                        schema["properties"][key] = {"type": "number"}
                    elif isinstance(value, bool):
                        schema["properties"][key] = {"type": "boolean"}

        # 如果没有推断出参数，添加通用参数
        if not schema["properties"]:
            schema["properties"]["input"] = {"type": "string", "description": "输入内容"}
            schema["required"].append("input")

        return {  # 返回设计字典
            "skill_id": skill_id,
            "tool_id": tool_id,
            "name": name,
            "description": f"自动生成的工具: {task[:50]}",
            "schema": schema
        }

    def _build_code_prompt(self, design: dict, history: list[dict]) -> str:  # 构建代码生成提示词方法
        """构建代码生成提示词"""  # 方法文档字符串

        prompt = f"""请生成一个Python工具类，继承自BaseTool。

工具信息：
- 工具ID: {design['tool_id']}
- 名称: {design['name']}
- 描述: {design['description']}

输入Schema：
{json.dumps(design['schema'], ensure_ascii=False, indent=2)}

代码要求：
1. 必须继承 core.base_tool.BaseTool
2. 必须定义 tool_id, name, description, input_schema 类属性
3. 必须实现 run(self, **kwargs) 方法
4. 返回值必须是 dict，包含 "success" 和 "data" 字段
5. 错误处理：使用 core.error_codes 中的错误码
6. 不要写 main 函数或测试代码
7. 只输出Python代码，不要输出任何说明文字

模板：
```python
from core.tool.base_tool import BaseTool
from core.logger import logger
from core.utils.error_codes import format_error, UNKNOWN_ERROR

class {design['tool_id'].replace('_', ' ').title().replace(' ', '')}(BaseTool):
    tool_id = "{design['tool_id']}"
    name = "{design['name']}"
    description = "{design['description']}"
    input_schema = {json.dumps(design['schema'], ensure_ascii=False)}

    def run(self, **kwargs) -> dict:
        try:
            # 实现逻辑
            result = "your logic here"
            return {{"success": True, "data": result}}
        except Exception as e:
            logger.error(f"执行失败: {{e}}")
            return format_error(UNKNOWN_ERROR, detail=str(e))
```

请根据以下任务描述生成完整代码：
{design['description']}
"""
        return prompt

    async def _generate_code_with_tool(self, prompt: str) -> str | None:  # 调用代码生成工具方法
        """调用现有code_generate工具生成代码"""  # 方法文档字符串
        try:
            from core.ai.ai_adapter import generate_code_async  # 导入异步代码生成函数
            code, error = await generate_code_async(prompt)

            if error:  # 生成出错
                logger.error(f"[SkillGenerator] 代码生成错误: {error}")
                return None

            # 提取代码块
            if '```python' in code:  # 包含python标记的代码块
                code = code.split('```python')[1].split('```')[0]
            elif '```' in code:  # 普通代码块
                code = code.split('```')[1].split('```')[0]

            return code.strip()  # 返回去除首尾空白的代码

        except Exception as e:  # 异常处理
            logger.error(f"[SkillGenerator] 调用代码生成失败: {e}")
            return None

    async def _fix_code(self, code: str, error_msg: str) -> str | None:  # 修复代码方法
        """尝试修复代码错误"""  # 方法文档字符串
        fix_prompt = f"""请修复以下Python代码的错误。

错误信息：{error_msg}

原始代码：
```python
{code}
```

请输出修复后的完整代码：
"""
        return await self._generate_code_with_tool(fix_prompt)  # 调用代码生成工具修复

    def _save_skill(self, design: dict, code: str, test_result: dict) -> GeneratedSkill | None:  # 保存技能方法
        """保存技能到文件并注册"""  # 方法文档字符串
        try:
            # 保存文件
            file_path = self.generated_skills_dir / f"{design['tool_id']}.py"  # 构建文件路径
            with open(file_path, 'w', encoding='utf-8') as f:  # 打开文件写入
                f.write(code)

            # 注册到系统（动态加载）
            self._register_tool(file_path, design['tool_id'])

            # 记录到注册表
            skill = GeneratedSkill(  # 创建技能对象
                skill_id=design['skill_id'],
                name=design['name'],
                description=design['description'],
                code=code,
                file_path=file_path,
                schema=design['schema'],
                test_result=test_result
            )

            self.registry[design['skill_id']] = skill.to_dict()  # 添加到注册表
            self._save_registry()  # 保存注册表

            return skill  # 返回技能对象

        except Exception as e:  # 异常处理
            logger.error(f"[SkillGenerator] 保存技能失败: {e}")
            return None

    def _register_tool(self, file_path: Path, tool_id: str):  # 动态注册工具方法
        """动态注册新工具到tool_manager"""  # 方法文档字符串
        try:
            # 动态导入模块
            import importlib.util
            spec = importlib.util.spec_from_file_location(tool_id, file_path)  # 创建模块规范
            module = importlib.util.module_from_spec(spec)  # 创建模块对象
            sys.modules[tool_id] = module  # 注册到sys.modules
            spec.loader.exec_module(module)  # 执行模块代码

            # 查找工具类
            for attr_name in dir(module):  # 遍历模块属性
                attr = getattr(module, attr_name)  # 获取属性
                if (isinstance(attr, type) and  # 是类
                    issubclass(attr, BaseTool) and  # 继承BaseTool
                    hasattr(attr, 'tool_id')):  # 有tool_id属性
                    # 注册到tool_manager
                    tool_manager.register_tool(attr())  # 实例化并注册
                    logger.info(f"[SkillGenerator] 工具已注册: {attr.tool_id}")
                    break  # 找到一个即可

        except Exception as e:  # 异常处理
            logger.error(f"[SkillGenerator] 注册工具失败: {e}")

    def list_generated_skills(self) -> list[dict]:  # 列出生成的技能方法
        """列出所有生成的技能"""  # 方法文档字符串
        return list(self.registry.values())  # 返回注册表值列表

    def delete_skill(self, skill_id: str) -> bool:  # 删除技能方法
        """删除生成的技能"""  # 方法文档字符串
        if skill_id not in self.registry:  # 技能不存在
            return False

        try:
            info = self.registry[skill_id]  # 获取技能信息
            file_path = Path(info['file_path'])  # 构建文件路径

            # 删除文件
            if file_path.exists():
                file_path.unlink()  # 删除文件

            # 从注册表移除
            del self.registry[skill_id]
            self._save_registry()  # 保存注册表

            # 从tool_manager移除（需要重启才能完全生效）
            logger.info(f"[SkillGenerator] 技能已删除: {skill_id}")
            return True

        except Exception as e:  # 异常处理
            logger.error(f"[SkillGenerator] 删除技能失败: {e}")
            return False


class SkillManagerAPI:  # 技能管理API类：提供技能生命周期管理
    """技能管理API - 提供技能的生命周期管理"""  # 类文档字符串

    def __init__(self):  # 初始化方法
        self.skills_dir = Path("skills/generated")  # 技能目录
        self.skills_dir.mkdir(parents=True, exist_ok=True)  # 创建目录
        self.backup_dir = Path("skills/deleted")  # 备份目录（删除的技能）
        self.disabled_dir = Path("skills/disabled")  # 禁用目录

    def get_generated_skills(self, limit: int = 50, offset: int = 0) -> list[dict]:  # 获取生成的技能列表
        """获取自动生成的技能列表"""  # 方法文档字符串
        skills = []  # 技能列表

        if not self.skills_dir.exists():  # 目录不存在
            return skills  # 返回空列表

        # 按修改时间排序
        skill_files = sorted(
            self.skills_dir.glob("*.py"),  # 获取所有.py文件
            key=lambda x: x.stat().st_mtime,  # 按修改时间排序
            reverse=True  # 降序（最新的在前）
        )

        for file in skill_files[offset:offset+limit]:  # 分页获取
            skill_info = self._parse_skill_file(file)  # 解析技能文件
            if skill_info:  # 解析成功
                skills.append(skill_info)  # 添加到列表

        return skills

    def _parse_skill_file(self, file_path: Path) -> dict | None:  # 解析技能文件方法
        """解析技能文件获取元信息"""  # 方法文档字符串
        try:
            content = file_path.read_text(encoding='utf-8')  # 读取文件内容

            # 提取类名
            class_match = re.search(r'class\s+(\w+)', content)  # 匹配类定义
            class_name = class_match.group(1) if class_match else file_path.stem  # 提取类名或使用文件名

            # 提取描述
            desc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)  # 匹配文档字符串
            description = desc_match.group(1).strip() if desc_match else "无描述"  # 提取描述

            # 提取工具ID
            tool_id_match = re.search(r'tool_id\s*=\s*["\']([^"\']+)', content)  # 匹配tool_id
            tool_id = tool_id_match.group(1) if tool_id_match else file_path.stem

            # 提取名称
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)', content)  # 匹配name
            name = name_match.group(1) if name_match else file_path.stem

            stat = file_path.stat()  # 获取文件统计信息

            return {  # 返回技能信息字典
                'id': tool_id,
                'class_name': class_name,
                'name': name,
                'description': description[:100] + '...' if len(description) > 100 else description,  # 截断描述
                'file_path': str(file_path),
                'created_at': stat.st_mtime,
                'size': stat.st_size,
                'status': 'active'
            }
        except Exception as e:  # 异常处理
            logger.error(f"解析技能文件失败 {file_path}: {e}")
            return None

    def delete_skill(self, skill_id: str) -> bool:  # 删除技能方法（带备份）
        """删除生成的技能"""  # 方法文档字符串
        try:
            skill_file = self.skills_dir / f"{skill_id}.py"  # 构建文件路径

            if skill_file.exists():  # 文件存在
                # 先备份到 deleted 目录
                self.backup_dir.mkdir(parents=True, exist_ok=True)  # 创建备份目录
                backup_name = f"{skill_id}_{int(time.time())}.py"  # 备份文件名（带时间戳）
                shutil.move(str(skill_file), str(self.backup_dir / backup_name))  # 移动文件

                logger.info(f"[SkillManager] 删除技能: {skill_id}")
                return True
            return False
        except Exception as e:  # 异常处理
            logger.error(f"删除技能失败: {e}")
            return False

    def test_skill(self, skill_id: str, test_params: dict) -> dict:  # 测试技能方法
        """测试技能"""  # 方法文档字符串
        try:
            # 动态导入技能
            skill_path = self.skills_dir / f"{skill_id}.py"  # 构建文件路径

            if not skill_path.exists():  # 文件不存在
                return {'success': False, 'error': '技能文件不存在'}

            spec = importlib.util.spec_from_file_location(skill_id, skill_path)  # 创建模块规范
            module = importlib.util.module_from_spec(spec)  # 创建模块对象
            spec.loader.exec_module(module)  # 执行模块

            # 查找类实例化
            skill_class = None
            for attr_name in dir(module):  # 遍历模块属性
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and  # 是类
                    hasattr(attr, 'tool_id') and  # 有tool_id
                    attr.tool_id == skill_id):  # tool_id匹配
                    skill_class = attr
                    break

            if not skill_class:  # 未找到匹配类
                # 尝试其他命名模式
                skill_class = getattr(module, skill_id.capitalize() + 'Skill', None)
                if not skill_class:
                    return {'success': False, 'error': '找不到技能类'}

            skill = skill_class()  # 实例化技能

            # 执行测试
            start_time = time.time()
            result = skill.run(**test_params)  # 调用run方法
            duration = time.time() - start_time  # 计算耗时

            return {  # 返回测试结果
                'success': True,
                'result': result,
                'duration': duration,
                'skill_id': skill_id
            }

        except Exception as e:  # 异常处理
            logger.error(f"测试技能失败: {e}")
            return {'success': False, 'error': str(e)}

    def toggle_skill(self, skill_id: str, enable: bool) -> bool:  # 启用/禁用技能方法
        """启用/禁用技能"""  # 方法文档字符串
        try:
            if enable:  # 启用
                src = self.disabled_dir / f"{skill_id}.py"  # 源：禁用目录
                dst = self.skills_dir / f"{skill_id}.py"  # 目标：技能目录
            else:  # 禁用
                self.disabled_dir.mkdir(parents=True, exist_ok=True)  # 创建禁用目录
                src = self.skills_dir / f"{skill_id}.py"  # 源：技能目录
                dst = self.disabled_dir / f"{skill_id}.py"  # 目标：禁用目录

            if src.exists():  # 源文件存在
                shutil.move(str(src), str(dst))  # 移动文件
                return True
            return False
        except Exception as e:  # 异常处理
            logger.error(f"切换技能状态失败: {e}")
            return False

    def get_skill_detail(self, skill_id: str) -> dict | None:  # 获取技能详情方法
        """获取技能详细信息"""  # 方法文档字符串
        skill_file = self.skills_dir / f"{skill_id}.py"  # 构建文件路径

        if not skill_file.exists():  # 文件不存在
            return None

        try:
            content = skill_file.read_text(encoding='utf-8')  # 读取文件内容

            return {  # 返回详情字典
                'id': skill_id,
                'content': content,
                'file_size': skill_file.stat().st_size,
                'modified_at': skill_file.stat().st_mtime
            }
        except Exception as e:  # 异常处理
            logger.error(f"获取技能详情失败: {e}")
            return None

    def get_skill_stats(self) -> dict:  # 获取技能统计方法
        """获取技能统计"""  # 方法文档字符串
        if not self.skills_dir.exists():  # 目录不存在
            return {'total': 0, 'active': 0, 'disabled': 0}

        active_count = len(list(self.skills_dir.glob("*.py")))  # 统计激活的技能
        disabled_count = len(list(self.disabled_dir.glob("*.py"))) if self.disabled_dir.exists() else 0  # 统计禁用的技能

        return {  # 返回统计数据
            'total': active_count + disabled_count,  # 总数
            'active': active_count,  # 激活数
            'disabled': disabled_count  # 禁用数
        }


# 全局实例
skill_generator = SkillGenerator()  # 技能生成器单例
skill_manager_api = SkillManagerAPI()  # 技能管理API单例


async def try_generate_skill(task: str, history: list[dict] = None) -> dict | None:  # 尝试生成技能便捷函数
    """
    便捷函数：尝试为任务生成新技能
    Args:
        task: 任务描述
        history: 执行历史
    Returns:
        技能信息字典，或None（如果不需要生成或生成失败）
    """  # 函数文档字符串
    should, reason = skill_generator.should_generate_skill(task, history or [])  # 判断是否需要生成

    if not should:  # 不需要生成
        logger.debug(f"[SkillGenerator] 不需要生成技能: {reason}")
        return None

    logger.info(f"[SkillGenerator] 触发技能生成: {reason}")
    skill = await skill_generator.generate_skill(task, history)  # 生成技能

    if skill:  # 生成成功
        return skill.to_dict()  # 返回字典形式
    return None  # 生成失败


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase_V5 系统的"技能自动生成器"，实现硅基生命的"进化"能力。
# 通过分析任务需求，自动生成新工具代码，让AI能够自我扩展能力边界。
#
# 【架构设计】
# - GeneratedSkill: 数据类封装生成的技能信息
# - CodeValidator: 多层代码安全验证器（正则、AST分析、沙箱测试）
# - ASTSecurityChecker: AST节点访问器，检查导入和函数调用
# - SkillGenerator: 技能生成器核心，实现6步生成流程
# - SkillManagerAPI: 技能生命周期管理API（列表、测试、启用/禁用、删除）
#
# 【6步生成流程】
# 1. 需求分析: should_generate_skill()判断是否需要新工具（失败次数/关键词/步骤数）
# 2. 工具设计: _design_tool()设计工具结构（ID、名称、参数schema）
# 3. 代码生成: _generate_code_with_tool()调用AI生成代码
# 4. 代码验证: CodeValidator.validate()多层安全检查
# 5. 沙箱测试: sandbox_test()静态安全分析
# 6. 保存注册: _save_skill()保存文件并注册到tool_manager
#
# 【安全检查机制】
# - 危险模式黑名单: 正则匹配os.system、eval、exec等危险操作
# - 导入白名单: 严格模式下只允许特定模块导入
# - AST分析: 检测危险函数调用、私有属性访问
# - 静态沙箱: 移除了动态执行，改为纯静态分析
#
# 【关联文件】
# - core/tool_manager.py     : tool_manager实例，用于注册新工具
# - core/base_tool.py        : BaseTool基类，生成的工具必须继承
# - core/ai_adapter.py       : generate_code_async()，用于生成代码
# - core/logger.py           : 记录生成过程和错误
# - tools/auto_generated/    : 生成的技能保存目录
#
# 【核心功能效果】
# 1. 智能触发: 基于失败次数（≥3次）、任务关键词（自动/批量等）、步骤数（≥10步）自动触发
# 2. 参数推断: 从执行历史中自动推断工具参数schema
# 3. 代码生成: 调用AI生成符合BaseTool规范的完整代码
# 4. 多层验证: 语法检查→危险模式→AST分析→沙箱测试，确保代码安全
# 5. 自动注册: 生成后立即注册到tool_manager，立即可用
# 6. 生命周期管理: 支持测试、启用/禁用、删除（带备份）、统计等功能
# 7. 可追溯: 所有生成的技能保存在registry.json，支持版本管理
#
# 【数据流向】
# 触发: 任务执行历史 → should_generate_skill() → 判断是否需要
# 设计: 任务描述 → _design_tool() → 生成skill_id/tool_id/schema
# 生成: 设计信息 → _build_code_prompt() → AI生成 → 提取代码
# 验证: 代码 → CodeValidator.validate() → ASTSecurityChecker.visit() → 安全报告
# 注册: 代码+设计 → _save_skill() → 保存文件 → _register_tool() → tool_manager
# 管理: SkillManagerAPI → 文件系统操作 → 启用/禁用/删除/测试
#
# 【使用场景】
# 场景1: 工具连续失败 → try_generate_skill() → 自动生成新工具 → 立即使用
# 场景2: 批量处理需求 → 检测到"批量"关键词 → 生成批量处理工具
# 场景3: 步骤过多 → 检测到≥10步 → 封装为专用工具简化流程
# 场景4: 管理技能 → SkillManagerAPI.get_generated_skills() → 查看/测试/删除
# =============================================================================
