#!/usr/bin/env bash
# Устанавливаем системные пакеты для компиляции и работы
apt-get update
apt-get install -y build-essential cmake ffmpeg

# Устанавливаем Python-зависимости
pip install -r requirements.txt