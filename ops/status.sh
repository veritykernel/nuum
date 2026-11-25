cat > ops/status.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source <(nuum-secrets-env --sh) 2>/dev/null || true
NUUM_KNOWN_HOSTS="${NUUM_KNOWN_HOSTS:?set an out-of-band verified known_hosts file}"
[[ "$NUUM_KNOWN_HOSTS" == /* && -s "$NUUM_KNOWN_HOSTS" ]] || {
  echo "NUUM_KNOWN_HOSTS must be an existing nonempty absolute file" >&2
  exit 1
}

echo "== Floating IPs =="
hcloud floating-ip list -o columns=id,description,ip,server || true

echo "== DNS =="
printf "exec.cntm.io -> %s\n" "$(dig +short exec.cntm.io | tr '\n' ' ')"
printf "relay.cntm.io -> %s\n" "$(dig +short relay.cntm.io | tr '\n' ' ')"

for H in op orc lake; do
  echo "== $H =="
  ssh-keygen -F "$H" -f "$NUUM_KNOWN_HOSTS" >/dev/null || {
    echo "Missing verified host key for $H" >&2
    exit 1
  }
  ssh -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$NUUM_KNOWN_HOSTS" \
    -o GlobalKnownHostsFile=/dev/null -o UpdateHostKeys=no -o BatchMode=yes \
    -o ForwardAgent=no "$H" '
    echo -n "host: "; hostnamectl --static
    echo -n "ip:   "; hostname -I | awk "{print \$1}"
    systemctl is-enabled nuum-health.timer 2>/dev/null || true
    systemctl is-active  nuum-health.timer 2>/dev/null || true
  '
done
EOF
chmod +x ops/status.sh
./ops/status.sh
