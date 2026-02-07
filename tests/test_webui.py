"""Tests for the ium web UI (webui.py).

Covers: status endpoints, CSRF protection, authentication, config CRUD,
check/daemon control, Socket.IO events, and pattern detection.
"""

import base64
import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Set env vars BEFORE importing webui so module-level code uses temp paths
_FIXTURES_SET = False


def _ensure_env(tmp_path_factory):
    """Set env vars to temp paths so webui module-level init doesn't touch real files."""
    global _FIXTURES_SET
    if _FIXTURES_SET:
        return
    tmp = tmp_path_factory.mktemp("webui")
    config_path = tmp / "config.json"
    state_path = tmp / "state.json"
    config_path.write_text(json.dumps({
        "images": [{
            "image": "nginx",
            "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
            "auto_update": False
        }]
    }))
    os.environ["CONFIG_FILE"] = str(config_path)
    os.environ["STATE_FILE"] = str(state_path)
    os.environ.pop("WEBUI_USER", None)
    os.environ.pop("WEBUI_PASSWORD", None)
    _FIXTURES_SET = True


@pytest.fixture(scope="session", autouse=True)
def _setup_env(tmp_path_factory):
    _ensure_env(tmp_path_factory)


# ---------------------------------------------------------------------------
# Import webui after env is configured
# ---------------------------------------------------------------------------

import webui as webui_mod
from ium import __version__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

XHR_HEADER = {"X-Requested-With": "XMLHttpRequest"}


def _auth_header(user="admin", password="secret"):
    """Return a Basic auth header dict."""
    cred = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {cred}"}


def _post_json(client, url, data, extra_headers=None):
    """POST JSON with the CSRF header included."""
    headers = {"Content-Type": "application/json", **XHR_HEADER}
    if extra_headers:
        headers.update(extra_headers)
    return client.post(url, data=json.dumps(data), headers=headers)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client(tmp_path):
    """Flask test client with a mock updater wired in."""
    # Create temp config/state files
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    config_path.write_text(json.dumps({
        "images": [{
            "image": "nginx",
            "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
            "auto_update": False
        }]
    }))

    mock_updater = MagicMock()
    mock_updater.dry_run = True
    mock_updater.config = {
        "images": [{
            "image": "nginx",
            "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
            "auto_update": False
        }]
    }
    mock_updater.state = {}
    mock_updater.config_file = config_path
    mock_updater.state_file = state_path

    # Reset global state
    webui_mod.updater = mock_updater
    webui_mod.is_checking = False
    webui_mod.daemon_running = False
    webui_mod.daemon_interval = 3600
    webui_mod.last_check_time = None
    webui_mod.last_updates = []
    webui_mod.update_history = []
    webui_mod.AUTH_ENABLED = False

    webui_mod.app.config["TESTING"] = True
    with webui_mod.app.test_client() as client:
        yield client

    # Cleanup
    webui_mod.daemon_running = False
    webui_mod.daemon_stop_event.set()


@pytest.fixture()
def auth_client(tmp_path):
    """Flask test client with authentication enabled."""
    config_path = tmp_path / "config.json"
    state_path = tmp_path / "state.json"
    config_path.write_text(json.dumps({
        "images": [{
            "image": "nginx",
            "regex": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
            "auto_update": False
        }]
    }))

    mock_updater = MagicMock()
    mock_updater.dry_run = True
    mock_updater.config = {"images": [{"image": "nginx", "regex": "^[0-9]+$"}]}
    mock_updater.state = {}
    mock_updater.config_file = config_path
    mock_updater.state_file = state_path

    webui_mod.updater = mock_updater
    webui_mod.is_checking = False
    webui_mod.daemon_running = False
    webui_mod.AUTH_ENABLED = True
    webui_mod.AUTH_USER = "admin"
    webui_mod.AUTH_PASSWORD = "secret"

    webui_mod.app.config["TESTING"] = True
    with webui_mod.app.test_client() as client:
        yield client

    webui_mod.AUTH_ENABLED = False
    webui_mod.AUTH_USER = ""
    webui_mod.AUTH_PASSWORD = ""
    webui_mod.daemon_running = False
    webui_mod.daemon_stop_event.set()


@pytest.fixture()
def socketio_client():
    """Flask-SocketIO test client."""
    webui_mod.is_checking = False
    webui_mod.daemon_running = False
    webui_mod.last_check_time = None
    webui_mod.AUTH_ENABLED = False

    webui_mod.app.config["TESTING"] = True
    client = webui_mod.socketio.test_client(webui_mod.app)
    yield client
    client.disconnect()

    webui_mod.AUTH_ENABLED = False


# ===========================================================================
# TestStatusEndpoints
# ===========================================================================

class TestStatusEndpoints:
    def test_get_status(self, app_client):
        resp = app_client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "updater_loaded" in data
        assert "dry_run" in data
        assert "is_checking" in data
        assert "daemon_running" in data
        assert data["updater_loaded"] is True

    def test_get_version(self, app_client):
        resp = app_client.get("/api/version")
        assert resp.status_code == 200
        assert resp.get_json()["version"] == __version__

    def test_get_config(self, app_client):
        resp = app_client.get("/api/config")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "images" in data
        assert data["images"][0]["image"] == "nginx"

    def test_get_state(self, app_client):
        resp = app_client.get("/api/state")
        assert resp.status_code == 200
        assert resp.get_json() == {}

    def test_get_history(self, app_client):
        webui_mod.update_history = [{"ts": "1"}, {"ts": "2"}, {"ts": "3"}]
        resp = app_client.get("/api/history?limit=2")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]["ts"] == "2"

    def test_get_updates(self, app_client):
        resp = app_client.get("/api/updates")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["last_check"] is None
        assert data["updates"] == []


# ===========================================================================
# TestCSRF
# ===========================================================================

class TestCSRF:
    def test_post_without_xhr_header_rejected(self, app_client):
        resp = app_client.post(
            "/api/config",
            data=json.dumps({"images": []}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.get_json()["error"]

    def test_post_with_xhr_header_accepted(self, app_client):
        """POST with X-Requested-With should pass CSRF check (may fail on other validation)."""
        resp = _post_json(app_client, "/api/config", {"images": []})
        # Should NOT be 403 — it passes CSRF. May be 200 or 400 depending on schema.
        assert resp.status_code != 403

    def test_get_requests_not_affected(self, app_client):
        resp = app_client.get("/api/status")
        assert resp.status_code == 200


# ===========================================================================
# TestAuth
# ===========================================================================

class TestAuth:
    def test_no_auth_when_disabled(self, app_client):
        resp = app_client.get("/api/status")
        assert resp.status_code == 200

    def test_auth_required_when_enabled(self, auth_client):
        resp = auth_client.get("/api/status")
        assert resp.status_code == 401

    def test_auth_succeeds_with_correct_credentials(self, auth_client):
        resp = auth_client.get("/api/status", headers=_auth_header("admin", "secret"))
        assert resp.status_code == 200

    def test_auth_fails_with_wrong_credentials(self, auth_client):
        resp = auth_client.get("/api/status", headers=_auth_header("admin", "wrong"))
        assert resp.status_code == 401


# ===========================================================================
# TestConfigEndpoint
# ===========================================================================

class TestConfigEndpoint:
    def test_save_valid_config(self, app_client, tmp_path):
        new_config = {
            "images": [{
                "image": "redis",
                "regex": "^[0-9]+\\.[0-9]+$",
                "auto_update": True
            }]
        }
        with patch.object(webui_mod, "load_updater", return_value=True):
            resp = _post_json(app_client, "/api/config", new_config)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_save_invalid_schema(self, app_client):
        bad_config = {"images": "not_a_list"}
        resp = _post_json(app_client, "/api/config", bad_config)
        assert resp.status_code == 400

    def test_save_invalid_regex(self, app_client):
        bad_config = {
            "images": [{"image": "test", "regex": "[invalid"}]
        }
        resp = _post_json(app_client, "/api/config", bad_config)
        assert resp.status_code == 400
        assert "Invalid regex" in resp.get_json()["error"]

    def test_save_empty_body(self, app_client):
        resp = app_client.post(
            "/api/config",
            data="",
            headers={"Content-Type": "application/json", **XHR_HEADER},
        )
        assert resp.status_code == 400

    def test_updater_not_loaded(self, app_client):
        webui_mod.updater = None
        resp = _post_json(app_client, "/api/config", {"images": []})
        assert resp.status_code == 503


# ===========================================================================
# TestCheckEndpoint
# ===========================================================================

class TestCheckEndpoint:
    def test_trigger_check(self, app_client):
        with patch.object(webui_mod, "run_check"):
            resp = app_client.post("/api/check", headers=XHR_HEADER)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "started"

    def test_check_already_running(self, app_client):
        webui_mod.is_checking = True
        resp = app_client.post("/api/check", headers=XHR_HEADER)
        assert resp.status_code == 409


# ===========================================================================
# TestDaemonEndpoint
# ===========================================================================

class TestDaemonEndpoint:
    def test_start_daemon(self, app_client):
        with patch.object(webui_mod, "save_daemon_state"):
            resp = _post_json(app_client, "/api/daemon", {"action": "start", "interval": 120})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "started"
        # Cleanup
        webui_mod.daemon_running = False
        webui_mod.daemon_stop_event.set()
        if webui_mod.daemon_thread:
            webui_mod.daemon_thread.join(timeout=2)

    def test_stop_daemon(self, app_client):
        # Start daemon first
        webui_mod.daemon_running = True
        webui_mod.daemon_stop_event.clear()
        webui_mod.daemon_thread = threading.Thread(target=lambda: None)
        webui_mod.daemon_thread.start()
        webui_mod.daemon_thread.join()

        with patch.object(webui_mod, "save_daemon_state"):
            resp = _post_json(app_client, "/api/daemon", {"action": "stop"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "stopped"

    def test_start_when_already_running(self, app_client):
        webui_mod.daemon_running = True
        resp = _post_json(app_client, "/api/daemon", {"action": "start", "interval": 120})
        assert resp.status_code == 409
        webui_mod.daemon_running = False

    def test_stop_when_not_running(self, app_client):
        webui_mod.daemon_running = False
        resp = _post_json(app_client, "/api/daemon", {"action": "stop"})
        assert resp.status_code == 409

    def test_invalid_action(self, app_client):
        resp = _post_json(app_client, "/api/daemon", {"action": "restart"})
        assert resp.status_code == 400

    def test_interval_validation(self, app_client):
        resp = _post_json(app_client, "/api/daemon", {"action": "start", "interval": 10})
        assert resp.status_code == 400
        assert "60 seconds" in resp.get_json()["error"]

    def test_interval_validation_non_numeric(self, app_client):
        resp = _post_json(app_client, "/api/daemon", {"action": "start", "interval": "fast"})
        assert resp.status_code == 400


# ===========================================================================
# TestSocketIO
# ===========================================================================

class TestSocketIO:
    def test_connect_emits_status(self, socketio_client):
        received = socketio_client.get_received()
        event_names = [msg["name"] for msg in received]
        assert "connected" in event_names
        assert "status_update" in event_names

    def test_connect_rejected_without_auth(self):
        """When auth is enabled, unauthenticated SocketIO connections are rejected."""
        webui_mod.AUTH_ENABLED = True
        webui_mod.AUTH_USER = "admin"
        webui_mod.AUTH_PASSWORD = "secret"

        webui_mod.app.config["TESTING"] = True
        client = webui_mod.socketio.test_client(webui_mod.app)
        assert not client.is_connected()
        webui_mod.AUTH_ENABLED = False
        webui_mod.AUTH_USER = ""
        webui_mod.AUTH_PASSWORD = ""


# ===========================================================================
# TestDetectPatterns
# ===========================================================================

class TestDetectPatterns:
    def test_detect_patterns_valid_image(self, app_client):
        mock_updater = webui_mod.updater
        mock_updater._parse_image_reference.return_value = ("registry-1.docker.io", "library", "nginx")
        mock_updater._get_all_tags_by_date.return_value = ["1.24.0", "1.25.0", "latest"]

        with patch("webui.detect_tag_patterns", return_value=[{"regex": "^[0-9]+$", "label": "semver"}]):
            with patch("webui.detect_base_tags", return_value=["1.25.0"]):
                resp = _post_json(app_client, "/api/detect-patterns", {"image": "nginx"})

        assert resp.status_code == 200
        data = resp.get_json()
        assert "patterns" in data
        assert data["total_tags"] == 3

    def test_detect_patterns_empty_image(self, app_client):
        resp = _post_json(app_client, "/api/detect-patterns", {"image": ""})
        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"].lower()
