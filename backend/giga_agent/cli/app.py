from __future__ import annotations

import typer

from .commands.alembic import alembic
from .commands.check import check
from .commands.dev import dev
from .commands.export_langgraph_json import export_langgraph_json
from .commands.makemigrations import makemigrations

app = typer.Typer()


def _register_commands() -> None:
    app.command(
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
    )(alembic)
    app.command()(check)
    app.command()(makemigrations)
    app.command()(dev)
    app.command()(export_langgraph_json)


_register_commands()
