import docker
import subprocess
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from core.models import Tool
from .models import DockerRegistry
from django.contrib.auth.decorators import login_required
from core.utils import run_sudo_command

@login_required
def container_action(request, container_id, action):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        container = client.containers.get(container_id)
        if action == 'start':
            container.start()
        elif action == 'stop':
            container.stop()
        elif action == 'restart':
            container.restart()
        elif action == 'remove':
            container.remove(force=True)
    except Exception:
        pass
    return redirect('tool_detail', tool_name='docker')

@login_required
def container_logs(request, container_id):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        container = client.containers.get(container_id)
        logs = container.logs(tail=200).decode('utf-8', errors='replace')
        return HttpResponse(logs)
    except Exception as e:
        return HttpResponse(f"Error: {str(e)}")

@login_required
def container_logs_download(request, container_id):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        container = client.containers.get(container_id)
        logs = container.logs().decode('utf-8', errors='replace')
        response = HttpResponse(logs, content_type='text/plain')
        response['Content-Disposition'] = f'attachment; filename="container_{container_id}_logs.log"'
        return response
    except Exception as e:
        return HttpResponse(f"Error downloading container logs: {str(e)}", status=500)

@login_required
def docker_service_logs(request):
    try:
        # Try journalctl without sudo first
        try:
            output = subprocess.check_output(['journalctl', '-u', 'docker', '-n', '200', '--no-pager'], stderr=subprocess.STDOUT).decode()
            # If output contains the restriction hint, it's basically empty for us
            if "Hint: You are currently not seeing messages" in output:
                raise subprocess.CalledProcessError(1, 'journalctl')
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to sudo if the first one fails or is restricted
            output = run_sudo_command(['journalctl', '-u', 'docker', '-n', '200', '--no-pager']).decode()
        
        if not output.strip() or "No entries" in output:
            return HttpResponse("No log entries found. Ensure the 'docker' service is running and you have permissions to view logs (group 'systemd-journal' or 'adm').", content_type='text/plain')
            
        return HttpResponse(output, content_type='text/plain')
    except Exception as e:
        return HttpResponse(f"Error fetching system logs: {str(e)}", status=500)

@login_required
def docker_service_logs_download(request):
    try:
        # Try journalctl without sudo first
        try:
            output = subprocess.check_output(['journalctl', '-u', 'docker', '--no-pager'], stderr=subprocess.STDOUT).decode()
            if "Hint: You are currently not seeing messages" in output:
                raise subprocess.CalledProcessError(1, 'journalctl')
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback to sudo if the first one fails or is restricted
            output = run_sudo_command(['journalctl', '-u', 'docker', '--no-pager']).decode()
        
        response = HttpResponse(output, content_type='text/plain')
        response['Content-Disposition'] = 'attachment; filename="docker_service_logs.log"'
        return response
    except Exception as e:
        return HttpResponse(f"Error downloading system logs: {str(e)}", status=500)

@login_required
def docker_container_config(request, container_id):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        container = client.containers.get(container_id)
        config = container.attrs
        
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'connect_network':
                net_id = request.POST.get('network_id')
                if net_id:
                    network = client.networks.get(net_id)
                    network.connect(container)
                return redirect('docker_container_config', container_id=container_id)
            
            elif action == 'disconnect_network':
                net_id = request.POST.get('network_id')
                if net_id:
                    network = client.networks.get(net_id)
                    network.disconnect(container)
                return redirect('docker_container_config', container_id=container_id)
            
            # Default recreation logic
            new_env = request.POST.getlist('env_vars')
            new_volumes = request.POST.getlist('volumes')
            new_port_containers = request.POST.getlist('port_container')
            new_port_hosts = request.POST.getlist('port_host')
            new_network = request.POST.get('network')
            
            # Portainer-style recreation logic
            image = container.image.id
            name = container.name
            
            # Parse Ports from pairs
            port_dict = {}
            for c_port, h_port in zip(new_port_containers, new_port_hosts):
                if c_port.strip() and h_port.strip():
                    port_dict[c_port.strip()] = h_port.strip()
            
            # Parse volumes: "source:target:mode"
            volume_dict = {}
            for v in new_volumes:
                if ':' in v:
                    parts = v.split(':')
                    if len(parts) >= 2:
                        source = parts[0]
                        target = parts[1]
                        mode = parts[2] if len(parts) > 2 else 'rw'
                        volume_dict[source] = {'bind': target, 'mode': mode}
            container.stop()
            container.remove()
            
            # Recreate container
            client.containers.run(
                image,
                name=name,
                environment=new_env,
                volumes=volume_dict,
                ports=port_dict,
                network=new_network,
                detach=True,
                restart_policy={"Name": "always"}
            )
            return redirect('tool_detail', tool_name='docker')

        context = {
            'container': container,
            'config': config,
            'networks_list': client.networks.list(),
            'tool': get_object_or_404(Tool, name='docker')
        }
        return render(request, 'core/docker_container_config.html', context)
    except Exception as e:
        return HttpResponse(str(e), status=500)

@login_required
def docker_image_action(request, image_id, action):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        if action == 'remove':
            client.images.remove(image_id, force=True)
        elif action == 'pull':
            image_name = request.POST.get('image_name')
            registry_id = request.POST.get('registry_id')
            
            auth_config = None
            if registry_id and not str(registry_id).startswith('sys_'):
                registry = get_object_or_404(DockerRegistry, id=registry_id)
                if registry.username and registry.password:
                    auth_config = {'username': registry.username, 'password': registry.password}
            
            if image_name:
                if ':' in image_name:
                    repository, tag = image_name.rsplit(':', 1)
                else:
                    repository, tag = image_name, 'latest'
                
                client.images.pull(repository, tag=tag, auth_config=auth_config)
    except Exception as e:
        print(f"Docker image action error: {e}")
    return redirect('/tool/docker/?tab=images')

@login_required
def docker_registry_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        url = request.POST.get('url')
        username = request.POST.get('username')
        password = request.POST.get('password')
        if name and url:
            DockerRegistry.objects.create(
                name=name,
                url=url,
                username=username,
                password=password
            )
    return redirect('/tool/docker/?tab=images')

@login_required
def docker_registry_delete(request, registry_id):
    registry = get_object_or_404(DockerRegistry, id=registry_id)
    registry.delete()
    return redirect('/tool/docker/?tab=images')

@login_required
def docker_network_action(request, network_id, action):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        network = client.networks.get(network_id)
        if action == 'remove':
            network.remove()
    except:
        pass
    return redirect('/tool/docker/?tab=networks')

@login_required
def docker_network_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        driver = request.POST.get('driver', 'bridge')
        if name:
            try:
                client = docker.DockerClient(base_url='unix://var/run/docker.sock')
                client.networks.create(name, driver=driver)
            except:
                pass
    return redirect('/tool/docker/?tab=networks')

@login_required
def docker_volume_action(request, volume_name, action):
    try:
        client = docker.DockerClient(base_url='unix://var/run/docker.sock')
        volume = client.volumes.get(volume_name)
        if action == 'remove':
            volume.remove(force=True)
    except:
        pass
    return redirect('/tool/docker/?tab=volumes')

@login_required
def docker_volume_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        driver = request.POST.get('driver', 'local')
        if name:
            try:
                client = docker.DockerClient(base_url='unix://var/run/docker.sock')
                client.volumes.create(name=name, driver=driver)
            except:
                pass
    return redirect('/tool/docker/?tab=volumes')

@login_required
def docker_container_shell(request, container_id):
    return HttpResponse("Shell initialised")
