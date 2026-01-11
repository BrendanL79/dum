# Docker Auto-Updater Context

## Project Overview
Python-based Docker image auto-updater that tracks version-specific tags matching regex patterns alongside base tags (e.g., "latest"). Originally created by Claude Opus 4.1 (bebfe84), enhanced with security fixes, web UI, and performance optimizations.

## Original Requirements (2025-09-28)
- Auto-update mechanism beyond simple "latest" tag pulling
- Track version-specific tags (e.g., v8.11.1-ls358) that match regex patterns
- Support different base tags per image (not just "latest")
- Architecture-agnostic solution
- Dry-run mode for testing

## Core Functionality
- Monitors Docker images for updates by comparing digests between base tag and regex-matched version tags
- Example: `linuxserver/calibre:latest` → `v8.11.1-ls358` via regex `^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$`
- Supports any base tag (not just "latest"): PostgreSQL uses base_tag="14"
- Multi-registry support: Docker Hub, gcr.io, private registries
- Architecture-aware via manifest lists
- State tracking prevents duplicate updates
- Container recreation preserves ALL settings with rollback on failure
- **Current version detection**: Cross-references container image IDs with local inventory to show current vs available versions

## Key Files
- `dum.py`: Main updater logic with DockerImageUpdater class (~900 lines)
- `webui.py`: Flask-SocketIO web interface with gunicorn production server (~320 lines)
- `docker-compose.yml`: Six deployment modes (dry-run, prod, webui, webui-prod, webui+dry-run, webui+prod)
- `config/config.json`: Image definitions with regex patterns (runtime, gitignored)
- `config/history.json`: Persistent update history (runtime, auto-managed, max 500 entries)
- `state/docker_update_state.json`: Tracks current versions/digests (runtime, gitignored)
- `static/js/app.js`: WebUI frontend with card-based config editor (~790 lines)
- `templates/index.html`: WebUI dashboard structure
- `static/css/style.css`: WebUI styling
- `README.md`: Comprehensive user documentation
- `README-webui.md`: API reference and developer guide for Web UI

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
- `keep_versions`: Number of image versions to retain when cleanup is enabled (default: 3)

## Security & Code Quality Improvements
- **Security fixes**: Fixed command injection, JSON schema validation, file locking, request timeouts
- **Exception handling**: Replaced bare `except:` with specific exception types (OSError, IOError, etc.)
- **Production hardening**: Cross-platform support (Unix fcntl, Windows msvcrt), proper subprocess usage
- **Code simplification (PR #2)**: Regex pattern caching, consolidated container inspection, dead code removal, `require_updater` decorator, `threading.Event` for efficient daemon sleep, DOM element caching, optional chaining

## Bug Fixes (cleanup-bugfixes branch)
- **Socket.IO threading**: Added `namespace='/'` to all `socketio.emit()` calls in background threads
- **Null tag handling**: Registry API can return `{"tags": null}`; fixed with `or []` pattern
- **Container config nulls**: Docker API returns `null` for empty arrays (CapAdd, Devices, etc.); fixed all `.get(key, [])` patterns
- **History 'Applied' status**: Now correctly checks both `dry_run` mode AND `auto_update` per-image setting
- **Defensive loading**: History file gracefully handles null/invalid JSON content

## Deployment Modes (6 Options)
1. **CLI Dry-run (default)**: `docker-compose up -d` - Safe monitoring only
2. **CLI Production**: `docker-compose --profile prod up -d` - Auto-updates enabled
3. **Web UI Only (dry-run)**: `docker-compose --profile webui up -d` - Browser interface (port 5050), monitoring only
4. **Web UI Only (production)**: `docker-compose --profile webui-prod up -d` - Browser interface with auto-updates
5. **Web UI + CLI Dry-run**: `docker-compose --profile webui up -d dum dum-webui` - Both services, monitoring only
6. **Web UI + CLI Production**: `docker-compose --profile webui-prod --profile prod up -d` - Full stack with auto-updates

## Web UI Features
- **Production-ready**: Gunicorn with eventlet workers, not Flask dev server
- **Real-time updates**: Socket.IO WebSocket for live status, check progress, daemon state
- **Dashboard**: Shows current vs available versions, connection status, mode indicator
- **Configuration editor**: Card-based GUI with form fields, expand/collapse, edit/delete per image
- **Live regex validation**: Test input field with colored match/no-match feedback
- **Manual checks**: Trigger update scans on-demand
- **Daemon control**: Start/stop background checking with configurable intervals
- **Update history**: Persistent history (survives restarts), tracks all checks with timestamps, applied vs dry-run indication
- **Activity log**: Real-time log streaming with color-coded severity
- **REST API**: Full API for integration (`/api/status`, `/api/config`, `/api/check`, `/api/state`, etc.)

## Critical Implementation Details
- **Docker API**: Direct HTTP requests to Docker socket for registry operations (manifest fetches)
- **Manifest digest comparison**: Compares SHA256 digests to detect updates, not just tag names
- **Container preservation**: Captures full container config before updates (env, volumes, networks, labels, etc.)
- **Rollback on failure**: If container fails to start post-update, reverts to old image automatically
- **Atomic state writes**: Temp file + rename for crash safety, platform-specific file locking (fcntl/msvcrt)
- **Dry-run mode**: Logs all operations without executing (default for safety)
- **Current version detection**: Cross-references container's image ID with local image inventory to find actual version tag (not just Config.Image which shows base tag)
- **Multi-registry support**: Docker Hub, gcr.io, ghcr.io (GitHub Container Registry uses /token endpoint)
- **Performance optimizations**:
  - HEAD requests for manifest digests (no body download, correct multi-arch comparison)
  - Parallel tag fetching with ThreadPoolExecutor (up to 10 concurrent, early termination on match)
  - Regex patterns compiled once at config load, cached in dictionary
  - Single container inspection call instead of 3+ subprocess invocations
  - Minimal string operations in image reference parsing

## Common Patterns
- LinuxServer.io (3-part): `^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` (e.g., sabnzbd)
- LinuxServer.io (with v): `^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$` (e.g., calibre)
- Semantic versioning: `^v?[0-9]+\.[0-9]+\.[0-9]+$` (e.g., portainer)
- PostgreSQL major.minor: `^[0-9]+\.[0-9]+$`

## Environment Variables & CLI Args
**CLI (dum.py)** - Uses command-line arguments:
- `--dry-run` - Safe mode, log operations without executing (default in docker-compose)
- `--daemon` - Run continuously instead of single check
- `--interval SECONDS` - Check interval for daemon mode (default: 3600)
- `--state PATH` - State file path (default: docker_update_state.json)
- `--log-level LEVEL` - DEBUG, INFO, WARNING, ERROR
- Positional: config file path

**Web UI (webui.py)** - Uses environment variables:
- `CONFIG_FILE=/config/config.json` - Path to image configuration
- `STATE_FILE=/state/docker_update_state.json` - Path to persistent state
- `DRY_RUN=true` - Safety default, set to "false" for auto-updates
- `LOG_LEVEL=INFO` - DEBUG, INFO, WARNING, ERROR
- `SECRET_KEY=change-me` - Flask session security (change in production)

## Docker Socket Permissions
- **Dry-run mode**: `:ro` (read-only) - Can inspect but not modify
- **Production mode**: `:rw` (read-write) - Required for container updates
- **Security**: Never mount socket read-write unless auto-updates are intentional

## NAS Deployment
See `nas-setup.md` for Synology/QNAP setup. Standard mounts:
- `/var/run/docker.sock:/var/run/docker.sock:ro` (or :rw for production)
- `./config:/config` (persistent, user-editable)
- `./state:/state` (persistent, auto-managed)

## Development Notes
**Dependencies:**
- Core: `requests`, `jsonschema` (for dum.py)
- Web UI: `flask`, `flask-socketio`, `gunicorn`, `eventlet` (for webui.py)
- Python 3.8+ compatible, tested on 3.11+

**Architecture:**
- No Docker Python SDK - direct socket HTTP requests via `requests` library
- State persistence via dataclasses (ImageState) serialized to JSON
- Web UI: Vanilla JavaScript, Socket.IO CDN, no build process required
- Production server: Gunicorn with eventlet workers for WebSocket support

**Code Style:**
- Type hints throughout (Tuple, Optional, Dict, etc.)
- Dataclasses for structured data (ImageState)
- Context managers for file locking
- Logging not print() statements

## Commit History
**Initial Development:**
- bebfe84: Initial output from Claude Opus 4.1
- 63ddb3d: Make base tag configurable
- f01fb76: Update README.md with AI warning
- fe869c9: Set up CLAUDE.md
- 47f1a10: First pass at dry run mode

**Security & Quality:**
- bb79953: Fix critical security vulnerabilities and improve code quality

**Web UI (PR #1):**
- 284db92: Merge webui branch - Flask-SocketIO interface, gunicorn production server, real-time updates

**Code Simplification (PR #2, squash merge):**
- bde2133: code-simplifier (2 passes) - Regex caching, consolidated container inspection, dead code removal, `require_updater` decorator, `threading.Event` for daemon sleep, DOM caching, optional chaining

**Web UI Config Editor (PR #4, squash merge):**
- fc0197d: Webui config take2 - Card-based GUI config editor, ghcr.io auth fix, improved version detection via image inventory, live regex validation with colored feedback

**State Tab Removal (PR #6):**
- e3e97c3: Remove unused State tab from Web UI (always showed empty in dry-run mode)

**Image Retention (PR #7):**
- 84c7fa0: Add configurable `keep_versions` option for image cleanup

**Cleanup & Bug Fixes (cleanup-bugfixes branch):**
- 367ddaa: Fix WebUI production mode with new `webui-prod` profile
- 3cc6521: Optimize registry API calls with HEAD requests and parallel fetching
- 119a9c0: Persist update history to `/config/history.json`
- 3159aca: Fix socket.emit from background threads
- d01e89e: Fix NoneType iteration error when registry returns null tags
- 7e85777: Fix null handling in container config parsing
- a6bf3b2: Fix history showing 'Applied' for images with auto_update=false

## Current Branch Status
- **main**: Production-ready with Web UI, code simplification, card-based config editor
- **claude/cleanup-bugfixes-1G3hk**: Performance optimizations, persistent history, bug fixes (pending merge)
- Old feature branches (webui, simplify1, etc.) have been merged via PRs and can be deleted

## Known Patterns & Anti-Patterns
**UI State Management:**
- ❌ Anti-pattern: Showing "All images are up to date!" before any check performed
- ✅ Solution: Check if `last_check` exists, show "No check performed yet" if null
- ❌ Anti-pattern: Displaying version as "unknown" when container is running
- ✅ Solution: Cross-reference container's image ID with local image inventory to find actual version tag
- ❌ Anti-pattern: Using Config.Image from docker inspect (shows base tag like "latest")
- ✅ Solution: Match image ID against all local images to find version-specific tag

**Performance:**
- ❌ Anti-pattern: Compiling regex patterns on every tag match attempt
- ✅ Solution: Compile once at config load, cache in dictionary
- ❌ Anti-pattern: Multiple `docker inspect` calls for same container
- ✅ Solution: Single inspection, extract all needed data at once
- ❌ Anti-pattern: Repeated `getElementById` calls for same elements
- ✅ Solution: Cache DOM references at initialization in `dom` object
- ❌ Anti-pattern: Busy-wait loop with 1-second sleeps for daemon interval
- ✅ Solution: Use `threading.Event.wait(timeout=interval)` for efficient blocking
- ❌ Anti-pattern: Sequential GET requests for each tag's manifest
- ✅ Solution: Parallel HEAD requests with ThreadPoolExecutor, early termination

**API Null Handling:**
- ❌ Anti-pattern: Using `.get('tags', [])` for registry API responses
- ✅ Solution: Use `.get('tags') or []` to handle both missing keys AND explicit null values
- ❌ Anti-pattern: Assuming Docker API arrays are never null
- ✅ Solution: Use `config.get('CapAdd') or []` pattern for all array fields (Env, Mounts, Devices, etc.)

**Git Workflow:**
- Systematic fixes: One commit per fix for clear history
- Feature branches: webui, simplify1 for isolated work
- Cherry-picking: Used to sync fixes between main and webui before merge
- Rebasing: `git pull --rebase` to keep linear history

## Testing Notes
**Local Development (Windows WSL):**
- Docker Desktop with WSL2 backend
- Test config monitors: sabnzbd (LinuxServer.io pattern), portainer (semantic version)
- WebUI tested on http://localhost:5050
- Dry-run mode default ensures safe testing

**Manual Testing Checklist:**
- [ ] Dry-run mode shows operations without executing
- [ ] Current version detection works for running containers
- [ ] WebUI shows "No check performed yet" on first load
- [ ] WebUI transitions to update list or "All up to date" after check
- [ ] Daemon start/stop works from WebUI
- [ ] Config save triggers updater reload
- [ ] Socket.IO real-time updates work (status, checks, daemon)
- [ ] No false "UPDATE AVAILABLE: X -> X" when versions match
- [ ] Card-based config editor: expand/collapse, add/edit/delete images
- [ ] Live regex validation shows colored match/no-match feedback
- [ ] ghcr.io images authenticate and fetch correctly
- [ ] Update history persists across WebUI restarts
- [ ] History correctly shows 'Dry Run' for auto_update=false images
- [ ] WebUI production mode (webui-prod profile) actually applies updates
- [ ] keep_versions limits retained images during cleanup