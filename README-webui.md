# Image Update Manager Web UI

This branch adds a web-based interface for the Image Update Manager.

## Features

- **Real-time Status**: See which containers have updates available
- **Manual Checks**: Trigger update checks with one click
- **Daemon Control**: Start/stop automatic checking from the web
- **Configuration Editor**: Edit your image configuration without SSH
- **Update History**: Track what has been updated and when
- **Live Activity Log**: Real-time log streaming via WebSocket
- **Dry-Run Safety**: Defaults to dry-run mode for testing

## Quick Start

### Using Docker Compose

```bash
# Build and run the web UI
docker-compose --profile webui up -d

# Access at http://your-nas-ip:5050
```

### Run with both Web UI and background daemon
```bash
# This runs both the web UI and the dry-run daemon
docker-compose --profile webui up -d
```

## Screenshots

### Main Dashboard
- Shows available updates for all monitored images
- Color-coded status indicators
- One-click update checks

### Configuration Tab
- Edit your image monitoring configuration
- Add new images to monitor
- Modify regex patterns for version matching

### History Tab
- Track all previous updates
- See what was changed and when
- Differentiate between dry-run and applied updates

## API Endpoints

The web UI exposes these REST API endpoints:

- `GET /api/status` - Current system status
- `GET /api/config` - Current configuration
- `POST /api/config` - Update configuration
- `GET /api/state` - Current image states
- `POST /api/check` - Trigger manual check
- `GET /api/updates` - Last check results
- `GET /api/history` - Update history
- `POST /api/daemon` - Start/stop daemon mode

## WebSocket Events

Real-time updates via Socket.IO:

- `status_update` - Status changes (checking, daemon state)
- `check_complete` - Update check finished
- `connected` - Connection established

## Environment Variables

- `CONFIG_FILE` - Path to config.json (default: /config/config.json)
- `STATE_FILE` - Path to state file (default: /state/image_update_state.json)
- `DRY_RUN` - Enable dry-run mode (default: true)
- `LOG_LEVEL` - Logging level (default: INFO)
- `SECRET_KEY` - Flask secret key for sessions

## Security Considerations

- The web UI defaults to dry-run mode
- No authentication is built in - use a reverse proxy for auth
- Docker socket is mounted read-only in dry-run mode
- Consider network isolation for production use

## Development

To run locally for development:

```bash
# Install dependencies
pip install -r requirements.txt -r requirements-webui.txt

# Set environment variables
export FLASK_APP=webui.py
export CONFIG_FILE=config/config.json
export STATE_FILE=state/image_update_state.json

# Run the development server
python webui.py
```

## Customization

The web UI uses standard HTML/CSS/JavaScript with no build process required. You can easily customize:

- `templates/index.html` - Main HTML structure
- `static/css/style.css` - All styling
- `static/js/app.js` - Frontend logic

## Future Enhancements

Potential improvements for the web UI:

- [ ] Authentication/authorization
- [ ] Email notifications for updates
- [ ] Bulk update operations
- [ ] Image update scheduling
- [ ] Update approval workflow
- [ ] Mobile-responsive improvements
- [ ] Dark mode theme
- [ ] Export/import configurations
- [ ] Webhook integrations