"""Tests for _build_run_command container recreation logic."""

import pytest

from dum import DockerImageUpdater


@pytest.fixture
def updater(tmp_path):
    """Create a minimal updater for testing _build_run_command."""
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
        cmd = updater._build_run_command('sabnzbd', 'linuxserver/sabnzbd:latest', info)
        labels = {cmd[i + 1] for i in range(len(cmd)) if cmd[i] == '--label'}

        assert 'com.docker.compose.project=vpn_downloader_stack' in labels
        assert 'com.docker.compose.service=sabnzbd' in labels
        assert 'com.docker.compose.container-number=1' in labels

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
        cmd = updater._build_run_command('test', 'image:latest', info)
        labels = {cmd[i + 1] for i in range(len(cmd)) if cmd[i] == '--label'}

        # compose label kept
        assert 'com.docker.compose.project=mystack' in labels
        # custom label kept
        assert 'custom.label=value' in labels
        # desktop label dropped
        assert 'com.docker.desktop.plugin=true' not in labels

    def test_no_compose_labels_still_works(self, updater):
        """Containers not from compose should work fine with no compose labels."""
        info = _make_container_info(Config={
            'Hostname': 'abcdef123456',
            'User': '', 'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Cmd': None,
            'Labels': {'maintainer': 'test'},
        })
        cmd = updater._build_run_command('test', 'image:latest', info)
        labels = {cmd[i + 1] for i in range(len(cmd)) if cmd[i] == '--label'}
        assert 'maintainer=test' in labels


class TestNetworkModeConstraints:
    """Hostname, ports, and extra networks must be skipped for shared network namespaces."""

    def test_default_network_includes_hostname(self, updater):
        info = _make_container_info(Config={
            'Hostname': 'myhost',
            'User': '', 'WorkingDir': '',
            'Env': ['PATH=/usr/bin:/bin'],
            'Cmd': None, 'Labels': {},
        })
        cmd = updater._build_run_command('test', 'image:latest', info)
        assert '--hostname' in cmd
        assert 'myhost' in cmd

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
        cmd = updater._build_run_command('qbittorrent', 'linuxserver/qbittorrent:latest', info)
        assert '--hostname' not in cmd
        assert '--network' in cmd
        idx = cmd.index('--network')
        assert cmd[idx + 1] == 'container:a1_vpn'

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
        cmd = updater._build_run_command('pihole', 'pihole/pihole:latest', info)
        assert '--hostname' not in cmd

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
        cmd = updater._build_run_command('qbittorrent', 'linuxserver/qbittorrent:latest', info)
        assert '-p' not in cmd

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
        cmd = updater._build_run_command('pihole', 'pihole/pihole:latest', info)
        assert '-p' not in cmd

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
        cmd = updater._build_run_command('test', 'image:latest', info)
        network_args = [cmd[i + 1] for i in range(len(cmd)) if cmd[i] == '--network']
        # Only the primary network mode, no additional networks
        assert network_args == ['container:a1_vpn']

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
        cmd = updater._build_run_command('test', 'image:latest', info)
        assert '-p' in cmd
        idx = cmd.index('-p')
        assert cmd[idx + 1] == '8080:8080/tcp'

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
        cmd = updater._build_run_command('test', 'image:latest', info)
        assert '--hostname' in cmd
        assert '-p' in cmd
