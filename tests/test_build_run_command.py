"""Tests for _build_create_config container recreation logic."""

import pytest

from ium import DockerImageUpdater


@pytest.fixture
def updater(tmp_path):
    """Create a minimal updater for testing _build_create_config."""
    config_file = tmp_path / "config.json"
    config_file.write_text('{"images": []}')
    return DockerImageUpdater(str(config_file), str(tmp_path / "state.json"))


def _make_container_info(**overrides):
    """Build a minimal docker inspect result with sensible defaults."""
    info = {
        'Id': 'abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
        'Config': {
            'Hostname': 'abcdef123456',  # matches Id[:12] by default
            'User': '',
            'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Labels': {},
            'Cmd': None,
        },
        'HostConfig': {
            'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
            'NetworkMode': 'default',
            'PortBindings': None,
            'Privileged': False,
            'CapAdd': None,
            'CapDrop': None,
            'Devices': None,
            'Memory': 0,
            'CpuShares': 0,
            'CpuQuota': 0,
            'SecurityOpt': None,
            'Runtime': '',
        },
        'Mounts': [],
        'NetworkSettings': {'Networks': {}},
    }
    # Apply overrides by merging into nested dicts
    for key, value in overrides.items():
        if key in info and isinstance(info[key], dict) and isinstance(value, dict):
            info[key].update(value)
        else:
            info[key] = value
    return info


class TestComposeLabels:
    """Compose stack labels must be preserved so Portainer shows stack membership."""

    def test_compose_project_label_preserved(self, updater):
        info = _make_container_info(Config={
            'Hostname': 'abcdef123456',
            'User': '', 'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Cmd': None,
            'Labels': {
                'com.docker.compose.project': 'vpn_downloader_stack',
                'com.docker.compose.service': 'sabnzbd',
                'com.docker.compose.container-number': '1',
                'com.docker.compose.project.config_files': '/data/compose/8/docker-compose.yml',
                'com.docker.compose.project.working_dir': '/data/compose/8',
            },
        })
        config, _ = updater._build_create_config('sabnzbd', 'linuxserver/sabnzbd:latest', info)
        labels = config.get('Labels', {})

        assert labels.get('com.docker.compose.project') == 'vpn_downloader_stack'
        assert labels.get('com.docker.compose.service') == 'sabnzbd'
        assert labels.get('com.docker.compose.container-number') == '1'

    def test_non_compose_docker_labels_skipped(self, updater):
        info = _make_container_info(Config={
            'Hostname': 'abcdef123456',
            'User': '', 'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Cmd': None,
            'Labels': {
                'com.docker.desktop.plugin': 'true',
                'com.docker.compose.project': 'mystack',
                'custom.label': 'value',
            },
        })
        config, _ = updater._build_create_config('test', 'image:latest', info)
        labels = config.get('Labels', {})

        # compose label kept
        assert labels.get('com.docker.compose.project') == 'mystack'
        # custom label kept
        assert labels.get('custom.label') == 'value'
        # desktop label dropped
        assert 'com.docker.desktop.plugin' not in labels

    def test_no_compose_labels_still_works(self, updater):
        """Containers not from compose should work fine with no compose labels."""
        info = _make_container_info(Config={
            'Hostname': 'abcdef123456',
            'User': '', 'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Cmd': None,
            'Labels': {'maintainer': 'test'},
        })
        config, _ = updater._build_create_config('test', 'image:latest', info)
        labels = config.get('Labels', {})
        assert labels.get('maintainer') == 'test'


class TestNetworkModeConstraints:
    """Hostname, ports, and extra networks must be skipped for shared network namespaces."""

    def test_default_network_includes_hostname(self, updater):
        info = _make_container_info(Config={
            'Hostname': 'myhost',
            'User': '', 'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Cmd': None, 'Labels': {},
        })
        config, _ = updater._build_create_config('test', 'image:latest', info)
        assert config.get('Hostname') == 'myhost'

    def test_container_network_skips_hostname(self, updater):
        info = _make_container_info(
            Config={
                'Hostname': 'vpnhost',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'container:a1_vpn',
                'PortBindings': None,
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
        )
        config, _ = updater._build_create_config('qbittorrent', 'linuxserver/qbittorrent:latest', info)
        assert 'Hostname' not in config
        assert config.get('HostConfig', {}).get('NetworkMode') == 'container:a1_vpn'

    def test_host_network_skips_hostname(self, updater):
        info = _make_container_info(
            Config={
                'Hostname': 'nas',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'host',
                'PortBindings': None,
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
        )
        config, _ = updater._build_create_config('pihole', 'pihole/pihole:latest', info)
        assert 'Hostname' not in config

    def test_container_network_skips_ports(self, updater):
        info = _make_container_info(
            Config={
                'Hostname': 'abcdef123456',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'container:a1_vpn',
                'PortBindings': {'8080/tcp': [{'HostIp': '', 'HostPort': '8080'}]},
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
        )
        config, _ = updater._build_create_config('qbittorrent', 'linuxserver/qbittorrent:latest', info)
        assert 'PortBindings' not in config.get('HostConfig', {})

    def test_host_network_skips_ports(self, updater):
        info = _make_container_info(
            Config={
                'Hostname': 'abcdef123456',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'host',
                'PortBindings': {'53/tcp': [{'HostIp': '', 'HostPort': '53'}]},
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
        )
        config, _ = updater._build_create_config('pihole', 'pihole/pihole:latest', info)
        assert 'PortBindings' not in config.get('HostConfig', {})

    def test_container_network_skips_additional_networks(self, updater):
        info = _make_container_info(
            Config={
                'Hostname': 'abcdef123456',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'container:a1_vpn',
                'PortBindings': None,
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
            NetworkSettings={'Networks': {'bridge': {}, 'custom_net': {}}},
        )
        config, extra_networks = updater._build_create_config('test', 'image:latest', info)
        # container: network mode — no additional networks
        assert extra_networks == []
        assert config.get('HostConfig', {}).get('NetworkMode') == 'container:a1_vpn'

    def test_default_network_includes_ports(self, updater):
        info = _make_container_info(
            Config={
                'Hostname': 'abcdef123456',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'default',
                'PortBindings': {'8080/tcp': [{'HostIp': '', 'HostPort': '8080'}]},
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
        )
        config, _ = updater._build_create_config('test', 'image:latest', info)
        port_bindings = config.get('HostConfig', {}).get('PortBindings', {})
        assert '8080/tcp' in port_bindings
        assert port_bindings['8080/tcp'] == [{'HostIp': '', 'HostPort': '8080'}]

    def test_bridge_network_includes_hostname_and_ports(self, updater):
        """Named bridge networks are NOT shared namespaces."""
        info = _make_container_info(
            Config={
                'Hostname': 'myapp',
                'User': '', 'WorkingDir': '',
                'Env': ['PATH=/usr/bin:/bin'],
                'Cmd': None, 'Labels': {},
            },
            HostConfig={
                'RestartPolicy': {'Name': '', 'MaximumRetryCount': 0},
                'NetworkMode': 'my_bridge',
                'PortBindings': {'3000/tcp': [{'HostIp': '', 'HostPort': '3000'}]},
                'Privileged': False, 'CapAdd': None, 'CapDrop': None,
                'Devices': None, 'Memory': 0, 'CpuShares': 0,
                'CpuQuota': 0, 'SecurityOpt': None, 'Runtime': '',
            },
        )
        config, _ = updater._build_create_config('test', 'image:latest', info)
        assert config.get('Hostname') == 'myapp'
        assert '3000/tcp' in config.get('HostConfig', {}).get('PortBindings', {})
