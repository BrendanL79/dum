# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-02-05

### Added
- Core updater engine with registry API integration (Docker Hub, ghcr.io, lscr.io, gcr.io, private registries)
- Web UI with real-time Socket.IO updates, card-based config editor, and update history
- 19 built-in image presets (LinuxServer, Jellyfin, Plex, Portainer, etc.)
- Auto-detect tag patterns from any registry, sorted by push recency
- Auto-detect base tags (latest, stable, lts, etc.)
- Auto-populate container name from image name
- Dry-run mode (enabled by default) for safe testing
- Flexible base tag tracking (latest, stable, lts, major versions, etc.)
- Regex-based version tag matching with live validation and test input
- Container management with full settings preservation and automatic rollback on failure
- State persistence with atomic file writes and cross-platform file locking
- Current version detection via container image inventory
- Optional basic authentication (WEBUI_USER/WEBUI_PASSWORD environment variables)
- Docker Compose profiles for CLI dry-run, CLI production, Web UI dry-run, and Web UI production
- Health checks in Docker images
- Persistent update history (max 500 entries)
- GitHub Actions CI/CD for automated testing and Docker Hub publishing
- MIT License
