FROM python:3.11-slim

LABEL org.opencontainers.image.title="dum"
LABEL org.opencontainers.image.description="Docker Update Manager — CLI daemon"
LABEL org.opencontainers.image.source="https://github.com/BrendanL79/dum"
LABEL org.opencontainers.image.licenses="MIT"

# Install required packages
RUN apt-get update && apt-get install -y \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY dum.py .

# Create directories for config and state
RUN mkdir -p /config /state

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Health check — verify the daemon process is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD pgrep -f "python dum.py" || exit 1

# Default to dry-run mode for safety
ENTRYPOINT ["python", "dum.py"]
CMD ["--dry-run", "--log-level", "INFO", "--state", "/state/docker_update_state.json", "/config/config.json"]
