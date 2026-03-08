"""
Strategy Registry - auto-discovery and registration of strategies.
"""
from typing import Dict, List, Type, Any
from strategies.base_strategy import BaseStrategy


class StrategyRegistry:
    _strategies: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, strategy_class: Type[BaseStrategy]) -> Type[BaseStrategy]:
        """Decorator to register a strategy class."""
        meta = strategy_class.metadata()
        cls._strategies[meta["name"]] = strategy_class
        return strategy_class

    @classmethod
    def get(cls, name: str) -> Type[BaseStrategy]:
        """Get strategy class by name."""
        if name not in cls._strategies:
            raise ValueError(f"Unknown strategy: {name}. Available: {list(cls._strategies.keys())}")
        return cls._strategies[name]

    @classmethod
    def list_all(cls) -> List[Dict[str, Any]]:
        """List all registered strategies with metadata."""
        return [s.metadata() for s in cls._strategies.values()]

    @classmethod
    def create(cls, name: str, params: Dict[str, Any]) -> BaseStrategy:
        """Create strategy instance with given params."""
        strategy_class = cls.get(name)
        # Fill defaults
        meta = strategy_class.metadata()
        full_params = {}
        for pname, pspec in meta.get("parameters", {}).items():
            if pname in params:
                # Type coercion
                if pspec["type"] == "int":
                    full_params[pname] = int(params[pname])
                elif pspec["type"] == "float":
                    full_params[pname] = float(params[pname])
                else:
                    full_params[pname] = params[pname]
            else:
                full_params[pname] = pspec["default"]
        instance = strategy_class(full_params)
        instance.validate_params()
        return instance
