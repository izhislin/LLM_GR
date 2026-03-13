#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Установка Prometheus-экспортёров на сервер AI-лаборатории
# Запускать с sudo: sudo bash setup_exporters.sh
# ============================================================

echo "=== 1. Node Exporter ==="
apt install -y prometheus-node-exporter
systemctl enable --now prometheus-node-exporter
echo "node_exporter: $(systemctl is-active prometheus-node-exporter)"
curl -sf http://localhost:9100/metrics | head -3

echo ""
echo "=== 2. NVIDIA GPU Exporter ==="
NVIDIA_EXPORTER_VERSION="1.3.2"
NVIDIA_EXPORTER_URL="https://github.com/utkuozdemir/nvidia_gpu_exporter/releases/download/v${NVIDIA_EXPORTER_VERSION}/nvidia_gpu_exporter_${NVIDIA_EXPORTER_VERSION}_linux_amd64.tar.gz"

cd /tmp
echo "Скачиваю nvidia_gpu_exporter v${NVIDIA_EXPORTER_VERSION}..."
curl -fsSL "$NVIDIA_EXPORTER_URL" -o nvidia_gpu_exporter.tar.gz
tar xzf nvidia_gpu_exporter.tar.gz nvidia_gpu_exporter
mv nvidia_gpu_exporter /usr/local/bin/nvidia_gpu_exporter
chmod +x /usr/local/bin/nvidia_gpu_exporter
rm nvidia_gpu_exporter.tar.gz

cat > /etc/systemd/system/nvidia-gpu-exporter.service <<'SVC'
[Unit]
Description=NVIDIA GPU Exporter for Prometheus
After=network.target

[Service]
ExecStart=/usr/local/bin/nvidia_gpu_exporter
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable --now nvidia-gpu-exporter
echo "nvidia_gpu_exporter: $(systemctl is-active nvidia-gpu-exporter)"
sleep 2
curl -sf http://localhost:9835/metrics | grep nvidia_gpu_utilization | head -1

echo ""
echo "=== 3. Ollama Metrics ==="
# Добавляем OLLAMA_METRICS через systemd override
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/metrics.conf <<'SVC'
[Service]
Environment="OLLAMA_METRICS=true"
SVC

systemctl daemon-reload
systemctl restart ollama
echo "ollama: $(systemctl is-active ollama)"
sleep 3
echo "Проверяю Ollama метрики..."
curl -sf http://localhost:11434/api/tags > /dev/null && echo "Ollama API: OK" || echo "Ollama API: FAIL"

echo ""
echo "=== Готово! ==="
echo ""
echo "Порты:"
echo "  :9100  — node_exporter       (CPU, RAM, Disk, Network)"
echo "  :9835  — nvidia_gpu_exporter (GPU util, memory, temp, power)"
echo "  :8000  — pipeline metrics    (RTF, этапы, токены) — при запуске пайплайна"
echo "  :11434 — ollama metrics      (request duration, tokens)"
echo ""
echo "Маппинг MikroTik → сервер:"
echo "  42363 → 9100   (node_exporter)"
echo "  42364 → 9835   (nvidia_gpu_exporter)"
echo "  42365 → 8000   (pipeline metrics)"
echo "  42366 → 11434  (ollama metrics)"
