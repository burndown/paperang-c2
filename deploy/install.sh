#!/usr/bin/env bash
# Install the Paperang C2 LAN print server on a Debian / Ubuntu / Raspberry Pi OS machine that has Bluetooth.
#
#   sudo ./deploy/install.sh                     # finds the printer by scanning, installs web UI + AirPrint
#   sudo ./deploy/install.sh --addr AA:BB:CC:DD:EE:FF --paper-mm 101.6
#   sudo ./deploy/install.sh --dry-run           # show what would be done, change nothing
#   sudo ./deploy/install.sh --uninstall
#
# What it does: installs packages (bluez, python3-pil, poppler-utils, fonts-noto-cjk and, for AirPrint,
# cups-ipp-utils + avahi-daemon), marks the printer as trusted in BlueZ, writes /etc/default/paperang-c2,
# and installs two systemd services that run from this directory:
#   paperang-c2   web UI + HTTP API  (default port 8765)
#   paperang-ipp  AirPrint / IPP Everywhere printer "Paperang C2" (port 8631, advertised over mDNS)
# The services have NO authentication: only use them on a network you trust.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ADDR=""; PORT=8765; IPP_PORT=8631; PAPER_MM="101.6"
RUN_USER="${SUDO_USER:-}"; WEB=1; AIRPRINT=1; DRY=0; UNINSTALL=0; ALLOW_HOSTS=()
SCAN_SECONDS=15

usage() { sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then printf '[dry-run] %s\n' "$*"; else "$@"; fi; }

while [ $# -gt 0 ]; do
  case "$1" in
    --addr) ADDR="${2^^}"; shift 2 ;;
    --user) RUN_USER="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --ipp-port) IPP_PORT="$2"; shift 2 ;;
    --paper-mm) PAPER_MM="$2"; shift 2 ;;
    --allow-host) ALLOW_HOSTS+=("$2"); shift 2 ;;
    --no-web) WEB=0; shift ;;
    --no-airprint) AIRPRINT=0; shift ;;
    --dry-run) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 ;;
  esac
done

if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ]; then echo "run with sudo (or use --dry-run)" >&2; exit 1; fi
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = root ]; then RUN_USER="$(logname 2>/dev/null || true)"; fi
if [ -z "$RUN_USER" ] || [ "$RUN_USER" = root ]; then
  echo "pass --user NAME: the services should not run as root" >&2; exit 1
fi
id "$RUN_USER" >/dev/null 2>&1 || { echo "no such user: $RUN_USER" >&2; exit 1; }

if [ "$UNINSTALL" = 1 ]; then
  say "removing services (packages, /etc/default/paperang-c2 and the Bluetooth trust are left alone)"
  for s in paperang-c2 paperang-ipp; do
    run systemctl disable --now "$s" 2>/dev/null || true
    run rm -f "/etc/systemd/system/$s.service"
  done
  run systemctl daemon-reload
  exit 0
fi

command -v apt-get >/dev/null || { echo "this script needs apt (Debian/Ubuntu/Raspberry Pi OS); see docs/DEPLOY.md for other systems" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "python3 >= 3.9 is required" >&2; exit 1; }

say "installing packages"
PKGS=(bluez python3-pil poppler-utils fonts-noto-cjk)
[ "$AIRPRINT" = 1 ] && PKGS+=(cups-ipp-utils avahi-daemon)
run env DEBIAN_FRONTEND=noninteractive apt-get install -y "${PKGS[@]}"
run systemctl enable --now bluetooth

if getent group bluetooth >/dev/null; then run usermod -aG bluetooth "$RUN_USER"; fi

if [ -z "$ADDR" ]; then
  say "looking for a Paperang printer (switch it on, keep it close, close the phone app) ..."
  if [ "$DRY" = 1 ]; then
    ADDR="AA:BB:CC:DD:EE:FF"; echo "[dry-run] would scan for ${SCAN_SECONDS}s; using the placeholder $ADDR"
  else
    mapfile -t FOUND < <(sudo -u "$RUN_USER" env PYTHONPATH="$DIR" python3 -m paperang_c2 scan --seconds "$SCAN_SECONDS" 2>/dev/null || true)
    if [ "${#FOUND[@]}" -eq 0 ]; then
      echo "no Paperang printer found. Wake it up and run again, or pass --addr AA:BB:CC:DD:EE:FF" >&2; exit 1
    fi
    if [ "${#FOUND[@]}" -gt 1 ]; then
      printf 'several printers found, pick one with --addr:\n'; printf '  %s\n' "${FOUND[@]}" >&2; exit 1
    fi
    ADDR="${FOUND[0]%% *}"
    echo "found: ${FOUND[0]}"
  fi
fi
[[ "$ADDR" =~ ^([0-9A-F]{2}:){5}[0-9A-F]{2}$ ]] || { echo "bad Bluetooth address: $ADDR" >&2; exit 1; }

say "trusting $ADDR in BlueZ (pairing is not needed)"
run bluetoothctl trust "$ADDR"

say "writing /etc/default/paperang-c2"
CONF="PAPERANG_ADDR=$ADDR
PAPERANG_PAPER_WIDTH_MM=$PAPER_MM
PAPERANG_CROP=1
"
if [ "$DRY" = 1 ]; then printf '[dry-run] would write:\n%s' "$CONF"; else printf '%s' "$CONF" > /etc/default/paperang-c2; fi

ALLOW_ARGS=""
HOSTN="$(hostname)"
for h in "$HOSTN" "$HOSTN.local" "${ALLOW_HOSTS[@]:-}"; do [ -n "$h" ] && ALLOW_ARGS+=" --allow-host $h"; done
# the address other machines reach us on = the source address of the default route (Docker bridges etc. are ignored)
PRIMARY_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") {print $(i + 1); exit}}')"
[ -n "$PRIMARY_IP" ] || PRIMARY_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[ -n "$PRIMARY_IP" ] && ALLOW_ARGS+=" --allow-host $PRIMARY_IP"

render() {   # render <template> <destination>
  local out
  out="$(sed -e "s|@USER@|$RUN_USER|g" -e "s|@DIR@|$DIR|g" -e "s|@PYTHON@|$(command -v python3)|g" \
             -e "s|@PORT@|$PORT|g" -e "s|@IPP_PORT@|$IPP_PORT|g" -e "s|@IPPEVE@|${IPPEVE:-/usr/sbin/ippeveprinter}|g" \
             -e "s|@ALLOW_HOST_ARGS@|$ALLOW_ARGS|g" "$1")"
  if [ "$DRY" = 1 ]; then printf '[dry-run] %s ->\n%s\n' "$2" "$out"; else printf '%s\n' "$out" > "$2"; fi
}

if [ "$AIRPRINT" = 1 ]; then
  IPPEVE="$(command -v ippeveprinter || true)"; [ -z "$IPPEVE" ] && [ -x /usr/sbin/ippeveprinter ] && IPPEVE=/usr/sbin/ippeveprinter
  [ -n "$IPPEVE" ] || [ "$DRY" = 1 ] || { echo "ippeveprinter not found (package cups-ipp-utils)" >&2; exit 1; }
  chmod +x "$DIR/deploy/paperang-ipp.sh"
fi

say "installing systemd services (running as $RUN_USER, from $DIR)"
[ "$WEB" = 1 ] && render "$DIR/deploy/paperang-c2.service.in" /etc/systemd/system/paperang-c2.service
[ "$AIRPRINT" = 1 ] && render "$DIR/deploy/paperang-ipp.service.in" /etc/systemd/system/paperang-ipp.service
run systemctl daemon-reload
[ "$WEB" = 1 ] && run systemctl enable --now paperang-c2
[ "$AIRPRINT" = 1 ] && run systemctl enable --now paperang-ipp
[ "$WEB" = 1 ] && run systemctl restart paperang-c2
[ "$AIRPRINT" = 1 ] && run systemctl restart paperang-ipp

if [ "$DRY" = 0 ]; then
  say "checking the printer (this connects over Bluetooth for a few seconds)"
  sleep 3
  if sudo -u "$RUN_USER" env PYTHONPATH="$DIR" PAPERANG_ADDR="$ADDR" python3 -m paperang_c2 info; then
    echo "printer reachable."
  else
    echo "could not talk to the printer yet. Is it on, close by, and not connected to a phone? See docs/DEPLOY.md" >&2
  fi
  IP="$PRIMARY_IP"
  say "done"
  [ "$WEB" = 1 ] && echo "  web UI : http://${IP:-$HOSTN}:$PORT/   (also http://$HOSTN.local:$PORT/)"
  [ "$AIRPRINT" = 1 ] && echo "  AirPrint: printer \"Paperang C2\" (iPhone: share > Print > Select Printer; make images portrait, paper A4)"
  echo "  logs   : journalctl -u paperang-c2 -u paperang-ipp -f"
  echo "  note   : no authentication, use only on a trusted network"
fi
