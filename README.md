# Image Update Manager (ium)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Docker image auto-updater that tracks version-specific tags matching regex patterns alongside configurable base tags. Compares manifest digests via registry APIs to detect updates, recreates containers preserving all settings, with rollback on failure.

## Features

- **Web UI**: Browser-based dashboard with real-time Socket.IO updates, card-based config editor, and update history
- **Image Presets**: 19 pre-configured popular images (LinuxServer, Jellyfin, Plex, Portainer, etc.) with known tag patterns
- **Auto-Detect Patterns**: Fetches tags from any registry and suggests regex patterns sorted by push recency
- **Dry-run Mode**: Safe testing without making changes (enabled by default)
- **Flexible Base Tag Tracking**: Track any base tag - not just "latest" (e.g., stable, mainline, lts, major versions)
- **Regex-based Matching**: Define custom patterns for version tags per image, with live validation and test input
- **Multi-Registry Support**: Docker Hub, ghcr.io, lscr.io, gcr.io, and private registries
- **Container Management**: Preserves all container settings during updates with automatic rollback on failure
- **State Persistence**: Tracks current versions/digests with atomic file writes and cross-platform file locking
- **Current Version Detection**: Cross-references container image IDs with local image inventory
- **Optional Authentication**: Basic auth via environment variables, or use a reverse proxy
- **Production Ready**: Gunicorn with gevent for WebSocket support, Docker health checks, CI/CD

## Quick Start

### Using Docker Compose (Recommended)

1. **Clone and configure:**
```bash
git clone https://github.com/BrendanL79/ium.git
cd ium
mkdir -p config state
```

You can create `config/config.json` manually or use the Web UI to configure images via presets and auto-detection.

2. **Choose your deployment mode:**

```bash
# Web UI (default)
docker-compose up -d

# CLI daemon only
docker-compose --profile cli up -d ium-cli
```

3. **Access Web UI** (if enabled): http://localhost:5050

### Starting from Scratch

If you have no config file yet, start the Web UI and create one from the browser:

```bash
echo '{"images": []}' > config/config.json
docker-compose up -d --build
```

Then open http://localhost:5050, go to the Configuration tab, and use **Add from Preset** to quickly add known images or **+ Add Image** for any image (patterns are auto-detected when you enter the image name).

## How It Works

1. **Registry API Integration**: Queries registries directly via HTTP — no images are pulled for checking
2. **Base Tag Tracking**: Monitors your chosen base tag (latest, stable, lts, major version, etc.)
3. **Digest Comparison**: Compares manifest digests to identify when the base tag points to a new version
4. **Pattern Matching**: Uses your regex patterns to find the version-specific tag with the same digest
5. **Current Version Detection**: Checks running containers to determine currently installed versions
6. **Smart Updates**: Only reports/applies updates when actual changes are detected
7. **State Management**: Maintains a state file to track current versions; update history persisted separately

### The Base Tag Concept

The `base_tag` is the moving target you want to track:
- **"latest"** - The default, tracks the newest release
- **"15"** (PostgreSQL) - Tracks the latest patch within major version 15
- **"stable"** (Home Assistant) - Tracks the stable channel
- **"lts"** (Node.js, Portainer) - Tracks the Long Term Support version
- **"mainline"** (nginx) - Tracks the mainline development branch

The regex pattern then finds the specific version tag (e.g., "15.4-alpine", "2024.1.5", "v8.11.1-ls358") that currently corresponds to your base tag.

## Configuration

### Image Configuration Fields

| Field | Type | Description | Required | Default |
|-------|------|-------------|----------|---------|
| `image` | string | Docker image name (e.g., "nginx", "user/repo") | Yes | - |
| `regex` | string | Regex pattern to match version tags | Yes | - |
| `base_tag` | string | Base tag to track (e.g., "latest", "stable", "15") | No | "latest" |
| `auto_update` | boolean | Whether to automatically pull and update | No | false |
| `cleanup_old_images` | boolean | Remove old images after successful update | No | false |
| `keep_versions` | integer | Number of image versions to retain when cleanup is enabled | No | 3 |
| `registry` | string | Custom registry URL (e.g., "ghcr.io", "lscr.io") | No | Docker Hub |

**Note:** Containers are auto-detected. The updater automatically discovers and updates all containers using each configured image.

### Example Configuration

```json
{
  "images": [
    {
      "image": "linuxserver/sonarr",
      "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$",
      "base_tag": "latest",
      "auto_update": false,
      "cleanup_old_images": true,
      "keep_versions": 3
    },
    {
      "image": "portainer/portainer-ce",
      "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
      "base_tag": "lts",
      "auto_update": false
    },
    {
      "image": "homarr-labs/homarr",
      "regex": "^v[0-9]+\\.[0-9]+\\.[0-9]+$",
      "registry": "ghcr.io",
      "auto_update": false
    }
  ]
}
```

### Common Regex Patterns

These patterns are also available as built-in presets in the Web UI:

| Pattern | Regex | Example Images |
|---------|-------|----------------|
| Semantic version | `^[0-9]+\.[0-9]+\.[0-9]+$` | portainer-ce, jellyfin, n8n, pihole |
| Semver with v-prefix | `^v[0-9]+\.[0-9]+\.[0-9]+$` | homarr, mealie |
| LinuxServer 3-part | `^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` | calibre-web, sabnzbd |
| LinuxServer v-prefix | `^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` | bazarr, calibre, tautulli |
| LinuxServer 4-part | `^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` | sonarr, radarr, prowlarr, lidarr |
| LinuxServer with -r | `^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+-ls[0-9]+$` | qbittorrent |
| 4-part + hex hash | `^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$` | pms-docker (Plex) |
| PostgreSQL major | `^15\.[0-9]+$` | postgres (pin to major version) |

**Regex Tips:**
- Use `^` and `$` anchors to match the entire tag
- Escape dots with `\\` in JSON (e.g., `\\.` for literal dots)
- Use the Web UI's regex test input to validate patterns before saving
- **Auto-detect**: Enter an image name in the Web UI and patterns are suggested automatically

## Deployment Modes

All modes are safe by default — `auto_update` is `false` per image until you explicitly enable it.

### 1. Web UI (Default)
```bash
docker-compose up -d
```
- Web interface at http://localhost:5050
- Card-based configuration editor with presets and auto-detect
- Real-time monitoring, daemon control, and update history

### 2. CLI Daemon
```bash
docker-compose --profile cli up -d ium-cli
```
- Background daemon, hourly checks (configurable via `CHECK_INTERVAL`)
- Monitor logs: `docker logs -f ium-cli`

### 3. Web UI + CLI Daemon
```bash
docker-compose --profile cli up -d
```
- Both services share config and state

### 4. Standalone CLI
```bash
python ium.py config/config.json [options]
```

**Options (all have env var equivalents):**
- `--dry-run` - Don't make actual changes (`DRY_RUN`)
- `--daemon` - Run continuously (`DAEMON`)
- `--interval SECONDS` - Check interval, default: 3600 (`CHECK_INTERVAL`)
- `--log-level LEVEL` - DEBUG, INFO, WARNING, ERROR, default: INFO (`LOG_LEVEL`)
- `--state FILE` - State file path (`STATE_FILE`)

## Docker Compose Services

| Service | Description | Profile |
|---------|-------------|---------|
| `ium` | Web UI | (default) |
| `ium-cli` | CLI daemon | `cli` |

Both services share the `ium-net` bridge network.

**Volumes:**
- `./config:/config` - Configuration and update history
- `./state:/state` - State tracking (current versions/digests)
- `/var/run/docker.sock:/var/run/docker.sock` - Docker access

## Environment Variables

| Variable | Description | Default | Used by |
|----------|-------------|---------|---------|
| `CONFIG_FILE` | Path to config JSON | `/config/config.json` | Both |
| `STATE_FILE` | Path to state JSON | `/state/image_update_state.json` | Both |
| `DRY_RUN` | Enable dry-run mode | `false` | Both |
| `DAEMON` | Run continuously | `true` | CLI |
| `CHECK_INTERVAL` | Seconds between checks | `3600` | CLI |
| `LOG_LEVEL` | Logging verbosity | `INFO` | Both |
| `WEBUI_USER` | Basic auth username (optional) | (disabled) | Web UI |
| `WEBUI_PASSWORD` | Basic auth password (optional) | (disabled) | Web UI |

## Web UI Guide

### Updates Tab
- **Status bar**: Connection state, mode indicator (DRY RUN / PRODUCTION), daemon status, last check time
- **Controls**: Check Now, Start/Stop Daemon, Refresh Config, interval setting
- Shows available updates with old -> new version, or "All images are up to date!"

### Configuration Tab
- **Add from Preset**: Modal with 19 pre-configured images, filterable, with regex patterns and example tags. Already-configured images are grayed out.
- **+ Add Image**: Blank card for any image. When you enter an image name and leave the field, the top 3 tag patterns are auto-detected from the registry.
- **Detect Patterns**: Manual button to fetch all patterns from the registry for any image.
- **Card editor**: Each image is a collapsible card with fields for registry, image name, regex, test tag, base tag, container name, auto-update, cleanup, and keep versions.
- **Regex validation**: Live feedback on pattern validity, plus a test input to check if a specific tag matches.
- **Save Configuration**: Validates all cards and saves to disk, reloading the updater.

### History Tab
- Persistent log of detected updates (max 500 entries, stored in `config/history.json`)
- Shows timestamp, image, old -> new tag, and whether the update was applied or dry-run

### Activity Log
- Real-time log output at the bottom of the page
- Color-coded by severity (info, warning, error)
- Auto-scrolls to newest entries, keeps last 100 lines

## Container Update Process

When `auto_update: true` and an update is detected:

1. **Pull** new image with base tag and version tag
2. **Inspect** running container to get full configuration
3. **Stop** running container
4. **Rename** old container as backup (with timestamp)
5. **Create** new container with identical settings
6. **Start** new container
7. **Verify** new container started successfully
8. **Remove** old container backup
9. **Optional**: Cleanup old images if `cleanup_old_images: true` (keeps `keep_versions` most recent)

**On failure:** Automatically rolls back by restoring the backup container and logging the error.

**Settings preserved:** Environment variables, volumes, networks, port mappings, restart policy, labels, capabilities, devices, and all other Docker container configuration.

## Security Considerations

### Docker Socket Access
- **Dry-run mode** mounts the socket read-only (`:ro`) - safe for monitoring
- **Production mode** requires write access (`:rw`) for pulling images and recreating containers
- Containers run as root because Docker socket access requires it (same as Portainer, Watchtower, Diun)

### Web UI Security
- **Authentication**: Set `WEBUI_USER` and `WEBUI_PASSWORD` environment variables to enable basic auth. When both are set, all HTTP and WebSocket connections require credentials. When unset, access is unrestricted (suitable for trusted LANs).
- Runs on port 5050 by default

### Best Practices
1. **Always test with dry-run first**
2. **Start with `auto_update: false`** and review updates manually
3. **Use specific base tags** (e.g., `15` not `latest`) for critical services
4. **Enable `cleanup_old_images`** to prevent disk space issues
5. **Monitor logs** for failed updates

## Troubleshooting

**"No check performed yet" persists**
- Click "Check Now" to trigger first check
- Verify container is running: `docker ps --filter "name=ium"`
- Check logs: `docker logs ium`

**"No tag matching pattern found"**
- Use the Web UI's regex test input to validate your pattern against a known tag
- Try "Detect Patterns" to see what patterns the registry actually has
- Remember to escape backslashes in JSON: `\\.` for literal dot

**"Container not found" or "unknown" version**
- Ensure `container_name` matches exactly: `docker ps --format '{{.Names}}'`
- Container must be running to detect current version

**Web UI shows "Disconnected"**
- Check container is running and port 5050 is accessible
- Review logs: `docker logs ium`

**Updates not applying in production mode**
- Verify `auto_update: true` in config
- Ensure Docker socket has write access (`:rw`)
- Confirm not running in dry-run mode (`DRY_RUN=false`)

### Debug Mode

```bash
# Via environment variable
LOG_LEVEL=DEBUG

# Via CLI
python ium.py config.json --log-level DEBUG
```

## NAS Deployment

See `nas-setup.md` for detailed instructions. Quick start:

```bash
cd /volume1/docker
git clone https://github.com/BrendanL79/ium.git
cd ium
mkdir -p config state
echo '{"images": []}' > config/config.json
docker-compose up -d --build
```

Access the Web UI at `http://<NAS-IP>:5050` to configure images via presets.

## Testing

The project includes a test suite under `tests/`:

```bash
pip install -r requirements.txt
pytest tests/
```

Test modules cover configuration validation, tag pattern detection, image reference parsing, regex patterns, and state management.

## Project Structure

```
ium/
├── ium.py                      # Core updater engine
├── webui.py                    # Flask-SocketIO web server
├── Dockerfile                  # CLI daemon image
├── Dockerfile.webui            # Web UI image
├── docker-compose.yml          # Multi-profile deployment
├── requirements.txt            # Core dependencies
├── requirements-webui.txt      # Web UI dependencies
├── .env.example                # Environment variable reference
├── CHANGELOG.md                # Version history
├── config_example.json         # Example configuration
├── templates/
│   └── index.html              # Dashboard HTML
├── static/
│   ├── css/style.css           # Web UI styles
│   └── js/app.js               # Frontend (Socket.IO, config editor, presets)
├── tests/                      # Test suite
├── .github/workflows/          # CI/CD (test on push, publish on tag)
├── config/                     # Runtime config (gitignored)
│   ├── config.json
│   └── history.json            # Persistent update history
└── state/                      # Runtime state (gitignored)
    └── image_update_state.json
```

## Roadmap

- Email/webhook notifications
- Rollback functionality via Web UI
- Update scheduling/maintenance windows
- Private registry authentication UI
- Multi-stage Docker builds for smaller images
