#!/system/bin/sh

MODDIR="${0%/*}"
LOG="$MODDIR/load.log"

log() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

if [ -e /dev/vhci ]; then
  log "hci_vhci already available"
  exit 0
fi

for _ in $(seq 1 120); do
  if [ -d /sys/module/bluetooth ]; then
    if insmod "$MODDIR/hci_vhci.ko"; then
      log "hci_vhci loaded"
      exit 0
    fi
    log "hci_vhci load failed"
    exit 1
  fi
  sleep 1
done

log "bluetooth core not ready; hci_vhci not loaded"
exit 1
