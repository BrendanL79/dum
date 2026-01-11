#!/usr/bin/env python3
"""
Web UI for Docker Image Auto-Updater
"""

import json
import os
import threading
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Dict, List, Any, Optional
from flask import Flask, render_template, jsonify, request, Response
from flask_socketio import SocketIO, emit
import logging

from dum import DockerImageUpdater, ImageState, DEFAULT_BASE_TAG

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
socketio = SocketIO(app, cors_allowed_origins="*")

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


def load_history():
    """Load update history from file."""
    global update_history
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r') as f:
                update_history = json.load(f)
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
    dry_run = os.environ.get('DRY_RUN', 'true').lower() == 'true'
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

    try:
        if updater:
            updates = updater.check_and_update()
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
                        'applied': not updater.dry_run
                    })
                save_history()  # Persist to disk

            socketio.emit('check_complete', {
                'updates': updates,
                'timestamp': last_check_time.isoformat()
            }, namespace='/')
    except Exception as e:
        logger.error(f"Check failed: {e}")
        socketio.emit('check_error', {'error': str(e)}, namespace='/')
    finally:
        is_checking = False
        socketio.emit('status_update', {'checking': False}, namespace='/')


def daemon_worker():
    """Background worker for daemon mode."""
    global daemon_running

    while daemon_running:
        run_check()
        # Wait with efficient interruption support
        if daemon_stop_event.wait(timeout=daemon_interval):
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
        # Validate and save new config
        with open(updater.config_file, 'w') as f:
            json.dump(new_config, f, indent=2)
        
        # Reload updater
        if load_updater():
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to reload updater'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/state')
@require_updater
def api_state():
    """Get current state."""
    state_dict = {
        image: {
            'base_tag': state.base_tag,
            'tag': state.tag,
            'digest': state.digest,
            'last_updated': state.last_updated
        }
        for image, state in updater.state.items()
    }
    
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

    action = request.json.get('action')

    if action == 'start':
        if daemon_running:
            return jsonify({'error': 'Daemon already running'}), 409

        if not updater:
            if not load_updater():
                return jsonify({'error': 'Failed to load updater'}), 503

        # Get interval from request or use default
        daemon_interval = request.json.get('interval', 3600)

        daemon_running = True
        daemon_stop_event.clear()
        daemon_thread = threading.Thread(target=daemon_worker)
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


@app.route('/api/logs')
def api_logs():
    """Stream logs."""
    def generate():
        # Simple log streaming - in production you'd tail actual log files
        log_file = Path('/var/log/docker-updater.log')
        if log_file.exists():
            with open(log_file, 'r') as f:
                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {json.dumps({'log': line.strip()})}\n\n"
                    else:
                        time.sleep(0.5)
                        
    return Response(generate(), mimetype='text/event-stream')


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
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