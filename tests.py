from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.cache import cache
from core.models import Tool
from unittest.mock import patch, MagicMock
import subprocess

User = get_user_model()

class DockerModuleTest(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_superuser(username='admin', password='password', email='admin@test.com')
        self.client.login(username='admin', password='password')
        self.tool = Tool.objects.create(name="docker", status="installed")

    @patch('modules.docker.module.run_command')
    @patch('core.docker_cli_wrapper.run_command')
    def test_docker_containers_partial(self, mock_wrapper_run, mock_module_run):
        # 1. get_service_status calls run_command in modules.docker.module
        mock_module_run.return_value = b"active"
        
        # 2. DockerCLI calls run_command in core.docker_cli_wrapper
        def docker_side_effect(cmd, **kwargs):
            if 'ps' in cmd: return b"abc123"
            if 'inspect' in cmd:
                if 'abc123' in cmd:
                    return b'[{"Id": "abc123", "Name": "/test-container", "State": {"Status": "running"}, "Config": {"Image": "nginx"}, "Mounts": []}]'
                return b'[]'
            if 'images' in cmd: return b""
            if 'volume' in cmd: return b""
            if 'network' in cmd: return b""
            if 'info' in cmd: return b'{}'
            return b""
            
        mock_wrapper_run.side_effect = docker_side_effect
        
        response = self.client.get(reverse('tool_detail', kwargs={'tool_name': 'docker'}) + "?tab=containers", HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "test-container")
        self.assertContains(response, "running")

    @patch('modules.docker.module.run_command')
    @patch('core.docker_cli_wrapper.run_command')
    def test_docker_images_partial(self, mock_wrapper_run, mock_module_run):
        mock_module_run.return_value = b"active"
        
        def docker_side_effect(cmd, **kwargs):
            if 'ps' in cmd: return b""
            if 'images' in cmd:
                if '-q' in cmd: return b"img123"
                return b""
            if 'inspect' in cmd:
                if 'img123' in cmd:
                    return b'[{"Id": "img123", "RepoTags": ["nginx:latest"]}]'
                return b'[]'
            if 'volume' in cmd: return b""
            if 'network' in cmd: return b""
            if 'info' in cmd: return b'{}'
            return b""

        mock_wrapper_run.side_effect = docker_side_effect
        
        response = self.client.get(reverse('tool_detail', kwargs={'tool_name': 'docker'}) + "?tab=images", HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "nginx:latest")

    @patch('modules.docker.views.DockerCLI')
    def test_container_action(self, mock_docker):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        url = reverse('docker_container_action', kwargs={'container_id': 'abc123', 'action': 'start'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        mock_container.start.assert_called_once()

    @patch('modules.docker.views.DockerCLI')
    def test_container_logs(self, mock_docker):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"test logs"
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        url = reverse('docker_container_logs', kwargs={'container_id': 'abc123'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "test logs")

    def test_docker_registry_create(self):
        url = reverse('docker_registry_create')
        response = self.client.post(url, {
            'name': 'Test Registry',
            'url': 'https://registry.test.com',
            'username': 'user',
            'password': 'password'
        })
        self.assertEqual(response.status_code, 302)
        from modules.docker.models import DockerRegistry
        self.assertTrue(DockerRegistry.objects.filter(name='Test Registry').exists())

    @patch('modules.docker.views.DockerCLI')
    def test_docker_network_create(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.return_value = mock_client
        url = reverse('docker_network_create')
        response = self.client.post(url, {'name': 'test-net', 'driver': 'bridge'})
        self.assertEqual(response.status_code, 302)
        mock_client.networks.create.assert_called_with('test-net', driver='bridge')

    @patch('modules.docker.views.DockerCLI')
    def test_docker_volume_create(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.return_value = mock_client
        url = reverse('docker_volume_create')
        response = self.client.post(url, {'name': 'test-vol', 'driver': 'local'})
        self.assertEqual(response.status_code, 302)
        mock_client.volumes.create.assert_called_with(name='test-vol', driver='local')

    @patch('modules.docker.module.run_command')
    def test_docker_module_logic(self, mock_run):
        from modules.docker.module import Module
        module = Module()
        
        mock_run.return_value = b"24.0.7"
        self.assertEqual(module.get_service_version(), "24.0.7")
        
        mock_run.return_value = b"active"
        self.assertEqual(module.get_service_status(self.tool), "running")
        
        module.service_start(self.tool)
        mock_run.assert_called_with(["systemctl", "start", "docker.socket", "docker.service"])
        
        module.service_stop(self.tool)
        mock_run.assert_called_with(["systemctl", "stop", "docker.service", "docker.socket"])
        
        module.service_restart(self.tool)
        mock_run.assert_called_with(["systemctl", "restart", "docker.service"])
        
        self.assertEqual(module.get_logs_url(self.tool), '/docker/service/logs/')
        self.tool.config_data['container_name'] = 'test-c'
        self.assertEqual(module.get_logs_url(self.tool), '/docker/container/test-c/logs/')
        
        self.assertEqual(module.get_extra_content_template_name(), "core/modules/docker_scripts.html")

    @patch('modules.docker.views.DockerCLI')
    def test_container_logs_download(self, mock_docker):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.logs.return_value = b"full logs"
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        url = reverse('docker_container_logs_download', kwargs={'container_id': 'abc123'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertIn(b"full logs", response.content)

    @patch('modules.docker.views.run_command')
    @patch('modules.docker.views.subprocess.check_output')
    def test_docker_service_logs_fallback(self, mock_sub, mock_run):
        # First call fails
        mock_sub.side_effect = subprocess.CalledProcessError(1, 'journalctl')
        # Fallback succeeds
        mock_run.return_value = b"fallback logs"
        url = reverse('docker_service_logs')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"fallback logs", response.content)

    @patch('modules.docker.views.DockerCLI')
    def test_docker_volume_action_remove(self, mock_docker):
        mock_client = MagicMock()
        mock_volume = MagicMock()
        mock_client.volumes.get.return_value = mock_volume
        mock_docker.return_value = mock_client
        url = reverse('docker_volume_action', kwargs={'volume_name': 'vol123', 'action': 'remove'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        mock_volume.remove.assert_called_with(force=True)

    @patch('modules.docker.views.DockerCLI')
    def test_docker_volume_create(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.return_value = mock_client
        url = reverse('docker_volume_create')
        response = self.client.post(url, {'name': 'test-vol', 'driver': 'local'})
        self.assertEqual(response.status_code, 302)
        mock_client.volumes.create.assert_called_with(name='test-vol', driver='local')

    @patch('modules.docker.views.subprocess.check_output')
    def test_docker_service_logs_download(self, mock_sub):
        mock_sub.return_value = b"full system logs"
        url = reverse('docker_service_logs_download')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertIn(b"full system logs", response.content)

    @patch('modules.docker.views.DockerCLI')
    def test_docker_container_config_post_recreate(self, mock_docker):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.image.id = "img123"
        mock_container.name = "test-cont"
        mock_client.containers.get.return_value = mock_container
        mock_docker.return_value = mock_client
        
        url = reverse('docker_container_config', kwargs={'container_id': 'abc123'})
        response = self.client.post(url, {
            'env_vars': ['K=V'],
            'volumes': ['/src:/dst:rw'],
            'port_container': ['80'],
            'port_host': ['8080'],
            'network': 'bridge'
        })
        self.assertEqual(response.status_code, 302)
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        mock_client.containers.run.assert_called()
        
        # Check volume parsing
        args, kwargs = mock_client.containers.run.call_args
        self.assertEqual(kwargs['volumes']['/src']['bind'], '/dst')

    @patch('modules.docker.module.DockerCLI')
    @patch('modules.docker.module.run_command')
    def test_docker_context_data_with_registries(self, mock_run, mock_docker):
        mock_run.return_value = b"active"
        mock_client = MagicMock()
        mock_client.info.return_value = {
            'RegistryConfig': {
                'IndexConfigs': {'registry.hub.docker.com': {}}
            }
        }
        mock_docker.return_value = mock_client
        
        from modules.docker.module import Module
        module = Module()
        context = module.get_context_data(None, self.tool)
        self.assertIn('registries', context)
        # Check if system registry is added
        self.assertTrue(any(r.get('is_system') for r in context['registries'] if isinstance(r, dict)))

    @patch('modules.docker.module.DockerCLI')
    @patch('modules.docker.module.run_command')
    def test_docker_context_data_error(self, mock_run, mock_docker):
        mock_run.return_value = b"active"
        mock_docker.side_effect = Exception("docker api error")
        
        from modules.docker.module import Module
        module = Module()
        context = module.get_context_data(None, self.tool)
        self.assertIn('docker_error', context)
        self.assertEqual(context['docker_error'], "docker api error")

    @patch('modules.docker.views.DockerCLI')
    def test_docker_image_action_remove(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.return_value = mock_client
        url = reverse('docker_image_action', kwargs={'image_id': 'img123', 'action': 'remove'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        mock_client.images.remove.assert_called_with('img123', force=True)

    @patch('modules.docker.views.DockerCLI')
    def test_docker_network_action_remove(self, mock_docker):
        mock_client = MagicMock()
        mock_network = MagicMock()
        mock_client.networks.get.return_value = mock_network
        mock_docker.return_value = mock_client
        url = reverse('docker_network_action', kwargs={'network_id': 'net123', 'action': 'remove'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        mock_network.remove.assert_called_once()

    def test_docker_registry_delete(self):
        from modules.docker.models import DockerRegistry
        reg = DockerRegistry.objects.create(name='To Delete', url='http://delete.me')
        url = reverse('docker_registry_delete', kwargs={'registry_id': reg.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(DockerRegistry.objects.filter(id=reg.id).exists())

    @patch('modules.docker.views.DockerCLI')
    def test_docker_container_config_get(self, mock_docker):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_container.attrs = {'Config': {}}
        mock_client.containers.get.return_value = mock_container
        mock_client.networks.list.return_value = []
        mock_docker.return_value = mock_client
        
        url = reverse('docker_container_config', kwargs={'container_id': 'abc123'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/docker_container_config.html')

    @patch('modules.docker.views.DockerCLI')
    def test_docker_container_config_post_network(self, mock_docker):
        mock_client = MagicMock()
        mock_container = MagicMock()
        mock_client.containers.get.return_value = mock_container
        mock_network = MagicMock()
        mock_client.networks.get.return_value = mock_network
        mock_docker.return_value = mock_client
        
        url = reverse('docker_container_config', kwargs={'container_id': 'abc123'})
        # Connect network
        response = self.client.post(url, {'action': 'connect_network', 'network_id': 'net1'})
        self.assertEqual(response.status_code, 302)
        mock_network.connect.assert_called_with(mock_container)
        
        # Disconnect network
        response = self.client.post(url, {'action': 'disconnect_network', 'network_id': 'net1'})
        self.assertEqual(response.status_code, 302)
        mock_network.disconnect.assert_called_with(mock_container)
