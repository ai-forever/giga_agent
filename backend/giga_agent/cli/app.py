from __future__ import annotations

import typer

from .commands.alembic import alembic
from .commands.agents import agents_app
from .commands.check import check
from .commands.cli_chat import cli_chat
from .commands.dev import dev
from .commands.export_langgraph_json import export_langgraph_json
from .commands.makemigrations import makemigrations
from .commands.migrate import migrate

app = typer.Typer()


def _register_commands() -> None:
    app.add_typer(agents_app, name="agents")
    app.command(
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
    )(alembic)
    app.command()(check)
    app.command()(makemigrations)
    app.command()(migrate)
    app.command()(dev)
    app.command(name="cli")(cli_chat)
    app.command()(export_langgraph_json)


_register_commands()
