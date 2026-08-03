"""Deprecated CLI alias for :mod:`web_agent.commands`.

Use ``python -m web_agent`` for new automation. This module remains executable
so existing scripts using ``python -m web_agent.final`` continue to work.
"""

from web_agent.commands import (
    create_runner,
    main,
    production_dependencies,
    run_excel,
)

dependencies = production_dependencies

__all__ = [
    "create_runner",
    "dependencies",
    "main",
    "production_dependencies",
    "run_excel",
]


if __name__ == "__main__":
    raise SystemExit(main())
