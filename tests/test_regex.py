"""Tests for regex pattern matching against real inventory tag lists."""

import re
import pytest
from tests.conftest import (
    ALL_TAG_LISTS, REGEX_PATTERNS, IMAGE_REGEX_MAP,
    get_pattern, filter_tags,
)


# ---------------------------------------------------------------------------
# Parametrized: every image × its regex → correct matches, no false positives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("image,pat_key", IMAGE_REGEX_MAP.items())
class TestRegexMatchesInventory:
    """Each image's regex should match its version tags and reject noise."""

    def test_matches_at_least_one_tag(self, image, pat_key):
        tags = ALL_TAG_LISTS[image]
        matched = filter_tags(tags, get_pattern(pat_key))
        assert matched, f"Pattern {pat_key!r} matched nothing in {tags}"

    def test_rejects_latest(self, image, pat_key):
        pattern = get_pattern(pat_key)
        assert not pattern.match("latest")

    def test_rejects_nightly_develop(self, image, pat_key):
        pattern = get_pattern(pat_key)
        for noise in ("nightly", "develop", "development", "edge", "unstable",
                       "testing", "master", "beta", "next"):
            assert not pattern.match(noise), f"Pattern {pat_key!r} should reject {noise!r}"


# ---------------------------------------------------------------------------
# Specific pattern tests: exact expected matches per image
# ---------------------------------------------------------------------------

class TestSimpleSemver:
    """Pattern: ^[0-9]+\\.[0-9]+\\.[0-9]+$"""
    pat = get_pattern("simple_semver")

    def test_budibase(self):
        matched = filter_tags(ALL_TAG_LISTS["budibase/budibase"], self.pat)
        assert set(matched) == {"3.20.12", "3.2.29", "3.19.0", "3.2.0", "2.32.13"}

    def test_pihole_date_based(self):
        """Date-based versions (YYYY.MM.patch) match simple semver regex."""
        matched = filter_tags(ALL_TAG_LISTS["pihole/pihole"], self.pat)
        assert "2025.11.1" in matched
        assert "2025.08.0" in matched

    def test_jellyfin_rejects_arch_suffix(self):
        """Tags like 10.11.4-amd64 should NOT match."""
        matched = filter_tags(ALL_TAG_LISTS["jellyfin/jellyfin"], self.pat)
        assert all("-amd64" not in t for t in matched)

    def test_n8n_rejects_prerelease(self):
        """2.0.3-beta should NOT match."""
        matched = filter_tags(ALL_TAG_LISTS["n8nio/n8n"], self.pat)
        assert "2.0.3-beta" not in matched
        assert "2.0.3" in matched

    def test_portainer_rejects_platform_tags(self):
        matched = filter_tags(ALL_TAG_LISTS["portainer/portainer-ce"], self.pat)
        assert "linux-amd64" not in matched
        assert "alpine" not in matched


class TestVSemver:
    """Pattern: ^v[0-9]+\\.[0-9]+\\.[0-9]+$"""
    pat = get_pattern("v_semver")

    def test_homarr(self):
        matched = filter_tags(ALL_TAG_LISTS["ghcr.io/homarr-labs/homarr"], self.pat)
        assert set(matched) == {"v1.46.0", "v1.41.0", "v1.40.0"}

    def test_mealie(self):
        matched = filter_tags(ALL_TAG_LISTS["ghcr.io/mealie-recipes/mealie"], self.pat)
        assert set(matched) == {"v2.5.0", "v2.4.0", "v2.3.0"}

    def test_rejects_sha_tags(self):
        assert not self.pat.match("sha-abc1234")

    def test_rejects_no_prefix(self):
        """Without v-prefix, should not match."""
        assert not self.pat.match("1.46.0")


class TestLinuxServerVPrefix:
    """Pattern: ^v[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$"""
    pat = get_pattern("ls_v_prefix")

    def test_calibre(self):
        matched = filter_tags(ALL_TAG_LISTS["linuxserver/calibre"], self.pat)
        assert set(matched) == {"v8.16.2-ls374", "v8.12.0-ls359", "v8.10.0-ls350"}

    def test_rejects_version_prefix(self):
        """Tags like version-v8.16.2 should not match."""
        assert not self.pat.match("version-v8.16.2")

    def test_rejects_no_ls(self):
        assert not self.pat.match("v1.5.3")


class TestLinuxServerNoPrefix:
    """Pattern: ^[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$"""
    pat = get_pattern("ls_no_prefix")

    def test_calibre_web(self):
        matched = filter_tags(ALL_TAG_LISTS["linuxserver/calibre-web"], self.pat)
        assert set(matched) == {"0.6.25-ls348", "0.6.25-ls345", "0.6.24-ls340"}

    def test_sabnzbd(self):
        matched = filter_tags(ALL_TAG_LISTS["linuxserver/sabnzbd"], self.pat)
        assert set(matched) == {"4.5.3-ls229", "4.5.1-ls217", "4.4.0-ls200"}

    def test_rejects_v_prefix(self):
        assert not self.pat.match("v1.5.3-ls321")


class TestLinuxServer4Part:
    """Pattern: ^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+-ls[0-9]+$"""
    pat = get_pattern("ls_4part")

    def test_prowlarr(self):
        matched = filter_tags(ALL_TAG_LISTS["linuxserver/prowlarr"], self.pat)
        assert set(matched) == {"2.3.0.5236-ls134", "2.0.5.5160-ls128", "1.37.0.5076-ls123"}

    def test_radarr(self):
        matched = filter_tags(ALL_TAG_LISTS["linuxserver/radarr"], self.pat)
        assert set(matched) == {"6.0.4.10291-ls289", "5.27.5.10198-ls284"}

    def test_rejects_3part(self):
        assert not self.pat.match("4.5.3-ls229")


class TestLinuxServerRSuffix:
    """Pattern: ^[0-9]+\\.[0-9]+\\.[0-9]+-r[0-9]+-ls[0-9]+$"""
    pat = get_pattern("ls_r_suffix")

    def test_qbittorrent(self):
        matched = filter_tags(ALL_TAG_LISTS["linuxserver/qbittorrent"], self.pat)
        assert set(matched) == {"5.1.2-r1-ls411", "5.1.0-r0-ls393", "5.0.0-r0-ls380"}

    def test_rejects_no_r(self):
        assert not self.pat.match("5.1.2-ls411")


class TestVersionGitHash:
    """Pattern: ^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+-[0-9a-f]+$"""
    pat = get_pattern("ver_git_hash")

    def test_plex(self):
        matched = filter_tags(ALL_TAG_LISTS["plexinc/pms-docker"], self.pat)
        assert "1.42.2.10156-f737b826c" in matched
        assert "1.42.1.10060-4e8b05daf" in matched

    def test_rejects_plexpass(self):
        assert not self.pat.match("plexpass")

    def test_rejects_no_hash(self):
        assert not self.pat.match("1.42.2.10156")


# ---------------------------------------------------------------------------
# Cross-pattern isolation: patterns should not overlap on inventory tags
# ---------------------------------------------------------------------------

class TestPatternIsolation:
    """Verify patterns don't accidentally match tags from other categories."""

    def test_ls_v_prefix_rejects_ls_no_prefix_tags(self):
        pat = get_pattern("ls_v_prefix")
        for tag in ["0.6.25-ls348", "4.5.3-ls229"]:
            assert not pat.match(tag)

    def test_ls_no_prefix_rejects_ls_v_prefix_tags(self):
        pat = get_pattern("ls_no_prefix")
        for tag in ["v8.16.2-ls374", "v1.5.3-ls328"]:
            assert not pat.match(tag)

    def test_ls_4part_rejects_3part_tags(self):
        pat = get_pattern("ls_4part")
        for tag in ["v8.16.2-ls374", "4.5.3-ls229"]:
            assert not pat.match(tag)

    def test_simple_semver_rejects_ls_tags(self):
        pat = get_pattern("simple_semver")
        for tag in ["v8.16.2-ls374", "4.5.3-ls229", "2.3.0.5236-ls134"]:
            assert not pat.match(tag)

    def test_ver_git_hash_rejects_ls_4part(self):
        """4-part-ls vs 4-part-hash should not overlap."""
        pat_hash = get_pattern("ver_git_hash")
        pat_ls = get_pattern("ls_4part")
        # ls tag should not match hash pattern
        assert not pat_hash.match("2.3.0.5236-ls134")
        # hash tag should not match ls pattern
        assert not pat_ls.match("1.42.2.10156-f737b826c")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestRegexEdgeCases:
    def test_invalid_regex_raises(self):
        with pytest.raises(re.error):
            re.compile("[invalid")

    def test_empty_tag_list(self):
        pat = get_pattern("simple_semver")
        assert filter_tags([], pat) == []

    def test_match_uses_match_not_search(self):
        """Verify pattern.match anchors at start (ium.py uses match, not search)."""
        pat = get_pattern("simple_semver")
        # "prefix-1.2.3" should not match because match() anchors at start
        assert not pat.match("prefix-1.2.3")
        # But without $ anchor, match() would match "1.2.3-suffix"
        # Our patterns have $, so this should fail too
        assert not pat.match("1.2.3-suffix")
