FROM python:3.12-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies only (cached as long as pyproject.toml doesn't change)
COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

# Copy source and install the local package — this layer always rebuilds when src/ changes
COPY src/ src/
RUN uv pip install --no-cache -e .

# Data directory (override with a volume in docker-compose)
RUN mkdir -p /data

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["dog-weather"]
