# Stage 1: Get Docker CLI binary
FROM docker:27-cli AS docker-cli

# Stage 2: Build final image
FROM python:3.11-alpine

LABEL org.opencontainers.image.title="dum-cli"
LABEL org.opencontainers.image.description="Docker Update Manager — CLI daemon"
LABEL org.opencontainers.image.source="https://github.com/BrendanL79/dum"
LABEL org.opencontainers.image.licenses="MIT"

# Copy only the docker CLI binary from official image
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
# Install Python packages (requests and jsonschema are pure Python, no build deps needed)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY dum.py .

# Create directories for config and state
RUN mkdir -p /config /state

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CONFIG_FILE=/config/config.json
ENV STATE_FILE=/state/docker_update_state.json
ENV DRY_RUN=false
ENV DAEMON=true
ENV CHECK_INTERVAL=3600
ENV LOG_LEVEL=INFO

# Health check — verify the daemon process is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD pgrep -f "python dum.py" || exit 1

CMD ["python", "dum.py"]
