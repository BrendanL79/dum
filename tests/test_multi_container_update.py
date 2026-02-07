"""Integration tests for multi-container update scenarios."""

import json
import pytest
from unittest.mock import Mock, patch, call
from dum import DockerImageUpdater


@pytest.fixture
def updater(tmp_path):
    """Create a DockerImageUpdater instance with test paths."""
    config_file = tmp_path / "config.json"
    state_file = tmp_path / "state.json"

    config = {
        "images": [{
            "image": "linuxserver/sonarr",
            "regex": r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
            "base_tag": "latest",
            "auto_update": True,
        }]
    }

    config_file.write_text(json.dumps(config))
    state_file.write_text("{}")

    return DockerImageUpdater(str(config_file), str(state_file))


class TestMultiContainerUpdate:
    """Test updating multiple containers with the same image."""

    def test_two_containers_both_updated(self, updater):
        """Test that both containers get updated when update is available."""
        # Mock container discovery
        containers = [
            {'name': 'sonarr-hd', 'id': 'abc123', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
            {'name': 'sonarr-4k', 'id': 'def456', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
        ]

        with patch.object(updater, '_get_containers_for_image', return_value=containers), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_get_container_current_tag', return_value='4.0.0.740-ls290'), \
             patch.object(updater, '_pull_image', return_value=True), \
             patch.object(updater, '_update_containers', return_value={'sonarr-hd': True, 'sonarr-4k': True}) as mock_update:

            updates = updater.check_and_update()

            # Verify update was called with both container names
            mock_update.assert_called_once_with(
                ['sonarr-hd', 'sonarr-4k'],
                'linuxserver/sonarr',
                '4.0.16.2944-ls299'
            )

            # Verify update was detected
            assert len(updates) == 1
            assert updates[0]['old_tag'] == '4.0.0.740-ls290'
            assert updates[0]['new_tag'] == '4.0.16.2944-ls299'

    def test_partial_update_success_updates_state(self, updater):
        """Test that state is updated if any container succeeds."""
        containers = [
            {'name': 'sonarr-hd', 'id': 'abc123', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
            {'name': 'sonarr-4k', 'id': 'def456', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
        ]

        with patch.object(updater, '_get_containers_for_image', return_value=containers), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_get_container_current_tag', return_value='4.0.0.740-ls290'), \
             patch.object(updater, '_pull_image', return_value=True), \
             patch.object(updater, '_update_containers', return_value={'sonarr-hd': True, 'sonarr-4k': False}):

            updater.check_and_update()

            # State should be updated because at least one container succeeded
            assert 'linuxserver/sonarr' in updater.state
            assert updater.state['linuxserver/sonarr'].tag == '4.0.16.2944-ls299'

    def test_no_containers_image_only_update(self, updater):
        """Test updating image when no containers exist."""
        with patch.object(updater, '_get_containers_for_image', return_value=[]), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_pull_image', return_value=True), \
             patch.object(updater, '_update_containers') as mock_update:

            updates = updater.check_and_update()

            # Should not call _update_containers when no containers found
            mock_update.assert_not_called()

            # State should still be updated
            assert 'linuxserver/sonarr' in updater.state
            assert updater.state['linuxserver/sonarr'].tag == '4.0.16.2944-ls299'

    def test_version_detection_from_first_container(self, updater):
        """Test that version is detected from first container when no saved state."""
        containers = [
            {'name': 'sonarr-hd', 'id': 'abc123', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
            {'name': 'sonarr-4k', 'id': 'def456', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
        ]

        with patch.object(updater, '_get_containers_for_image', return_value=containers), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_get_container_current_tag', return_value='4.0.0.740-ls290') as mock_get_tag, \
             patch.object(updater, '_pull_image', return_value=True), \
             patch.object(updater, '_update_containers', return_value={'sonarr-hd': True, 'sonarr-4k': True}):

            updates = updater.check_and_update()

            # Should query first container for current version
            mock_get_tag.assert_called_once_with('sonarr-hd', 'linuxserver/sonarr', updater.config['images'][0]['regex'])

            # Update should use detected version as old_tag
            assert updates[0]['old_tag'] == '4.0.0.740-ls290'


class TestNoAutoUpdate:
    """Test behavior when auto_update is false."""

    def test_containers_not_updated_when_auto_update_false(self, updater):
        """Test that containers aren't updated when auto_update is false."""
        # Modify config to disable auto_update
        updater.config['images'][0]['auto_update'] = False

        containers = [
            {'name': 'sonarr', 'id': 'abc123', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
        ]

        with patch.object(updater, '_get_containers_for_image', return_value=containers), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_get_container_current_tag', return_value='4.0.0.740-ls290'), \
             patch.object(updater, '_pull_image') as mock_pull, \
             patch.object(updater, '_update_containers') as mock_update:

            updates = updater.check_and_update()

            # Should not pull or update
            mock_pull.assert_not_called()
            mock_update.assert_not_called()

            # But state should still be updated to prevent re-reporting
            assert 'linuxserver/sonarr' in updater.state
            assert updates[0]['auto_update'] is False


class TestImageCleanup:
    """Test image cleanup after updates."""

    def test_cleanup_after_successful_update(self, updater):
        """Test that old images are cleaned up after successful update."""
        updater.config['images'][0]['cleanup_old_images'] = True
        updater.config['images'][0]['keep_versions'] = 3

        containers = [
            {'name': 'sonarr', 'id': 'abc123', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
        ]

        with patch.object(updater, '_get_containers_for_image', return_value=containers), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_get_container_current_tag', return_value='4.0.0.740-ls290'), \
             patch.object(updater, '_pull_image', return_value=True), \
             patch.object(updater, '_update_containers', return_value={'sonarr': True}), \
             patch.object(updater, '_cleanup_old_images') as mock_cleanup:

            updater.check_and_update()

            # Should call cleanup after successful update
            mock_cleanup.assert_called_once_with('linuxserver/sonarr', 3)

    def test_no_cleanup_after_failed_update(self, updater):
        """Test that cleanup doesn't happen if update fails."""
        updater.config['images'][0]['cleanup_old_images'] = True

        containers = [
            {'name': 'sonarr', 'id': 'abc123', 'state': 'running', 'image_ref': 'linuxserver/sonarr:4.0.0.740'},
        ]

        with patch.object(updater, '_get_containers_for_image', return_value=containers), \
             patch.object(updater, 'find_matching_tag', return_value=('4.0.16.2944-ls299', 'sha256:newdigest')), \
             patch.object(updater, '_get_container_current_tag', return_value='4.0.0.740-ls290'), \
             patch.object(updater, '_pull_image', return_value=True), \
             patch.object(updater, '_update_containers', return_value={'sonarr': False}), \
             patch.object(updater, '_cleanup_old_images') as mock_cleanup:

            updater.check_and_update()

            # Should NOT call cleanup after failed update
            mock_cleanup.assert_not_called()
