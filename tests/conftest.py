"""Shared fixtures for ium tests."""

import re
import pytest
from dataclasses import asdict

from ium import CONFIG_SCHEMA, ImageState

# ---------------------------------------------------------------------------
# Tag lists derived from the real Docker image inventory (test_data.txt)
# ---------------------------------------------------------------------------

# Simulated tag lists: real version tags + noise that should NOT match
DOCKERHUB_TAG_LISTS = {
    "budibase/budibase": [
        "latest", "develop", "3.20.12", "3.2.29", "3.19.0", "3.2.0",
        "v2-latest", "master", "2.32.13",
    ],
    "crazymax/diun": [
        "latest", "edge", "4.30.0", "4.29.0", "4.28.0", "4.0.0-rc.1",
    ],
    "jellyfin/jellyfin": [
        "latest", "unstable", "10.11.4", "10.11.1", "10.10.0",
        "10.11.4-amd64", "latest-amd64",
    ],
    "n8nio/n8n": [
        "latest", "next", "2.0.3", "1.99.0", "2.0.3-beta",
    ],
    "portainer/portainer-ce": [
        "latest", "alpine", "2.33.1", "2.27.9", "2.26.0", "linux-amd64",
    ],
    "pihole/pihole": [
        "latest", "development", "nightly", "2025.11.1", "2025.08.0",
        "2024.07.0", "v6", "beta",
    ],
    "linuxserver/calibre": [
        "latest", "nightly", "v8.16.2-ls374", "v8.12.0-ls359",
        "v8.10.0-ls350", "version-v8.16.2", "arm64v8-latest",
    ],
    "linuxserver/calibre-web": [
        "latest", "nightly", "0.6.25-ls348", "0.6.25-ls345",
        "0.6.24-ls340", "amd64-latest",
    ],
    "linuxserver/bazarr": [
        "latest", "development", "v1.5.3-ls328", "v1.5.3-ls321",
        "v1.5.2-ls310", "testing",
    ],
    "linuxserver/tautulli": [
        "latest", "develop", "v2.16.0-ls203", "v2.15.3-ls199",
    ],
    "linuxserver/sabnzbd": [
        "latest", "unstable", "4.5.3-ls229", "4.5.1-ls217", "4.4.0-ls200",
    ],
    "linuxserver/lidarr": [
        "latest", "nightly", "2.8.2.4493-ls22", "2.7.0.4420-ls18",
    ],
    "linuxserver/prowlarr": [
        "latest", "develop", "nightly", "2.3.0.5236-ls134",
        "2.0.5.5160-ls128", "1.37.0.5076-ls123",
    ],
    "linuxserver/radarr": [
        "latest", "nightly", "6.0.4.10291-ls289", "5.27.5.10198-ls284",
    ],
    "linuxserver/sonarr": [
        "latest", "develop", "4.0.16.2944-ls299", "4.0.15.2941-ls294",
    ],
    "linuxserver/qbittorrent": [
        "latest", "unstable", "5.1.2-r1-ls411", "5.1.0-r0-ls393",
        "5.0.0-r0-ls380",
    ],
    "plexinc/pms-docker": [
        "latest", "plexpass", "beta", "public",
        "1.42.2.10156-f737b826c", "1.42.1.10060-4e8b05daf",
        "1.41.0.9430-abc123def",
    ],
}

GHCR_TAG_LISTS = {
    "ghcr.io/homarr-labs/homarr": [
        "latest", "dev", "v1.46.0", "v1.41.0", "v1.40.0", "sha-abc1234",
    ],
    "ghcr.io/mealie-recipes/mealie": [
        "latest", "nightly", "v2.5.0", "v2.4.0", "v2.3.0",
    ],
}

ALL_TAG_LISTS = {**DOCKERHUB_TAG_LISTS, **GHCR_TAG_LISTS}


# ---------------------------------------------------------------------------
# Regex patterns for each image category (from CLAUDE.md + inventory analysis)
# ---------------------------------------------------------------------------

REGEX_PATTERNS = {
    # Simple semver (no v-prefix)
    "simple_semver": r"^[0-9]+\.[0-9]+\.[0-9]+$",
    # v-prefixed semver
    "v_semver": r"^v[0-9]+\.[0-9]+\.[0-9]+$",
    # LinuxServer with v-prefix
    "ls_v_prefix": r"^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
    # LinuxServer without v-prefix
    "ls_no_prefix": r"^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
    # LinuxServer 4-part version
    "ls_4part": r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
    # LinuxServer with -r suffix (qbittorrent)
    "ls_r_suffix": r"^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+-ls[0-9]+$",
    # Version + git hash (Plex)
    "ver_git_hash": r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$",
}

# Map images to their expected regex pattern key
IMAGE_REGEX_MAP = {
    "budibase/budibase": "simple_semver",
    "crazymax/diun": "simple_semver",
    "jellyfin/jellyfin": "simple_semver",
    "n8nio/n8n": "simple_semver",
    "portainer/portainer-ce": "simple_semver",
    "pihole/pihole": "simple_semver",
    "ghcr.io/homarr-labs/homarr": "v_semver",
    "ghcr.io/mealie-recipes/mealie": "v_semver",
    "linuxserver/calibre": "ls_v_prefix",
    "linuxserver/bazarr": "ls_v_prefix",
    "linuxserver/tautulli": "ls_v_prefix",
    "linuxserver/calibre-web": "ls_no_prefix",
    "linuxserver/sabnzbd": "ls_no_prefix",
    "linuxserver/lidarr": "ls_4part",
    "linuxserver/prowlarr": "ls_4part",
    "linuxserver/radarr": "ls_4part",
    "linuxserver/sonarr": "ls_4part",
    "linuxserver/qbittorrent": "ls_r_suffix",
    "plexinc/pms-docker": "ver_git_hash",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_pattern(key: str) -> re.Pattern:
    """Compile and return a regex pattern by key."""
    return re.compile(REGEX_PATTERNS[key])


def filter_tags(tags: list[str], pattern: re.Pattern) -> list[str]:
    """Return tags that match the pattern (same logic as ium.py)."""
    return [t for t in tags if pattern.match(t)]


# ---------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_config():
    """Minimal valid config with one image."""
    return {
        "images": [{
            "image": "linuxserver/calibre",
            "regex": r"^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
        }]
    }


@pytest.fixture
def full_config():
    """Config exercising all optional fields."""
    return {
        "images": [{
            "image": "linuxserver/calibre",
            "regex": r"^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
            "base_tag": "latest",
            "auto_update": False,
            "cleanup_old_images": True,
            "keep_versions": 3,
        }]
    }


@pytest.fixture
def sample_state():
    """Sample ImageState for serialization tests."""
    return ImageState(
        base_tag="latest",
        tag="v8.16.2-ls374",
        digest="sha256:abc123",
        last_updated="2025-01-01T00:00:00",
    )


@pytest.fixture
def multi_image_config():
    """Config with one image per regex category."""
    return {
        "images": [
            {"image": image, "regex": REGEX_PATTERNS[pat_key]}
            for image, pat_key in IMAGE_REGEX_MAP.items()
        ]
    }
