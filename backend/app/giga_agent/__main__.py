"""
Entry point for `python -m giga_agent`.

The project CLI is implemented in `giga_agent.cli` and exposed as a console script
via `pyproject.toml` (`giga_agent = giga_agent.cli:app`). Some IDE run
configurations prefer `python -m <package> ...`, so we provide this shim.
"""

from __future__ import annotations


def main() -> None:
    from giga_agent.cli import app

    app(prog_name="giga_agent")


if __name__ == "__main__":
    main()
