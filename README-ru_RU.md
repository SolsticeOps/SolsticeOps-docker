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
