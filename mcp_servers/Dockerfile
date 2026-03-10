FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY . .

# Default: run restaurant server on HTTP
ENV MCP_SERVER=restaurant
ENV MCP_RESTAURANT_PORT=8800
ENV MCP_BARBERSHOP_PORT=8801

EXPOSE 8800 8801

CMD ["sh", "-c", "python -m mcp_servers.${MCP_SERVER}.server --http"]
