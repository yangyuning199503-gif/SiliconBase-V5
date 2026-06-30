"""
动态规则加载器

功能:
1. 从YAML文件加载规则
2. 支持热加载（文件变更自动重载）
3. 规则增删改不需要重启系统
4. 线程安全
"""

import os
import re
import threading
import time
from datetime import datetime

import yaml

# 尝试导入watchdog，如果没有则使用轮询
HAVE_WATCHDOG = False
try:
    from watchdog.observers import Observer
    HAVE_WATCHDOG = True
except ImportError:
    pass

# 尝试导入logger
try:
    from core.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class RuleConfigHandler:
    """配置文件变更处理器（watchdog版本）"""

    def __init__(self, loader):
        self.loader = loader
        self.last_reload = 0

    def on_modified(self, event):
        if event.src_path.endswith('moral_rules.yaml'):
            # 防抖处理
            current_time = time.time()
            if current_time - self.last_reload > 5:  # 5秒内不重复加载
                self.last_reload = current_time
                logger.info("[RuleLoader] 检测到规则文件变更，重新加载...")
                self.loader.reload_rules()


class DynamicRuleLoader:
    """
    动态规则加载器

    功能:
    1. 从YAML文件加载规则
    2. 支持热加载（文件变更自动重载）
    3. 规则增删改不需要重启系统
    4. 提供规则匹配功能
    """

    def __init__(self, config_path: str = None):
        # 自动查找配置文件路径
        if config_path is None:
            possible_paths = [
                "config/moral_rules.yaml",
                "../config/moral_rules.yaml",
                "../../config/moral_rules.yaml",
                os.path.join(os.path.dirname(__file__), "../config/moral_rules.yaml"),
            ]
            for path in possible_paths:
                if os.path.exists(path):
                    config_path = path
                    break

        self.config_path = config_path or "config/moral_rules.yaml"
        self.rules: dict[str, dict] = {}
        self.config: dict = {}
        self._lock = threading.RLock()
        self._observer = None
        self._last_load_time = 0
        self._compiled_patterns: dict[str, re.Pattern] = {}

        # 初始加载
        self.load_rules()

        # 启动文件监控（如果可用）
        if HAVE_WATCHDOG and self.config.get('global', {}).get('auto_reload', True):
            self._start_watching()
        else:
            # 使用轮询机制
            self._start_polling()

    def load_rules(self) -> bool:
        """加载规则配置文件"""
        try:
            if not os.path.exists(self.config_path):
                logger.warning(f"[RuleLoader] 规则文件不存在: {self.config_path}")
                # 使用默认规则
                self._load_default_rules()
                return True

            with open(self.config_path, encoding='utf-8') as f:
                self.config = yaml.safe_load(f)

            with self._lock:
                self.rules = {}
                self._compiled_patterns = {}

                for rule in self.config.get('rules', []):
                    if rule.get('enabled', True):
                        rule_id = rule['id']
                        self.rules[rule_id] = rule

                        # 预编译正则表达式
                        for pattern in rule.get('patterns', []):
                            try:
                                key = f"{rule_id}:{pattern}"
                                self._compiled_patterns[key] = re.compile(pattern, re.IGNORECASE)
                            except re.error as e:
                                logger.warning(f"[RuleLoader] 规则 {rule_id} 的正则编译失败: {pattern} - {e}")

            self._last_load_time = time.time()
            logger.info(f"[RuleLoader] 成功加载 {len(self.rules)} 条规则")
            return True

        except Exception as e:
            logger.error(f"[RuleLoader] 加载规则失败: {e}")
            self._load_default_rules()
            return False

    def _load_default_rules(self):
        """加载默认规则（当配置文件不存在时）"""
        # 从moral_rules模块加载
        try:
            from core.moral_rules import get_all_enhanced_rules
            from core.safety.moral_module import MoralRule

            enhanced_rules = get_all_enhanced_rules()

            with self._lock:
                self.rules = {}
                for rule in enhanced_rules:
                    if isinstance(rule, MoralRule):
                        rule_dict = {
                            'id': rule.rule_id,
                            'category': rule.category.value,
                            'name': rule.name,
                            'description': rule.description,
                            'severity': rule.severity.value,
                            'action': rule.action,
                            'message': rule.message,
                            'patterns': rule.patterns,
                            'keywords': rule.forbidden_keywords,
                            'enabled': True
                        }
                        self.rules[rule.rule_id] = rule_dict

            logger.info(f"[RuleLoader] 加载默认规则 {len(self.rules)} 条")

        except Exception as e:
            logger.error(f"[RuleLoader] 加载默认规则失败: {e}")

    def reload_rules(self) -> bool:
        """重新加载规则"""
        logger.info("[RuleLoader] 重新加载规则...")
        return self.load_rules()

    def get_rule(self, rule_id: str) -> dict | None:
        """获取单条规则"""
        with self._lock:
            return self.rules.get(rule_id)

    def get_all_rules(self) -> list[dict]:
        """获取所有规则"""
        with self._lock:
            return list(self.rules.values())

    def get_rules_by_category(self, category: str) -> list[dict]:
        """按类别获取规则"""
        with self._lock:
            return [r for r in self.rules.values() if r.get('category') == category]

    def check_text_against_rules(self, text: str, categories: list[str] = None) -> tuple:
        """
        检查文本是否违反规则

        Args:
            text: 要检查的文本
            categories: 指定类别（None表示所有）

        Returns:
            (是否违反, 违反的规则列表, 最高严重级别)
        """
        if not text:
            return False, [], None

        text_lower = text.lower()
        violated_rules = []
        max_severity = None

        severity_order = {'safe': 0, 'warning': 1, 'dangerous': 2, 'forbidden': 3}

        with self._lock:
            for rule in self.rules.values():
                # 过滤类别
                if categories and rule.get('category') not in categories:
                    continue

                is_violated = False

                # 检查关键词
                for keyword in rule.get('keywords', []):
                    if keyword.lower() in text_lower:
                        is_violated = True
                        break

                # 检查正则模式
                if not is_violated:
                    for pattern in rule.get('patterns', []):
                        key = f"{rule['id']}:{pattern}"
                        compiled = self._compiled_patterns.get(key)
                        if compiled:
                            if compiled.search(text):
                                is_violated = True
                                break
                        else:
                            # 回退到直接匹配
                            try:
                                if re.search(pattern, text, re.IGNORECASE):
                                    is_violated = True
                                    break
                            except re.error:
                                continue

                if is_violated:
                    violated_rules.append(rule)

                    # 更新最高严重级别
                    rule_severity = rule.get('severity', 'warning')
                    if max_severity is None or severity_order.get(rule_severity, 0) > severity_order.get(max_severity, 0):
                        max_severity = rule_severity

        return len(violated_rules) > 0, violated_rules, max_severity

    def add_rule(self, rule: dict) -> bool:
        """动态添加规则（运行时）"""
        try:
            with self._lock:
                self.rules[rule['id']] = rule

                # 预编译正则
                for pattern in rule.get('patterns', []):
                    try:
                        key = f"{rule['id']}:{pattern}"
                        self._compiled_patterns[key] = re.compile(pattern, re.IGNORECASE)
                    except re.error:
                        pass

            # 同步保存到文件
            self._save_rules()
            logger.info(f"[RuleLoader] 添加规则: {rule['id']}")
            return True
        except Exception as e:
            logger.error(f"[RuleLoader] 添加规则失败: {e}")
            return False

    def update_rule(self, rule_id: str, updates: dict) -> bool:
        """更新规则"""
        try:
            with self._lock:
                if rule_id in self.rules:
                    self.rules[rule_id].update(updates)
                    self._save_rules()
                    logger.info(f"[RuleLoader] 更新规则: {rule_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[RuleLoader] 更新规则失败: {e}")
            return False

    def remove_rule(self, rule_id: str) -> bool:
        """删除规则"""
        try:
            with self._lock:
                if rule_id in self.rules:
                    del self.rules[rule_id]
                    # 清理编译的正则
                    keys_to_remove = [k for k in self._compiled_patterns if k.startswith(f"{rule_id}:")]
                    for k in keys_to_remove:
                        del self._compiled_patterns[k]
                    self._save_rules()
                    logger.info(f"[RuleLoader] 删除规则: {rule_id}")
                    return True
            return False
        except Exception as e:
            logger.error(f"[RuleLoader] 删除规则失败: {e}")
            return False

    def toggle_rule(self, rule_id: str, enabled: bool) -> bool:
        """启用/禁用规则"""
        return self.update_rule(rule_id, {'enabled': enabled})

    def _save_rules(self):
        """保存规则到文件"""
        try:
            self.config['rules'] = list(self.rules.values())
            self.config['last_updated'] = datetime.now().isoformat()

            # 确保目录存在
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logger.error(f"[RuleLoader] 保存规则失败: {e}")

    def _start_watching(self):
        """启动文件监控（watchdog）"""
        try:
            directory = os.path.dirname(os.path.abspath(self.config_path))
            self._observer = Observer()
            handler = RuleConfigHandler(self)
            self._observer.schedule(handler, directory, recursive=False)
            self._observer.start()
            logger.info(f"[RuleLoader] 启动规则文件监控: {directory}")
        except Exception as e:
            logger.warning(f"[RuleLoader] 启动文件监控失败: {e}")

    def _start_polling(self):
        """启动轮询监控（备用方案）"""
        interval = self.config.get('global', {}).get('reload_interval', 60)

        def poll():
            last_mtime = 0
            while True:
                try:
                    if os.path.exists(self.config_path):
                        mtime = os.path.getmtime(self.config_path)
                        if mtime > last_mtime and last_mtime > 0:
                            logger.info("[RuleLoader] 检测到规则文件变更（轮询）")
                            self.reload_rules()
                        last_mtime = mtime
                except Exception as e:
                    logger.warning(f"[RuleLoader] 轮询检查失败: {e}")

                time.sleep(interval)

        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        logger.info(f"[RuleLoader] 启动规则轮询监控（间隔{interval}秒）")

    def stop_watching(self):
        """停止文件监控"""
        if self._observer:
            self._observer.stop()
            self._observer.join()

    def get_stats(self) -> dict:
        """获取加载统计"""
        return {
            "total_rules": len(self.rules),
            "config_path": self.config_path,
            "last_load": self._last_load_time,
            "categories": self._count_by_category()
        }

    def _count_by_category(self) -> dict:
        """按类别统计规则数"""
        counts = {}
        for rule in self.rules.values():
            cat = rule.get('category', 'unknown')
            counts[cat] = counts.get(cat, 0) + 1
        return counts


# 全局实例
_rule_loader = None
_rule_loader_lock = threading.Lock()


def get_rule_loader() -> DynamicRuleLoader:
    """获取全局规则加载器实例"""
    global _rule_loader
    if _rule_loader is None:
        with _rule_loader_lock:
            if _rule_loader is None:
                _rule_loader = DynamicRuleLoader()
    return _rule_loader


# 便捷函数
def check_text(text: str, categories: list[str] = None) -> tuple:
    """便捷函数：检查文本"""
    return get_rule_loader().check_text_against_rules(text, categories)


def get_all_rules() -> list[dict]:
    """便捷函数：获取所有规则"""
    return get_rule_loader().get_all_rules()


if __name__ == "__main__":
    # 测试
    loader = DynamicRuleLoader()
    print(f"加载统计: {loader.get_stats()}")

    # 测试检查
    test_cases = [
        "窃取用户数据",
        "格式化磁盘",
        "打开记事本",
    ]

    for text in test_cases:
        violated, rules, severity = loader.check_text_against_rules(text)
        print(f"'{text}': 违反={violated}, 严重级别={severity}, 规则数={len(rules)}")
