#!/usr/bin/env bash
set -Eeuo pipefail

# Cloudsmith's Caddy stable public key; rotate these values only after issuer review.
EXPECTED_KEY_SHA256=783dfee04b19e851a928cd87b34710213ebbe7628f98d9f34595ab83be578c00
EXPECTED_KEY_FINGERPRINT=65760C51EDEA2017CEA2CA15155B6D79CA56EA34
KEY_URL=https://dl.cloudsmith.io/public/caddy/stable/gpg.155B6D79CA56EA34.key
KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
SOURCE_LIST=/etc/apt/sources.list.d/caddy-stable.list

verify_key() {
  local file="$1" digest identity
  digest=$(sha256sum "$file" | awk '{print $1}')
  [[ "$digest" == "$EXPECTED_KEY_SHA256" ]] || {
    echo "Caddy key bytes do not match reviewed issuer key" >&2
    return 1
  }
  identity=$(gpg --batch --show-keys --with-colons "$file" 2>/dev/null |
    awk -F: '$1=="pub"{count++} $1=="fpr" && first==""{first=$10} END{print count,first}')
  [[ "$identity" == "1 $EXPECTED_KEY_FINGERPRINT" ]] || {
    echo "Caddy key fingerprint does not match reviewed issuer key" >&2
    return 1
  }
}

if [[ "${1:-}" == "--verify-key" ]]; then
  [[ $# -eq 2 ]] || exit 2
  verify_key "$2"
  exit
fi
[[ $# -eq 0 ]] || exit 2

# Disable and retain the prior unsigned source before any package operation.
if sudo test -e /etc/apt/sources.list.d/caddy.list; then
  sudo test ! -e /etc/apt/sources.list.d/caddy.list.disabled || {
    echo "Existing disabled Caddy source needs owner reconciliation" >&2
    exit 1
  }
  sudo mv /etc/apt/sources.list.d/caddy.list /etc/apt/sources.list.d/caddy.list.disabled
fi
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl gnupg

key_file=$(mktemp)
trap 'rm -f "$key_file"' EXIT
curl -fsSL --proto '=https' --tlsv1.2 "$KEY_URL" -o "$key_file"
verify_key "$key_file"
gpg --batch --dearmor < "$key_file" | sudo tee "$KEYRING" >/dev/null
sudo chmod 0644 "$KEYRING"
printf 'deb [signed-by=%s] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main\n' "$KEYRING" |
  sudo tee "$SOURCE_LIST" >/dev/null
sudo chmod 0644 "$SOURCE_LIST"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
