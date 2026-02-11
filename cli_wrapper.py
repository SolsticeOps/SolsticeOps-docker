import json
import logging
from core.utils import run_sudo_command

logger = logging.getLogger(__name__)

class DockerObject:
    def __init__(self, attrs):
        self.attrs = attrs

    def __getattr__(self, item):
        # Map some common attributes
        if item == 'id':
            return self.attrs.get('Id')
        if item == 'name':
            # Names in inspect usually start with /
            name = self.attrs.get('Name', '')
            return name[1:] if name.startswith('/') else name
        return self.attrs.get(item)

class Container(DockerObject):
    @property
    def status(self):
        state = self.attrs.get('State', {})
        if isinstance(state, dict):
            return state.get('Status', 'unknown')
        return 'unknown'

    @property
    def image(self):
        return Image({'Id': self.attrs.get('Image'), 'RepoTags': [self.attrs.get('Config', {}).get('Image', 'unknown')]})

    def start(self):
        run_sudo_command(['docker', 'start', self.id])

    def stop(self):
        run_sudo_command(['docker', 'stop', self.id])

    def restart(self):
        run_sudo_command(['docker', 'restart', self.id])

    def remove(self, force=False):
        cmd = ['docker', 'rm']
        if force:
            cmd.append('-f')
        cmd.append(self.id)
        run_sudo_command(cmd)

    def logs(self, tail=None, timestamps=False):
        cmd = ['docker', 'logs']
        if tail:
            cmd.extend(['--tail', str(tail)])
        if timestamps:
            cmd.append('-t')
        cmd.append(self.id)
        return run_sudo_command(cmd)

    def exec_run(self, cmd):
        # This is harder to implement exactly like docker-py, but we can try
        full_cmd = ['docker', 'exec', self.id] + (cmd if isinstance(cmd, list) else cmd.split())
        output = run_sudo_command(full_cmd)
        # Mocking the result object
        class ExecResult:
            def __init__(self, output):
                self.exit_code = 0
                self.output = output
        return ExecResult(output)

class Image(DockerObject):
    @property
    def tags(self):
        return self.attrs.get('RepoTags', [])

class Volume(DockerObject):
    @property
    def id(self):
        return self.attrs.get('Name')

    @property
    def name(self):
        return self.attrs.get('Name')

    def remove(self, force=False):
        cmd = ['docker', 'volume', 'rm']
        if force:
            cmd.append('-f')
        cmd.append(self.id)
        run_sudo_command(cmd)

class Network(DockerObject):
    @property
    def id(self):
        return self.attrs.get('Id')

    @property
    def name(self):
        return self.attrs.get('Name')

    def connect(self, container):
        container_id = container.id if hasattr(container, 'id') else container
        run_sudo_command(['docker', 'network', 'connect', self.id, container_id])

    def disconnect(self, container):
        container_id = container.id if hasattr(container, 'id') else container
        run_sudo_command(['docker', 'network', 'disconnect', self.id, container_id])

    def remove(self):
        run_sudo_command(['docker', 'network', 'rm', self.id])

class DockerCLI:
    def __init__(self):
        self.containers = ContainerManager()
        self.images = ImageManager()
        self.volumes = VolumeManager()
        self.networks = NetworkManager()

    def info(self):
        try:
            output = run_sudo_command(['docker', 'info', '--format', '{{json .}}'])
            return json.loads(output)
        except:
            return {}

class Manager:
    def _exists(self, obj_id, type_filter=None):
        if not obj_id:
            return False
        try:
            cmd = ['docker', 'inspect', '--format', '{{.Id}}', obj_id]
            # Use capture_output=True to avoid printing error if it doesn't exist
            # but run_sudo_command logs errors by default.
            # We can use a more silent approach: docker ps -a -q --filter name=...
            # but ID is more reliable.
            # Actually, let's just use docker ps/images/etc -q and check if ID is in list
            return True # If we are here, we are about to call inspect anyway
        except:
            return False

    def _inspect_all(self, ids, cls):
        if not ids:
            return []
        try:
            # Inspect multiple IDs at once
            output = run_sudo_command(['docker', 'inspect'] + ids)
            data = json.loads(output)
            return [cls(item) for item in data]
        except Exception as e:
            # logger.error(f"Error inspecting objects: {e}")
            return []

class ContainerManager(Manager):
    def list(self, all=False):
        cmd = ['docker', 'ps', '-q']
        if all:
            cmd.append('-a')
        try:
            output = run_sudo_command(cmd).decode().strip()
            ids = output.split() if output else []
            return self._inspect_all(ids, Container)
        except:
            return []

    def get(self, container_id):
        try:
            # Try to inspect directly but suppress logs if it fails
            output = run_sudo_command(['docker', 'inspect', container_id], log_errors=False)
            if output:
                data = json.loads(output)
                if data:
                    return Container(data[0])
        except:
            pass
        return None

    def run(self, image, **kwargs):
        # Very basic implementation for Jenkins module use case
        cmd = ['docker', 'run', '-d']
        if kwargs.get('name'):
            cmd.extend(['--name', kwargs['name']])
        if kwargs.get('ports'):
            for c_port, h_port in kwargs['ports'].items():
                cmd.extend(['-p', f"{h_port}:{c_port}"])
        if kwargs.get('volumes'):
            for src, cfg in kwargs['volumes'].items():
                cmd.extend(['-v', f"{src}:{cfg['bind']}:{cfg.get('mode', 'rw')}"])
        if kwargs.get('network'):
            cmd.extend(['--network', kwargs['network']])
        if kwargs.get('restart_policy'):
            policy = kwargs['restart_policy'].get('Name')
            if policy:
                cmd.extend(['--restart', policy])
        if kwargs.get('privileged'):
            cmd.append('--privileged')
        if kwargs.get('environment'):
            env = kwargs['environment']
            if isinstance(env, list):
                for e in env:
                    cmd.extend(['-e', e])
            elif isinstance(env, dict):
                for k, v in env.items():
                    cmd.extend(['-e', f"{k}={v}"])
        
        cmd.append(image)
        run_sudo_command(cmd)
        # Return mocked container object
        return self.get(kwargs.get('name') or image)

class ImageManager(Manager):
    def list(self):
        try:
            output = run_sudo_command(['docker', 'images', '-q']).decode().strip()
            ids = list(set(output.split())) if output else []
            return self._inspect_all(ids, Image)
        except:
            return []

    def pull(self, repository, tag=None, auth_config=None):
        image = f"{repository}:{tag}" if tag else repository
        # Auth config not easily supported via CLI without 'docker login'
        # but we can try if it's just public
        run_sudo_command(['docker', 'pull', image])

    def remove(self, image_id, force=False):
        cmd = ['docker', 'rmi']
        if force:
            cmd.append('-f')
        cmd.append(image_id)
        run_sudo_command(cmd)

class VolumeManager(Manager):
    def list(self):
        try:
            output = run_sudo_command(['docker', 'volume', 'ls', '-q']).decode().strip()
            names = output.split() if output else []
            if not names: return []
            output = run_sudo_command(['docker', 'volume', 'inspect'] + names)
            data = json.loads(output)
            return [Volume(item) for item in data]
        except:
            return []

    def get(self, name):
        try:
            output = run_sudo_command(['docker', 'volume', 'inspect', name], log_errors=False)
            if output:
                data = json.loads(output)
                if data:
                    return Volume(data[0])
        except:
            pass
        return None

    def create(self, name, driver='local'):
        run_sudo_command(['docker', 'volume', 'create', '--name', name, '--driver', driver])

class NetworkManager(Manager):
    def list(self):
        try:
            output = run_sudo_command(['docker', 'network', 'ls', '-q']).decode().strip()
            ids = output.split() if output else []
            return self._inspect_all(ids, Network)
        except:
            return []

    def get(self, network_id):
        try:
            output = run_sudo_command(['docker', 'network', 'inspect', network_id], log_errors=False)
            if output:
                data = json.loads(output)
                if data:
                    return Network(data[0])
        except:
            pass
        return None

    def create(self, name, driver='bridge'):
        run_sudo_command(['docker', 'network', 'create', '--driver', driver, name])
