"""
Shared MCP instance module.

This module provides a shared FastMCP instance that can be imported by both
the server module and tool modules without creating cyclic imports.
"""

from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error

# Pas de lifespan : FastMCP l'exécute par session (par requête en mode sans état), et y fermer le
# client httpx partagé coupait les requêtes en cours des autres appels.
mcp: FastMCP = FastMCP("intervals-icu")  # pylint: disable=invalid-name
