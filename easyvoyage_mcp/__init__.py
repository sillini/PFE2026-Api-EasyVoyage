"""
mcp/__init__.py
===============
Package MCP EasyVoyage — Espace Admin.

Exporte l'instance FastMCP principale depuis server.py
pour que run_mcp.py puisse l'importer simplement.

Usage dans run_mcp.py :
    from mcp import mcp
    mcp.run()
"""
from easyvoyage_mcp.server import mcp

__all__ = ["mcp"]