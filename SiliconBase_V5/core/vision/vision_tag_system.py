"""
vision_tag_system.py

视觉标签权重分级系统 (Vision Tag Weight Classification System)

用途：
    为视觉识别模块提供统一的标签权重分级逻辑，决定不同视觉标签
    的处理方式：就地忽略、视觉层自主处理、或上报文本AI进行决策。

三级权重定义：
    - L0_IGNORE (0): 就地消化，不上报。例如常见背景类或人体/外设
      对象（person, keyboard, mouse, background）。
    - L1_VISUAL (1): 视觉层自己处理。例如 UI 控件或通用界面元素
      （button, window, dialog, text, input, icon）。
    - L2_REPORT (2): 上报文本AI。例如需要高层决策的告警或敌对
      对象（enemy, boss, alert, warning, danger）。

典型使用场景：
    1. 视觉流水线检测到对象后，通过 classify() 获取权重。
    2. 根据权重决定对象信息是否封装为事件上报给文本AI。
    3. 支持运行时动态扩展标签表，以适应不同游戏/应用域。

接口概览：
    - classify(tag: str) -> int
    - should_report(tag: str) -> bool
    - should_visual_handle(tag: str) -> bool
    - get_all_l2_tags() -> List[str]
    - add_custom_tag(tag: str, level: int) -> None
"""



class VisionTagSystem:
    """
    视觉标签权重分级系统。

    维护一张标签 -> 权重级别的映射表，并提供查询、判断和动态扩展能力。
    """

    # 权重常量
    L0_IGNORE = 0
    L1_VISUAL = 1
    L2_REPORT = 2

    # 默认标签权重表：覆盖常见 COCO 类别与 UI 类别
    _DEFAULT_TAGS: dict[str, int] = {
        # --- L0: 背景/人体/外设 (就地忽略) ---
        "person": L0_IGNORE,
        "keyboard": L0_IGNORE,
        "mouse": L0_IGNORE,
        "background": L0_IGNORE,
        "laptop": L0_IGNORE,
        "tv": L0_IGNORE,
        "monitor": L0_IGNORE,
        "cell phone": L0_IGNORE,
        "remote": L0_IGNORE,
        "book": L0_IGNORE,
        "cup": L0_IGNORE,
        "bottle": L0_IGNORE,
        "chair": L0_IGNORE,
        "desk": L0_IGNORE,
        "table": L0_IGNORE,
        "couch": L0_IGNORE,
        "bed": L0_IGNORE,
        "door": L0_IGNORE,
        "wall": L0_IGNORE,
        "floor": L0_IGNORE,
        "ceiling": L0_IGNORE,
        "curtain": L0_IGNORE,
        "rug": L0_IGNORE,
        "pillow": L0_IGNORE,
        "mirror": L0_IGNORE,
        "picture": L0_IGNORE,
        "clock": L0_IGNORE,
        "vase": L0_IGNORE,
        "plant": L0_IGNORE,
        "potted plant": L0_IGNORE,
        "refrigerator": L0_IGNORE,
        "microwave": L0_IGNORE,
        "oven": L0_IGNORE,
        "sink": L0_IGNORE,
        "toilet": L0_IGNORE,

        # --- L1: UI/界面元素 (视觉层自己处理) ---
        "button": L1_VISUAL,
        "window": L1_VISUAL,
        "dialog": L1_VISUAL,
        "text": L1_VISUAL,
        "input": L1_VISUAL,
        "icon": L1_VISUAL,
        "menu": L1_VISUAL,
        "tab": L1_VISUAL,
        "checkbox": L1_VISUAL,
        "radio": L1_VISUAL,
        "slider": L1_VISUAL,
        "scrollbar": L1_VISUAL,
        "dropdown": L1_VISUAL,
        "tooltip": L1_VISUAL,
        "progress": L1_VISUAL,
        "list": L1_VISUAL,
        "grid": L1_VISUAL,
        "card": L1_VISUAL,
        "panel": L1_VISUAL,
        "toolbar": L1_VISUAL,
        "sidebar": L1_VISUAL,
        "header": L1_VISUAL,
        "footer": L1_VISUAL,
        "link": L1_VISUAL,
        "badge": L1_VISUAL,
        "avatar": L1_VISUAL,
        "modal": L1_VISUAL,
        "notification": L1_VISUAL,
        "banner": L1_VISUAL,
        "search": L1_VISUAL,
        "breadcrumb": L1_VISUAL,
        "pagination": L1_VISUAL,

        # --- L2: 需上报文本AI的高优先级对象 ---
        "enemy": L2_REPORT,
        "boss": L2_REPORT,
        "alert": L2_REPORT,
        "warning": L2_REPORT,
        "danger": L2_REPORT,
        "npc": L2_REPORT,
        "quest": L2_REPORT,
        "loot": L2_REPORT,
        "item": L2_REPORT,
        "chest": L2_REPORT,
        "portal": L2_REPORT,
        "trap": L2_REPORT,
        "fire": L2_REPORT,
        "smoke": L2_REPORT,
        "explosion": L2_REPORT,
        "gun": L2_REPORT,
        "knife": L2_REPORT,
        "sword": L2_REPORT,
        "shield": L2_REPORT,
        "potion": L2_REPORT,
        "spell": L2_REPORT,
        "magic": L2_REPORT,
        "target": L2_REPORT,
        "objective": L2_REPORT,
        "mission": L2_REPORT,
        "event": L2_REPORT,
        "error": L2_REPORT,
        "critical": L2_REPORT,
        "enemy_base": L2_REPORT,
        "ally": L2_REPORT,
        "teammate": L2_REPORT,
    }

    def __init__(self) -> None:
        """初始化标签系统，拷贝默认标签表供实例独立使用。"""
        self._tags: dict[str, int] = dict(self._DEFAULT_TAGS)

    def classify(self, tag: str) -> int:
        """
        根据标签名返回对应的权重级别。

        若标签不在表中，默认返回 L0_IGNORE，避免未知标签造成噪音。

        Args:
            tag: 标签名称（不区分大小写）。

        Returns:
            权重级别：L0_IGNORE, L1_VISUAL 或 L2_REPORT。
        """
        normalized = tag.strip().lower()
        return self._tags.get(normalized, self.L0_IGNORE)

    def should_report(self, tag: str) -> bool:
        """
        判断该标签是否应上报给文本AI。

        Args:
            tag: 标签名称。

        Returns:
            True 当且仅当标签级别 >= L2_REPORT。
        """
        return self.classify(tag) >= self.L2_REPORT

    def should_visual_handle(self, tag: str) -> bool:
        """
        判断该标签是否由视觉层自己处理。

        Args:
            tag: 标签名称。

        Returns:
            True 当且仅当标签级别 == L1_VISUAL。
        """
        return self.classify(tag) == self.L1_VISUAL

    def get_all_l2_tags(self) -> list[str]:
        """
        返回当前系统中所有 L2_REPORT 级别的标签列表。

        Returns:
            L2 标签名称列表（按字母序排序）。
        """
        return sorted([tag for tag, level in self._tags.items() if level == self.L2_REPORT])

    def add_custom_tag(self, tag: str, level: int) -> None:
        """
        运行时动态添加或覆盖自定义标签及其权重级别。

        Args:
            tag: 标签名称。
            level: 权重级别（应为 L0_IGNORE, L1_VISUAL 或 L2_REPORT）。

        Raises:
            ValueError: 若 level 不是合法的三级之一。
        """
        if level not in (self.L0_IGNORE, self.L1_VISUAL, self.L2_REPORT):
            raise ValueError(
                f"Invalid level {level}. Must be one of "
                f"L0_IGNORE({self.L0_IGNORE}), L1_VISUAL({self.L1_VISUAL}), "
                f"L2_REPORT({self.L2_REPORT})."
            )
        normalized = tag.strip().lower()
        if not normalized:
            raise ValueError("Tag cannot be empty or whitespace only.")
        self._tags[normalized] = level
