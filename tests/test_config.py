"""Tests for configuration schema validation."""

import copy
import pytest
import jsonschema

from ium import CONFIG_SCHEMA


class TestConfigSchemaValid:
    """Valid configurations that should pass validation."""

    def test_minimal(self, minimal_config):
        jsonschema.validate(minimal_config, CONFIG_SCHEMA)

    def test_full(self, full_config):
        jsonschema.validate(full_config, CONFIG_SCHEMA)

    def test_all_optional_fields(self):
        config = {
            "images": [{
                "image": "linuxserver/calibre",
                "regex": r"^v[0-9]+$",
                "base_tag": "stable",
                "auto_update": True,
                "container_name": "calibre",
                "registry": "ghcr.io",
                "cleanup_old_images": True,
                "keep_versions": 5,
            }]
        }
        jsonschema.validate(config, CONFIG_SCHEMA)

    def test_multiple_images(self, multi_image_config):
        jsonschema.validate(multi_image_config, CONFIG_SCHEMA)

    def test_empty_images_array(self):
        """Empty images array is valid per schema (no minItems)."""
        jsonschema.validate({"images": []}, CONFIG_SCHEMA)

    def test_booleans_explicitly_false(self):
        """auto_update and cleanup_old_images set to false explicitly."""
        config = {
            "images": [{
                "image": "test/image",
                "regex": "^v.*$",
                "auto_update": False,
                "cleanup_old_images": False,
            }]
        }
        jsonschema.validate(config, CONFIG_SCHEMA)

    def test_keep_versions_minimum(self):
        """keep_versions=1 is the minimum valid value."""
        config = {
            "images": [{
                "image": "test/image",
                "regex": "^v.*$",
                "keep_versions": 1,
            }]
        }
        jsonschema.validate(config, CONFIG_SCHEMA)


class TestConfigSchemaInvalid:
    """Invalid configurations that should fail validation."""

    def test_missing_images_key(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({}, CONFIG_SCHEMA)

    def test_images_not_array(self):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"images": "not-an-array"}, CONFIG_SCHEMA)

    def test_missing_image_field(self):
        config = {"images": [{"regex": "^v.*$"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)

    def test_missing_regex_field(self):
        config = {"images": [{"image": "test/image"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)

    def test_image_wrong_type(self):
        config = {"images": [{"image": 123, "regex": "^v.*$"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)

    def test_auto_update_wrong_type(self):
        config = {"images": [{"image": "x", "regex": "^v$", "auto_update": "yes"}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)

    def test_keep_versions_zero(self):
        """keep_versions has minimum: 1."""
        config = {"images": [{"image": "x", "regex": "^v$", "keep_versions": 0}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)

    def test_keep_versions_negative(self):
        config = {"images": [{"image": "x", "regex": "^v$", "keep_versions": -1}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)

    def test_keep_versions_float(self):
        config = {"images": [{"image": "x", "regex": "^v$", "keep_versions": 2.5}]}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(config, CONFIG_SCHEMA)
