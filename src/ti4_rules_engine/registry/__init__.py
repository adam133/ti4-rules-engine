"""
TI4 Rules Engine – registry package.

Provides the ``ComponentRegistry`` (searchable component database) and
the ``EffectRegistry`` (modifier/effect query system).
"""

from ti4_rules_engine.registry.component_registry import ComponentRegistry
from ti4_rules_engine.registry.effect_registry import Effect, EffectRegistry, TriggerType

__all__ = [
    "ComponentRegistry",
    "Effect",
    "EffectRegistry",
    "TriggerType",
]
