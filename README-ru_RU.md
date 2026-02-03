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

Модуль управления Docker для SolsticeOps.

[English Version](README.md)

## Возможности
- Управление контейнерами (запуск, остановка, перезапуск, удаление)
- Список образов и их очистка
- Управление томами и сетями
- Логи контейнеров в реальном времени
- Доступ к терминалу контейнеров

## Установка
Добавьте как субмодуль в SolsticeOps-core:
```bash
git submodule add https://github.com/SolsticeOps/SolsticeOps-docker.git modules/docker
pip install -r modules/docker/requirements.txt
```
