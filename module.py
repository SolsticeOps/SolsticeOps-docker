import docker
import subprocess
import threading
from django.shortcuts import render, redirect
from django.urls import path
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
    module_id = "docker"
    module_name = "Docker"
    description = "Manage Docker containers, images, volumes and networks."

    def get_context_data(self, request, tool):
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

    def get_urls(self):
        from . import views
        return [
            path('docker/container/<str:container_id>/act/<str:action>/', views.container_action, name='docker_container_action'),
            path('docker/container/<str:container_id>/logs/', views.container_logs, name='docker_container_logs'),
        ]
