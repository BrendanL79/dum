FROM python:3.14-alpine

LABEL org.opencontainers.image.title="ium-cli"
LABEL org.opencontainers.image.description="Image Update Manager — CLI daemon"
LABEL org.opencontainers.image.source="https://github.com/BrendanL79/ium"
LABEL org.opencontainers.image.licenses="MIT"

# Create app directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
# Install Python packages (requests and jsonschema are pure Python, no build deps needed)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY ium.py pattern_utils.py ./

# Create directories for config and state
RUN mkdir -p /config /state

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CONFIG_FILE=/config/config.json
ENV STATE_FILE=/state/image_update_state.json
ENV DRY_RUN=false
ENV DAEMON=true
ENV CHECK_INTERVAL=3600
ENV LOG_LEVEL=INFO

# Health check — verify the daemon process is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD pgrep -f "python ium.py" || exit 1

CMD ["python", "ium.py"]
