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
import subprocess
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


@dataclass
class ImageState:
    """State information for a tracked image."""
    base_tag: str
    tag: str
    digest: str
    last_updated: str


class DockerImageUpdater:
    def __init__(self, config_file: str, state_file: str = "docker_update_state.json", 
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
                try:
                    self.compiled_patterns[regex_pattern] = re.compile(regex_pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex pattern '{regex_pattern}': {e}")
                    
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
        Pull a Docker image.
        
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
            # Use subprocess with proper argument handling
            subprocess.run(
                ['docker', 'pull', full_image],
                capture_output=True,
                text=True,
                check=True
            )
            self.logger.info(f"Successfully pulled {full_image}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error pulling {full_image}: {e.stderr}")
            return False
            
    def _get_container_config(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get full container configuration."""
        try:
            result = subprocess.run(
                ['docker', 'inspect', container_name],
                capture_output=True,
                text=True,
                check=True
            )
            return json.loads(result.stdout)[0]
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or '').strip()
            self.logger.error(
                f"Error inspecting container '{container_name}': {stderr or e}. "
                f"Check that the container_name in config matches a running container (docker ps -a --format '{{{{.Names}}}}')"
            )
            return None
        except (json.JSONDecodeError, IndexError) as e:
            self.logger.error(f"Error parsing container config for '{container_name}': {e}")
            return None

    def _get_containers_for_image(self, image: str) -> List[Dict[str, str]]:
        """Get all containers (running or stopped) using a specific image.

        Returns:
            List of dicts with keys: name, id, state, image_ref
        """
        try:
            result = subprocess.run(
                ['docker', 'ps', '-a', '--format', 'json'],
                capture_output=True,
                text=True,
                check=True
            )

            containers = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                try:
                    container = json.loads(line)
                    container_image = container.get('Image', '')

                    if self._image_matches(image, container_image):
                        containers.append({
                            'name': container.get('Names', ''),
                            'id': container.get('ID', ''),
                            'state': container.get('State', ''),
                            'image_ref': container_image
                        })
                except json.JSONDecodeError:
                    continue

            return containers

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to list containers: {e}")
            return []

    def _image_matches(self, config_image: str, container_image: str) -> bool:
        """Check if a container image matches the configured image.

        Handles:
        - Tag variations: nginx matches nginx:alpine
        - Registry prefixes: linuxserver/sonarr matches lscr.io/linuxserver/sonarr:latest
        - Implicit library namespace: postgres matches library/postgres
        """
        # Normalize images by removing tags for comparison
        def normalize(img: str) -> str:
            # Split on last colon to separate tag
            parts = img.rsplit(':', 1)
            base = parts[0]

            # Handle registry prefixes (keep everything before /)
            # linuxserver/sonarr stays as-is
            # lscr.io/linuxserver/sonarr becomes linuxserver/sonarr
            if '/' in base:
                path_parts = base.split('/')
                # If first part has a dot or is localhost, it's a registry
                if '.' in path_parts[0] or path_parts[0] == 'localhost':
                    base = '/'.join(path_parts[1:])

            # Handle implicit library namespace
            # postgres becomes library/postgres for comparison
            if '/' not in base:
                return f"library/{base}"

            return base

        normalized_config = normalize(config_image)
        normalized_container = normalize(container_image)

        # Also check without library prefix
        normalized_config_no_lib = normalized_config.replace('library/', '')
        normalized_container_no_lib = normalized_container.replace('library/', '')

        return (normalized_config == normalized_container or
                normalized_config_no_lib == normalized_container_no_lib)

    def _get_container_current_tag(self, container_name: str, image: str, regex: str) -> Optional[str]:
        """Get the current version tag of a running container by checking image inventory."""
        try:
            container_info = self._get_container_config(container_name)
            if not container_info:
                self.logger.debug(f"Container {container_name} not found or no config")
                return None

            # Get the image ID (sha256) from the container
            image_id = container_info.get('Image', '')
            if not image_id:
                self.logger.debug(f"No image ID found for container {container_name}")
                return None

            # Get cached compiled pattern
            pattern = self.compiled_patterns.get(regex)
            if not pattern:
                self.logger.debug(f"Pattern not found in cache: '{regex}'")
                return None

            # Query docker images to find all tags for this image name
            result = subprocess.run(
                ['docker', 'images', image, '--format', '{{.Tag}} {{.ID}}'],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                self.logger.debug(f"Failed to get image tags for {image}")
                return None

            # Extract short ID from container's image (first 12 chars after sha256:)
            short_id = image_id.replace('sha256:', '')[:12]

            # Find tags that match both the image ID and regex pattern
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    tag, tag_id = parts[0], parts[1]
                    if tag_id == short_id and pattern.match(tag):
                        self.logger.debug(f"Found matching tag for {container_name}: {tag}")
                        return tag

            self.logger.debug(f"No matching tag found in image inventory for {container_name}")
            return None
        except Exception as e:
            self.logger.debug(f"Could not get current tag for {container_name}: {e}")
            return None

    def _update_container(self, container_name: str, image: str, tag: str) -> bool:
        """
        Update a running container with a new image.
        
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
            
        try:
            # Build docker run command preserving all settings
            run_cmd = self._build_run_command(container_name, full_image, container_info)

            # Stop the container
            self.logger.info(f"Stopping container {container_name}...")
            subprocess.run(['docker', 'stop', container_name], check=True)
            
            # Rename old container as backup
            backup_name = f"{container_name}_backup_{int(time.time())}"
            self.logger.info(f"Renaming old container to {backup_name}")
            subprocess.run(['docker', 'rename', container_name, backup_name], check=True)
            
            # Create new container
            self.logger.info(f"Creating new container {container_name}...")
            result = subprocess.run(run_cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                # Rollback on failure
                self.logger.error(f"Failed to create new container: {result.stderr}")
                self.logger.info("Rolling back...")
                subprocess.run(['docker', 'rename', backup_name, container_name], check=False)
                subprocess.run(['docker', 'start', container_name], check=False)
                return False
                
            # Success - remove old container
            self.logger.info(f"Removing old container {backup_name}")
            subprocess.run(['docker', 'rm', backup_name], check=True)
            
            self.logger.info(f"Successfully updated container {container_name}")
            return True
            
        except subprocess.CalledProcessError as e:
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

    def _build_run_command(self, container_name: str, image: str, 
                          container_info: Dict[str, Any]) -> List[str]:
        """Build docker run command preserving container settings."""
        cmd = ['docker', 'run', '-d', '--name', container_name]
        
        config = container_info['Config']
        host_config = container_info['HostConfig']

        # Determine network mode constraints
        network_mode = host_config.get('NetworkMode', 'default')
        is_host_network = network_mode == 'host'
        is_container_network = network_mode.startswith('container:')
        shares_network_namespace = is_host_network or is_container_network

        # Restart policy
        restart_policy = host_config.get('RestartPolicy', {})
        if restart_policy.get('Name'):
            if restart_policy['Name'] == 'on-failure':
                cmd.extend(['--restart', f"on-failure:{restart_policy.get('MaximumRetryCount', 0)}"])
            else:
                cmd.extend(['--restart', restart_policy['Name']])

        # Hostname (not allowed with host or container: network modes)
        if not shares_network_namespace:
            if config.get('Hostname') and config['Hostname'] != container_info['Id'][:12]:
                cmd.extend(['--hostname', config['Hostname']])

        # User
        if config.get('User'):
            cmd.extend(['--user', config['User']])

        # Working directory
        if config.get('WorkingDir'):
            cmd.extend(['--workdir', config['WorkingDir']])

        # Environment variables
        for env_var in config.get('Env') or []:
            # Skip Docker-injected variables
            if not any(env_var.startswith(prefix) for prefix in ('PATH=', 'HOSTNAME=')):
                cmd.extend(['-e', env_var])

        # Port mappings (not applicable with host or container: network modes)
        if not shares_network_namespace:
            for container_port, bindings in (host_config.get('PortBindings') or {}).items():
                if bindings:
                    for binding in bindings:
                        host_ip = binding.get('HostIp', '')
                        host_port = binding.get('HostPort', '')
                        if host_ip and host_ip != '0.0.0.0':
                            cmd.extend(['-p', f"{host_ip}:{host_port}:{container_port}"])
                        else:
                            cmd.extend(['-p', f"{host_port}:{container_port}"])
                        
        # Volume mappings
        for mount in container_info.get('Mounts') or []:
            if mount['Type'] == 'bind':
                source = mount['Source']
            elif mount['Type'] == 'volume':
                source = mount['Name']
            else:
                continue

            mount_str = f"{source}:{mount['Destination']}"
            if mount.get('Mode'):
                mount_str += f":{mount['Mode']}"
            cmd.extend(['-v', mount_str])
                
        # Network mode
        if network_mode and network_mode != 'default':
            cmd.extend(['--network', network_mode])

        # Additional networks (not applicable with container: network mode)
        if not is_container_network:
            for network in ((container_info.get('NetworkSettings') or {}).get('Networks') or {}).keys():
                if network != network_mode:
                    cmd.extend(['--network', network])
                
        # Privileged
        if host_config.get('Privileged'):
            cmd.append('--privileged')
            
        # Capabilities
        for cap in host_config.get('CapAdd') or []:
            cmd.extend(['--cap-add', cap])
        for cap in host_config.get('CapDrop') or []:
            cmd.extend(['--cap-drop', cap])

        # Devices
        for device in host_config.get('Devices') or []:
            device_str = device['PathOnHost']
            if device.get('PathInContainer'):
                device_str += f":{device['PathInContainer']}"
            if device.get('CgroupPermissions'):
                device_str += f":{device['CgroupPermissions']}"
            cmd.extend(['--device', device_str])
            
        # Memory limits
        if host_config.get('Memory'):
            cmd.extend(['-m', str(host_config['Memory'])])
            
        # CPU limits
        if host_config.get('CpuShares'):
            cmd.extend(['--cpu-shares', str(host_config['CpuShares'])])
        if host_config.get('CpuQuota'):
            cmd.extend(['--cpu-quota', str(host_config['CpuQuota'])])
            
        # Labels (preserve compose labels for stack membership)
        for key, value in (config.get('Labels') or {}).items():
            if key.startswith('com.docker.compose.'):
                cmd.extend(['--label', f"{key}={value}"])
            elif not key.startswith('com.docker.'):
                cmd.extend(['--label', f"{key}={value}"])

        # Security options
        for opt in host_config.get('SecurityOpt') or []:
            cmd.extend(['--security-opt', opt])
            
        # Runtime
        if host_config.get('Runtime'):
            cmd.extend(['--runtime', host_config['Runtime']])
            
        # Add the image
        cmd.append(image)
        
        # Command and args
        if config.get('Cmd'):
            cmd.extend(config['Cmd'])
            
        return cmd
        
    def _cleanup_old_images(self, image: str, keep_versions: int = 3) -> None:
        """Remove old images, keeping the specified number of most recent versions."""
        try:
            # Get all images for this repository with ID, tag, and creation time
            result = subprocess.run(
                ['docker', 'images', '--format', '{{.ID}}\t{{.Tag}}\t{{.CreatedAt}}', image],
                capture_output=True,
                text=True,
                check=True
            )

            lines = result.stdout.strip().split('\n')
            lines = [line for line in lines if line]

            if not lines:
                return

            # Parse and sort by creation time (newest first)
            images = []
            for line in lines:
                parts = line.split('\t')
                if len(parts) >= 3:
                    img_id, tag, created = parts[0], parts[1], parts[2]
                    # Skip <none> tags
                    if tag != '<none>':
                        images.append({'id': img_id, 'tag': tag, 'created': created})

            # Sort by creation date descending (newest first)
            images.sort(key=lambda x: x['created'], reverse=True)

            # Keep the first N versions, mark the rest for removal
            images_to_remove = images[keep_versions:]

            if not images_to_remove:
                self.logger.debug(f"No old images to clean up for {image} (keeping {keep_versions})")
                return

            if self.dry_run:
                for img in images_to_remove:
                    self.logger.info(f"[DRY RUN] Would remove old image {image}:{img['tag']} ({img['id'][:12]})")
                return

            # Remove old images
            for img in images_to_remove:
                try:
                    result = subprocess.run(
                        ['docker', 'rmi', f"{image}:{img['tag']}"],
                        capture_output=True,
                        text=True,
                        check=False  # Don't fail if image is in use
                    )
                    if result.returncode == 0:
                        self.logger.info(f"Removed old image {image}:{img['tag']}")
                    else:
                        self.logger.debug(f"Could not remove {image}:{img['tag']} (may be in use)")
                except (subprocess.SubprocessError, OSError):
                    pass

        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Error during image cleanup: {e}")
            
    def check_and_update(self) -> List[Dict[str, Any]]:
        """Check for updates and apply them if configured."""
        if self.dry_run:
            self.logger.info("=== DRY RUN MODE ===")
            
        updates_found = []
        
        for image_config in self.config.get('images', []):
            image = image_config['image']
            regex = image_config['regex']
            base_tag = image_config.get('base_tag', DEFAULT_BASE_TAG)
            auto_update = image_config.get('auto_update', False)
            registry = image_config.get('registry')
            cleanup = image_config.get('cleanup_old_images', False)
            keep_versions = image_config.get('keep_versions', 3)
            
            self.logger.info(f"Checking {image}:{base_tag}...")
            
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

                        updates_found.append({
                            'image': image,
                            'base_tag': base_tag,
                            'old_tag': old_tag,
                            'new_tag': matching_tag,
                            'digest': digest,
                            'auto_update': auto_update
                        })

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
                        self.logger.info(f"Already up to date: {matching_tag}")
                else:
                    self.logger.info("No update available")
                    
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


# ---------------------------------------------------------------------------
# Tag Pattern Detection
# ---------------------------------------------------------------------------

KNOWN_PATTERNS = {
    r"^[0-9]+\.[0-9]+\.[0-9]+$": "Semantic version (X.Y.Z)",
    r"^v[0-9]+\.[0-9]+\.[0-9]+$": "Semantic version with v (vX.Y.Z)",
    r"^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$": "LinuxServer with v (vX.Y.Z-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$": "LinuxServer (X.Y.Z-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$": "LinuxServer 4-part (W.X.Y.Z-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+-ls[0-9]+$": "LinuxServer with revision (X.Y.Z-rN-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$": "Version with git hash (W.X.Y.Z-hash)",
    r"^[0-9]+\.[0-9]+$": "Major.Minor (X.Y)",
}

# Tags that are pure noise and should be filtered out
_NOISE_TAGS = {
    "latest", "nightly", "develop", "development", "dev", "edge", "master",
    "main", "stable", "unstable", "testing", "beta", "alpha", "rc", "next",
    "canary", "preview", "experimental", "plexpass", "public", "alpine",
}


def _tokenize_tag(tag: str) -> List[tuple]:
    """Parse a tag into typed tokens: (type, literal).

    Token types: PREFIX_V, NUM, DOT, DASH, ALPHA, HEX
    """
    tokens = []
    i = 0
    length = len(tag)

    while i < length:
        ch = tag[i]

        if ch == '.':
            tokens.append(('DOT', '.'))
            i += 1
        elif ch == '-':
            # Look ahead: hex sequence (>=7 hex chars) after a dash
            rest = tag[i + 1:]
            hex_match = re.match(r'^([0-9a-f]{7,})(?=$|[^0-9a-zA-Z])', rest)
            if hex_match:
                tokens.append(('DASH', '-'))
                tokens.append(('HEX', hex_match.group(1)))
                i += 1 + len(hex_match.group(1))
            else:
                tokens.append(('DASH', '-'))
                i += 1
        elif ch.isdigit():
            j = i
            while j < length and tag[j].isdigit():
                j += 1
            tokens.append(('NUM', tag[i:j]))
            i = j
        elif ch.isalpha():
            j = i
            while j < length and tag[j].isalpha():
                j += 1
            word = tag[i:j]
            # 'v' before digits is a PREFIX_V
            if word == 'v' and j < length and tag[j].isdigit() and not tokens:
                tokens.append(('PREFIX_V', 'v'))
            else:
                tokens.append(('ALPHA', word))
            i = j
        else:
            # Skip unexpected characters
            i += 1

    return tokens


def _signature_from_tokens(tokens: List[tuple]) -> str:
    """Build a hashable signature string from token types.

    ALPHA tokens include their literal so that 'ls' and 'rc' produce
    different signatures.
    """
    parts = []
    for ttype, literal in tokens:
        if ttype == 'ALPHA':
            parts.append(f'ALPHA:{literal}')
        else:
            parts.append(ttype)
    return '|'.join(parts)


def _regex_from_token_groups(token_groups: List[List[tuple]]) -> str:
    """Generate an anchored regex from a list of token sequences sharing the
    same signature.

    For each position:
      NUM    -> [0-9]+
      DOT    -> \\.
      DASH   -> -
      PREFIX_V -> v
      HEX    -> [0-9a-f]+
      ALPHA  -> literal if all identical, else [a-z]+
    """
    if not token_groups:
        return ''

    # Use first group as the template (all share the same signature)
    template = token_groups[0]
    parts = []

    for pos, (ttype, _) in enumerate(template):
        if ttype == 'NUM':
            parts.append('[0-9]+')
        elif ttype == 'DOT':
            parts.append('\\.')
        elif ttype == 'DASH':
            parts.append('-')
        elif ttype == 'PREFIX_V':
            parts.append('v')
        elif ttype == 'HEX':
            parts.append('[0-9a-f]+')
        elif ttype == 'ALPHA':
            # Check if all groups have the same literal at this position
            literals = {group[pos][1] for group in token_groups}
            if len(literals) == 1:
                parts.append(literals.pop())
            else:
                parts.append('[a-z]+')

    return '^' + ''.join(parts) + '$'


def _auto_label(regex: str) -> str:
    """Generate a human-readable label from a regex pattern."""
    label = regex.strip('^$')

    # Build a readable representation
    replacements = [
        ('[0-9]+', 'N'),
        ('\\.', '.'),
        ('[0-9a-f]+', 'hash'),
        ('[a-z]+', 'text'),
    ]
    readable = label
    for old, new in replacements:
        readable = readable.replace(old, new)

    return f"Pattern: {readable}"


def detect_tag_patterns(tags: List[str]) -> List[Dict[str, Any]]:
    """Detect structural tag patterns from a list of registry tags.

    Returns a list of dicts sorted by match_count descending:
        {regex, label, match_count, example_tags}
    """
    if not tags:
        return []

    # 1. Filter noise
    filtered = []
    for tag in tags:
        low = tag.lower()
        # Skip pure-alpha noise tags
        if low in _NOISE_TAGS:
            continue
        # Skip single-char tags
        if len(tag) <= 1:
            continue
        # Skip sha refs
        if tag.startswith('sha-') or tag.startswith('sha256:'):
            continue
        # Skip arch suffixes as standalone tags
        if re.match(r'^(linux-)?(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        # Skip tags ending with arch suffixes (e.g., "latest-amd64", "10.11.4-amd64")
        if re.search(r'-(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        # Skip pure-alpha tags (all letters, no digits)
        if re.match(r'^[a-zA-Z][-a-zA-Z]*$', tag):
            continue
        filtered.append(tag)

    if not filtered:
        return []

    # Build index for recency: last in list = most recently pushed
    tag_index = {tag: i for i, tag in enumerate(filtered)}

    # 2. Tokenize each tag
    tokenized = []  # list of (tag, tokens)
    for tag in filtered:
        tokens = _tokenize_tag(tag)
        if tokens:
            tokenized.append((tag, tokens))

    # 3. Group by signature
    groups: Dict[str, List] = {}  # signature -> list of (tag, tokens)
    for tag, tokens in tokenized:
        sig = _signature_from_tokens(tokens)
        groups.setdefault(sig, []).append((tag, tokens))

    # 4. Generate regex per group, filter groups with <2 tags
    results = []
    for sig, members in groups.items():
        if len(members) < 2:
            continue

        token_groups = [tokens for _, tokens in members]
        regex = _regex_from_token_groups(token_groups)
        if not regex:
            continue

        # Compile and verify it actually matches the tags
        try:
            compiled = re.compile(regex)
        except re.error:
            continue

        matching_tags = [tag for tag, _ in members if compiled.match(tag)]
        if len(matching_tags) < 2:
            continue

        # 5. Match against KNOWN_PATTERNS for label
        label = KNOWN_PATTERNS.get(regex) or _auto_label(regex)

        # Pick example tags (up to 3, newest first — last in list = most recent)
        examples = matching_tags[-3:][::-1]

        # Track recency: index of the most recently pushed tag in this group
        most_recent_idx = max(tag_index[t] for t in matching_tags)

        results.append({
            'regex': regex,
            'label': label,
            'match_count': len(matching_tags),
            'example_tags': examples,
            '_recency': most_recent_idx,
        })

    # 6. Sort by recency (most recently pushed pattern first)
    results.sort(key=lambda r: r.pop('_recency'), reverse=True)

    return results


def detect_base_tags(tags: List[str], version_patterns: List[Dict[str, Any]]) -> List[str]:
    """Detect likely base tags (non-version tags like 'latest', 'stable', 'lts').

    Finds tags that don't match any detected version pattern, filtering out
    architecture variants and other noise. Returns tags sorted by recency
    (most recently pushed first).
    """
    if not tags:
        return []

    # Compile version regexes from detected patterns
    compiled = []
    for p in version_patterns:
        try:
            compiled.append(re.compile(p['regex']))
        except re.error:
            continue

    candidates = []
    for tag in tags:
        low = tag.lower()
        # Skip single-char tags
        if len(tag) <= 1:
            continue
        # Skip sha refs
        if tag.startswith('sha-') or tag.startswith('sha256:'):
            continue
        # Skip architecture tags
        if re.match(r'^(linux-)?(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        if re.search(r'-(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        # Skip tags that match any detected version pattern
        if any(r.match(tag) for r in compiled):
            continue
        candidates.append(tag)

    # Most recently pushed last in list → reverse for recency-first
    candidates.reverse()
    return candidates


def main():
    parser = argparse.ArgumentParser(
        description='Docker image auto-updater with tag tracking'
    )
    parser.add_argument(
        'config',
        nargs='?',
        default=os.environ.get('CONFIG_FILE', 'config.json'),
        help='Path to configuration JSON file (env: CONFIG_FILE, default: config.json)'
    )
    parser.add_argument(
        '--state',
        default=os.environ.get('STATE_FILE', 'docker_update_state.json'),
        help='Path to state file (env: STATE_FILE, default: docker_update_state.json)'
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