<div align="center">
    <picture>
        <source
            srcset="https://raw.githubusercontent.com/SolsticeOps/SolsticeOps-core/refs/heads/main/docs/images/logo_dark.png"
            media="(prefers-color-scheme: light), (prefers-color-scheme: no-preference)"
        />
        <source
            srcset="https://raw.githubusercontent.com/SolsticeOps/SolsticeOps-core/refs/heads/main/docs/images/logo_light.png"
            media="(prefers-color-scheme: dark)"
        />
        <img src="https://raw.githubusercontent.com/SolsticeOps/SolsticeOps-core/refs/heads/main/docs/images/logo_light.png" />
    </picture>
</div>

# SolsticeOps-docker

Docker management module for SolsticeOps.

[Русская версия](README-ru_RU.md)

## Features
- Container management (start, stop, restart, remove)
- Image list and cleanup
- Volume and network management
- Real-time container logs
- Terminal access to containers

## Installation
Add as a submodule to SolsticeOps-core:
```bash
git submodule add https://github.com/SolsticeOps/SolsticeOps-docker.git modules/docker
pip install -r modules/docker/requirements.txt
```
