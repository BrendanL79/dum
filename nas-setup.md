# Setting Up Image Update Manager on NAS

This guide will help you set up the Image Update Manager on your NAS in dry-run mode.

## Prerequisites

- Docker and Docker Compose installed on your NAS
- SSH access to your NAS
- Containers you want to monitor already running

## Setup Instructions

### 1. Create directories

```bash
# Create a directory for the updater
mkdir -p /volume1/docker/docker-updater
cd /volume1/docker/docker-updater

# Create subdirectories
mkdir -p config state
```

### 2. Copy files

Copy these files to your NAS:
- `ium.py`
- `Dockerfile`
- `requirements.txt`
- `docker-compose.yml`

### 3. Create your configuration

Create `/volume1/docker/docker-updater/config/config.json`:

```json
{
  "images": [
    {
      "image": "linuxserver/plex",
      "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$",
      "base_tag": "latest",
      "auto_update": false,
      "container_name": "plex"
    },
    {
      "image": "linuxserver/sonarr",
      "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$",
      "base_tag": "latest",
      "auto_update": false,
      "container_name": "sonarr"
    },
    {
      "image": "postgres",
      "regex": "^[0-9]+\\.[0-9]+$",
      "base_tag": "14",
      "auto_update": false,
      "container_name": "postgres"
    }
  ]
}
```

### 4. Build and run in dry-run mode

```bash
# Build the image
docker-compose build

# Run in dry-run mode (default)
docker-compose up -d

# Check logs to see what would be updated
docker-compose logs -f
```

### 5. Verify dry-run operation

The updater will:
- Check for updates every hour (3600 seconds)
- Log what it would do WITHOUT making any changes
- Show which containers have updates available
- Display the version changes (e.g., "v1.29.2-ls123 -> v1.29.3-ls124")

### 6. Monitor the logs

```bash
# View real-time logs
docker logs -f docker-updater

# View last 100 lines
docker logs --tail 100 docker-updater
```

## Configuration Options

### Per-image settings:

- `image`: Docker image name
- `regex`: Pattern to match version tags (use regex101.com to test)
- `base_tag`: Tag to track (default: "latest")
- `auto_update`: Set to true to enable updates (keep false for dry-run)
- `container_name`: Name of container to update
- `cleanup_old_images`: Remove old images after update (default: false)

### Environment variables:

- `CHECK_INTERVAL`: Seconds between checks (default: 3600)
- `LOG_LEVEL`: DEBUG, INFO, WARNING, or ERROR (default: INFO)

## Moving to Production

When you're ready to enable actual updates:

1. Edit `config/config.json` and set `"auto_update": true` for desired images
2. Use production mode:
   ```bash
   docker-compose down
   docker-compose --profile prod up -d
   ```

## Updating IUM

To update IUM to a newer version on your NAS:

```bash
cd /volume1/docker/docker-updater

# Stop the running containers
docker-compose down

# Replace the application files with the new version
# (ium.py, webui.py, Dockerfile, Dockerfile.webui,
# requirements.txt, requirements-webui.txt,
# docker-compose.yml, static/, templates/)

# Rebuild and restart
docker-compose build
docker-compose up -d
```

Your `config/` and `state/` directories are preserved across updates since they are volume-mounted.

## Safety Features

- Dry-run mode by default
- Read-only Docker socket mount in dry-run
- Container rollback on update failure
- State tracking prevents duplicate updates
- Comprehensive logging

## Troubleshooting

### Permission issues
```bash
# If you get permission errors, ensure the user has Docker access
sudo usermod -aG docker your-nas-user
```

### View state file
```bash
cat state/image_update_state.json | jq .
```

### Test single run
```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v $(pwd)/config:/config \
  -v $(pwd)/state:/state \
  docker-updater:latest \
  --dry-run \
  --log-level DEBUG \
  /config/config.json
```

## Common Regex Patterns

### LinuxServer.io images
```
^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$
```

### Semantic versions
```
^v?[0-9]+\.[0-9]+\.[0-9]+$
```

### PostgreSQL style
```
^[0-9]+\.[0-9]+$
```

### Date-based tags
```
^[0-9]{4}-[0-9]{2}-[0-9]{2}$
```