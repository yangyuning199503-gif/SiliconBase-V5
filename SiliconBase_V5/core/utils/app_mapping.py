#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""
应用映射管理器 - 维护常用应用信息，支持别名、URL、搜索模板
"""
import json  # 导入JSON模块，用于序列化和反序列化数据
import os  # 导入操作系统模块，用于文件路径操作


class AppMapping:  # 定义应用映射数据类，存储单个应用的信息
    def __init__(self, name: str, app_path: str = "", urls: list[str] = None,  # 初始化方法，定义应用名称、可执行路径、URL列表
                 aliases: list[str] = None, category: str = "other",  # 别名列表、应用分类
                 search_url: str = "", win_path: str = ""):  # 搜索URL模板、Windows路径
        self.name = name  # 应用名称（主键）
        self.app_path = app_path or win_path  # 应用可执行文件路径，优先使用app_path，否则使用win_path
        self.urls = urls or []  # URL列表，默认为空列表
        self.aliases = aliases or []  # 别名列表，默认为空列表
        self.category = category  # 应用分类（search/video/music/social/system/other）
        self.search_url = search_url  # 搜索URL模板，含{keyword}占位符
        self.win_path = win_path  # Windows系统下的路径


class AppMappingManager:  # 应用映射管理器类，管理所有应用映射
    """应用映射管理器，可加载内置和自定义映射"""  # 类文档字符串

    DEFAULT_MAPPINGS = {  # 类级常量：内置默认应用映射字典
        "百度": AppMapping("百度", urls=["https://www.baidu.com"],  # 百度搜索引擎
                           search_url="https://www.baidu.com/s?wd={keyword}",  # 百度搜索URL模板
                           aliases=["baidu", "度娘", "百度一下", "bd"], category="search"),  # 别名和分类
        "谷歌": AppMapping("谷歌", urls=["https://www.google.com"],  # Google搜索引擎
                           search_url="https://www.google.com/search?q={keyword}",  # Google搜索URL模板
                           aliases=["google", "咕果", "gg"], category="search"),  # 别名和分类
        "B站": AppMapping("B站", urls=["https://www.bilibili.com"],  # 哔哩哔哩视频平台
                          search_url="https://search.bilibili.com/all?keyword={keyword}",  # B站搜索URL模板
                          aliases=["bilibili", "哔哩哔哩", "小破站", "b站"], category="video"),  # 别名和分类
        # 新增应用
        "网易云音乐": AppMapping("网易云音乐", app_path="cloudmusic.exe",  # 网易云音乐客户端
                              urls=["https://music.163.com"],  # 网易云音乐网址
                              search_url="https://music.163.com/#/search/m/?s={keyword}",  # 搜索URL模板
                              aliases=["网易云", "云音乐", "netease"], category="music"),  # 别名和分类
        "微信": AppMapping("微信", app_path="wechat.exe",  # 微信客户端
                         urls=["https://wx.qq.com"],  # 微信网页版
                         aliases=["wechat", "vx"], category="social"),  # 别名和分类
        "QQ": AppMapping("QQ", app_path="qq.exe",  # QQ客户端
                        urls=["https://im.qq.com"],  # QQ官网
                        aliases=["qq", "tencent"], category="social"),  # 别名和分类
        "记事本": AppMapping("记事本", app_path="notepad.exe",  # Windows记事本
                         aliases=["notepad", "文本编辑器"], category="system"),  # 别名和分类
        "计算器": AppMapping("计算器", app_path="calc.exe",  # Windows计算器
                         aliases=["calculator"], category="system"),  # 别名和分类
        "任务管理器": AppMapping("任务管理器", app_path="taskmgr.exe",  # Windows任务管理器
                           aliases=["task manager", "进程管理器"], category="system"),  # 别名和分类
        "命令行": AppMapping("命令行", app_path="cmd.exe",  # Windows命令提示符
                         aliases=["cmd", "命令提示符"], category="system"),  # 别名和分类
        "画图": AppMapping("画图", app_path="mspaint.exe",  # Windows画图程序
                        aliases=["paint"], category="system"),  # 别名和分类
    }

    def __init__(self, custom_file: str = None):  # 初始化方法，可选传入自定义映射文件路径
        self.mappings: dict[str, AppMapping] = {}  # 存储所有应用映射的字典
        self._alias_to_name: dict[str, str] = {}  # 别名到应用名称的索引字典，用于快速查找
        self._load_default_mappings()  # 加载内置默认映射
        if custom_file and os.path.exists(custom_file):  # 如果提供了自定义文件且存在
            self._load_custom_mappings(custom_file)  # 加载自定义映射

    def _load_default_mappings(self):  # 私有方法：加载内置默认映射
        self.mappings = self.DEFAULT_MAPPINGS.copy()  # 复制默认映射到实例
        self._rebuild_alias_index()  # 重建别名索引

    def _rebuild_alias_index(self):  # 私有方法：重建别名索引
        self._alias_to_name = {}  # 清空索引
        for name, mapping in self.mappings.items():  # 遍历所有映射
            self._alias_to_name[name.lower()] = name  # 应用名称本身也作为别名（小写）
            for alias in mapping.aliases:  # 遍历每个别名
                self._alias_to_name[alias.lower()] = name  # 别名（小写）映射到应用名称

    def _load_custom_mappings(self, file_path: str):  # 私有方法：从JSON文件加载自定义映射
        try:  # 异常处理
            with open(file_path, encoding='utf-8') as f:  # 以UTF-8编码打开文件
                data = json.load(f)  # 解析JSON数据
            for name, info in data.items():  # 遍历JSON中的每个应用
                mapping = AppMapping(  # 创建AppMapping对象
                    name=name,  # 应用名称
                    app_path=info.get('app_path', ''),  # 可执行路径
                    urls=info.get('urls', []),  # URL列表
                    aliases=info.get('aliases', []),  # 别名列表
                    category=info.get('category', 'other'),  # 分类
                    search_url=info.get('search_url', '')  # 搜索URL模板
                )
                self.mappings[name] = mapping  # 添加到映射字典
            self._rebuild_alias_index()  # 重建别名索引
        except Exception as e:  # 捕获异常
            print(f"加载自定义映射失败: {e}")  # 打印错误信息

    def find_app(self, query: str) -> AppMapping | None:  # 根据查询查找应用映射
        query_lower = query.lower().strip()  # 查询字符串转小写并去除首尾空格
        if query_lower in self._alias_to_name:  # 如果查询匹配某个别名
            name = self._alias_to_name[query_lower]  # 获取应用名称
            return self.mappings.get(name)  # 返回对应的AppMapping对象
        for alias, name in self._alias_to_name.items():  # 遍历所有别名进行模糊匹配
            if query_lower in alias or alias in query_lower:  # 如果查询包含别名或别名包含查询
                return self.mappings.get(name)  # 返回匹配的AppMapping
        return None  # 未找到匹配，返回None

    def get_search_url(self, app_name: str, keyword: str) -> str | None:  # 获取应用的搜索URL
        mapping = self.find_app(app_name)  # 查找应用映射
        if mapping and mapping.search_url:  # 如果找到且存在搜索URL
            return mapping.search_url.format(keyword=keyword)  # 格式化搜索URL，替换{keyword}
        return None  # 未找到，返回None

    def get_app_url(self, app_name: str) -> str | None:  # 获取应用的主URL
        mapping = self.find_app(app_name)  # 查找应用映射
        if mapping and mapping.urls:  # 如果找到且存在URL列表
            return mapping.urls[0]  # 返回第一个URL
        return None  # 未找到，返回None


# 全局单例
_app_mapping_manager = None  # 模块级变量，存储单例实例


def get_app_mapping_manager() -> AppMappingManager:  # 获取应用映射管理器单例的工厂函数
    global _app_mapping_manager  # 声明使用全局变量
    if _app_mapping_manager is None:  # 如果单例尚未创建
        _app_mapping_manager = AppMappingManager()  # 创建新实例
    return _app_mapping_manager  # 返回单例实例


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"应用映射管理器"，负责维护常用应用的信息映射，
# 包括应用名称、别名、可执行路径、URL地址和搜索模板等。
#
# 【主要功能】
# 1. 应用信息映射：将用户友好的应用名称/别名映射到实际的应用路径或URL
# 2. 别名支持：支持多个别名指向同一应用（如"百度"、"baidu"、"度娘"）
# 3. 搜索集成：提供搜索URL模板，支持直接在应用内搜索
# 4. 分类管理：应用按search/video/music/social/system等分类
# 5. 自定义扩展：支持从JSON文件加载自定义应用映射
#
# 【关联文件】
# - core/tool_manager.py            : 工具管理器，可能调用本模块获取应用路径
# - tools/app_launcher.py           : 应用启动工具，使用本模块解析应用名称
# - tools/web_search.py             : 网页搜索工具，使用本模块获取搜索URL
# - data/custom_app_mappings.json   : 可选的自定义应用映射配置文件
#
# 【使用场景】
# - 用户说"打开微信"时，通过别名"微信"找到可执行路径"wechat.exe"
# - 用户说"在百度搜Python"时，通过搜索模板生成搜索URL
# - 系统内置常用应用映射，同时支持用户自定义扩展
#
# 【数据结构】
# - AppMapping: 单个应用的完整信息
# - AppMappingManager: 管理所有应用映射，提供查找和索引功能
# =============================================================================
