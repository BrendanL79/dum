#!/usr/bin/env python3
"""
Web UI for Docker Image Auto-Updater
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import traceback
from dataclasses import asdict
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Dict, List, Any, Optional

import jsonschema
from flask import Flask, render_template, jsonify, request, Response
from flask_socketio import SocketIO, emit

from dum import DockerImageUpdater, CONFIG_SCHEMA, __version__
from pattern_utils import detect_tag_patterns, detect_base_tags

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(32).hex()
socketio = SocketIO(app)

# Global variables
updater: Optional[DockerImageUpdater] = None
daemon_thread: Optional[threading.Thread] = None
daemon_stop_event = threading.Event()
last_check_time: Optional[datetime] = None
last_updates: List[Dict[str, Any]] = []
update_history: List[Dict[str, Any]] = []
is_checking = False
daemon_running = False
daemon_interval = 3600

# History file path (in config directory for persistence)
HISTORY_FILE = Path(os.environ.get('CONFIG_FILE', '/config/config.json')).parent / 'history.json'
MAX_HISTORY_ENTRIES = 500  # Limit history size

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Optional basic auth
AUTH_USER = os.environ.get('WEBUI_USER', '').strip()
AUTH_PASSWORD = os.environ.get('WEBUI_PASSWORD', '').strip()
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASSWORD)

if AUTH_ENABLED:
    logger.info("Basic authentication enabled")


def _check_credentials(username: str, password: str) -> bool:
    """Verify credentials using constant-time comparison."""
    return (hmac.compare_digest(username, AUTH_USER) and
            hmac.compare_digest(password, AUTH_PASSWORD))


@app.before_request
def require_auth():
    """Enforce basic auth on all requests when enabled."""
    if not AUTH_ENABLED:
        return None

    auth = request.authorization
    if auth and _check_credentials(auth.username, auth.password):
        return None

    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="dum"'}
    )


def load_history():
    """Load update history from file."""
    global update_history
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r') as f:
                loaded = json.load(f)
                # Ensure we have a list, not None or other type
                update_history = loaded if isinstance(loaded, list) else []
                logger.info(f"Loaded {len(update_history)} history entries from {HISTORY_FILE}")
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load history file: {e}")
        update_history = []


def save_history():
    """Save update history to file."""
    try:
        # Trim to max entries before saving
        trimmed = update_history[-MAX_HISTORY_ENTRIES:]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(trimmed, f, indent=2)
    except IOError as e:
        logger.error(f"Could not save history file: {e}")


def load_updater():
    """Load or reload the updater instance."""
    global updater
    config_file = os.environ.get('CONFIG_FILE', '/config/config.json')
    state_file = os.environ.get('STATE_FILE', '/state/docker_update_state.json')
    dry_run = os.environ.get('DRY_RUN', 'false').lower() == 'true'
    log_level = os.environ.get('LOG_LEVEL', 'INFO')
    
    try:
        updater = DockerImageUpdater(config_file, state_file, dry_run, log_level)
        return True
    except Exception as e:
        logger.error(f"Failed to load updater: {e}")
        return False


def require_updater(f):
    """Decorator to check if updater is loaded before executing route."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not updater:
            return jsonify({'error': 'Updater not loaded'}), 503
        return f(*args, **kwargs)
    return decorated


def run_check():
    """Run a single check cycle."""
    global is_checking, last_check_time, last_updates

    if is_checking:
        return

    is_checking = True
    socketio.emit('status_update', {'checking': True}, namespace='/')

    def progress_callback(event_type, data):
        """Emit progress updates to connected clients."""
        socketio.emit('check_progress', {
            'event': event_type,
            'data': data
        }, namespace='/')

    try:
        if updater:
            updates = updater.check_and_update(progress_callback=progress_callback)
            last_updates = updates
            last_check_time = datetime.now()

            # Add to history
            if updates:
                for update in updates:
                    update_history.append({
                        'timestamp': last_check_time.isoformat(),
                        'image': update['image'],
                        'old_tag': update['old_tag'],
                        'new_tag': update['new_tag'],
                        'applied': not updater.dry_run and update.get('auto_update', False)
                    })
                save_history()  # Persist to disk

            socketio.emit('check_complete', {
                'updates': updates,
                'timestamp': last_check_time.isoformat()
            }, namespace='/')
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Check failed: {e}\n{tb}")
        socketio.emit('check_error', {'error': str(e), 'traceback': tb}, namespace='/')
    finally:
        is_checking = False
        socketio.emit('status_update', {'checking': False}, namespace='/')


def daemon_worker(interval):
    """Background worker for daemon mode."""
    global daemon_running

    while daemon_running:
        run_check()
        # Wait with efficient interruption support
        if daemon_stop_event.wait(timeout=interval):
            break


@app.route('/')
def index():
    """Main web interface."""
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    """Get current status."""
    return jsonify({
        'updater_loaded': updater is not None,
        'dry_run': updater.dry_run if updater else True,
        'is_checking': is_checking,
        'daemon_running': daemon_running,
        'daemon_interval': daemon_interval,
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'config_file': updater.config_file.as_posix() if updater else None,
        'state_file': updater.state_file.as_posix() if updater else None
    })


@app.route('/api/version')
def api_version():
    """Get application version."""
    return jsonify({'version': __version__})


@app.route('/api/config')
@require_updater
def api_config():
    """Get current configuration."""
    return jsonify(updater.config)


@app.route('/api/config', methods=['POST'])
@require_updater
def api_update_config():
    """Update configuration."""
    try:
        new_config = request.json
        if not new_config:
            return jsonify({'error': 'No configuration provided'}), 400

        # Validate against schema before saving
        jsonschema.validate(new_config, CONFIG_SCHEMA)

        with open(updater.config_file, 'w') as f:
            json.dump(new_config, f, indent=2)

        # Reload updater
        if load_updater():
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to reload updater'}), 500
    except jsonschema.ValidationError as e:
        return jsonify({'error': f'Invalid configuration: {e.message}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/detect-patterns', methods=['POST'])
@require_updater
def api_detect_patterns():
    """Fetch tags from registry and detect regex patterns."""
    try:
        data = request.json or {}
        image = data.get('image', '').strip()
        if not image:
            return jsonify({'error': 'Image name is required'}), 400

        registry_override = data.get('registry', '').strip() or None

        registry, namespace, repo = updater._parse_image_reference(image)
        if registry_override:
            registry = registry_override

        tags = updater._get_all_tags_by_date(registry, namespace, repo)

        if not tags:
            return jsonify({'error': f'No tags found for {image}. Check the image name and registry.'}), 404

        patterns = detect_tag_patterns(tags)
        base_tags = detect_base_tags(tags, patterns)
        return jsonify({'patterns': patterns, 'base_tags': base_tags, 'total_tags': len(tags)})

    except Exception as e:
        logger.error(f"Pattern detection failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/state')
@require_updater
def api_state():
    """Get current state."""
    state_dict = {image: asdict(state) for image, state in updater.state.items()}
    return jsonify(state_dict)


@app.route('/api/check', methods=['POST'])
def api_check():
    """Trigger a manual check."""
    if is_checking:
        return jsonify({'error': 'Check already in progress'}), 409
        
    if not updater:
        if not load_updater():
            return jsonify({'error': 'Failed to load updater'}), 503
            
    # Run check in background
    threading.Thread(target=run_check).start()
    
    return jsonify({'status': 'started'})


@app.route('/api/updates')
def api_updates():
    """Get last update results."""
    return jsonify({
        'last_check': last_check_time.isoformat() if last_check_time else None,
        'updates': last_updates
    })


@app.route('/api/history')
def api_history():
    """Get update history."""
    limit = request.args.get('limit', 50, type=int)
    return jsonify(update_history[-limit:])


@app.route('/api/daemon', methods=['POST'])
def api_daemon():
    """Start/stop daemon mode."""
    global daemon_running, daemon_thread, daemon_interval

    data = request.json or {}
    action = data.get('action')

    if action == 'start':
        if daemon_running:
            return jsonify({'error': 'Daemon already running'}), 409

        if not updater:
            if not load_updater():
                return jsonify({'error': 'Failed to load updater'}), 503

        # Get interval from request or use default
        daemon_interval = data.get('interval', 3600)

        daemon_running = True
        daemon_stop_event.clear()
        daemon_thread = threading.Thread(target=daemon_worker, args=(daemon_interval,))
        daemon_thread.start()

        return jsonify({'status': 'started', 'interval': daemon_interval})

    elif action == 'stop':
        if not daemon_running:
            return jsonify({'error': 'Daemon not running'}), 409

        daemon_running = False
        daemon_stop_event.set()
        if daemon_thread:
            daemon_thread.join(timeout=5)

        return jsonify({'status': 'stopped'})
        
    else:
        return jsonify({'error': 'Invalid action'}), 400


@socketio.on('connect')
def handle_connect():
    """Handle client connection, rejecting unauthenticated Socket.IO when auth is enabled."""
    if AUTH_ENABLED:
        auth = request.authorization
        if not auth or not _check_credentials(auth.username, auth.password):
            return False  # Reject connection

    emit('connected', {'status': 'Connected to Docker Updater'})
    
    # Send current status
    emit('status_update', {
        'checking': is_checking,
        'daemon_running': daemon_running,
        'last_check': last_check_time.isoformat() if last_check_time else None
    })


# Load updater and history on startup (runs when gunicorn imports this module)
load_updater()
load_history()

if __name__ == '__main__':
    # For local development only
    socketio.run(app, host='0.0.0.0', port=5050, debug=True)