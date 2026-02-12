"""Tests for container discovery functionality."""

import json
import pytest
from unittest.mock import Mock, patch
from ium import DockerImageUpdater


@pytest.fixture
def updater(tmp_path):
    """Create a DockerImageUpdater instance with test paths."""
    config_file = tmp_path / "config.json"
    state_file = tmp_path / "state.json"

    config = {
        "images": [{
            "image": "linuxserver/sonarr",
            "regex": r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$",
        }]
    }

    config_file.write_text(json.dumps(config))
    state_file.write_text("{}")

    return DockerImageUpdater(str(config_file), str(state_file))


class TestImageMatches:
    """Test the _image_matches helper method."""

    def test_exact_match(self, updater):
        """Test exact image name match."""
        assert updater._image_matches("nginx", "nginx")

    def test_tag_ignored(self, updater):
        """Test that tags are ignored in matching."""
        assert updater._image_matches("nginx", "nginx:alpine")
        assert updater._image_matches("nginx", "nginx:1.21")

    def test_registry_prefix_stripped(self, updater):
        """Test registry prefix handling."""
        assert updater._image_matches("linuxserver/sonarr", "lscr.io/linuxserver/sonarr:latest")
        assert updater._image_matches("linuxserver/sonarr", "ghcr.io/linuxserver/sonarr:4.0.0")

    def test_library_namespace(self, updater):
        """Test implicit library namespace."""
        assert updater._image_matches("postgres", "library/postgres:15")
        assert updater._image_matches("library/postgres", "postgres:15")

    def test_no_match_different_images(self, updater):
        """Test that different images don't match."""
        assert not updater._image_matches("nginx", "apache")
        assert not updater._image_matches("linuxserver/sonarr", "linuxserver/radarr")

    def test_portainer_standard(self, updater):
        """Test standard Portainer CE deployment."""
        assert updater._image_matches("portainer/portainer-ce", "portainer/portainer-ce:latest")
        assert updater._image_matches("portainer/portainer-ce", "portainer/portainer-ce:2.21.0")
        assert updater._image_matches("portainer/portainer-ce", "portainer/portainer-ce:2.21.0-alpine")

    def test_portainer_with_registry(self, updater):
        """Test Portainer from custom registries."""
        assert updater._image_matches("portainer/portainer-ce", "cr.portainer.io/portainer/portainer-ce:latest")
        assert updater._image_matches("portainer/portainer-ce", "docker.io/portainer/portainer-ce:2.21.0")
        assert updater._image_matches("portainer/portainer-ce", "index.docker.io/portainer/portainer-ce:latest")

    def test_digest_qualifier(self, updater):
        """Test images pinned with @sha256: digest."""
        assert updater._image_matches("portainer/portainer-ce", "portainer/portainer-ce:latest@sha256:abc123def456")
        assert updater._image_matches("nginx", "nginx:1.25@sha256:abc123def456")
        assert updater._image_matches("linuxserver/sonarr", "lscr.io/linuxserver/sonarr:latest@sha256:abc123")

    def test_localhost_registry_with_port(self, updater):
        """Test localhost registry with port number."""
        assert updater._image_matches("myapp", "localhost:5000/myapp:v1")
        assert updater._image_matches("myapp", "localhost:5000/myapp")
        assert updater._image_matches("org/myapp", "localhost:5000/org/myapp:v1")

    def test_registry_with_port(self, updater):
        """Test custom registry with port number."""
        assert updater._image_matches("myapp", "registry.local:5000/myapp:v1")
        assert updater._image_matches("org/myapp", "myregistry.io:5000/org/myapp:latest")


class TestGetContainersForImage:
    """Test the _get_containers_for_image method."""

    def test_no_containers(self, updater):
        """Test when no containers exist."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch('subprocess.run', return_value=mock_result):
            containers = updater._get_containers_for_image("nginx")
            assert containers == []

    def test_single_container(self, updater):
        """Test finding a single container."""
        container_json = json.dumps({
            "ID": "abc123",
            "Names": "sonarr",
            "Image": "linuxserver/sonarr:4.0.0.740",
            "State": "running"
        })

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = container_json

        with patch('subprocess.run', return_value=mock_result):
            containers = updater._get_containers_for_image("linuxserver/sonarr")

            assert len(containers) == 1
            assert containers[0]['name'] == 'sonarr'
            assert containers[0]['id'] == 'abc123'
            assert containers[0]['state'] == 'running'
            assert containers[0]['image_ref'] == 'linuxserver/sonarr:4.0.0.740'

    def test_multiple_containers(self, updater):
        """Test finding multiple containers with same image."""
        container1 = json.dumps({
            "ID": "abc123",
            "Names": "sonarr-hd",
            "Image": "linuxserver/sonarr:4.0.0.740",
            "State": "running"
        })
        container2 = json.dumps({
            "ID": "def456",
            "Names": "sonarr-4k",
            "Image": "linuxserver/sonarr:4.0.0.740",
            "State": "running"
        })

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = f"{container1}\n{container2}"

        with patch('subprocess.run', return_value=mock_result):
            containers = updater._get_containers_for_image("linuxserver/sonarr")

            assert len(containers) == 2
            assert containers[0]['name'] == 'sonarr-hd'
            assert containers[1]['name'] == 'sonarr-4k'

    def test_stopped_containers_included(self, updater):
        """Test that stopped containers are also returned."""
        container_json = json.dumps({
            "ID": "abc123",
            "Names": "sonarr",
            "Image": "linuxserver/sonarr:4.0.0.740",
            "State": "exited"
        })

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = container_json

        with patch('subprocess.run', return_value=mock_result):
            containers = updater._get_containers_for_image("linuxserver/sonarr")

            assert len(containers) == 1
            assert containers[0]['state'] == 'exited'

    def test_filters_non_matching_containers(self, updater):
        """Test that only matching containers are returned."""
        container1 = json.dumps({
            "ID": "abc123",
            "Names": "sonarr",
            "Image": "linuxserver/sonarr:4.0.0.740",
            "State": "running"
        })
        container2 = json.dumps({
            "ID": "def456",
            "Names": "radarr",
            "Image": "linuxserver/radarr:6.0.0.123",
            "State": "running"
        })

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = f"{container1}\n{container2}"

        with patch('subprocess.run', return_value=mock_result):
            containers = updater._get_containers_for_image("linuxserver/sonarr")

            assert len(containers) == 1
            assert containers[0]['name'] == 'sonarr'

    def test_docker_command_failure(self, updater):
        """Test handling of docker command failure."""
        from subprocess import CalledProcessError

        with patch('subprocess.run', side_effect=CalledProcessError(1, 'docker')):
            containers = updater._get_containers_for_image("nginx")
            assert containers == []


class TestUpdateContainers:
    """Test the _update_containers method."""

    def test_all_containers_succeed(self, updater):
        """Test updating multiple containers successfully."""
        with patch.object(updater, '_update_container') as mock_update:
            mock_update.return_value = True

            results = updater._update_containers(
                ['sonarr-hd', 'sonarr-4k'],
                'linuxserver/sonarr',
                '4.0.16.2944-ls299'
            )

            assert results == {'sonarr-hd': True, 'sonarr-4k': True}
            assert mock_update.call_count == 2

    def test_partial_failure(self, updater):
        """Test when some containers fail to update."""
        with patch.object(updater, '_update_container') as mock_update:
            # First succeeds, second fails
            mock_update.side_effect = [True, False]

            results = updater._update_containers(
                ['sonarr-hd', 'sonarr-4k'],
                'linuxserver/sonarr',
                '4.0.16.2944-ls299'
            )

            assert results == {'sonarr-hd': True, 'sonarr-4k': False}

    def test_all_containers_fail(self, updater):
        """Test when all containers fail to update."""
        with patch.object(updater, '_update_container') as mock_update:
            mock_update.return_value = False

            results = updater._update_containers(
                ['sonarr-hd', 'sonarr-4k'],
                'linuxserver/sonarr',
                '4.0.16.2944-ls299'
            )

            assert results == {'sonarr-hd': False, 'sonarr-4k': False}

    def test_single_container(self, updater):
        """Test updating a single container."""
        with patch.object(updater, '_update_container') as mock_update:
            mock_update.return_value = True

            results = updater._update_containers(
                ['sonarr'],
                'linuxserver/sonarr',
                '4.0.16.2944-ls299'
            )

            assert results == {'sonarr': True}
            assert mock_update.call_count == 1
