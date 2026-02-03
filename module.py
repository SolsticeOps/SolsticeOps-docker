import docker
import subprocess
import threading
from django.shortcuts import render, redirect
from django.urls import path, re_path
from core.plugin_system import BaseModule
from core.terminal_manager import TerminalSession
import logging
import select

logger = logging.getLogger(__name__)

class DockerSession(TerminalSession):
    def __init__(self, container_id):
        super().__init__()
        self.container_id = container_id
        self.client = docker.from_env()
        self._setup_session()

    def _setup_session(self):
        cmd = ['/bin/bash', '--login']
        try:
            self.exec_id = self.client.api.exec_create(
                self.container_id, cmd, stdin=True, tty=True, stdout=True, stderr=True
            )['Id']
        except:
            self.exec_id = self.client.api.exec_create(
                self.container_id, ['sh'], stdin=True, tty=True, stdout=True, stderr=True
            )['Id']
            
        self.socket = self.client.api.exec_start(
            self.exec_id, detach=False, tty=True, stream=True, socket=True
        )._sock
        self.socket.settimeout(0.1)

    def run(self):
        try:
            while self.keep_running:
                try:
                    r, w, e = select.select([self.socket], [], [], 0.5)
                    if self.socket in r:
                        data = self.socket.recv(4096)
                        if data:
                            self.add_history(data)
                        else:
                            break
                except (TimeoutError, BlockingIOError):
                    continue
                except Exception:
                    break
        finally:
            try:
                self.socket.close()
            except:
                pass

    def send_input(self, data):
        try:
            self.socket.send(data.encode())
        except:
            pass

    def resize(self, rows, cols):
        try:
            self.client.api.exec_resize(self.exec_id, height=rows, width=cols)
        except:
            pass

class Module(BaseModule):
    @property
    def module_id(self):
        return "docker"

    @property
    def module_name(self):
        return "Docker"

    description = "Manage Docker containers, images, volumes and networks."
    version = "1.0.0"

    def get_service_version(self):
        try:
            process = subprocess.run(["docker", "version", "--format", "{{.Client.Version}}"], capture_output=True, text=True)
            if process.returncode == 0:
                return process.stdout.strip()
        except Exception:
            pass
        return None

    def get_context_data(self, request, tool):
        from .models import DockerRegistry
        context = {}
        if tool.status == 'installed':
            try:
                client = docker.from_env()
                containers = client.containers.list(all=True)
                used_images = {c.image.id for c in containers}
                used_volumes = {m.get('Name') for c in containers for m in c.attrs.get('Mounts', []) if m.get('Type') == 'volume'}
                
                context['used_images'] = used_images
                context['used_volumes'] = used_volumes
                context['containers'] = sorted(containers, key=lambda x: x.name)
                context['images'] = sorted(client.images.list(), key=lambda x: x.tags[0] if x.tags else x.id)
                context['volumes'] = sorted(client.volumes.list(), key=lambda x: x.name)
                context['networks'] = sorted(client.networks.list(), key=lambda x: x.name)
                context['docker_info'] = client.info()
                
                # Get registries
                db_registries = list(DockerRegistry.objects.all())
                system_registries = []
                try:
                    reg_config = context['docker_info'].get('RegistryConfig', {})
                    index_configs = reg_config.get('IndexConfigs', {})
                    for name, config in index_configs.items():
                        if not any(r.url == name or r.url in name for r in db_registries):
                            system_registries.append({
                                'id': f"sys_{name}",
                                'name': f"{name} (System)",
                                'url': name,
                                'is_system': True
                            })
                except:
                    pass
                context['registries'] = db_registries + system_registries
            except Exception as e:
                context['docker_error'] = str(e)
        return context

    def handle_hx_request(self, request, tool, target):
        context = self.get_context_data(request, tool)
        context['tool'] = tool
        if target == 'containers':
            return render(request, 'core/partials/docker_containers.html', context)
        elif target == 'images':
            return render(request, 'core/partials/docker_images.html', context)
        elif target == 'volumes':
            return render(request, 'core/partials/docker_volumes.html', context)
        elif target == 'networks':
            return render(request, 'core/partials/docker_networks.html', context)
        return None

    def install(self, request, tool):
        if tool.status != 'not_installed':
            return

        tool.status = 'installing'
        tool.save()
        
        def run_install():
            stages = [
                ("Updating apt repositories...", "sudo apt-get update"),
                ("Installing dependencies...", "sudo apt-get install -y ca-certificates curl gnupg"),
                ("Setting up Docker GPG key...", "sudo install -m 0755 -d /etc/apt/keyrings && curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes && sudo chmod a+r /etc/apt/keyrings/docker.gpg"),
                ("Adding Docker repository...", "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null"),
                ("Updating package index...", "sudo apt-get update"),
                ("Installing Docker packages...", "sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"),
                ("Configuring user groups...", f"sudo usermod -aG docker {request.user.username}")
            ]
            try:
                for stage_name, command in stages:
                    tool.current_stage = stage_name
                    tool.save()
                    subprocess.run(command, shell=True, check=True)
                tool.status = 'installed'
                tool.current_stage = "Installation completed successfully"
            except Exception as e:
                tool.status = 'error'
                tool.config_data['error_log'] = str(e)
            tool.save()

        threading.Thread(target=run_install).start()

    def get_terminal_session_types(self):
        return {'docker': DockerSession}

    def get_extra_content_template_name(self):
        return "core/modules/docker_scripts.html"

    def get_logs_url(self, tool):
        container_name = tool.config_data.get('container_name')
        if container_name:
            return f'/docker/container/{container_name}/logs/'
        return '/docker/service/logs/'

    def get_resource_tabs(self):
        return [
            {'id': 'containers', 'label': 'Containers', 'template': 'core/partials/docker_containers.html', 'hx_get': '/tool/docker/?tab=containers', 'hx_auto_refresh': 'every 30s'},
            {'id': 'images', 'label': 'Images', 'template': 'core/partials/docker_images.html', 'hx_get': '/tool/docker/?tab=images', 'hx_auto_refresh': 'every 60s'},
            {'id': 'volumes', 'label': 'Volumes', 'template': 'core/partials/docker_volumes.html', 'hx_get': '/tool/docker/?tab=volumes', 'hx_auto_refresh': 'every 60s'},
            {'id': 'networks', 'label': 'Networks', 'template': 'core/partials/docker_networks.html', 'hx_get': '/tool/docker/?tab=networks', 'hx_auto_refresh': 'every 60s'},
        ]

    def get_urls(self):
        from . import views
        return [
            path('docker/container/<str:container_id>/act/<str:action>/', views.container_action, name='docker_container_action'),
            path('docker/container/<str:container_id>/logs/', views.container_logs, name='docker_container_logs'),
            path('docker/service/logs/', views.docker_service_logs, name='docker_service_logs'),
            path('docker/container/<str:container_id>/config/', views.docker_container_config, name='docker_container_config'),
            path('docker/container/<str:container_id>/shell/', views.docker_container_shell, name='docker_container_shell'),
            path('docker/image/<str:image_id>/<str:action>/', views.docker_image_action, name='docker_image_action'),
            path('docker/registry/create/', views.docker_registry_create, name='docker_registry_create'),
            path('docker/registry/<int:registry_id>/delete/', views.docker_registry_delete, name='docker_registry_delete'),
            path('docker/network/create/', views.docker_network_create, name='docker_network_create'),
            path('docker/network/<str:network_id>/<str:action>/', views.docker_network_action, name='docker_network_action'),
            path('docker/volume/create/', views.docker_volume_create, name='docker_volume_create'),
            path('docker/volume/<str:volume_name>/<str:action>/', views.docker_volume_action, name='docker_volume_action'),
        ]

    def get_websocket_urls(self):
        from core import consumers
        return [
            re_path(r'ws/docker/shell/(?P<container_id>[\w.-]+)/$', consumers.TerminalConsumer.as_asgi(), {'session_type': 'docker'}),
        ]
