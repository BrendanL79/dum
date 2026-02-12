#!/usr/bin/env python3
"""
Docker Image Auto-Update with Specific Tag Tracking

This script monitors Docker images for updates by comparing a base tag
(e.g., 'latest', 'stable', or a version like '14') with version-specific
tags that match user-defined regex patterns.
"""

__version__ = "1.0.0"

import json
import re
import socket as _socket
import sys
import time
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import argparse
import os
import platform
import requests
import jsonschema
from urllib3.connection import HTTPConnection as _HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool as _HTTPConnectionPool
from requests.adapters import HTTPAdapter as _HTTPAdapter

from pattern_utils import detect_tag_patterns, detect_base_tags

# Platform-specific imports and constant
IS_WINDOWS = platform.system() == 'Windows'
if not IS_WINDOWS:
    import fcntl
else:
    import msvcrt


# Constants
DEFAULT_REGISTRY = "registry-1.docker.io"
DEFAULT_AUTH_URL = "https://auth.docker.io/token"
DEFAULT_NAMESPACE = "library"
DEFAULT_BASE_TAG = "latest"
REQUEST_TIMEOUT = 30
MANIFEST_ACCEPT_HEADER = (
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.docker.distribution.manifest.v2+json,"
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.oci.image.manifest.v1+json"
)
DOCKER_SOCKET_PATH = os.environ.get('DOCKER_SOCKET', '/var/run/docker.sock')

# Configuration schema
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image": {"type": "string"},
                    "regex": {"type": "string"},
                    "base_tag": {"type": "string"},
                    "auto_update": {"type": "boolean"},
                    "registry": {"type": "string"},
                    "cleanup_old_images": {"type": "boolean"},
                    "keep_versions": {"type": "integer", "minimum": 1}
                },
                "required": ["image", "regex"]
            }
        }
    },
    "required": ["images"]
}


# ---------------------------------------------------------------------------
# Docker Engine socket client (replaces docker CLI subprocess calls)
# ---------------------------------------------------------------------------

class _UnixSocketConnection(_HTTPConnection):
    """HTTPConnection that connects via a Unix domain socket."""

    def __init__(self, socket_path: str):
        super().__init__('localhost')
        self._socket_path = socket_path

    def connect(self):
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.connect(self._socket_path)
        self.sock = sock


class _UnixSocketPool(_HTTPConnectionPool):
    """Connection pool backed by a Unix domain socket."""

    def __init__(self, socket_path: str):
        super().__init__('localhost')
        self._socket_path = socket_path

    def _new_conn(self):
        return _UnixSocketConnection(self._socket_path)


class _UnixSocketAdapter(_HTTPAdapter):
    """requests adapter that routes all requests through a Unix socket."""

    def __init__(self, socket_path: str):
        self._socket_path = socket_path
        super().__init__()

    def get_connection(self, url: str, proxies=None):
        return _UnixSocketPool(self._socket_path)

    # Needed in requests >= 2.32 / urllib3 >= 2.x
    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        return _UnixSocketPool(self._socket_path)


class DockerClient:
    """Minimal Docker Engine API v1.41 client over the Unix socket."""

    def __init__(self, socket_path: str = DOCKER_SOCKET_PATH):
        self._session = requests.Session()
        self._session.mount('http+unix://', _UnixSocketAdapter(socket_path))

    def _url(self, path: str) -> str:
        return f'http+unix://docker{path}'

    def get(self, path: str, **kwargs) -> requests.Response:
        r = self._session.get(self._url(path), timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r

    def post(self, path: str, **kwargs) -> requests.Response:
        r = self._session.post(self._url(path), timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r

    def delete(self, path: str, **kwargs) -> requests.Response:
        r = self._session.delete(self._url(path), timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r


# ---------------------------------------------------------------------------

def _validate_regex(pattern: str, timeout: float = 2.0) -> re.Pattern:
    """Compile a regex pattern and test it against a short string to detect ReDoS.

    Raises ValueError on invalid pattern or catastrophic backtracking.
    """
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern '{pattern}': {e}")

    # Test-match against a string that can trigger catastrophic backtracking
    test_string = "a" * 100
    import threading
    result = [None]
    error = [None]

    def _run():
        try:
            compiled.match(test_string)
            result[0] = True
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_run)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise ValueError(
            f"Regex pattern '{pattern}' is too expensive (possible ReDoS). "
            f"Simplify the pattern to avoid catastrophic backtracking."
        )
    if error[0]:
        raise ValueError(f"Regex pattern '{pattern}' failed test: {error[0]}")

    return compiled


@dataclass
class ImageState:
    """State information for a tracked image."""
    base_tag: str
    tag: str
    digest: str
    last_updated: str


class DockerImageUpdater:
    def __init__(self, config_file: str, state_file: str = "image_update_state.json",
                 dry_run: bool = False, log_level: str = "INFO"):
        """
        Initialize the Docker Image Updater.

        Args:
            config_file: Path to JSON configuration file
            state_file: Path to store state between runs
            dry_run: If True, only log what would be done without making changes
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        self.config_file = Path(config_file)
        self.state_file = Path(state_file)
        self.dry_run = dry_run

        # Setup logging
        self.logger = self._setup_logging(log_level)

        # Docker Engine API client
        self._docker = DockerClient()

        # Load configuration and state
        self.compiled_patterns = {}  # Cache for compiled regex patterns
        self.config = self._load_config()
        self.state = self._load_state()

    def _setup_logging(self, level: str) -> logging.Logger:
        """Setup logging configuration."""
        logger = logging.getLogger('DockerImageUpdater')
        logger.setLevel(getattr(logging, level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _load_config(self) -> Dict[str, Any]:
        """Load and validate configuration from JSON file."""
        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)

            # Validate against schema
            jsonschema.validate(config, CONFIG_SCHEMA)

            # Validate and cache regex patterns
            for image_config in config.get('images', []):
                regex_pattern = image_config['regex']
                self.compiled_patterns[regex_pattern] = _validate_regex(regex_pattern)

            return config

        except FileNotFoundError:
            self.logger.error(f"Config file {self.config_file} not found")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing config file: {e}")
            raise
        except jsonschema.ValidationError as e:
            self.logger.error(f"Configuration validation failed: {e}")
            raise

    @contextmanager
    def _file_lock(self, file_path: Path):
        """Context manager for file locking."""
        lock_file = file_path.with_suffix('.lock')
        fp = open(lock_file, 'w')
        try:
            if IS_WINDOWS:
                # Windows
                while True:
                    try:
                        msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except IOError:
                        time.sleep(0.1)
            else:
                # Unix-like systems
                fcntl.flock(fp, fcntl.LOCK_EX)
            yield
        finally:
            if IS_WINDOWS:
                try:
                    msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass
            else:
                fcntl.flock(fp, fcntl.LOCK_UN)
            fp.close()
            try:
                lock_file.unlink()
            except (OSError, FileNotFoundError):
                pass

    def _load_state(self) -> Dict[str, ImageState]:
        """Load previous state from file with validation."""
        try:
            if not self.state_file.exists():
                return {}

            with self._file_lock(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)

            # Convert to ImageState objects
            state = {}
            for image, image_data in data.items():
                try:
                    state[image] = ImageState(**image_data)
                except (TypeError, KeyError) as e:
                    self.logger.warning(f"Invalid state data for {image}: {e}")

            return state

        except json.JSONDecodeError as e:
            self.logger.warning(f"Error parsing state file, starting fresh: {e}")
            return {}
        except Exception as e:
            self.logger.warning(f"Error loading state: {e}")
            return {}

    def _save_state(self):
        """Save current state to file with locking."""
        if self.dry_run:
            self.logger.info("[DRY RUN] Would save state to file")
            return

        try:
            # Convert ImageState objects to dicts
            state_dict = {
                image: asdict(state)
                for image, state in self.state.items()
            }

            with self._file_lock(self.state_file):
                # Write to temp file first
                temp_file = self.state_file.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump(state_dict, f, indent=2)

                # Atomic rename
                temp_file.replace(self.state_file)

        except Exception as e:
            self.logger.error(f"Error saving state: {e}")
            raise

    def _parse_image_reference(self, image: str) -> Tuple[str, str, str]:
        """
        Parse image reference into registry, namespace, and repository.

        Args:
            image: Image reference (e.g., 'ubuntu', 'linuxserver/calibre', 'gcr.io/project/image')

        Returns:
            Tuple of (registry, namespace, repository)
        """
        # Handle explicit protocol prefixes first
        if image.startswith(('http://', 'https://')):
            parts = image.split('/', 1)
            registry = parts[0]
            remaining = parts[1] if len(parts) > 1 else ''
        else:
            # Split once to check first component
            parts = image.split('/', 1)
            first_part = parts[0]

            # Registry indicators: contains '.', is localhost, or has port ':'
            if '.' in first_part or first_part == 'localhost' or ':' in first_part:
                # First part is a custom registry
                registry = first_part
                remaining = parts[1] if len(parts) > 1 else ''
            else:
                # No custom registry detected, use default
                registry = DEFAULT_REGISTRY
                remaining = image

        # Parse namespace and repository from remaining path
        if '/' in remaining:
            namespace, repo = remaining.split('/', 1)
        else:
            namespace = DEFAULT_NAMESPACE
            repo = remaining

        return registry, namespace, repo

    def _get_docker_token(self, registry: str, namespace: str, repo: str) -> Optional[str]:
        """
        Get authentication token for Docker registry.

        Args:
            registry: Registry hostname
            namespace: Image namespace
            repo: Repository name

        Returns:
            Authentication token or None
        """
        # Different auth endpoints for different registries
        if registry == DEFAULT_REGISTRY:
            auth_url = f"{DEFAULT_AUTH_URL}?service=registry.docker.io&scope=repository:{namespace}/{repo}:pull"
        elif registry in ("ghcr.io", "lscr.io"):
            # GitHub Container Registry (and lscr.io which delegates auth to ghcr.io)
            auth_url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{namespace}/{repo}:pull"
        else:
            # Generic registry auth (may need customization)
            auth_url = f"https://{registry}/v2/auth?service={registry}&scope=repository:{namespace}/{repo}:pull"

        try:
            response = requests.get(auth_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json().get('token')
        except requests.RequestException as e:
            self.logger.error(f"Error getting token for {namespace}/{repo}: {e}")
            return None

    def _get_manifest_digest(self, registry: str, namespace: str, repo: str,
                           tag: str, token: Optional[str], platform: Optional[str] = None) -> Optional[str]:
        """
        Get manifest digest for a specific image:tag.

        Args:
            registry: Registry hostname
            namespace: Image namespace
            repo: Repository name
            tag: Tag name
            token: Authentication token
            platform: Platform (e.g., 'linux/amd64')

        Returns:
            Manifest digest or None
        """
        manifest_url = f"https://{registry}/v2/{namespace}/{repo}/manifests/{tag}"

        headers = {
            'Accept': MANIFEST_ACCEPT_HEADER
        }
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            response = requests.get(manifest_url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '')

            # Handle manifest lists for multi-arch support
            if 'manifest.list' in content_type or 'image.index' in content_type:
                manifest_list = response.json()
                manifests = manifest_list.get('manifests') or []

                # If platform specified, find matching manifest
                if platform:
                    for manifest in manifests:
                        plat = manifest.get('platform', {})
                        plat_str = f"{plat.get('os', '')}/{plat.get('architecture', '')}"
                        if plat_str == platform:
                            return manifest.get('digest')

                # Return first manifest if no platform specified
                if manifests:
                    return manifests[0].get('digest')

            # Single manifest
            return response.headers.get('Docker-Content-Digest')

        except requests.RequestException as e:
            self.logger.error(f"Error getting manifest for {namespace}/{repo}:{tag}: {e}")
            return None

    def _get_manifest_digest_head(self, registry: str, namespace: str, repo: str,
                                   tag: str, token: Optional[str]) -> Optional[str]:
        """
        Get manifest digest using HEAD request (faster, no body transfer).

        Returns the Docker-Content-Digest header which is the digest of the
        manifest list for multi-arch images, or the manifest itself for single-arch.
        This is more correct for comparison than parsing manifest list JSON.

        Args:
            registry: Registry hostname
            namespace: Image namespace
            repo: Repository name
            tag: Tag name
            token: Authentication token

        Returns:
            Manifest digest or None
        """
        manifest_url = f"https://{registry}/v2/{namespace}/{repo}/manifests/{tag}"

        headers = {
            'Accept': MANIFEST_ACCEPT_HEADER
        }
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            response = requests.head(manifest_url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.headers.get('Docker-Content-Digest')
        except requests.RequestException as e:
            self.logger.debug(f"Error getting manifest digest for {namespace}/{repo}:{tag}: {e}")
            return None

    def _get_all_tags(self, registry: str, namespace: str, repo: str, token: Optional[str]) -> List[str]:
        """
        Get all available tags for an image.

        Args:
            registry: Registry hostname
            namespace: Image namespace
            repo: Repository name
            token: Authentication token

        Returns:
            List of available tags
        """
        tags_url = f"https://{registry}/v2/{namespace}/{repo}/tags/list"

        headers = {}
        if token:
            headers['Authorization'] = f'Bearer {token}'

        try:
            response = requests.get(tags_url, headers=headers, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json().get('tags') or []
        except requests.RequestException as e:
            self.logger.error(f"Error getting tags for {namespace}/{repo}: {e}")
            return []

    def _get_all_tags_by_date(self, registry: str, namespace: str, repo: str) -> List[str]:
        """
        Get all tags ordered by last_updated (oldest first) via Docker Hub API.

        Falls back to _get_all_tags() for non-Docker Hub registries.

        Args:
            registry: Registry hostname
            namespace: Image namespace
            repo: Repository name

        Returns:
            List of tags ordered oldest-first (last element = most recent)
        """
        if registry != DEFAULT_REGISTRY:
            token = self._get_docker_token(registry, namespace, repo)
            return self._get_all_tags(registry, namespace, repo, token)

        tag_dates = []  # list of (name, tag_last_pushed_iso)
        # Docker Hub: ordering=last_updated gives newest first
        url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags?page_size=100&ordering=last_updated"
        max_tags = 500
        while url and len(tag_dates) < max_tags:
            try:
                response = requests.get(url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()
                for result in data.get('results') or []:
                    name = result.get('name')
                    if name:
                        tag_dates.append((name, result.get('tag_last_pushed', '')))
                url = data.get('next')
            except requests.RequestException as e:
                self.logger.error(f"Error getting tags from Hub API for {namespace}/{repo}: {e}")
                if not tag_dates:
                    token = self._get_docker_token(registry, namespace, repo)
                    return self._get_all_tags(registry, namespace, repo, token)
                break
        # Sort by push date ascending — last element = most recently pushed
        tag_dates.sort(key=lambda x: x[1])
        return [name for name, _ in tag_dates]

    def find_matching_tag(self, image: str, base_tag: str, regex_pattern: str,
                         registry_override: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        Find a tag matching the regex pattern that has the same digest as the base tag.

        Uses HEAD requests for faster digest fetching and parallel requests
        for checking multiple tags concurrently.

        Args:
            image: Image name
            base_tag: Base tag to track (e.g., 'latest', 'stable', '14')
            regex_pattern: Regex pattern to match tags
            registry_override: Override registry from config

        Returns:
            Tuple of (matching_tag, digest) or None
        """
        # Parse image reference
        registry, namespace, repo = self._parse_image_reference(image)
        if registry_override:
            registry = registry_override

        # Get authentication token
        token = self._get_docker_token(registry, namespace, repo)

        # Get digest for base tag using HEAD request
        base_digest = self._get_manifest_digest_head(registry, namespace, repo, base_tag, token)
        if not base_digest:
            self.logger.error(f"Could not get digest for {image}:{base_tag}")
            return None

        # Get all available tags
        all_tags = self._get_all_tags(registry, namespace, repo, token)
        if not all_tags:
            self.logger.error(f"Could not get tags for {image}")
            return None

        # Get cached compiled pattern
        pattern = self.compiled_patterns.get(regex_pattern)
        if not pattern:
            self.logger.error(f"Pattern not found in cache: '{regex_pattern}'")
            return None

        # Find tags matching the pattern
        matching_tags = [tag for tag in all_tags if pattern.match(tag)]
        self.logger.debug(f"Found {len(matching_tags)} tags matching pattern")

        if not matching_tags:
            self.logger.warning(f"No tags matching pattern '{regex_pattern}'")
            return None

        # Sort tags in reverse order - newest versions typically come last alphabetically
        # For semver-like tags (v1.2.3), reverse sort puts newest first
        matching_tags.sort(reverse=True)

        # Fetch digests in parallel using HEAD requests
        def fetch_digest(tag: str) -> Tuple[str, Optional[str]]:
            digest = self._get_manifest_digest_head(registry, namespace, repo, tag, token)
            return (tag, digest)

        # Use ThreadPoolExecutor for parallel fetching (limit concurrency to be nice to registries)
        max_workers = min(10, len(matching_tags))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_digest, tag): tag for tag in matching_tags}

            for future in as_completed(futures):
                tag, digest = future.result()
                if digest == base_digest:
                    # Found a match - cancel remaining futures and return
                    for f in futures:
                        f.cancel()
                    self.logger.debug(f"Found matching tag {tag} with digest {digest[:16]}...")
                    return (tag, base_digest)

        self.logger.warning(f"No tag matching pattern '{regex_pattern}' found with same digest as {base_tag}")
        return None

    def _pull_image(self, image: str, tag: str) -> bool:
        """
        Pull a Docker image via the Engine API.

        Args:
            image: Image name
            tag: Tag to pull

        Returns:
            True if successful, False otherwise
        """
        full_image = f"{image}:{tag}"

        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would pull {full_image}")
            return True

        self.logger.info(f"Pulling {full_image}...")

        try:
            response = self._docker._session.post(
                self._docker._url('/images/create'),
                params={'fromImage': image, 'tag': tag},
                stream=True,
                timeout=300,  # image pulls can take a while
            )
            response.raise_for_status()

            # Consume the stream; detect errors reported in the JSON event stream
            for line in response.iter_lines():
                if line:
                    try:
                        event = json.loads(line)
                        if 'error' in event:
                            self.logger.error(f"Error pulling {full_image}: {event['error']}")
                            return False
                    except json.JSONDecodeError:
                        pass

            self.logger.info(f"Successfully pulled {full_image}")
            return True
        except requests.RequestException as e:
            self.logger.error(f"Error pulling {full_image}: {e}")
            return False

    def _get_container_config(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get full container configuration via the Engine API."""
        try:
            response = self._docker.get(f'/containers/{container_name}/json')
            return response.json()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 404:
                self.logger.error(
                    f"Container '{container_name}' not found. "
                    f"Check that container_name in config matches an existing container."
                )
            else:
                self.logger.error(f"Error inspecting container '{container_name}': {e}")
            return None
        except requests.RequestException as e:
            self.logger.error(f"Error inspecting container '{container_name}': {e}")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            self.logger.error(f"Error parsing container config for '{container_name}': {e}")
            return None

    def _get_containers_for_image(self, image: str) -> List[Dict[str, str]]:
        """Get all containers (running or stopped) using a specific image via the Engine API.

        Returns:
            List of dicts with keys: name, id, state, image_ref
        """
        try:
            response = self._docker.get('/containers/json', params={'all': '1'})
            all_containers = response.json()

            containers = []
            all_images = []
            for container in all_containers:
                container_image = container.get('Image', '')
                all_images.append(container_image)

                if self._image_matches(image, container_image):
                    # API returns Names as a list with leading slashes, e.g. ["/mycontainer"]
                    names = container.get('Names') or []
                    name = names[0].lstrip('/') if names else ''
                    containers.append({
                        'name': name,
                        'id': container.get('Id', ''),
                        'state': container.get('State', ''),
                        'image_ref': container_image,
                    })

            if not containers and all_images:
                normalized = self._normalize_image_ref(image)
                self.logger.debug(
                    f"No containers matched '{image}' (normalized: '{normalized}'). "
                    f"All container images: {all_images}"
                )

            return containers

        except requests.RequestException as e:
            self.logger.error(f"Failed to list containers: {e}")
            return []

    @staticmethod
    def _normalize_image_ref(img: str) -> str:
        """Normalize a Docker image reference for comparison.

        Strips tags, digest qualifiers, and registry prefixes to yield just
        the repository path (e.g. ``portainer/portainer-ce``).  Single-name
        images get an implicit ``library/`` prefix so that ``nginx`` and
        ``library/nginx`` compare equal.
        """
        # Strip digest qualifier (@sha256:...)
        at_pos = img.find('@')
        if at_pos != -1:
            img = img[:at_pos]

        # Strip tag — but only when the colon is in the *tag* position
        # (after the last slash), not in a registry:port position.
        last_slash = img.rfind('/')
        last_colon = img.rfind(':')
        if last_colon > last_slash:
            img = img[:last_colon]

        # Strip registry prefix.  The first path component is a registry if
        # it contains a dot, a colon (port), or is literally "localhost".
        if '/' in img:
            path_parts = img.split('/')
            first = path_parts[0]
            if '.' in first or ':' in first or first == 'localhost':
                img = '/'.join(path_parts[1:])

        # Implicit library namespace: postgres → library/postgres
        if '/' not in img:
            return f"library/{img}"

        return img

    def _image_matches(self, config_image: str, container_image: str) -> bool:
        """Check if a container image matches the configured image.

        Handles:
        - Tag variations: nginx matches nginx:alpine
        - Registry prefixes: linuxserver/sonarr matches lscr.io/linuxserver/sonarr:latest
        - Implicit library namespace: postgres matches library/postgres
        - Digest qualifiers: image:tag@sha256:... matches image
        - Registry ports: localhost:5000/img matches img
        """
        normalized_config = self._normalize_image_ref(config_image)
        normalized_container = self._normalize_image_ref(container_image)

        # Also check without library/ prefix so that "library/nginx" matches "nginx"
        def strip_library(s: str) -> str:
            return s[len('library/'):] if s.startswith('library/') else s

        return (normalized_config == normalized_container or
                strip_library(normalized_config) == strip_library(normalized_container))

    def _get_container_current_tag(self, container_name: str, image: str, regex: str) -> Optional[str]:
        """Get the current version tag of a running container by checking image inventory."""
        try:
            container_info = self._get_container_config(container_name)
            if not container_info:
                self.logger.debug(f"Container {container_name} not found or no config")
                return None

            # Full sha256 image ID from the container (e.g. "sha256:abc123...")
            image_id = container_info.get('Image', '')
            if not image_id:
                self.logger.debug(f"No image ID found for container {container_name}")
                return None

            # Get cached compiled pattern
            pattern = self.compiled_patterns.get(regex)
            if not pattern:
                self.logger.debug(f"Pattern not found in cache: '{regex}'")
                return None

            # List locally-available images for this repository
            response = self._docker.get(
                '/images/json',
                params={'filters': json.dumps({'reference': [image]})},
            )
            local_images = response.json()

            # Find an image whose ID matches the container's image and whose tag matches regex
            for img in local_images:
                if img.get('Id') != image_id:
                    continue
                for repo_tag in img.get('RepoTags') or []:
                    # repo_tag is "image:tag" or "registry/image:tag"
                    tag = repo_tag.rsplit(':', 1)[-1] if ':' in repo_tag else ''
                    if tag and pattern.match(tag):
                        self.logger.debug(f"Found matching tag for {container_name}: {tag}")
                        return tag

            self.logger.debug(f"No matching tag found in image inventory for {container_name}")
            return None
        except Exception as e:
            self.logger.debug(f"Could not get current tag for {container_name}: {e}")
            return None

    def _update_container(self, container_name: str, image: str, tag: str) -> bool:
        """
        Update a running container with a new image via the Engine API.

        Args:
            container_name: Name of the container to update
            image: Image name
            tag: Tag to use

        Returns:
            True if successful, False otherwise
        """
        full_image = f"{image}:{tag}"

        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would update container {container_name} with image {full_image}")
            return True

        # Get current container configuration
        container_info = self._get_container_config(container_name)
        if not container_info:
            return False

        backup_name = f"{container_name}_backup_{int(time.time())}"

        try:
            # Build container create body preserving all settings
            body = self._build_container_create_body(full_image, container_info)

            # Stop the container
            self.logger.info(f"Stopping container {container_name}...")
            self._docker.post(f'/containers/{container_name}/stop')

            # Rename old container as backup
            self.logger.info(f"Renaming old container to {backup_name}")
            self._docker.post(
                f'/containers/{container_name}/rename',
                params={'name': backup_name},
            )

            # Create new container
            self.logger.info(f"Creating new container {container_name}...")
            try:
                create_resp = self._docker._session.post(
                    self._docker._url('/containers/create'),
                    params={'name': container_name},
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                )
                create_resp.raise_for_status()
                new_id = create_resp.json()['Id']
                self._docker.post(f'/containers/{new_id}/start')
            except requests.RequestException as create_err:
                # Rollback on failure
                self.logger.error(f"Failed to create new container: {create_err}")
                self.logger.info("Rolling back...")
                try:
                    self._docker.post(
                        f'/containers/{backup_name}/rename',
                        params={'name': container_name},
                    )
                    self._docker.post(f'/containers/{container_name}/start')
                except requests.RequestException:
                    pass
                return False

            # Connect to additional networks (non-fatal if this fails)
            network_mode = (container_info.get('HostConfig') or {}).get('NetworkMode', '')
            is_container_network = network_mode.startswith('container:')
            if not is_container_network:
                networks = (container_info.get('NetworkSettings') or {}).get('Networks') or {}
                for network, endpoint_config in networks.items():
                    if network != network_mode:
                        try:
                            self._docker.post(
                                f'/networks/{network}/connect',
                                json={'Container': new_id, 'EndpointConfig': endpoint_config},
                            )
                        except requests.RequestException as e:
                            self.logger.warning(
                                f"Could not connect {container_name} to network {network}: {e}"
                            )

            # Success - remove old container
            self.logger.info(f"Removing old container {backup_name}")
            self._docker.delete(f'/containers/{backup_name}')

            self.logger.info(f"Successfully updated container {container_name}")
            return True

        except requests.RequestException as e:
            self.logger.error(f"Error updating container: {e}")
            return False

    def _update_containers(self, container_names: List[str], image: str, tag: str) -> Dict[str, bool]:
        """Update multiple containers to a new image tag.

        Args:
            container_names: List of container names to update
            image: Base image name
            tag: Target tag to update to

        Returns:
            Dict mapping container_name -> success boolean
        """
        results = {}
        for container_name in container_names:
            self.logger.info(f"Updating container {container_name} to {image}:{tag}")
            success = self._update_container(container_name, image, tag)
            results[container_name] = success

        # Log summary
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        if success_count == total_count:
            self.logger.info(f"Container update summary: {success_count}/{total_count} succeeded (all)")
        else:
            self.logger.warning(f"Container update summary: {success_count}/{total_count} succeeded")

        return results

    def _build_container_create_body(self, image: str,
                                     container_info: Dict[str, Any]) -> Dict[str, Any]:
        """Build Docker Engine API container-create request body from an existing container's config."""
        config = container_info['Config']
        host_config = container_info['HostConfig']

        # Determine network mode constraints
        network_mode = host_config.get('NetworkMode', 'default')
        is_host_network = network_mode == 'host'
        is_container_network = network_mode.startswith('container:')
        shares_network_namespace = is_host_network or is_container_network

        body: Dict[str, Any] = {'Image': image}

        # Hostname (not allowed with host or container: network modes)
        if not shares_network_namespace:
            if config.get('Hostname') and config['Hostname'] != container_info['Id'][:12]:
                body['Hostname'] = config['Hostname']

        # User
        if config.get('User'):
            body['User'] = config['User']

        # Working directory
        if config.get('WorkingDir'):
            body['WorkingDir'] = config['WorkingDir']

        # Environment variables (skip Docker-injected ones)
        body['Env'] = [
            e for e in (config.get('Env') or [])
            if not any(e.startswith(p) for p in ('PATH=', 'HOSTNAME='))
        ]

        # Command
        if config.get('Cmd'):
            body['Cmd'] = config['Cmd']

        # Labels (preserve compose labels for stack membership)
        body['Labels'] = {
            k: v for k, v in (config.get('Labels') or {}).items()
            if k.startswith('com.docker.compose.') or not k.startswith('com.docker.')
        }

        # HostConfig
        hc: Dict[str, Any] = {}

        # Restart policy
        restart_policy = host_config.get('RestartPolicy', {})
        if restart_policy.get('Name'):
            hc['RestartPolicy'] = restart_policy

        # Port bindings (not applicable with host or container: network modes)
        if not shares_network_namespace and host_config.get('PortBindings'):
            hc['PortBindings'] = host_config['PortBindings']

        # Volume/bind mounts
        binds = []
        for mount in container_info.get('Mounts') or []:
            if mount['Type'] == 'bind':
                source = mount['Source']
            elif mount['Type'] == 'volume':
                source = mount['Name']
            else:
                continue
            bind_str = f"{source}:{mount['Destination']}"
            if mount.get('Mode'):
                bind_str += f":{mount['Mode']}"
            binds.append(bind_str)
        if binds:
            hc['Binds'] = binds

        # Network mode
        if network_mode and network_mode != 'default':
            hc['NetworkMode'] = network_mode

        # Privileged
        if host_config.get('Privileged'):
            hc['Privileged'] = True

        # Capabilities
        if host_config.get('CapAdd'):
            hc['CapAdd'] = host_config['CapAdd']
        if host_config.get('CapDrop'):
            hc['CapDrop'] = host_config['CapDrop']

        # Devices
        if host_config.get('Devices'):
            hc['Devices'] = host_config['Devices']

        # Memory limits
        if host_config.get('Memory'):
            hc['Memory'] = host_config['Memory']

        # CPU limits
        if host_config.get('CpuShares'):
            hc['CpuShares'] = host_config['CpuShares']
        if host_config.get('CpuQuota'):
            hc['CpuQuota'] = host_config['CpuQuota']

        # Security options
        if host_config.get('SecurityOpt'):
            hc['SecurityOpt'] = host_config['SecurityOpt']

        # Runtime
        if host_config.get('Runtime'):
            hc['Runtime'] = host_config['Runtime']

        body['HostConfig'] = hc

        # Primary network endpoint config (for custom networks)
        if not is_container_network:
            networks = (container_info.get('NetworkSettings') or {}).get('Networks') or {}
            primary_endpoint = networks.get(network_mode)
            if primary_endpoint:
                body['NetworkingConfig'] = {
                    'EndpointsConfig': {network_mode: primary_endpoint}
                }

        return body

    def _cleanup_old_images(self, image: str, keep_versions: int = 3) -> None:
        """Remove old images via the Engine API, keeping the specified number of most recent versions."""
        try:
            response = self._docker.get(
                '/images/json',
                params={'filters': json.dumps({'reference': [image]})},
            )
            local_images = response.json()

            if not local_images:
                return

            # Expand to one entry per tag, sorted newest-first by creation timestamp
            entries = []
            for img in local_images:
                created = img.get('Created', 0)  # Unix timestamp
                for repo_tag in img.get('RepoTags') or []:
                    tag = repo_tag.rsplit(':', 1)[-1] if ':' in repo_tag else ''
                    if tag and tag != '<none>':
                        entries.append({
                            'id': img['Id'].replace('sha256:', '')[:12],
                            'tag': tag,
                            'created': created,
                        })

            if not entries:
                return

            entries.sort(key=lambda x: x['created'], reverse=True)
            images_to_remove = entries[keep_versions:]

            if not images_to_remove:
                self.logger.debug(f"No old images to clean up for {image} (keeping {keep_versions})")
                return

            if self.dry_run:
                for img in images_to_remove:
                    self.logger.info(
                        f"[DRY RUN] Would remove old image {image}:{img['tag']} ({img['id']})"
                    )
                return

            for img in images_to_remove:
                try:
                    self._docker.delete(f'/images/{image}:{img["tag"]}')
                    self.logger.info(f"Removed old image {image}:{img['tag']}")
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 409:
                        self.logger.debug(f"Could not remove {image}:{img['tag']} (in use)")
                    else:
                        self.logger.debug(f"Could not remove {image}:{img['tag']}: {e}")
                except requests.RequestException:
                    pass

        except requests.RequestException as e:
            self.logger.warning(f"Error during image cleanup: {e}")

    def check_and_update(self, progress_callback=None) -> List[Dict[str, Any]]:
        """Check for updates and apply them if configured.

        Args:
            progress_callback: Optional function(event_type, data) called for progress updates
        """
        if self.dry_run:
            self.logger.info("=== DRY RUN MODE ===")

        updates_found = []
        total_images = len(self.config.get('images', []))

        for idx, image_config in enumerate(self.config.get('images', []), 1):
            image = image_config['image']
            regex = image_config['regex']
            base_tag = image_config.get('base_tag', DEFAULT_BASE_TAG)
            auto_update = image_config.get('auto_update', False)
            registry = image_config.get('registry')
            cleanup = image_config.get('cleanup_old_images', False)
            keep_versions = image_config.get('keep_versions', 3)

            self.logger.info(f"Checking {image}:{base_tag}...")

            # Emit progress: starting check for this image
            if progress_callback:
                progress_callback('checking_image', {
                    'image': image,
                    'base_tag': base_tag,
                    'progress': idx,
                    'total': total_images
                })

            # Find matching tag for current base tag
            result = self.find_matching_tag(image, base_tag, regex, registry)

            if result:
                matching_tag, digest = result
                self.logger.info(f"Base tag '{base_tag}' corresponds to: {matching_tag}")
                self.logger.debug(f"Digest: {digest}")

                # Check if this is different from our saved state
                saved_state = self.state.get(image)

                # Discover all containers using this image
                containers = self._get_containers_for_image(image)

                if not saved_state or saved_state.digest != digest:
                    # Determine current version (from saved state or first container)
                    old_tag = saved_state.tag if saved_state else None
                    if not old_tag and containers:
                        old_tag = self._get_container_current_tag(containers[0]['name'], image, regex)
                    if not old_tag:
                        old_tag = 'unknown'

                    # Only report update if tags are actually different
                    if old_tag != matching_tag:
                        self.logger.info(f"UPDATE AVAILABLE: {old_tag} -> {matching_tag}")

                        update_info = {
                            'image': image,
                            'base_tag': base_tag,
                            'old_tag': old_tag,
                            'new_tag': matching_tag,
                            'digest': digest,
                            'auto_update': auto_update
                        }
                        updates_found.append(update_info)

                        # Emit progress: update found
                        if progress_callback:
                            progress_callback('update_found', update_info)

                        update_ok = True
                        if auto_update:
                            # Pull the new images
                            if self._pull_image(image, base_tag):
                                self._pull_image(image, matching_tag)

                                if containers:
                                    # Update all discovered containers
                                    container_names = [c['name'] for c in containers]
                                    self.logger.info(f"Found {len(containers)} container(s) using {image}: {', '.join(container_names)}")
                                    update_results = self._update_containers(container_names, image, matching_tag)

                                    # Success if any container updated
                                    update_ok = any(update_results.values()) if update_results else True
                                else:
                                    # No containers - just image update
                                    self.logger.info(f"No containers found for {image}, image updated only")
                                    update_ok = True

                                # Only cleanup old images after a successful update,
                                # otherwise we may remove tags still in use
                                if update_ok and cleanup:
                                    self._cleanup_old_images(image, keep_versions)
                            else:
                                update_ok = False

                        # Update state: always for non-auto (to prevent
                        # re-reporting), but only on success for auto_update
                        # so the update is retried next cycle
                        if not auto_update or update_ok:
                            self.state[image] = ImageState(
                                base_tag=base_tag,
                                tag=matching_tag,
                                digest=digest,
                                last_updated=datetime.now().isoformat()
                            )
                    else:
                        # Digest changed but tag is the same — image was
                        # rebuilt under the same tag.  Treat as an update.
                        self.logger.info(f"IMAGE REBUILT: {matching_tag} (new digest)")

                        update_info = {
                            'image': image,
                            'base_tag': base_tag,
                            'old_tag': matching_tag,
                            'new_tag': matching_tag,
                            'digest': digest,
                            'auto_update': auto_update
                        }
                        updates_found.append(update_info)

                        # Emit progress: image rebuilt
                        if progress_callback:
                            progress_callback('image_rebuilt', {
                                'image': image,
                                'tag': matching_tag
                            })

                        update_ok = True
                        if auto_update:
                            # Pull the fresh image
                            if self._pull_image(image, base_tag):
                                self._pull_image(image, matching_tag)

                                if containers:
                                    container_names = [c['name'] for c in containers]
                                    self.logger.info(f"Found {len(containers)} container(s) using {image}: {', '.join(container_names)}")
                                    update_results = self._update_containers(container_names, image, matching_tag)
                                    update_ok = any(update_results.values()) if update_results else True
                                else:
                                    self.logger.info(f"No containers found for {image}, image updated only")
                                    update_ok = True

                                if update_ok and cleanup:
                                    self._cleanup_old_images(image, keep_versions)
                            else:
                                update_ok = False

                        # Update state
                        if not auto_update or update_ok:
                            self.state[image] = ImageState(
                                base_tag=base_tag,
                                tag=matching_tag,
                                digest=digest,
                                last_updated=datetime.now().isoformat()
                            )
                else:
                    self.logger.info("No update available")
                    # Emit progress: no update
                    if progress_callback:
                        progress_callback('no_update', {
                            'image': image,
                            'base_tag': base_tag
                        })

        # Save state
        self._save_state()

        # Summary
        if updates_found:
            self.logger.info("=== Update Summary ===")
            for update in updates_found:
                self.logger.info(
                    f"{update['image']}: {update['old_tag']} -> {update['new_tag']}"
                )
        else:
            self.logger.info("No updates found")

        return updates_found


def main():
    parser = argparse.ArgumentParser(
        description='Image auto-updater with tag tracking'
    )
    parser.add_argument(
        'config',
        nargs='?',
        default=os.environ.get('CONFIG_FILE', 'config.json'),
        help='Path to configuration JSON file (env: CONFIG_FILE, default: config.json)'
    )
    parser.add_argument(
        '--state',
        default=os.environ.get('STATE_FILE', 'image_update_state.json'),
        help='Path to state file (env: STATE_FILE, default: image_update_state.json)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=os.environ.get('DRY_RUN', '').lower() == 'true',
        help='Show what would be done without making any changes (env: DRY_RUN)'
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        default=os.environ.get('DAEMON', '').lower() == 'true',
        help='Run continuously, checking at intervals (env: DAEMON)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=int(os.environ.get('CHECK_INTERVAL', '3600')),
        help='Check interval in seconds when running as daemon (env: CHECK_INTERVAL, default: 3600)'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default=os.environ.get('LOG_LEVEL', 'INFO'),
        help='Logging level (env: LOG_LEVEL, default: INFO)'
    )

    args = parser.parse_args()

    try:
        updater = DockerImageUpdater(
            args.config,
            args.state,
            args.dry_run,
            args.log_level
        )

        if args.daemon:
            updater.logger.info(f"Running in daemon mode, checking every {args.interval} seconds")
            while True:
                try:
                    updater.check_and_update()
                    updater.logger.info(f"Sleeping for {args.interval} seconds...")
                    time.sleep(args.interval)
                except KeyboardInterrupt:
                    updater.logger.info("Exiting...")
                    break
                except Exception as e:
                    updater.logger.error(f"Error during update check: {e}")
                    time.sleep(args.interval)
        else:
            updater.check_and_update()

    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
