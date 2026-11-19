"""MCP-сервер Троеточия."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("troetochie-mcp")
except PackageNotFoundError:  # запуск из исходников без установки
    __version__ = "0.0.0-dev"
