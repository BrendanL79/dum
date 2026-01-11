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
- **Current version detection**: Inspects running containers to show current vs available versions

## Key Files
- `dum.py`: Main updater logic with DockerImageUpdater class (~880 lines)
- `webui.py`: Flask-SocketIO web interface with gunicorn production server (~280 lines)
- `docker-compose.yml`: Five deployment modes (dry-run, prod, webui, webui+dry-run, webui+prod)
- `config/config.json`: Image definitions with regex patterns (runtime, gitignored)
- `state/docker_update_state.json`: Tracks current versions/digests (runtime, gitignored)
- `static/js/app.js`: WebUI frontend logic with Socket.IO real-time updates (~370 lines)
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
    "registry": "optional-custom-registry"
  }]
}
```

## Security & Code Quality Improvements
- **Security fixes (bb79953)**: Fixed command injection, JSON schema validation, file locking, request timeouts
- **Exception handling**: Replaced bare `except:` with specific exception types (OSError, IOError, etc.)
- **Production hardening**: Cross-platform support (Unix fcntl, Windows msvcrt), proper subprocess usage
- **Code simplification (simplify1 branch)** - Two analysis passes:
  - **Pass 1**: Regex pattern caching, consolidated container inspection, simplified parsing, removed validation indirection
  - **Pass 2**: Removed dead code (unused imports, variables, unreachable checks), added `require_updater` decorator, consolidated mount string construction, `threading.Event` for efficient daemon sleep, DOM element caching in JS, optional chaining

## Deployment Modes (5 Options)
1. **CLI Dry-run (default)**: `docker-compose up -d` - Safe monitoring only
2. **CLI Production**: `docker-compose --profile prod up -d` - Auto-updates enabled
3. **Web UI Only**: `docker-compose --profile webui up -d` - Browser interface (port 5050), dry-run mode
4. **Web UI + CLI Dry-run**: `docker-compose --profile webui up -d dum dum-webui` - Both services, monitoring only
5. **Web UI + CLI Production**: `docker-compose --profile webui --profile prod up -d` - Full stack with auto-updates

## Web UI Features (Merged to Main)
- **Production-ready**: Gunicorn with eventlet workers, not Flask dev server
- **Real-time updates**: Socket.IO WebSocket for live status, check progress, daemon state
- **Dashboard**: Shows current vs available versions, connection status, mode indicator
- **Configuration editor**: Edit JSON with syntax validation, auto-reload on save
- **Manual checks**: Trigger update scans on-demand
- **Daemon control**: Start/stop background checking with configurable intervals
- **Update history**: Track all checks with timestamps, applied vs dry-run indication
- **Activity log**: Real-time log streaming with color-coded severity
- **REST API**: Full API for integration (`/api/status`, `/api/config`, `/api/check`, etc.)
- **State display**: View tracked digests and last update timestamps

## Critical Implementation Details
- **Docker API**: Direct HTTP requests to Docker socket for registry operations (manifest fetches)
- **Manifest digest comparison**: Compares SHA256 digests to detect updates, not just tag names
- **Container preservation**: Captures full container config before updates (env, volumes, networks, labels, etc.)
- **Rollback on failure**: If container fails to start post-update, reverts to old image automatically
- **Atomic state writes**: Temp file + rename for crash safety, platform-specific file locking (fcntl/msvcrt)
- **Dry-run mode**: Logs all operations without executing (default for safety)
- **Current version detection**: Uses `docker inspect` to extract running container's image tag, validates against regex
- **Performance optimizations**:
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

**Security & Quality (main branch):**
- bb79953: Fix critical security vulnerabilities and improve code quality

**Web UI Development (webui branch, merged to main):**
- 94bcd24: Add web UI for Docker updater
- 7cb1e4f: Update CLAUDE.md with comprehensive project context
- c939cd0: Rename containers from docker-updater to dum
- 74a1dcc: Add current version detection from running containers
- 6c949bc: Replace development server with production-ready gunicorn
- 35b8f27: Improve UI state communication and daemon visibility
- 284db92: Merge webui into main (PR #1)

**Post-merge improvements (main branch):**
- 30f1c16: Rename containers from docker-updater to dum (main)
- eafaebb: Add current version detection from running containers (main)
- 9df7d1f: Complete rewrite of README.md with current features

**Code Simplification (simplify1 branch) - Pass 1:**
- 5fb75a7: Fix: Move platform detection to module level
- 2a447c4: Fix: Replace bare exception handlers with specific exceptions
- 9219b42: Fix: Make Docker socket permissions explicit in production
- df3fcd8: Fix: Cache compiled regex patterns for performance
- f0075cb: Fix: Consolidate container inspection calls
- 637e491: Fix: Simplify image reference parsing logic
- 9b2cf46: Fix: Simplify redundant state validation
- c717745: Update CLAUDE.md with comprehensive project context

**Code Simplification (simplify1 branch) - Pass 2:**
- b3d650b: Fix: Remove unused shlex import
- 8dc78c7: Fix: Remove dead code duplicate dry_run check
- 7073161: Fix: Replace unused updater_thread with daemon_thread declaration
- d92e4a2: Fix: Remove unused status variable from app.js
- c418f54: Fix: Consolidate duplicated mount string construction
- f8b02f5: Fix: Add require_updater decorator to reduce code duplication
- 9f8c428: Fix: Remove unnecessary else block returning None
- 8f82371: Fix: Use tuple instead of list for prefix iteration
- 5ee80bf: Fix: Use threading.Event for efficient daemon sleep
- d6f3bab: Fix: Cache DOM element references for better performance
- 5d5f422: Fix: Use optional chaining for cleaner null checks
- c59b134: Fix: Remove unused container_id variable

## Current Branch Status
- **main**: Production-ready with Web UI merged, comprehensive README
- **webui**: Merged into main (PR #1), can be deleted
- **simplify1**: Code quality improvements across two analysis passes
  - 20 commits total (8 from pass 1 + 12 from pass 2)
  - Pass 1: Performance optimizations (regex caching, reduced subprocess calls), code clarity
  - Pass 2: Dead code removal, reduced duplication (decorators, consolidated logic), modern JS patterns
  - Ready to merge after review

## Known Patterns & Anti-Patterns
**UI State Management:**
- ❌ Anti-pattern: Showing "All images are up to date!" before any check performed
- ✅ Solution: Check if `last_check` exists, show "No check performed yet" if null
- ❌ Anti-pattern: Displaying version as "unknown" when container is running
- ✅ Solution: Use `docker inspect` to extract actual running image tag

**Performance:**
- ❌ Anti-pattern: Compiling regex patterns on every tag match attempt
- ✅ Solution: Compile once at config load, cache in dictionary
- ❌ Anti-pattern: Multiple `docker inspect` calls for same container
- ✅ Solution: Single inspection, extract all needed data at once
- ❌ Anti-pattern: Repeated `getElementById` calls for same elements
- ✅ Solution: Cache DOM references at initialization in `dom` object
- ❌ Anti-pattern: Busy-wait loop with 1-second sleeps for daemon interval
- ✅ Solution: Use `threading.Event.wait(timeout=interval)` for efficient blocking

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