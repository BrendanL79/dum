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
- `dum.py`: Main updater logic with DockerImageUpdater class (~850 lines)
- `webui.py`: Flask-SocketIO web interface with gunicorn production server (~400 lines)
- `docker-compose.yml`: Five deployment modes (dry-run, prod, webui, webui+dry-run, webui+prod)
- `config/config.json`: Image definitions with regex patterns (runtime, gitignored)
- `state/docker_update_state.json`: Tracks current versions/digests (runtime, gitignored)
- `static/js/app.js`: WebUI frontend logic with Socket.IO real-time updates
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
- **Code simplification (simplify1 branch)**:
  - Regex pattern caching eliminates redundant compilation
  - Reduced container inspection from 3+ subprocess calls to 1
  - Simplified image reference parsing (eliminated redundant string operations)
  - Removed unnecessary validation indirection layers

## Deployment Modes (5 Options)
1. **CLI Dry-run (default)**: `docker-compose up -d` - Safe monitoring only
2. **CLI Production**: `docker-compose --profile prod up -d` - Auto-updates enabled
3. **Web UI Only**: `docker-compose --profile webui up -d` - Browser monitoring (port 5050)
4. **Web UI + Dry-run**: Both services together for monitoring with browser interface
5. **Web UI + Production**: `docker-compose --profile webui --profile prod up -d` - Full stack with auto-updates

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
- LinuxServer.io: `^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$`
- Semantic: `^v?[0-9]+\.[0-9]+\.[0-9]+$`
- PostgreSQL: `^[0-9]+\.[0-9]+$`

## Environment Variables
**CLI (dum.py):**
- `CONFIG_FILE=/config/config.json` - Path to image configuration
- `STATE_FILE=/state/docker_update_state.json` - Path to persistent state
- `DRY_RUN=true` - Safety default, set to false for auto-updates
- `LOG_LEVEL=INFO` - DEBUG, INFO, WARNING, ERROR
- `CHECK_INTERVAL=3600` - Seconds between daemon checks (CLI mode)

**Web UI (webui.py):**
- Same as above, plus:
- `SECRET_KEY=dev-secret-key-change-in-production` - Flask session security

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

**Code Simplification (simplify1 branch):**
- 5fb75a7: Fix: Move platform detection to module level
- 2a447c4: Fix: Replace bare exception handlers with specific exceptions
- 9219b42: Fix: Make Docker socket permissions explicit in production
- df3fcd8: Fix: Cache compiled regex patterns for performance
- f0075cb: Fix: Consolidate container inspection calls
- 637e491: Fix: Simplify image reference parsing logic
- 9b2cf46: Fix: Simplify redundant state validation

## Current Branch Status
- **main**: Production-ready with Web UI merged, comprehensive README
- **webui**: Merged into main (PR #1), can be deleted
- **simplify1**: Code quality improvements, ready for review/merge
  - 7 commits total (3 critical + 4 high-priority fixes)
  - Performance optimizations (regex caching, reduced subprocess calls)
  - Code clarity improvements (simplified parsing, removed indirection)
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