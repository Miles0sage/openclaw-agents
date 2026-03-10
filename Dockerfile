# Multi-stage Dockerfile for OpenClaw Python Gateway
# Optimized for production deployment with security hardening

# ===== Stage 1: Builder =====
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# ===== Stage 2: Runtime =====
FROM python:3.13-slim

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with proper permissions
RUN groupadd -r openclaw && \
    useradd -r -g openclaw -u 1000 -d /app -s /sbin/nologin openclaw

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code with proper ownership
COPY --chown=openclaw:openclaw gateway.py .
COPY --chown=openclaw:openclaw orchestrator.py .
COPY --chown=openclaw:openclaw cost_tracker.py .
COPY --chown=openclaw:openclaw quota_manager.py .
COPY --chown=openclaw:openclaw complexity_classifier.py .
COPY --chown=openclaw:openclaw heartbeat_monitor.py .
COPY --chown=openclaw:openclaw agent_router.py .
COPY --chown=openclaw:openclaw config.json .
COPY --chown=openclaw:openclaw dashboard_api.py .

# Create runtime directories
RUN mkdir -p /app/sessions /app/logs \
        /app/data/jobs/runs \
        /app/data/clients \
        /app/data/sessions \
        /app/data/costs \
        /app/data/events \
        /app/data/reviews \
        /app/data/memories \
        /app/data/workflows \
        /app/data/tasks \
        /app/data/agents && \
    chown -R openclaw:openclaw /app/sessions /app/logs /app/data

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENCLAW_DATA_DIR=/app/data \
    OPENCLAW_SESSIONS_DIR=/app/data/sessions \
    OPENCLAW_LOGS_DIR=/app/logs

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Switch to non-root user
USER openclaw

# Run the gateway with production settings
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info", "--workers", "4"]
