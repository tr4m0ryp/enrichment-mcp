# Container image for the enrichment-mcp FastMCP server (Cloud Run).
# Cloud Run injects $PORT (default 8080); config.py honors it.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code (src) + the schema (handy for one-off psql applies).
COPY src ./src
COPY schema ./schema

ENV MCP_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

# Cloud Run sets PORT; the server binds MCP_HOST:$PORT and serves /mcp.
CMD ["python", "-m", "src.mcp_server"]
