from typing import List, Set, Optional
from typing_extensions import override

from fastapi import FastAPI
from pydantic import Field, PrivateAttr, ConfigDict
from langchain_core.load.serializable import Serializable
from giga_agent.core.module import BaseModule
from langchain_core.language_models import BaseChatModel

from giga_agent.sandbox.base import BaseSandbox


class BaseAgent(Serializable):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    modules: List[BaseModule] = Field(default_factory=list)
    llm: Optional[BaseChatModel] = None
    sandbox: Optional[BaseSandbox] = None

    _app: FastAPI = PrivateAttr()
    _module_ids: Set[str] = PrivateAttr(default_factory=set)

    @classmethod
    @override
    def is_lc_serializable(cls) -> bool:
        return True

    def __init__(self, modules: List[BaseModule] = None, **data):
        if modules is not None:
            data["modules"] = modules
        super().__init__(**data)

        self._app = FastAPI()

        # Re-initialize modules through add_module to ensure validation and route registration
        initial_modules = self.modules
        self.modules = []

        for module in initial_modules:
            self.add_module(module)

    def add_module(self, module: BaseModule):
        if module.id in self._module_ids:
            raise ValueError(
                f"Agent cannot have multiple modules with the same id: '{module.id}'"
            )

        self.modules.append(module)
        self._module_ids.add(module.id)

        # Re-setup routes or just add the new one if possible
        if hasattr(self, "_app") and module.get_api_router():
            self._app.include_router(module.get_api_router())

    def _setup_routes(self):
        for module in self.modules:
            router = module.get_api_router()
            if router:
                self._app.include_router(router)

    @property
    def app(self) -> FastAPI:
        return self._app
