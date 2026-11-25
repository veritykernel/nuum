#!/usr/bin/env bash
set -Eeuo pipefail

# Cloudflare's global authenticated origin pull CA, downloaded from its current docs.
EXPECTED_SHA256=c14fed0ce5210db0719fea11d1f10b33750dc17d609aeaf47c75e9eff0d7b843
CA_URL=https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem

verify_ca() {
  local digest
  digest=$(sha256sum "$1" | awk '{print $1}')
  [[ "$digest" == "$EXPECTED_SHA256" ]] || {
    echo "Cloudflare authenticated origin pull CA bytes changed" >&2
    return 1
  }
  openssl x509 -in "$1" -noout >/dev/null
}

if [[ "${1:-}" == "--verify-file" ]]; then
  [[ $# -eq 2 ]] || exit 2
  verify_ca "$2"
  exit
fi
[[ $# -eq 0 ]] || exit 2

ca_file=$(mktemp)
trap 'rm -f "$ca_file"' EXIT
curl -fsSL --proto '=https' --tlsv1.2 "$CA_URL" -o "$ca_file"
verify_ca "$ca_file"
sudo install -m 0644 "$ca_file" /etc/ssl/cf_origin_pull_ca.pem
