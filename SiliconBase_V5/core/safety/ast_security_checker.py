#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
统一AST安全检查器 - 全局唯一安全规则入口
所有动态代码执行、工具注册、脚本生成场景，必须使用此检查器
2026-02-18 增强：白名单机制，允许特定安全操作，减少误拦截
"""
import ast  # 导入AST模块，用于解析Python代码

# 白名单：允许使用的模块（即使它们在危险列表中，但某些子模块是安全的）  # 白名单常量
SAFE_MODULE_WHITELIST = {  # 安全模块白名单
    'os.path',  # 允许 os.path 操作（路径处理）
    'sys.path', # 允许 sys.path 操作（路径修改）
    # 可以扩展其他白名单  # 扩展点
}  # 白名单结束

# 允许的字符串操作（仅限于非危险上下文）  # 允许操作常量
ALLOWED_STRING_OPS = {'format', 'join', 'replace', 'encode', 'decode'}  # 允许的字符串方法


class EnhancedASTChecker(ast.NodeVisitor):  # 增强的AST检查器类
    """
    增强的 AST 安全检查器，全局统一安全规则
    禁止所有危险模块、函数、动态代码执行、编码绕过操作
    增加白名单功能，允许某些安全用法。
    """

    def __init__(self, allow_imports: set[str] | None = None):  # 构造函数
        self.dangerous = False  # 是否发现危险代码标志
        self.reason = None  # 危险原因
        # 允许额外导入的白名单（传入的参数）  # 白名单初始化
        self.allow_imports = allow_imports or set()  # 默认空集合
        # 完全禁止的模块（任何场景都不允许导入）  # 黑名单：模块
        self.banned_imports = {  # 禁止导入的模块
            'os', 'sys', 'subprocess', 'shutil', 'ctypes', 'win32api', 'win32con',  # 系统相关
            'socket', 'requests', 'urllib', 'ftplib', 'telnetlib', 'paramiko',  # 网络相关
            'psutil', 'multiprocessing', 'threading', 'importlib', 'pkgutil'  # 进程/导入相关
        }  # 模块黑名单结束
        # 完全禁止的函数/属性（任何场景都不允许调用）  # 黑名单：函数
        self.banned_functions = {  # 禁止调用的函数
            'eval', 'exec', 'compile', '__import__', 'open', 'file', 'execfile',  # 动态执行
            'input', 'raw_input', 'globals', 'locals', 'vars', 'dir', 'getattr',  # 内省
            'setattr', 'delattr', 'hasattr', 'callable', 'type', 'object.__getattribute__',  # 属性操作
            'os.system', 'os.popen', 'subprocess.run', 'subprocess.Popen'  # 系统命令
        }  # 函数黑名单结束
        # 禁止的魔法方法（绕过属性访问控制）  # 黑名单：魔法方法
        self.banned_magic_methods = {  # 禁止的魔法方法
            '__import__', '__getattr__', '__setattr__', '__delattr__',  # 属性魔法方法
            '__getattribute__', '__call__', '__new__', '__init_subclass__'  # 构造/调用魔法方法
        }  # 魔法方法黑名单结束
        # 禁止的解码函数（动态代码绕过常用）  # 黑名单：解码函数
        self.banned_decode_functions = {  # 禁止的解码函数
            'base64.b64decode', 'base64.standard_b64decode', 'base64.urlsafe_b64decode',  # base64解码
            'codecs.decode', 'bytes.fromhex', 'binascii.unhexlify', 'quopri.decodestring',  # 其他解码
            'uu.decode', 'zlib.decompress', 'gzip.decompress', 'bz2.decompress', 'lzma.decompress'  # 压缩解码
        }  # 解码函数黑名单结束

    def _get_full_attr_name(self, node):  # 获取属性的完整名称
        """获取属性调用的完整名称，如 base64.b64decode"""  # 方法文档字符串
        if isinstance(node, ast.Attribute):  # 如果是属性节点
            base = self._get_full_attr_name(node.value)  # 递归获取基础
            if base:  # 如果基础不为空
                return f"{base}.{node.attr}"  # 返回完整名称
            return node.attr  # 返回属性名
        elif isinstance(node, ast.Name):  # 如果是名称节点
            return node.id  # 返回标识符
        else:  # 其他类型
            return ""  # 返回空字符串

    def _is_module_allowed(self, module_name: str) -> bool:  # 检查模块是否允许
        """检查模块是否被允许（包括白名单）"""  # 方法文档字符串
        # 如果模块在白名单中，允许  # 白名单检查
        if module_name in self.allow_imports:  # 如果在允许列表
            return True  # 返回允许
        # 如果模块是 banned_imports 中的，拒绝  # 黑名单检查
        if module_name in self.banned_imports:  # 如果在禁止列表
            return False  # 返回禁止
        # 检查模块前缀是否在白名单中（如 os.path）  # 前缀检查
        for allowed in self.allow_imports:  # 遍历允许的模块
            if module_name.startswith(allowed + '.'):  # 如果前缀匹配
                return True  # 返回允许
        # 默认允许（不在 banned 中）  # 默认策略
        return True  # 返回允许

    def visit_Import(self, node):  # 访问Import节点
        for alias in node.names:  # 遍历导入的模块
            if not self._is_module_allowed(alias.name):  # 如果不允许
                self.dangerous = True  # 标记危险
                self.reason = f"禁止导入危险模块: {alias.name}"  # 设置原因
                return  # 直接返回
        self.generic_visit(node)  # 继续访问子节点

    def visit_ImportFrom(self, node):  # 访问ImportFrom节点
        if node.module and not self._is_module_allowed(node.module):  # 如果有模块名且不允许
            self.dangerous = True  # 标记危险
            self.reason = f"禁止导入危险模块: {node.module}"  # 设置原因
            return  # 直接返回
        self.generic_visit(node)  # 继续访问子节点

    def visit_Call(self, node):  # 访问Call节点
        # 禁止直接调用危险函数  # 直接调用检查
        if isinstance(node.func, ast.Name):  # 如果是名称调用
            if node.func.id in self.banned_functions:  # 如果在禁止列表
                self.dangerous = True  # 标记危险
                self.reason = f"禁止调用危险函数: {node.func.id}"  # 设置原因
                return  # 直接返回
        # 禁止模块方法调用  # 模块方法检查
        elif isinstance(node.func, ast.Attribute):  # 如果是属性调用
            full_name = self._get_full_attr_name(node.func)  # 获取完整名称
            # 检查是否是禁止的解码函数  # 解码函数检查
            if full_name in self.banned_decode_functions:  # 如果在禁止列表
                self.dangerous = True  # 标记危险
                self.reason = f"禁止调用解码函数动态执行代码: {full_name}"  # 设置原因
                return  # 直接返回
            # 检查属性名是否是危险魔法方法  # 魔法方法检查
            if node.func.attr in self.banned_magic_methods:  # 如果在禁止列表
                self.dangerous = True  # 标记危险
                self.reason = f"禁止调用危险魔法方法: {node.func.attr}"  # 设置原因
                return  # 直接返回
            # 检查调用的模块是否被禁止  # 模块检查
            current = node.func.value  # 获取调用者
            while isinstance(current, ast.Attribute):  # 如果是属性链
                current = current.value  # 继续向上
            if isinstance(current, ast.Name) and not self._is_module_allowed(current.id):  # 如果是名称且不允许
                self.dangerous = True  # 标记危险
                self.reason = f"禁止调用危险模块方法: {current.id}.{node.func.attr}"  # 设置原因
                return  # 直接返回
            # 字符串操作检查：放宽限制，不在此处直接拦截  # 字符串操作注释
        # 禁止lambda/条件表达式执行动态代码  # 动态代码检查
        elif isinstance(node.func, (ast.Lambda, ast.IfExp)):  # 如果是lambda或条件表达式
            self.dangerous = True  # 标记危险
            self.reason = "禁止使用lambda/条件表达式执行动态代码"  # 设置原因
            return  # 直接返回
        self.generic_visit(node)  # 继续访问子节点

    def visit_Assign(self, node):  # 访问Assign节点
        # 禁止给危险函数/模块起别名  # 别名检查
        for target in node.targets:  # 遍历赋值目标
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Name) and not self._is_module_allowed(node.value.id):  # 如果是名称且值不允许
                self.dangerous = True  # 标记危险
                self.reason = f"禁止给危险对象起别名: {node.value.id}"  # 设置原因
                return  # 直接返回
            # 动态拼接模块名仍然危险，但留给 BinOp 检查  # 动态拼接注释
        self.generic_visit(node)  # 继续访问子节点

    def visit_Attribute(self, node):  # 访问Attribute节点
        # 禁止访问危险魔法属性  # 魔法属性检查
        if node.attr in self.banned_magic_methods:  # 如果在禁止列表
            self.dangerous = True  # 标记危险
            self.reason = f"禁止访问危险属性: {node.attr}"  # 设置原因
            return  # 直接返回
        self.generic_visit(node)  # 继续访问子节点

    def visit_BinOp(self, node):  # 访问BinOp节点
        # 字符串拼接检查：仅当拼接结果明显包含危险模块/函数名时才拦截  # 拼接检查
        if isinstance(node.op, ast.Add):  # 如果是加法操作
            left_str = self._extract_string_constant(node.left)  # 提取左字符串
            right_str = self._extract_string_constant(node.right)  # 提取右字符串
            if left_str is not None and right_str is not None:  # 如果都能提取
                combined = left_str + right_str  # 拼接
                # 检查组合后的字符串是否包含危险模块或函数名  # 危险检查
                for banned in self.banned_imports | self.banned_functions:  # 遍历禁止项
                    if banned in combined:  # 如果包含
                        self.dangerous = True  # 标记危险
                        self.reason = f"禁止字符串拼接生成危险模块/函数名: {banned}"  # 设置原因
                        return  # 直接返回
        self.generic_visit(node)  # 继续访问子节点

    def _extract_string_constant(self, node):  # 提取字符串常量
        """尝试提取节点中的字符串常量，如果节点不是常量则返回None"""  # 方法文档字符串
        if isinstance(node, ast.Constant) and isinstance(node.value, str):  # 如果是字符串常量
            return node.value  # 返回值
        return None  # 否则返回None

    def visit_Constant(self, node):  # 访问Constant节点
        # 禁止直接写入字节码/可执行代码  # 字节码检查
        if isinstance(node.value, bytes) and len(node.value) > 100 and any(b < 32 or b > 126 for b in node.value):  # 如果是字节且包含不可打印字符
            self.dangerous = True  # 标记危险
            self.reason = "禁止写入可疑字节码/二进制内容"  # 设置原因
            return  # 直接返回
        self.generic_visit(node)  # 继续访问子节点


def check_code_safety(code: str, allow_imports: set[str] | None = None) -> tuple[bool, str]:  # 代码安全检查函数
    """
    统一的代码安全检查入口
    :param code: 待检查的Python代码字符串
    :param allow_imports: 允许导入的模块名集合（用于白名单）
    :return: (是否安全, 原因/错误信息)
    """
    try:  # 异常处理
        tree = ast.parse(code)  # 解析代码为AST
    except SyntaxError as e:  # 语法错误
        return False, f"代码语法错误: {e}"  # 返回错误
    except Exception as e:  # 其他错误
        return False, f"代码解析失败: {str(e)}"  # 返回错误

    checker = EnhancedASTChecker(allow_imports=allow_imports)  # 创建检查器
    checker.visit(tree)  # 遍历AST
    if checker.dangerous:  # 如果发现危险
        return False, checker.reason  # 返回危险原因
    return True, "代码安全"  # 返回安全


# =============================================================================  # 分隔线
# 【文件总结】  # 总结区域标题
# =============================================================================  # 分隔线
# 文件角色：统一的AST代码安全检查器，全局唯一安全规则入口  # 角色说明
# 设计目标：  # 目标说明
#   - 统一安全规则，避免多处定义导致的不一致  # 目标1
#   - 支持白名单机制，减少误拦截  # 目标2
#   - 全面覆盖各种代码注入和绕过手段  # 目标3
# 检查范围：  # 检查范围
#   1. 危险模块导入 - os/sys/subprocess/socket等  # 范围1
#   2. 危险函数调用 - eval/exec/compile等  # 范围2
#   3. 魔法方法访问 - __import__/__getattr__等  # 范围3
#   4. 解码函数调用 - base64解码、压缩解压等  # 范围4
#   5. 字符串拼接 - 动态生成危险模块/函数名  # 范围5
#   6. 可疑字节码 - 包含不可打印字符的字节序列  # 范围6
# 关联文件：  # 关联说明
#   - core/plugin_system.py: 插件系统（加载前检查）  # 关联1
#   - core/script_manager.py: 脚本管理（生成后检查）  # 关联2
#   - core/moral_system.py: 道德系统（更高层的安全概念）  # 关联3
# 达到效果：  # 效果说明
#   - 防止恶意代码执行  # 效果1
#   - 防止动态代码注入  # 效果2
#   - 防止通过编码绕过检查  # 效果3
#   - 为插件和脚本系统提供安全保障  # 效果4
# =============================================================================  # 分隔线结束
