#!/usr/bin/env bash
set -euo pipefail

GCP_PROJECT=my-agro-research
PROJECT="${GCP_PROJECT:-}"
ZONE="${GCP_ZONE:-us-central1-a}"
VM_NAME="${GCP_VM_NAME:-siat-agent}"
MACHINE_TYPE="${GCP_MACHINE_TYPE:-e2-medium}"
DISK_SIZE="${GCP_DISK_SIZE:-40GB}"
IMAGE_FAMILY="debian-12"
IMAGE_PROJECT="debian-cloud"
FIREWALL_RULE="allow-siat-agent-8000"

require_project() {
  if [[ -z "$PROJECT" ]]; then
    echo "Set GCP_PROJECT env var (e.g. export GCP_PROJECT=my-project)" >&2
    exit 1
  fi
}

gc() { gcloud --project "$PROJECT" "$@"; }

cmd_create() {
  require_project
  gc compute instances create "$VM_NAME" \
    --zone "$ZONE" \
    --machine-type "$MACHINE_TYPE" \
    --image-family "$IMAGE_FAMILY" \
    --image-project "$IMAGE_PROJECT" \
    --boot-disk-size "$DISK_SIZE" \
    --boot-disk-type pd-balanced \
    --tags siat-agent

  if ! gc compute firewall-rules describe "$FIREWALL_RULE" >/dev/null 2>&1; then
    gc compute firewall-rules create "$FIREWALL_RULE" \
      --allow tcp:8000 \
      --target-tags siat-agent \
      --description "siat-agent app port"
  fi

  echo "VM created. Next: ./scripts/gcp-vm.sh bootstrap"
}

cmd_bootstrap() {
  require_project
  gc compute ssh "$VM_NAME" --zone "$ZONE" --command "
    set -e
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl rsync
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | \
      sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/debian \$(. /etc/os-release && echo \$VERSION_CODENAME) stable\" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker \$USER
    mkdir -p ~/siat_agent/vector ~/siat_agent/logs ~/siat_agent/hf-cache
    sudo chown -R 1000:1000 ~/siat_agent/vector ~/siat_agent/logs ~/siat_agent/hf-cache
  "
  echo "Bootstrap done. Re-SSH once for docker group to take effect, then: ./scripts/gcp-vm.sh deploy"
}

cmd_deploy() {
  require_project
  if [[ ! -f .env ]]; then
    echo ".env not found at repo root. Copy .env.example to .env and fill it in first." >&2
    exit 1
  fi
  gc compute scp --zone "$ZONE" --recurse \
    Dockerfile docker-compose.yml pyproject.toml uv.lock main.py \
    core tools static jsons .env \
    "${VM_NAME}:~/siat_agent/"
  gc compute ssh "$VM_NAME" --zone "$ZONE" --command "
    cd ~/siat_agent && docker compose up -d --build
  "
  IP=$(gc compute instances describe "$VM_NAME" --zone "$ZONE" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
  echo "Deployed. App at: http://${IP}:8000"
}

cmd_start() { require_project; gc compute instances start "$VM_NAME" --zone "$ZONE"; }
cmd_stop()  { require_project; gc compute instances stop  "$VM_NAME" --zone "$ZONE"; }
cmd_ssh()   { require_project; gc compute ssh "$VM_NAME" --zone "$ZONE"; }

cmd_status() {
  require_project
  gc compute instances describe "$VM_NAME" --zone "$ZONE" \
    --format='table(name,status,networkInterfaces[0].accessConfigs[0].natIP)'
}

cmd_logs() {
  require_project
  gc compute ssh "$VM_NAME" --zone "$ZONE" --command \
    "cd ~/siat_agent && docker compose logs -f --tail=200"
}

cmd_destroy() {
  require_project
  read -rp "Delete VM '$VM_NAME' (this destroys the disk and Qdrant data)? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Aborted."; exit 0; }
  gc compute instances delete "$VM_NAME" --zone "$ZONE" --quiet
}

usage() {
  cat <<EOF
Usage: $0 <command>

Lifecycle:
  create      Provision the VM + firewall rule
  bootstrap   Install Docker on the VM (run once after create)
  deploy      Sync code and run 'docker compose up -d --build'

Day-to-day:
  start       Start the VM (resume billing)
  stop        Stop the VM (pause billing; disk still costs ~\$0.40/mo)
  status      Show VM state and external IP
  ssh         Open SSH session
  logs        Tail container logs

Teardown:
  destroy     Delete the VM and its boot disk

Env vars: GCP_PROJECT (required), GCP_ZONE, GCP_VM_NAME, GCP_MACHINE_TYPE, GCP_DISK_SIZE
EOF
}

case "${1:-}" in
  create)    cmd_create ;;
  bootstrap) cmd_bootstrap ;;
  deploy)    cmd_deploy ;;
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  status)    cmd_status ;;
  ssh)       cmd_ssh ;;
  logs)      cmd_logs ;;
  destroy)   cmd_destroy ;;
  *)         usage; exit 1 ;;
esac
