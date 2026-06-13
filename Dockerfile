FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install build dependencies and Python build backend
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python build tool
RUN pip install --no-cache-dir hatchling

# Copy project files
COPY pyproject.toml pyproject.toml
COPY src src
COPY README.md README.md
COPY .env.example .env.example

# Install the package and runtime dependencies
RUN pip install --no-cache-dir .

# Off-laptop deployment defaults: streamable-HTTP, bind all interfaces, fixed port.
# (host/port are read from FASTMCP_* by FastMCP at startup; transport from MCP_TRANSPORT)
ENV MCP_TRANSPORT=streamable-http \
    FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8000

EXPOSE 8000

# Run the server as an installed module so imports resolve regardless of CWD
CMD ["python", "-m", "intervals_mcp_server.server"]
