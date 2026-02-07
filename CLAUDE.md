# Image Update Manager (ium)

Python-based Docker image auto-updater that tracks version-specific tags matching regex patterns alongside configurable base tags. Compares manifest digests to detect updates, recreates containers preserving all settings, with rollback on failure.

## Key Files
- `ium.py`: Core updater — `DockerImageUpdater` class, registry API, container management
- `webui.py`: Flask-SocketIO web interface with gunicorn/gevent production server
- `static/js/app.js`: Frontend — Socket.IO, card-based config editor, live regex validation
- `static/css/style.css`: Web UI styling
- `templates/index.html`: Dashboard structure
- `docker-compose.yml`: Two services (ium Web UI default, ium-cli with `cli` profile)
- `config/config.json`: Image definitions (runtime, gitignored)
- `config/history.json`: Persistent update history (auto-managed, max 500 entries)
- `state/image_update_state.json`: Current versions/digests (runtime, gitignored)

## Configuration Schema
```json
{
  "images": [{
    "image": "linuxserver/calibre",
    "regex": "^v[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$",
    "base_tag": "latest",
    "auto_update": false,
    "cleanup_old_images": true,
    "keep_versions": 3,
    "registry": "optional-custom-registry"
  }]
}
```

**Note:** Containers are auto-detected. The updater automatically discovers and updates all containers using each configured image. Multiple containers with the same image (e.g., `sonarr-hd` and `sonarr-4k` both using `linuxserver/sonarr`) are all updated automatically.

## Common Regex Patterns
- LinuxServer.io: `^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` or `^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$`
- Semantic versioning: `^v?[0-9]+\.[0-9]+\.[0-9]+$`
- PostgreSQL major.minor: `^[0-9]+\.[0-9]+$`

## Architecture
- **No Docker SDK** — direct HTTP to registries via `requests`, Docker socket for local operations
- **Auto-discovery** — `docker ps -a --format json` scans all containers, matches by image name with registry/tag normalization
- **State persistence** via `ImageState` dataclass serialized to JSON with atomic writes (temp+rename)
- **Cross-platform** file locking (Unix fcntl / Windows msvcrt)
- **Registry auth**: Docker Hub, ghcr.io (/token endpoint), gcr.io, private registries
- **Manifest comparison**: HEAD requests for digest comparison, parallel tag fetching via ThreadPoolExecutor
- **Current version detection**: Cross-references container image ID with local image inventory
- **Multi-container updates**: Parallel updates with per-container success tracking
- **Config validation**: JSON schema (`CONFIG_SCHEMA`) validated on load and on web UI save
- **Web UI**: Vanilla JS + Socket.IO CDN, no build process; gunicorn with gevent for WebSocket

## Deployment
| Service | Profile | Command |
|---------|---------|---------|
| Web UI (`ium`) | (default) | `docker-compose up -d` |
| CLI daemon (`ium-cli`) | `cli` | `docker-compose --profile cli up -d ium-cli` |

Both services mount the Docker socket `:rw`. Updates are safe by default — `auto_update` is `false` per image.

## Environment Variables
**CLI (`ium.py`)**: `--dry-run`, `--daemon`, `--interval SECONDS`, `--state PATH`, `--log-level LEVEL`, positional config path. All flags have env var equivalents: `DRY_RUN`, `DAEMON`, `CHECK_INTERVAL`, `STATE_FILE`, `LOG_LEVEL`, `CONFIG_FILE`

**Web UI (`webui.py`)**: `CONFIG_FILE`, `STATE_FILE`, `DRY_RUN=false`, `LOG_LEVEL=INFO`, `WEBUI_USER`, `WEBUI_PASSWORD`

## Code Conventions
- **Type hints** throughout (Tuple, Optional, Dict, etc.)
- **Dataclasses** for structured data (`ImageState`)
- **Logging** not print(), specific exception types (no bare `except:`)
- **Null handling**: Use `or []` pattern for API responses that may return explicit `null` (registry tags, Docker arrays like CapAdd, Devices, Env, Mounts)
- **Regex caching**: Patterns compiled once at config load in `compiled_patterns` dict
- **DOM caching**: Frontend caches element references in `dom` object at init
- **Socket.IO**: All `socketio.emit()` from background threads must include `namespace='/'`
- **State updates**: State is updated whenever a new version is detected, regardless of `auto_update` setting, to prevent re-reporting in daemon mode. Disk persistence is skipped in dry-run mode.
- **Config booleans**: `auto_update` and `cleanup_old_images` are always saved explicitly (including `false`), never omitted
- **Auth**: Optional basic auth via `WEBUI_USER`/`WEBUI_PASSWORD` env vars; `hmac.compare_digest` for credential checks
- **Versioning**: `__version__` in `ium.py`, semver, CI publishes Docker images on `v*` tags

## Dependencies
- **Core**: `requests`, `jsonschema`
- **Web UI**: `flask`, `flask-socketio`, `gunicorn`, `gevent`, `gevent-websocket`, `jsonschema`
- Python 3.8+, tested on 3.11+

## NAS Deployment
See `nas-setup.md`. Standard mounts: docker socket, `./config:/config`, `./state:/state`.
