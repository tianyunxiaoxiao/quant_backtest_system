"""CLI 入口。"""

from __future__ import annotations


def main(argv: list[str] | None = None) -> int:
    """Load the command implementation lazily for ``python -m qbt.cli.main`` safety."""
    from qbt.cli.main import main as run_main

    return run_main(argv)

__all__ = ["main"]
