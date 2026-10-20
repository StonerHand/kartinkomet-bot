"""Load aiogram without building every Telegram model up front.

aiogram declares its ~300 types with pydantic's `defer_build=True`, then defeats it: importing
`aiogram.types` calls `model_rebuild()` on each of them, compiling validators for payments,
stories, giveaways and everything else this bot never receives. That alone takes ~85 MB.

`load_aiogram()` imports aiogram with model_rebuild intercepted for those deferred models: it
only remembers the namespace aiogram passes (so forward references still resolve) and lets
pydantic build each model the first time a matching update actually arrives. The bot ends up
with validators for messages, callbacks and a few more types, ~45 MB less memory.

Relies on pydantic internals (`__pydantic_parent_namespace__`), so pydantic is pinned in
requirements.txt. The whole test suite runs in this mode (tests/__init__.py).
"""

import importlib
import sys

from pydantic import BaseModel


def load_aiogram() -> None:
    if "aiogram.types" in sys.modules:
        return  # already imported the usual way; nothing to save any more
    original = BaseModel.model_rebuild.__func__
    namespace: dict = {}

    def remember_namespace(cls, *, force=False, raise_errors=True, _parent_namespace_depth=2, _types_namespace=None):
        if _types_namespace is not None and cls.model_config.get("defer_build") and not force:
            namespace.update(_types_namespace)
            cls.__pydantic_parent_namespace__ = namespace  # one shared dict for all types
            return None
        return original(
            cls,
            force=force,
            raise_errors=raise_errors,
            _parent_namespace_depth=_parent_namespace_depth,
            _types_namespace=_types_namespace,
        )

    BaseModel.model_rebuild = classmethod(remember_namespace)
    try:
        importlib.import_module("aiogram.types")
    finally:
        BaseModel.model_rebuild = classmethod(original)
    # API methods are built eagerly and fail to resolve the types that are still deferred; give
    # them the same namespace, and pydantic completes each one the first time it is sent.
    methods = importlib.import_module("aiogram.methods")
    for name in getattr(methods, "__all__", ()):
        method = getattr(methods, name, None)
        if isinstance(method, type) and issubclass(method, BaseModel) and not method.__pydantic_complete__:
            method.__pydantic_parent_namespace__ = {**namespace, **(method.__pydantic_parent_namespace__ or {})}
