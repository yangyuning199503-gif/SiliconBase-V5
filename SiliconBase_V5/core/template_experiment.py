#!/usr/bin/env python3
"""
TemplateExperiment 代理模块 - 向后兼容

此文件仅用于向后兼容，实际实现在 core/experiment/template_experiment.py
"""

from .experiment.template_experiment import (
    TemplateExperiment,
    WeeklyReport,
    template_experiment,
)

__all__ = [
    "template_experiment",
    "WeeklyReport",
    "TemplateExperiment",
]
