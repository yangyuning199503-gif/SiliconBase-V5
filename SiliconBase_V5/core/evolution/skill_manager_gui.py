#!/usr/bin/env python3  # 指定使用Python3解释器执行此脚本
# 声明文件编码为UTF-8，支持中文
"""  # 多行文档字符串开始
技能管理器GUI - SiliconBase V5  # 模块功能概述：技能管理图形界面
提供图形界面管理自动生成的技能  # 功能说明
"""  # 文档字符串结束

import json  # 导入JSON模块
import tkinter as tk  # 导入tkinter模块，GUI框架
from collections.abc import Callable  # 从typing导入类型注解
from tkinter import messagebox, scrolledtext, ttk  # 导入主题控件、消息框、滚动文本

from core.evolution.skill_generator import skill_manager_api  # 导入技能管理API
from core.logger import logger  # 导入日志记录器


class SkillManagerGUI:  # 技能管理器图形界面类
    """技能管理器图形界面"""  # 类文档字符串

    def __init__(self, parent: tk.Tk | None = None):  # 初始化方法
        self.parent = parent or tk.Tk()  # 使用传入的窗口或创建新窗口
        self.parent.title("SiliconBase V5 - 技能管理器")  # 设置窗口标题
        self.parent.geometry("900x600")  # 设置窗口大小

        self.selected_skill: str | None = None  # 当前选中的技能ID
        self.on_skill_select: Callable | None = None  # 选择回调函数

        self._setup_ui()  # 设置UI
        self._refresh_skill_list()  # 刷新技能列表

    def _setup_ui(self):  # 设置UI布局
        """设置UI布局"""  # 方法文档字符串
        # 主框架
        main_frame = ttk.Frame(self.parent, padding="10")  # 创建主框架，带内边距
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))  # 网格布局

        # 配置网格权重
        self.parent.columnconfigure(0, weight=1)  # 列可扩展
        self.parent.rowconfigure(0, weight=1)  # 行可扩展
        main_frame.columnconfigure(1, weight=1)  # 右侧面板可扩展
        main_frame.rowconfigure(0, weight=1)  # 内容区可扩展

        # 左侧面板 - 技能列表
        left_frame = ttk.LabelFrame(main_frame, text="技能列表", padding="5")  # 创建标签框架
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))  # 网格布局
        left_frame.columnconfigure(0, weight=1)  # 列表可扩展
        left_frame.rowconfigure(0, weight=1)  # 列表可扩展

        # 技能列表框
        self.skill_listbox = tk.Listbox(left_frame, width=30, height=20)  # 创建列表框
        self.skill_listbox.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))  # 网格布局
        self.skill_listbox.bind('<<ListboxSelect>>', self._on_list_select)  # 绑定选择事件

        # 滚动条
        scrollbar = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.skill_listbox.yview)  # 创建垂直滚动条
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))  # 网格布局
        self.skill_listbox.configure(yscrollcommand=scrollbar.set)  # 关联列表框和滚动条

        # 左侧按钮
        btn_frame = ttk.Frame(left_frame)  # 创建按钮框架
        btn_frame.grid(row=1, column=0, columnspan=2, pady=(5, 0))  # 网格布局

        ttk.Button(btn_frame, text="刷新", command=self._refresh_skill_list).pack(side=tk.LEFT, padx=2)  # 刷新按钮
        ttk.Button(btn_frame, text="删除", command=self._delete_selected).pack(side=tk.LEFT, padx=2)  # 删除按钮

        # 右侧面板 - 技能详情
        right_frame = ttk.LabelFrame(main_frame, text="技能详情", padding="5")  # 创建标签框架
        right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))  # 网格布局
        right_frame.columnconfigure(0, weight=1)  # 内容可扩展
        right_frame.rowconfigure(1, weight=1)  # 代码区可扩展

        # 基本信息
        info_frame = ttk.Frame(right_frame)  # 创建信息框架
        info_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 5))  # 网格布局

        self.info_labels = {}  # 信息标签字典
        fields = ['ID', '名称', '类名', '状态', '创建时间', '大小']  # 字段列表
        for i, field in enumerate(fields):  # 遍历字段
            ttk.Label(info_frame, text=f"{field}:").grid(row=i, column=0, sticky=tk.W, padx=(0, 5))  # 标签
            self.info_labels[field] = ttk.Label(info_frame, text="-")  # 创建值标签
            self.info_labels[field].grid(row=i, column=1, sticky=tk.W)  # 网格布局

        # 代码预览
        ttk.Label(right_frame, text="代码预览:").grid(row=1, column=0, sticky=tk.W, pady=(5, 0))  # 代码预览标签

        self.code_text = scrolledtext.ScrolledText(  # 创建滚动文本框
            right_frame,
            wrap=tk.WORD,  # 自动换行
            width=60,  # 宽度
            height=20,  # 高度
            font=('Consolas', 9)  # 等宽字体
        )
        self.code_text.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)  # 网格布局

        # 操作按钮
        action_frame = ttk.Frame(right_frame)  # 创建操作按钮框架
        action_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(5, 0))  # 网格布局

        ttk.Button(action_frame, text="测试", command=self._test_skill).pack(side=tk.LEFT, padx=2)  # 测试按钮
        ttk.Button(action_frame, text="启用/禁用", command=self._toggle_skill).pack(side=tk.LEFT, padx=2)  # 启用/禁用按钮
        ttk.Button(action_frame, text="导出", command=self._export_skill).pack(side=tk.LEFT, padx=2)  # 导出按钮

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")  # 状态变量
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN)  # 状态栏标签
        status_bar.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(5, 0))  # 网格布局

    def _refresh_skill_list(self):  # 刷新技能列表
        """刷新技能列表"""  # 方法文档字符串
        self.skill_listbox.delete(0, tk.END)  # 清空列表

        skills = skill_manager_api.get_generated_skills(limit=100)  # 获取技能列表

        for skill in skills:  # 遍历技能
            display_text = f"{skill['name']} ({skill['id']})"  # 显示文本
            self.skill_listbox.insert(tk.END, display_text)  # 插入列表
            self.skill_listbox.itemconfig(tk.END, foreground='green' if skill['status'] == 'active' else 'gray')  # 设置颜色

        stats = skill_manager_api.get_skill_stats()  # 获取统计
        self.status_var.set(f"共 {stats['total']} 个技能 | 活跃: {stats['active']} | 禁用: {stats['disabled']}")  # 更新状态栏

        logger.info(f"[SkillManagerGUI] 刷新技能列表: {len(skills)} 个技能")  # 记录日志

    def _on_list_select(self, event):  # 列表选择事件
        """列表选择事件"""  # 方法文档字符串
        selection = self.skill_listbox.curselection()  # 获取选中项
        if not selection:  # 如果没有选中
            return  # 直接返回

        # 获取选中的技能ID
        text = self.skill_listbox.get(selection[0])  # 获取文本
        skill_id = text.split('(')[-1].rstrip(')')  # 提取ID
        self.selected_skill = skill_id  # 保存选中ID

        # 显示详情
        self._show_skill_detail(skill_id)  # 显示详情

        if self.on_skill_select:  # 如果有回调
            self.on_skill_select(skill_id)  # 调用回调

    def _show_skill_detail(self, skill_id: str):  # 显示技能详情
        """显示技能详情"""  # 方法文档字符串
        # 获取基本信息
        skills = skill_manager_api.get_generated_skills(limit=100)  # 获取技能列表
        skill_info = next((s for s in skills if s['id'] == skill_id), None)  # 查找技能

        if skill_info:  # 如果找到
            from datetime import datetime  # 导入datetime
            created_time = datetime.fromtimestamp(skill_info['created_at']).strftime('%Y-%m-%d %H:%M:%S')  # 格式化时间

            self.info_labels['ID'].config(text=skill_info['id'])  # 显示ID
            self.info_labels['名称'].config(text=skill_info.get('name', '-'))  # 显示名称
            self.info_labels['类名'].config(text=skill_info['class_name'])  # 显示类名
            self.info_labels['状态'].config(text=skill_info['status'])  # 显示状态
            self.info_labels['创建时间'].config(text=created_time)  # 显示创建时间
            self.info_labels['大小'].config(text=f"{skill_info['size']} bytes")  # 显示大小

        # 获取代码详情
        detail = skill_manager_api.get_skill_detail(skill_id)  # 获取详情
        if detail:  # 如果获取成功
            self.code_text.delete(1.0, tk.END)  # 清空文本框
            self.code_text.insert(1.0, detail['content'])  # 插入代码

    def _delete_selected(self):  # 删除选中的技能
        """删除选中的技能"""  # 方法文档字符串
        if not self.selected_skill:  # 如果未选中
            messagebox.showwarning("警告", "请先选择一个技能")  # 显示警告
            return  # 直接返回

        if messagebox.askyesno("确认", f"确定要删除技能 '{self.selected_skill}' 吗？"):  # 确认对话框
            if skill_manager_api.delete_skill(self.selected_skill):  # 删除技能
                messagebox.showinfo("成功", "技能已删除")  # 显示成功
                self._refresh_skill_list()  # 刷新列表
                self.code_text.delete(1.0, tk.END)  # 清空代码区
            else:  # 删除失败
                messagebox.showerror("错误", "删除失败")  # 显示错误

    def _test_skill(self):  # 测试选中的技能
        """测试选中的技能"""  # 方法文档字符串
        if not self.selected_skill:  # 如果未选中
            messagebox.showwarning("警告", "请先选择一个技能")  # 显示警告
            return  # 直接返回

        # 简单的测试参数输入对话框
        test_window = tk.Toplevel(self.parent)  # 创建顶级窗口
        test_window.title(f"测试技能: {self.selected_skill}")  # 设置标题
        test_window.geometry("400x300")  # 设置大小

        ttk.Label(test_window, text="测试参数 (JSON格式):").pack(pady=5)  # 标签

        param_text = tk.Text(test_window, height=10, width=40)  # 创建文本输入框
        param_text.pack(pady=5)  # 布局
        param_text.insert(1.0, '{}')  # 默认空JSON

        def do_test():  # 执行测试函数
            try:  # 异常处理
                params = json.loads(param_text.get(1.0, tk.END))  # 解析JSON
                result = skill_manager_api.test_skill(self.selected_skill, params)  # 测试技能

                if result['success']:  # 如果成功
                    messagebox.showinfo("测试结果",  # 显示结果
                        f"成功!\n耗时: {result['duration']:.3f}s\n结果:\n{json.dumps(result['result'], indent=2, ensure_ascii=False)}")
                else:  # 如果失败
                    messagebox.showerror("测试失败", f"错误: {result.get('error', '未知错误')}")  # 显示错误
            except json.JSONDecodeError:  # JSON解析错误
                messagebox.showerror("错误", "JSON格式无效")  # 显示错误
            except Exception as e:  # 其他异常
                messagebox.showerror("错误", f"测试异常: {e}")  # 显示错误

            test_window.destroy()  # 关闭测试窗口

        ttk.Button(test_window, text="运行测试", command=do_test).pack(pady=5)  # 测试按钮

    def _toggle_skill(self):  # 启用/禁用技能
        """启用/禁用技能"""  # 方法文档字符串
        if not self.selected_skill:  # 如果未选中
            messagebox.showwarning("警告", "请先选择一个技能")  # 显示警告
            return  # 直接返回

        # 获取当前状态
        skills = skill_manager_api.get_generated_skills(limit=100)  # 获取技能列表
        skill_info = next((s for s in skills if s['id'] == self.selected_skill), None)  # 查找技能

        if skill_info:  # 如果找到
            current_status = skill_info['status']  # 获取当前状态
            enable = current_status == 'disabled'  # 确定目标状态

            if skill_manager_api.toggle_skill(self.selected_skill, enable):  # 切换状态
                messagebox.showinfo("成功", f"技能已{'启用' if enable else '禁用'}")  # 显示成功
                self._refresh_skill_list()  # 刷新列表
            else:  # 失败
                messagebox.showerror("错误", "操作失败")  # 显示错误

    def _export_skill(self):  # 导出技能
        """导出技能"""  # 方法文档字符串
        if not self.selected_skill:  # 如果未选中
            messagebox.showwarning("警告", "请先选择一个技能")  # 显示警告
            return  # 直接返回

        from tkinter import filedialog  # 导入文件对话框

        detail = skill_manager_api.get_skill_detail(self.selected_skill)  # 获取详情
        if detail:  # 如果获取成功
            file_path = filedialog.asksaveasfilename(  # 显示保存对话框
                defaultextension=".py",  # 默认扩展名
                filetypes=[("Python文件", "*.py"), ("所有文件", "*.*")],  # 文件类型
                initialfile=f"{self.selected_skill}.py"  # 默认文件名
            )

            if file_path:  # 如果选择了路径
                try:  # 异常处理
                    with open(file_path, 'w', encoding='utf-8') as f:  # 打开文件
                        f.write(detail['content'])  # 写入代码
                    messagebox.showinfo("成功", f"技能已导出到:\n{file_path}")  # 显示成功
                except Exception as e:  # 捕获异常
                    messagebox.showerror("错误", f"导出失败: {e}")  # 显示错误

    def run(self):  # 运行GUI
        """运行GUI"""  # 方法文档字符串
        self.parent.mainloop()  # 进入主循环


def show_skill_manager():  # 显示技能管理器窗口
    """显示技能管理器窗口"""  # 函数文档字符串
    gui = SkillManagerGUI()  # 创建GUI实例
    gui.run()  # 运行


# 便捷函数
def quick_skill_list():  # 快速获取技能列表（命令行模式）
    """快速获取技能列表（命令行模式）"""  # 函数文档字符串
    skills = skill_manager_api.get_generated_skills(limit=50)  # 获取技能列表
    print(f"\n{'='*60}")  # 分隔线
    print(f"{'技能列表':^60}")  # 标题
    print(f"{'='*60}")  # 分隔线

    for skill in skills:  # 遍历技能
        status_icon = "✓" if skill['status'] == 'active' else "✗"  # 状态图标
        print(f"{status_icon} {skill['name']} ({skill['id']})")  # 名称和ID
        print(f"   描述: {skill['description'][:50]}...")  # 描述（截断）
        print(f"   大小: {skill['size']} bytes")  # 大小
        print()  # 空行

    stats = skill_manager_api.get_skill_stats()  # 获取统计
    print(f"总计: {stats['total']} (活跃: {stats['active']}, 禁用: {stats['disabled']})")  # 统计信息
    print(f"{'='*60}\n")  # 分隔线


if __name__ == "__main__":  # 主入口
    import sys  # 导入sys模块

    if len(sys.argv) > 1 and sys.argv[1] == '--cli':  # 如果命令行参数有--cli
        quick_skill_list()  # 命令行模式
    else:  # 否则
        show_skill_manager()  # GUI模式


# =============================================================================
# 文件角色总结
# =============================================================================
#
# 【核心定位】
# 本文件是 SiliconBase V5 系统的"技能管理器GUI"，提供图形界面用于
# 查看、测试、删除、导出自动生成的技能。
#
# 【主要功能】
# 1. 技能列表：显示所有生成的技能，按状态区分颜色
# 2. 技能详情：显示ID、名称、类名、状态、创建时间、大小等元信息
# 3. 代码预览：以等宽字体显示技能代码，支持滚动
# 4. 测试功能：提供参数输入对话框，测试技能执行
# 5. 启用/禁用：切换技能状态
# 6. 删除功能：删除技能（有备份）
# 7. 导出功能：将技能代码导出到指定位置
#
# 【关联文件】
# - core/skill_generator.py       : 技能生成器，提供skill_manager_api
# - skills/generated/             : 活跃技能存储目录
# - skills/disabled/              : 禁用技能存储目录
# - skills/deleted/               : 删除技能备份目录
#
# 【界面布局】
# - 左侧面板：技能列表 + 刷新/删除按钮
# - 右侧面板：技能详情 + 代码预览 + 测试/启用/导出按钮
# - 底部：状态栏显示统计信息
#
# 【核心功能效果】
# 1. 可视化：直观展示所有生成技能的状态和信息
# 2. 便捷操作：一键测试、启用/禁用、删除、导出
# 3. 代码审查：可直接查看生成代码的内容和质量
# 4. 双模式：支持GUI模式和命令行模式
#
# 【使用场景】
# - 审查AI自动生成的技能代码
# - 测试新技能的功能是否正常
# - 导出优质技能供其他系统使用
# - 清理不再需要的技能
# =============================================================================
