# model_upgrade 目录状态说明

> ⚠️ 【Phase 7 延后开发声明】
> 本目录自 2026-04-18 起标记为 DEFER。
>
> **原因**：完全悬空，零生产调用方。
>
> **当前状态**：代码保留但不做维护。目录内所有模块均未被生产链路导入。
>
> **未来计划**：如需模型升级/降级/成本控制能力，必须基于 asyncio 重新设计，
> 不可直接使用当前同步代码。
>
> **文件清单**：
> - `cost_controller.py` — 成本控制器
> - `enhanced_router.py` — 增强路由
> - `examples.py` — 示例
> - `fallback_manager.py` — 降级管理器
> - `orchestrator.py` — 编排器
> - `__init__.py` — 包初始化
