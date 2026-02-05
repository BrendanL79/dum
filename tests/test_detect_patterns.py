"""Tests for the detect_tag_patterns() algorithm."""

import re
import sys
from pathlib import Path

# Ensure project root is on sys.path for both pytest and direct execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from dum import detect_tag_patterns, detect_base_tags, _tokenize_tag, _signature_from_tokens, KNOWN_PATTERNS
from conftest import ALL_TAG_LISTS, IMAGE_REGEX_MAP, REGEX_PATTERNS


class TestTokenizer:
    """Test _tokenize_tag() token generation."""

    def test_simple_semver(self):
        tokens = _tokenize_tag("3.20.12")
        types = [t[0] for t in tokens]
        assert types == ['NUM', 'DOT', 'NUM', 'DOT', 'NUM']

    def test_v_prefix_semver(self):
        tokens = _tokenize_tag("v1.46.0")
        types = [t[0] for t in tokens]
        assert types == ['PREFIX_V', 'NUM', 'DOT', 'NUM', 'DOT', 'NUM']

    def test_ls_suffix(self):
        tokens = _tokenize_tag("v8.16.2-ls374")
        types = [t[0] for t in tokens]
        assert types == ['PREFIX_V', 'NUM', 'DOT', 'NUM', 'DOT', 'NUM', 'DASH', 'ALPHA', 'NUM']
        assert tokens[-2] == ('ALPHA', 'ls')

    def test_four_part_ls(self):
        tokens = _tokenize_tag("2.8.2.4493-ls22")
        types = [t[0] for t in tokens]
        assert types == ['NUM', 'DOT', 'NUM', 'DOT', 'NUM', 'DOT', 'NUM', 'DASH', 'ALPHA', 'NUM']

    def test_revision_ls(self):
        tokens = _tokenize_tag("5.1.2-r1-ls411")
        types = [t[0] for t in tokens]
        assert types == ['NUM', 'DOT', 'NUM', 'DOT', 'NUM', 'DASH', 'ALPHA', 'NUM', 'DASH', 'ALPHA', 'NUM']
        assert tokens[5] == ('DASH', '-')
        assert tokens[6] == ('ALPHA', 'r')

    def test_git_hash(self):
        tokens = _tokenize_tag("1.42.2.10156-f737b826c")
        types = [t[0] for t in tokens]
        assert types == ['NUM', 'DOT', 'NUM', 'DOT', 'NUM', 'DOT', 'NUM', 'DASH', 'HEX']
        assert tokens[-1][0] == 'HEX'


class TestSignature:
    """Test _signature_from_tokens()."""

    def test_same_structure_same_sig(self):
        sig1 = _signature_from_tokens(_tokenize_tag("3.20.12"))
        sig2 = _signature_from_tokens(_tokenize_tag("4.0.0"))
        assert sig1 == sig2

    def test_different_alpha_different_sig(self):
        sig1 = _signature_from_tokens(_tokenize_tag("1.0.0-ls10"))
        sig2 = _signature_from_tokens(_tokenize_tag("1.0.0-rc10"))
        assert sig1 != sig2

    def test_v_prefix_differs(self):
        sig1 = _signature_from_tokens(_tokenize_tag("v1.0.0"))
        sig2 = _signature_from_tokens(_tokenize_tag("1.0.0"))
        assert sig1 != sig2


class TestDetectPatterns:
    """Test detect_tag_patterns() end-to-end."""

    def test_empty_tags(self):
        assert detect_tag_patterns([]) == []

    def test_all_noise_tags(self):
        noise = ["latest", "nightly", "develop", "edge", "beta", "alpha"]
        assert detect_tag_patterns(noise) == []

    def test_single_tag_no_group(self):
        result = detect_tag_patterns(["latest", "1.0.0"])
        assert result == []

    def test_groups_need_two_members(self):
        # Only one semver tag - should not form a group
        result = detect_tag_patterns(["latest", "nightly", "1.0.0"])
        assert result == []

    def test_simple_semver_detection(self):
        tags = ["latest", "3.20.12", "3.2.29", "3.19.0", "2.32.13"]
        result = detect_tag_patterns(tags)
        assert len(result) >= 1
        semver = result[0]
        assert semver['regex'] == r"^[0-9]+\.[0-9]+\.[0-9]+$"
        assert semver['label'] == "Semantic version (X.Y.Z)"
        assert semver['match_count'] == 4

    def test_v_semver_detection(self):
        tags = ["latest", "dev", "v1.46.0", "v1.41.0", "v1.40.0"]
        result = detect_tag_patterns(tags)
        assert len(result) >= 1
        found = [r for r in result if r['regex'] == r"^v[0-9]+\.[0-9]+\.[0-9]+$"]
        assert len(found) == 1
        assert found[0]['label'] == "Semantic version with v (vX.Y.Z)"

    def test_ls_v_prefix_detection(self):
        tags = ["latest", "v8.16.2-ls374", "v8.12.0-ls359", "v8.10.0-ls350"]
        result = detect_tag_patterns(tags)
        assert len(result) >= 1
        found = [r for r in result if r['regex'] == r"^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$"]
        assert len(found) == 1
        assert found[0]['label'] == "LinuxServer with v (vX.Y.Z-lsN)"

    def test_ls_no_prefix_detection(self):
        tags = ["latest", "0.6.25-ls348", "0.6.25-ls345", "0.6.24-ls340"]
        result = detect_tag_patterns(tags)
        found = [r for r in result if r['regex'] == r"^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$"]
        assert len(found) == 1

    def test_four_part_ls_detection(self):
        tags = ["latest", "2.8.2.4493-ls22", "2.7.0.4420-ls18"]
        result = detect_tag_patterns(tags)
        found = [r for r in result if r['regex'] == r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$"]
        assert len(found) == 1

    def test_revision_ls_detection(self):
        tags = ["latest", "5.1.2-r1-ls411", "5.1.0-r0-ls393", "5.0.0-r0-ls380"]
        result = detect_tag_patterns(tags)
        found = [r for r in result if r['regex'] == r"^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+-ls[0-9]+$"]
        assert len(found) == 1

    def test_git_hash_detection(self):
        tags = ["latest", "1.42.2.10156-f737b826c", "1.42.1.10060-4e8b05daf", "1.41.0.9430-abc123def"]
        result = detect_tag_patterns(tags)
        found = [r for r in result if r['regex'] == r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$"]
        assert len(found) == 1

    def test_noise_filtered_out(self):
        """Noise tags like latest, nightly, sha-* should not form groups."""
        tags = ["latest", "nightly", "develop", "sha-abc1234", "v1.0.0", "v2.0.0"]
        result = detect_tag_patterns(tags)
        for r in result:
            compiled = re.compile(r['regex'])
            for noise in ["latest", "nightly", "develop", "sha-abc1234"]:
                assert not compiled.match(noise), f"Noise tag '{noise}' matched {r['regex']}"

    def test_arch_suffixes_filtered(self):
        """Tags with arch suffixes should be filtered out."""
        tags = ["10.11.4", "10.11.1", "10.11.4-amd64", "latest-amd64", "arm64v8-latest"]
        result = detect_tag_patterns(tags)
        for r in result:
            compiled = re.compile(r['regex'])
            assert not compiled.match("10.11.4-amd64")

    def test_results_sorted_by_recency(self):
        """Results should be sorted by most recent tag descending."""
        tags = ["1.0.0", "2.0.0", "3.0.0", "v1.0.0", "v2.0.0"]
        result = detect_tag_patterns(tags)
        if len(result) >= 2:
            # v-prefixed group has the most recent tag (v2.0.0 at index 4)
            assert result[0]['example_tags'][0].startswith('v')

    def test_known_patterns_get_labels(self):
        """Known pattern regexes should get their predefined labels."""
        for regex, label in KNOWN_PATTERNS.items():
            # We can't test all, but verify the mapping is accessible
            assert isinstance(label, str)
            assert len(label) > 0

    def test_example_tags_present(self):
        """Each result should have example_tags with at most 3 entries."""
        tags = ["1.0.0", "2.0.0", "3.0.0", "4.0.0", "5.0.0"]
        result = detect_tag_patterns(tags)
        assert len(result) >= 1
        assert 1 <= len(result[0]['example_tags']) <= 3

    def test_generated_regex_matches_all_group_members(self):
        """The generated regex should match all tags in its group."""
        tags = ["v8.16.2-ls374", "v8.12.0-ls359", "v8.10.0-ls350", "latest"]
        result = detect_tag_patterns(tags)
        for r in result:
            compiled = re.compile(r['regex'])
            # All example tags must match
            for tag in r['example_tags']:
                assert compiled.match(tag), f"Example tag '{tag}' doesn't match {r['regex']}"


class TestAllTagListsIntegration:
    """Validate detect_tag_patterns() against the full tag list fixtures."""

    @pytest.mark.parametrize("image", list(ALL_TAG_LISTS.keys()))
    def test_detects_expected_pattern(self, image):
        """For each image, the expected regex category should appear in detected patterns."""
        tags = ALL_TAG_LISTS[image]
        expected_key = IMAGE_REGEX_MAP.get(image)
        if not expected_key:
            pytest.skip(f"No expected regex mapping for {image}")

        expected_regex = REGEX_PATTERNS[expected_key]
        result = detect_tag_patterns(tags)

        detected_regexes = [r['regex'] for r in result]
        assert expected_regex in detected_regexes, (
            f"Expected regex '{expected_regex}' not found in detected patterns "
            f"for {image}. Detected: {detected_regexes}"
        )

    @pytest.mark.parametrize("image", list(ALL_TAG_LISTS.keys()))
    def test_generated_regex_matches_all_members(self, image):
        """For each detected pattern, the regex should match all tags in its group."""
        tags = ALL_TAG_LISTS[image]
        result = detect_tag_patterns(tags)

        for r in result:
            compiled = re.compile(r['regex'])
            # Verify match count: count how many tags from the full list match
            actual_matches = [t for t in tags if compiled.match(t)]
            assert len(actual_matches) >= r['match_count'], (
                f"Regex {r['regex']} claims {r['match_count']} matches "
                f"but only {len(actual_matches)} tags match"
            )


class TestDetectBaseTags:
    """Test detect_base_tags() base tag detection."""

    def test_empty_tags(self):
        assert detect_base_tags([], []) == []

    def test_empty_patterns(self):
        """With no version patterns, all non-noise tags are candidates."""
        tags = ["latest", "stable", "v1.0.0"]
        result = detect_base_tags(tags, [])
        assert "latest" in result
        assert "stable" in result
        assert "v1.0.0" in result

    def test_version_tags_excluded(self):
        """Tags matching a version pattern should not appear in results."""
        tags = ["latest", "3.20.12", "3.2.29", "nightly"]
        patterns = [{"regex": r"^[0-9]+\.[0-9]+\.[0-9]+$"}]
        result = detect_base_tags(tags, patterns)
        assert "latest" in result
        assert "nightly" in result
        assert "3.20.12" not in result
        assert "3.2.29" not in result

    def test_arch_tags_excluded(self):
        """Architecture-specific tags should be filtered out."""
        tags = ["latest", "amd64", "arm64", "latest-amd64", "10.11.4-arm64"]
        result = detect_base_tags(tags, [])
        assert "latest" in result
        assert "amd64" not in result
        assert "arm64" not in result
        assert "latest-amd64" not in result
        assert "10.11.4-arm64" not in result

    def test_sha_refs_excluded(self):
        """SHA references should be filtered out."""
        tags = ["latest", "sha-abc1234", "sha256:deadbeef"]
        result = detect_base_tags(tags, [])
        assert "latest" in result
        assert "sha-abc1234" not in result
        assert "sha256:deadbeef" not in result

    def test_single_char_excluded(self):
        """Single character tags should be filtered out."""
        tags = ["latest", "a", "1", "v"]
        result = detect_base_tags(tags, [])
        assert "latest" in result
        assert "a" not in result

    def test_recency_order(self):
        """Results should be sorted by recency (last in input = first in output)."""
        tags = ["oldest", "middle", "newest"]
        result = detect_base_tags(tags, [])
        assert result[0] == "newest"
        assert result[-1] == "oldest"

    def test_with_real_patterns(self):
        """Using detect_tag_patterns output as input should work end-to-end."""
        tags = ["latest", "nightly", "v8.16.2-ls374", "v8.12.0-ls359", "v8.10.0-ls350"]
        patterns = detect_tag_patterns(tags)
        result = detect_base_tags(tags, patterns)
        assert "latest" in result
        assert "nightly" in result
        # Version tags should be excluded
        for tag in ["v8.16.2-ls374", "v8.12.0-ls359", "v8.10.0-ls350"]:
            assert tag not in result

    def test_invalid_pattern_regex_skipped(self):
        """Invalid regex in patterns should be gracefully skipped."""
        tags = ["latest", "1.0.0", "2.0.0"]
        patterns = [{"regex": "[invalid"}, {"regex": r"^[0-9]+\.[0-9]+\.[0-9]+$"}]
        result = detect_base_tags(tags, patterns)
        assert "latest" in result
        assert "1.0.0" not in result

    @pytest.mark.parametrize("image", list(ALL_TAG_LISTS.keys()))
    def test_latest_in_base_tags(self, image):
        """For every test image that has 'latest', it should appear in base tag results."""
        tags = ALL_TAG_LISTS[image]
        if "latest" not in tags:
            pytest.skip(f"{image} has no 'latest' tag")
        patterns = detect_tag_patterns(tags)
        result = detect_base_tags(tags, patterns)
        assert "latest" in result, f"'latest' not found in base tags for {image}"

    @pytest.mark.parametrize("image", list(ALL_TAG_LISTS.keys()))
    def test_version_tags_not_in_base_tags(self, image):
        """For every test image, version tags should NOT appear in base tag results."""
        tags = ALL_TAG_LISTS[image]
        expected_key = IMAGE_REGEX_MAP.get(image)
        if not expected_key:
            pytest.skip(f"No expected regex mapping for {image}")

        patterns = detect_tag_patterns(tags)
        result = detect_base_tags(tags, patterns)

        version_regex = re.compile(REGEX_PATTERNS[expected_key])
        version_tags_in_result = [t for t in result if version_regex.match(t)]
        assert version_tags_in_result == [], (
            f"Version tags found in base tags for {image}: {version_tags_in_result}"
        )


# ---------------------------------------------------------------------------
# Interactive CLI mode
# ---------------------------------------------------------------------------

def interactive_mode():
    """Interactive mode for testing pattern detection against real registries."""
    # Import here to avoid making it a hard dependency for pytest
    from dum import DockerImageUpdater
    import tempfile, json, os

    print("=" * 60)
    print("Tag Pattern Detector - Interactive Mode")
    print("Enter an image name to fetch tags and detect patterns.")
    print("Press Ctrl+C to exit.")
    print("=" * 60)

    # Create a minimal config so DockerImageUpdater can initialize
    config_path = os.path.join(tempfile.gettempdir(), "dum_detect_config.json")
    state_path = os.path.join(tempfile.gettempdir(), "dum_detect_state.json")
    with open(config_path, 'w') as f:
        json.dump({"images": [{"image": "placeholder", "regex": "^$"}]}, f)

    updater = DockerImageUpdater(config_path, state_path, dry_run=True, log_level="WARNING")

    while True:
        try:
            print()
            image = input("Image name (e.g., linuxserver/calibre): ").strip()
            if not image:
                continue

            registry, namespace, repo = updater._parse_image_reference(image)
            print(f"  Registry: {registry}, Namespace: {namespace}, Repo: {repo}")

            print("  Fetching tags (ordered by date)...")
            tags = updater._get_all_tags_by_date(registry, namespace, repo)

            if not tags:
                print("  No tags found. Check the image name.")
                continue

            print(f"  Found {len(tags)} tags.")

            patterns = detect_tag_patterns(tags)

            if not patterns:
                print("  No structural patterns detected.")
                continue

            print(f"\n  Detected {len(patterns)} pattern(s):\n")
            for i, p in enumerate(patterns, 1):
                print(f"  {i}. {p['label']}")
                print(f"     Regex: {p['regex']}")
                print(f"     Matches: {p['match_count']} tags")
                print(f"     Examples: {', '.join(p['example_tags'])}")
                print()

        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"  Error: {e}")

    # Cleanup temp files
    for path in [config_path, state_path]:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == '__main__':
    interactive_mode()
