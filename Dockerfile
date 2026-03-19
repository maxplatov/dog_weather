FROM python:3.12-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project definition and source
COPY pyproject.toml .
COPY src/ src/

# Install dependencies into a venv inside /app
RUN uv sync --no-dev

# Data directory (override with a volume in docker-compose)
RUN mkdir -p /data

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

CMD ["dog-weather"]
