"""Compatibility export to the stable CLI command implementation."""

from web_agent.commands import (
    _normalized_argv,
    build_parser,
    create_runner,
    main,
    production_dependencies,
    run_excel,
    run_planned_task,
)

__all__ = [
    "_normalized_argv", "build_parser", "create_runner", "main",
    "production_dependencies", "run_excel", "run_planned_task",
]
