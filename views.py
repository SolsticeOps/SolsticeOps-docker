import docker
from django.shortcuts import redirect, get_object_or_404
from django.http import HttpResponse
from core.models import Tool

def container_action(request, container_id, action):
    try:
        client = docker.from_env()
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

def container_logs(request, container_id):
    try:
        client = docker.from_env()
        container = client.containers.get(container_id)
        logs = container.logs(tail=200).decode('utf-8', errors='replace')
        return HttpResponse(logs)
    except Exception as e:
        return HttpResponse(f"Error: {str(e)}")
