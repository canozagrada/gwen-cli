"""GWEN - Multi-Agent Cloud Status Monitor

Modern Python package for monitoring cloud service status.
"""
from .cli import main as cli_main
from .server import main as server_main

__version__ = "1.0.0"
__all__ = ["cli_main", "server_main"]
