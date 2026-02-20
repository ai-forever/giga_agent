from __future__ import annotations

import typer

from .commands.alembic import alembic
from .commands.check import check
from .commands.dev import dev
from .commands.makemigrations import makemigrations

app = typer.Typer()


def _register_commands() -> None:
    app.command(
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
    )(alembic)
    app.command()(check)
    app.command()(makemigrations)
    app.command()(dev)


_register_commands()

