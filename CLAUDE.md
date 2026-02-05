# Docker Auto-Updater (dum)

Python-based Docker image auto-updater that tracks version-specific tags matching regex patterns alongside configurable base tags. Compares manifest digests to detect updates, recreates containers preserving all settings, with rollback on failure.

## Key Files
- `dum.py`: Core updater — `DockerImageUpdater` class, registry API, container management
- `webui.py`: Flask-SocketIO web interface with gunicorn/eventlet production server
- `static/js/app.js`: Frontend — Socket.IO, card-based config editor, live regex validation
- `static/css/style.css`: Web UI styling
- `templates/index.html`: Dashboard structure
- `docker-compose.yml`: Six deployment profiles (dry-run, prod, webui, webui-prod, combos)
- `config/config.json`: Image definitions (runtime, gitignored)
- `config/history.json`: Persistent update history (auto-managed, max 500 entries)
- `state/docker_update_state.json`: Current versions/digests (runtime, gitignored)

## Configuration Schema
```json
{
  "images": [{
    "image": "linuxserver/calibre",
    "regex": "^v[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$",
    "base_tag": "latest",
    "auto_update": false,
    "container_name": "calibre",
    "cleanup_old_images": true,
    "keep_versions": 3,
    "registry": "optional-custom-registry"
  }]
}
```

## Common Regex Patterns
- LinuxServer.io: `^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` or `^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$`
- Semantic versioning: `^v?[0-9]+\.[0-9]+\.[0-9]+$`
- PostgreSQL major.minor: `^[0-9]+\.[0-9]+$`

## Architecture
- **No Docker SDK** — direct HTTP to registries via `requests`, Docker socket for local operations
- **State persistence** via `ImageState` dataclass serialized to JSON with atomic writes (temp+rename)
- **Cross-platform** file locking (Unix fcntl / Windows msvcrt)
- **Registry auth**: Docker Hub, ghcr.io (/token endpoint), gcr.io, private registries
- **Manifest comparison**: HEAD requests for digest comparison, parallel tag fetching via ThreadPoolExecutor
- **Current version detection**: Cross-references container image ID with local image inventory
- **Config validation**: JSON schema (`CONFIG_SCHEMA`) validated on load and on web UI save
- **Web UI**: Vanilla JS + Socket.IO CDN, no build process; gunicorn with eventlet for WebSocket

## Deployment
| Profile | Socket | Mode | Command |
|---------|--------|------|---------|
| (default) | `:ro` | CLI dry-run | `docker-compose up -d` |
| `prod` | `:rw` | CLI auto-update | `docker-compose --profile prod up -d` |
| `webui` | `:ro` | Web UI dry-run | `docker-compose --profile webui up -d` |
| `webui-prod` | `:rw` | Web UI auto-update | `docker-compose --profile webui-prod up -d` |

Combine profiles for both CLI + Web UI. Never mount socket `:rw` unless auto-updates are intentional.

## Environment Variables
**CLI (`dum.py`)**: `--dry-run`, `--daemon`, `--interval SECONDS`, `--state PATH`, `--log-level LEVEL`, positional config path

**Web UI (`webui.py`)**: `CONFIG_FILE`, `STATE_FILE`, `DRY_RUN=true`, `LOG_LEVEL=INFO`, `SECRET_KEY`

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

## Dependencies
- **Core**: `requests`, `jsonschema`
- **Web UI**: `flask`, `flask-socketio`, `gunicorn`, `eventlet`, `jsonschema`
- Python 3.8+, tested on 3.11+

## NAS Deployment
See `nas-setup.md`. Standard mounts: docker socket, `./config:/config`, `./state:/state`.
