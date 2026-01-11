#!/usr/bin/env python3
"""
Docker Image Auto-Update with Specific Tag Tracking

This script monitors Docker images for updates by comparing the 'latest' tag
with version-specific tags that match user-defined regex patterns.
"""

import json
import re
import subprocess
import sys
import time
import logging
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Union
from pathlib import Path
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import argparse
import os
import platform
import requests
from urllib.parse import urlparse
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
                    "container_name": {"type": "string"},
                    "registry": {"type": "string"},
                    "cleanup_old_images": {"type": "boolean"}
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
                
                # If platform specified, find matching manifest
                if platform:
                    for manifest in manifest_list.get('manifests', []):
                        if manifest.get('platform', {}).get('os') + '/' + \
                           manifest.get('platform', {}).get('architecture') == platform:
                            return manifest.get('digest')
                            
                # Return first manifest if no platform specified
                if manifest_list.get('manifests'):
                    return manifest_list['manifests'][0].get('digest')
                    
            # Single manifest
            return response.headers.get('Docker-Content-Digest')
            
        except requests.RequestException as e:
            self.logger.error(f"Error getting manifest for {namespace}/{repo}:{tag}: {e}")
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
            return response.json().get('tags', [])
        except requests.RequestException as e:
            self.logger.error(f"Error getting tags for {namespace}/{repo}: {e}")
            return []
            
    def find_matching_tag(self, image: str, base_tag: str, regex_pattern: str,
                         registry_override: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        Find a tag matching the regex pattern that has the same digest as the base tag.
        
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
        
        # Get digest for base tag
        base_digest = self._get_manifest_digest(registry, namespace, repo, base_tag, token)
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
        
        # Find which matching tag has the same digest as base tag
        for tag in matching_tags:
            tag_digest = self._get_manifest_digest(registry, namespace, repo, tag, token)
            if tag_digest == base_digest:
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
            result = subprocess.run(
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
        except (subprocess.CalledProcessError, json.JSONDecodeError, IndexError) as e:
            self.logger.error(f"Error getting container config: {e}")
            return None

    def _get_container_current_tag(self, container_name: str, image: str, regex: str) -> Optional[str]:
        """Get the current version tag of a running container."""
        try:
            container_info = self._get_container_config(container_name)
            if not container_info:
                self.logger.debug(f"Container {container_name} not found or no config")
                return None

            # Get the image reference from the container config
            image_ref = container_info.get('Config', {}).get('Image', '')
            if not image_ref:
                self.logger.debug(f"No image reference found for container {container_name}")
                return None

            # Extract tag from image reference
            if ':' in image_ref and image_ref.startswith(image):
                tag = image_ref.split(':', 1)[1]

                # Get cached compiled pattern
                pattern = self.compiled_patterns.get(regex)
                if not pattern:
                    self.logger.debug(f"Pattern not found in cache: '{regex}'")
                    return None

                # Check if tag matches the regex pattern
                if pattern.match(tag):
                    self.logger.debug(f"Found matching tag for {container_name}: {tag}")
                    return tag

                self.logger.debug(f"Tag {tag} doesn't match pattern for {container_name}")

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
            # Save container ID for cleanup
            container_id = container_info['Id']
            
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
            
    def _build_run_command(self, container_name: str, image: str, 
                          container_info: Dict[str, Any]) -> List[str]:
        """Build docker run command preserving container settings."""
        cmd = ['docker', 'run', '-d', '--name', container_name]
        
        config = container_info['Config']
        host_config = container_info['HostConfig']
        
        # Restart policy
        restart_policy = host_config.get('RestartPolicy', {})
        if restart_policy.get('Name'):
            if restart_policy['Name'] == 'on-failure':
                cmd.extend(['--restart', f"on-failure:{restart_policy.get('MaximumRetryCount', 0)}"])
            else:
                cmd.extend(['--restart', restart_policy['Name']])
                
        # Hostname
        if config.get('Hostname') and config['Hostname'] != container_info['Id'][:12]:
            cmd.extend(['--hostname', config['Hostname']])
            
        # User
        if config.get('User'):
            cmd.extend(['--user', config['User']])
            
        # Working directory
        if config.get('WorkingDir'):
            cmd.extend(['--workdir', config['WorkingDir']])
            
        # Environment variables
        for env_var in config.get('Env', []):
            # Skip Docker-injected variables
            if not any(env_var.startswith(prefix) for prefix in ['PATH=', 'HOSTNAME=']):
                cmd.extend(['-e', env_var])
                
        # Port mappings
        for container_port, bindings in host_config.get('PortBindings', {}).items():
            if bindings:
                for binding in bindings:
                    host_ip = binding.get('HostIp', '')
                    host_port = binding.get('HostPort', '')
                    if host_ip and host_ip != '0.0.0.0':
                        cmd.extend(['-p', f"{host_ip}:{host_port}:{container_port}"])
                    else:
                        cmd.extend(['-p', f"{host_port}:{container_port}"])
                        
        # Volume mappings
        for mount in container_info.get('Mounts', []):
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
        if host_config.get('NetworkMode') and host_config['NetworkMode'] != 'default':
            cmd.extend(['--network', host_config['NetworkMode']])
            
        # Additional networks
        for network in container_info.get('NetworkSettings', {}).get('Networks', {}).keys():
            if network != host_config.get('NetworkMode'):
                cmd.extend(['--network', network])
                
        # Privileged
        if host_config.get('Privileged'):
            cmd.append('--privileged')
            
        # Capabilities
        for cap in host_config.get('CapAdd', []):
            cmd.extend(['--cap-add', cap])
        for cap in host_config.get('CapDrop', []):
            cmd.extend(['--cap-drop', cap])
            
        # Devices
        for device in host_config.get('Devices', []):
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
            
        # Labels
        for key, value in config.get('Labels', {}).items():
            # Skip Docker-injected labels
            if not key.startswith('com.docker.'):
                cmd.extend(['--label', f"{key}={value}"])
                
        # Security options
        for opt in host_config.get('SecurityOpt', []):
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
        
    def _cleanup_old_images(self, image: str) -> None:
        """Remove unused images."""
        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would cleanup old images for {image}")
            return
            
        try:
            # Get all image IDs for this repository
            result = subprocess.run(
                ['docker', 'images', '-q', image],
                capture_output=True,
                text=True,
                check=True
            )
            
            image_ids = result.stdout.strip().split('\n')
            image_ids = [img_id for img_id in image_ids if img_id]
            
            # Try to remove each image (will fail if in use)
            for img_id in image_ids:
                try:
                    subprocess.run(
                        ['docker', 'rmi', img_id],
                        capture_output=True,
                        check=False  # Don't fail if image is in use
                    )
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
            container_name = image_config.get('container_name')
            registry = image_config.get('registry')
            cleanup = image_config.get('cleanup_old_images', False)
            
            self.logger.info(f"Checking {image}:{base_tag}...")
            
            # Find matching tag for current base tag
            result = self.find_matching_tag(image, base_tag, regex, registry)
            
            if result:
                matching_tag, digest = result
                self.logger.info(f"Base tag '{base_tag}' corresponds to: {matching_tag}")
                self.logger.debug(f"Digest: {digest}")
                
                # Check if this is different from our saved state
                saved_state = self.state.get(image)

                if not saved_state or saved_state.digest != digest:
                    # Try to get current tag from saved state, or from running container
                    old_tag = saved_state.tag if saved_state else None
                    if not old_tag and container_name:
                        old_tag = self._get_container_current_tag(container_name, image, regex)
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
                            'digest': digest
                        })

                        if auto_update:
                            # Pull the new images
                            if self._pull_image(image, base_tag):
                                self._pull_image(image, matching_tag)

                                # Update container if specified
                                if container_name:
                                    self._update_container(container_name, image, base_tag)

                                # Cleanup old images if requested
                                if cleanup:
                                    self._cleanup_old_images(image)

                                # Update state
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


def main():
    parser = argparse.ArgumentParser(
        description='Docker image auto-updater with tag tracking'
    )
    parser.add_argument('config', help='Path to configuration JSON file')
    parser.add_argument(
        '--state', 
        default='docker_update_state.json',
        help='Path to state file (default: docker_update_state.json)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making any changes'
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run continuously, checking at intervals'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=3600,
        help='Check interval in seconds when running as daemon (default: 3600)'
    )
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level (default: INFO)'
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