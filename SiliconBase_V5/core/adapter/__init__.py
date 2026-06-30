#!/usr/bin/env python3
"""
适配器层 - 标准化接口包装
"""

from .agent_loop_adapter import AgentLoopAdapter, get_agent_loop_adapter
from .consciousness_adapter import ConsciousnessAdapter, get_consciousness_adapter
from .evolution_adapter import EvolutionAdapter, get_evolution_adapter

__all__ = [
    'AgentLoopAdapter',
    'EvolutionAdapter',
    'ConsciousnessAdapter',
    'get_agent_loop_adapter',
    'get_evolution_adapter',
    'get_consciousness_adapter',
]
