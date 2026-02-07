# Docker Hub Publication Release — v1.0.0

## Goal

Publish ium to Docker Hub as `brendanl79/ium` (CLI) and `brendanl79/ium-webui` (Web UI) at version 1.0.0. Address security, infrastructure, and packaging gaps to meet the expectations of public Docker Hub users.

## Decisions

| Topic | Decision | Rationale |
|-------|----------|-----------|
| Authentication | Optional basic auth via env vars | Doesn't break LAN users, protects exposed installs |
| CORS | Same-origin only | `*` was dev-only; reverse proxies are same-origin |
| Versioning | Semver (1.0.0) | Config schema is an API contract; signals stability |
| Root user | Keep root, document why | Portainer/Watchtower precedent; socket access requires it |
| Multi-stage builds | Defer | Optimization, not blocking for v1.0.0 |
| Base image pinning | Defer | Adds maintenance overhead without automated dependency updates |

## Changes

### 1. Optional Basic Auth

Two env vars control auth:
- `WEBUI_USER` — username (no default)
- `WEBUI_PASSWORD` — password (no default)

When both are set, all HTTP requests and Socket.IO connections require basic auth. When either is unset, auth is disabled (current behavior).

Implementation:
- `check_auth()` function returns 401 with `WWW-Authenticate: Basic` header on failure, triggering the browser's native login prompt (no login page needed)
- Applied via `@app.before_request` to cover all routes including API
- Socket.IO auth checked in the `connect` event handler
- Credentials compared with `hmac.compare_digest` to prevent timing attacks
- Docker-compose env vars commented out by default

### 2. Docker Hardening

**`.dockerignore`:**
```
.claude/
.git/
config/
state/
tests/
__pycache__/
*.md
*.txt
!requirements*.txt
docker-compose.yml
Dockerfile*
```

**CORS** — remove `cors_allowed_origins="*"` from SocketIO constructor. Flask-SocketIO defaults to same-origin.

**Secret key** — generate a random key at startup if `SECRET_KEY` env var is not set. No more hardcoded `dev-secret-key`. Sessions won't persist across restarts, which is fine — no login state when auth is disabled.

**Health checks** in Dockerfiles:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:5050/api/status || exit 1
```
CLI Dockerfile checks process existence instead (no HTTP server).

**OCI labels** — maintainer, description, source URL, license. Version label injected via build arg from CI.

**Root user** — keep as-is. Document the Docker socket requirement in README security section (same pattern as Portainer, Watchtower, Diun).

### 3. Project Infrastructure

**Version tracking:**
- `__version__ = "1.0.0"` in `ium.py`
- `/api/version` endpoint in `webui.py`
- Version displayed in Web UI footer

**CHANGELOG.md:**
- Start with 1.0.0 documenting current features as initial release
- Keep a Changelog format (Added/Changed/Fixed sections)

**`.env.example`:**
```env
CONFIG_FILE=/config/config.json
STATE_FILE=/state/image_update_state.json
DRY_RUN=true
LOG_LEVEL=INFO
# SECRET_KEY=your-secret-here
# WEBUI_USER=admin
# WEBUI_PASSWORD=changeme
```

**GitHub Actions CI/CD** (`.github/workflows/release.yml`):
- On push to `main`: run `pytest tests/ --ignore=tests/test_live.py`
- On tag push (`v*`): run tests, build and push both images to Docker Hub tagged with version and `latest`
- Docker Hub credentials as GitHub repo secrets (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`)

## Out of Scope

- Multi-stage Docker builds (future optimization)
- Base image pinning (needs automated dependency updates first)
- Login page UI (browser native basic auth prompt is sufficient)
- Additional test coverage (current 251 tests are adequate for v1.0.0)
