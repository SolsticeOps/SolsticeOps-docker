import subprocess
import threading
import os
import pty
import time
from django.shortcuts import render, redirect
from django.urls import path, re_path
from core.plugin_system import BaseModule
from core.terminal_manager import TerminalSession
from core.utils import run_command
from .cli_wrapper import DockerCLI
import logging
import select

logger = logging.getLogger(__name__)

class DockerSession(TerminalSession):
    def __init__(self, container_id):
        super().__init__()
        self.container_id = container_id
        self._setup_session()

    def _setup_session(self):
        self.master_fd, self.slave_fd = pty.openpty()
        
        cmd = ['docker', 'exec', '-it', self.container_id, '/bin/bash']
        
        env = os.environ.copy()
        env['TERM'] = 'xterm-256color'
        
        self.process = subprocess.Popen(
            cmd, preexec_fn=os.setsid, stdin=self.slave_fd, stdout=self.slave_fd, stderr=self.slave_fd,
            universal_newlines=False, env=env
        )
        os.close(self.slave_fd)

    def run(self):
        try:
            while self.keep_running:
                if self.process.poll() is not None:
                    break
                r, w, e = select.select([self.master_fd], [], [], 0.5)
                if self.master_fd in r:
                    data = os.read(self.master_fd, 4096)
                    if data:
                        self.add_history(data)
                    else:
                        break
        except:
            pass
        finally:
            try:
                os.close(self.master_fd)
            except:
                pass
            if self.process.poll() is None:
                self.process.terminate()

    def send_input(self, data):
        try:
            os.write(self.master_fd, data.encode())
        except:
            pass

    def resize(self, rows, cols):
        try:
            import fcntl, termios, struct
            s = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, s)
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
            process = run_command(["docker", "version", "--format", "{{.Client.Version}}"], capture_output=True)
            if process:
                return process.decode().strip()
        except Exception:
            pass
        return None

    def get_context_data(self, request, tool):
        from .models import DockerRegistry
        context = {}
        if tool.status == 'installed':
            try:
                # Use sudo-based CLI wrapper
                client = DockerCLI()
                containers = client.containers.list(all=True)
                used_images = {c.attrs.get('Image') for c in containers}
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
        if tool.status not in ['not_installed', 'error']:
            return

        tool.status = 'installing'
        tool.save()
        
        def run_install():
            stages = [
                ("Uninstalling conflicting packages...", "apt-get remove -y docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc"),
                ("Updating apt repositories...", "apt-get update"),
                ("Installing dependencies...", "apt-get install -y ca-certificates curl"),
                ("Setting up Docker GPG key...", "bash -c 'install -m 0755 -d /etc/apt/keyrings && curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo \"$ID\")/gpg -o /etc/apt/keyrings/docker.asc && chmod a+r /etc/apt/keyrings/docker.asc'"),
                ("Adding Docker repository...", "bash -c 'echo \"Types: deb\nURIs: https://download.docker.com/linux/$(. /etc/os-release && echo \"$ID\")\nSuites: $(. /etc/os-release && echo \"${UBUNTU_CODENAME:-$VERSION_CODENAME}\")\nComponents: stable\nArchitectures: $(dpkg --print-architecture)\nSigned-By: /etc/apt/keyrings/docker.asc\" | tee /etc/apt/sources.list.d/docker.sources > /dev/null && rm -f /etc/apt/sources.list.d/docker.list'"),
                ("Updating package index...", "apt-get update"),
                ("Installing Docker packages...", "apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin")
            ]
            try:
                for stage_name, command in stages:
                    tool.current_stage = stage_name
                    tool.save()
                    run_command(command, shell=True, capture_output=False, timeout=600)
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
            path('docker/container/<str:container_id>/logs/download/', views.container_logs_download, name='docker_container_logs_download'),
            path('docker/service/logs/', views.docker_service_logs, name='docker_service_logs'),
            path('docker/service/logs/download/', views.docker_service_logs_download, name='docker_service_logs_download'),
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
