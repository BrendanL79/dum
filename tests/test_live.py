"""Live registry tests — hit real Docker Hub and ghcr.io APIs.

These tests are non-destructive (read-only: token fetch, tag list, HEAD digest).
Mark with @pytest.mark.live so they can be skipped in offline/CI environments:

    pytest tests/test_live.py                  # run live tests
    pytest tests/ -m "not live"                # skip live tests
    pytest tests/                              # runs everything (live included)

Requires network access. May be slow or flaky if registries are down.
"""

import re
import pytest

from ium import DockerImageUpdater, DEFAULT_REGISTRY
from tests.conftest import REGEX_PATTERNS, get_pattern

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Shared fixture: minimal updater for calling internal methods
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def updater(tmp_path_factory):
    """Create a minimal DockerImageUpdater for registry methods.

    Module-scoped so we only create one per test run.
    Preload compiled_patterns for all our regex patterns.
    """
    tmp = tmp_path_factory.mktemp("live")
    config_file = tmp / "config.json"
    config_file.write_text('{"images": []}')
    u = DockerImageUpdater(str(config_file), str(tmp / "state.json"))
    # Preload all patterns into the cache
    for key, pattern_str in REGEX_PATTERNS.items():
        u.compiled_patterns[pattern_str] = re.compile(pattern_str)
    return u


# ---------------------------------------------------------------------------
# Token auth tests — one per registry type
# ---------------------------------------------------------------------------

class TestTokenAuth:
    """Verify token endpoints return valid tokens."""

    def test_dockerhub_token(self, updater):
        token = updater._get_docker_token(DEFAULT_REGISTRY, "linuxserver", "calibre")
        assert token is not None
        assert len(token) > 0

    def test_ghcr_token(self, updater):
        token = updater._get_docker_token("ghcr.io", "homarr-labs", "homarr")
        assert token is not None
        assert len(token) > 0


# ---------------------------------------------------------------------------
# Tag listing — one representative image per registry
# ---------------------------------------------------------------------------

class TestTagListing:
    """Verify we can fetch tag lists from real registries."""

    def test_dockerhub_tags(self, updater):
        token = updater._get_docker_token(DEFAULT_REGISTRY, "linuxserver", "calibre")
        tags = updater._get_all_tags(DEFAULT_REGISTRY, "linuxserver", "calibre", token)
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert "latest" in tags

    def test_ghcr_tags(self, updater):
        token = updater._get_docker_token("ghcr.io", "homarr-labs", "homarr")
        tags = updater._get_all_tags("ghcr.io", "homarr-labs", "homarr", token)
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert "latest" in tags


# ---------------------------------------------------------------------------
# Tag filtering — verify regex matches against real tag lists
# ---------------------------------------------------------------------------

class TestTagFiltering:
    """Fetch real tags, apply regex, verify sensible matches."""

    def _get_matching_tags(self, updater, registry, namespace, repo, pattern):
        token = updater._get_docker_token(registry, namespace, repo)
        tags = updater._get_all_tags(registry, namespace, repo, token)
        return [t for t in tags if pattern.match(t)]

    def test_dockerhub_calibre_ls_pattern(self, updater):
        pat = get_pattern("ls_v_prefix")
        matched = self._get_matching_tags(
            updater, DEFAULT_REGISTRY, "linuxserver", "calibre", pat
        )
        assert len(matched) > 0
        # All matched tags should have the -ls suffix
        assert all("-ls" in t for t in matched)

    def test_dockerhub_plex_hash_pattern(self, updater):
        pat = get_pattern("ver_git_hash")
        matched = self._get_matching_tags(
            updater, DEFAULT_REGISTRY, "plexinc", "pms-docker", pat
        )
        assert len(matched) > 0
        # All matched tags should have a hex hash suffix
        assert all(re.search(r'-[0-9a-f]+$', t) for t in matched)

    def test_ghcr_homarr_v_semver(self, updater):
        pat = get_pattern("v_semver")
        matched = self._get_matching_tags(
            updater, "ghcr.io", "homarr-labs", "homarr", pat
        )
        assert len(matched) > 0
        assert all(t.startswith("v") for t in matched)

    def test_dockerhub_pihole_semver(self, updater):
        pat = get_pattern("simple_semver")
        matched = self._get_matching_tags(
            updater, DEFAULT_REGISTRY, "pihole", "pihole", pat
        )
        assert len(matched) > 0


# ---------------------------------------------------------------------------
# Digest fetching — verify HEAD requests return valid digests
# ---------------------------------------------------------------------------

class TestDigestFetching:
    """Verify manifest digest fetching via HEAD requests."""

    def test_dockerhub_latest_digest(self, updater):
        token = updater._get_docker_token(DEFAULT_REGISTRY, "linuxserver", "calibre")
        digest = updater._get_manifest_digest_head(
            DEFAULT_REGISTRY, "linuxserver", "calibre", "latest", token
        )
        assert digest is not None
        assert digest.startswith("sha256:")

    def test_ghcr_latest_digest(self, updater):
        token = updater._get_docker_token("ghcr.io", "homarr-labs", "homarr")
        digest = updater._get_manifest_digest_head(
            "ghcr.io", "homarr-labs", "homarr", "latest", token
        )
        assert digest is not None
        assert digest.startswith("sha256:")

    def test_dockerhub_version_tag_digest(self, updater):
        """Fetch digest for a specific version tag."""
        token = updater._get_docker_token(DEFAULT_REGISTRY, "jellyfin", "jellyfin")
        digest = updater._get_manifest_digest_head(
            DEFAULT_REGISTRY, "jellyfin", "jellyfin", "10.11.4", token
        )
        assert digest is not None
        assert digest.startswith("sha256:")

    def test_latest_and_version_share_digest_when_current(self, updater):
        """If a version tag is current, its digest should match latest.

        We can't guarantee which tag is current, so we just verify the
        mechanism works — fetch both and compare. They may or may not match.
        """
        token = updater._get_docker_token(DEFAULT_REGISTRY, "crazymax", "diun")
        latest_digest = updater._get_manifest_digest_head(
            DEFAULT_REGISTRY, "crazymax", "diun", "latest", token
        )
        assert latest_digest is not None

        # Get a version tag and its digest
        tags = updater._get_all_tags(DEFAULT_REGISTRY, "crazymax", "diun", token)
        pat = get_pattern("simple_semver")
        version_tags = sorted(
            [t for t in tags if pat.match(t)], reverse=True
        )
        assert len(version_tags) > 0

        newest_digest = updater._get_manifest_digest_head(
            DEFAULT_REGISTRY, "crazymax", "diun", version_tags[0], token
        )
        assert newest_digest is not None
        assert newest_digest.startswith("sha256:")
        # Both are valid digests; they may or may not be equal


# ---------------------------------------------------------------------------
# find_matching_tag end-to-end — the full pipeline
# ---------------------------------------------------------------------------

class TestFindMatchingTag:
    """End-to-end test of find_matching_tag against real registries.

    These call the real API pipeline: parse → token → digest → tags → filter → compare.
    """

    def test_dockerhub_simple_semver(self, updater):
        """Find matching tag for a simple semver Docker Hub image."""
        pattern = REGEX_PATTERNS["simple_semver"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag("crazymax/diun", "latest", pattern)
        # Should find a matching tag (or None if latest points to a non-semver tag)
        if result is not None:
            tag, digest = result
            assert re.match(pattern, tag)
            assert digest.startswith("sha256:")

    def test_dockerhub_ls_v_prefix(self, updater):
        """Find matching tag for a LinuxServer image with v-prefix."""
        pattern = REGEX_PATTERNS["ls_v_prefix"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag("linuxserver/calibre", "latest", pattern)
        if result is not None:
            tag, digest = result
            assert re.match(pattern, tag)
            assert "-ls" in tag

    def test_ghcr_v_semver(self, updater):
        """Find matching tag for a ghcr.io image."""
        pattern = REGEX_PATTERNS["v_semver"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag(
            "ghcr.io/homarr-labs/homarr", "latest", pattern
        )
        if result is not None:
            tag, digest = result
            assert tag.startswith("v")
            assert digest.startswith("sha256:")

    def test_dockerhub_plex_git_hash(self, updater):
        """Find matching tag for Plex (version + git hash pattern)."""
        pattern = REGEX_PATTERNS["ver_git_hash"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag("plexinc/pms-docker", "latest", pattern)
        if result is not None:
            tag, digest = result
            assert re.match(pattern, tag)

    def test_dockerhub_ls_4part(self, updater):
        """Find matching tag for a 4-part LS version."""
        pattern = REGEX_PATTERNS["ls_4part"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag("linuxserver/sonarr", "latest", pattern)
        if result is not None:
            tag, digest = result
            assert re.match(pattern, tag)

    def test_dockerhub_ls_r_suffix(self, updater):
        """Find matching tag for qbittorrent (-r suffix)."""
        pattern = REGEX_PATTERNS["ls_r_suffix"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag("linuxserver/qbittorrent", "latest", pattern)
        if result is not None:
            tag, digest = result
            assert "-r" in tag
            assert "-ls" in tag

    def test_nonexistent_image_returns_none(self, updater):
        """Bogus image should return None, not raise."""
        pattern = REGEX_PATTERNS["simple_semver"]
        updater.compiled_patterns[pattern] = re.compile(pattern)
        result = updater.find_matching_tag(
            "this-namespace-does-not-exist/fake-image", "latest", pattern
        )
        assert result is None
