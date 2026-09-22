#!/bin/bash

set -e

PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

ACTION="${1:-install}"
USERNAME="${REPORT_COLLECTOR_USERNAME:-ansible_user}"
RAW_BASE="${MONITOR_RAW_BASE:-https://raw.githubusercontent.com/jianghujs/jh-monitor/master}"
MONITOR_SERVER_URL="${MONITOR_SERVER_URL:-}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
SCRIPT_HOME="/home/${USERNAME}/jh-monitor-scripts"
DATA_HOME="/home/${USERNAME}/jh-monitor-data"
LOG_DIR="/home/${USERNAME}/jh-monitor-logs"
DATA_DIR="${DATA_HOME}"
LOG_FILE="${LOG_DIR}/report-collector.log"
CRON_FILE="/etc/cron.d/jh-monitor-report-collector"
LOCK_FILE="/tmp/jh-monitor-report-collector.lock"
FILES_TO_DEPLOY="report_collector.py get_debian_system_status.py get_pve_system_status.py get_host_usage.py get_host_info.py get_pve_hardware_report.py"
CRON_HELPER_NAME="report_collector_cron.sh"

log() {
  echo "[report-collector] $*"
}

fail() {
  echo "[report-collector] ERROR: $*" >&2
  exit 1
}

ensure_python() {
  if [ -z "$PYTHON_BIN" ]; then
    fail "python3 未安装，无法部署 report collector"
  fi
}

ensure_user() {
  if id "$USERNAME" >/dev/null 2>&1; then
    return 0
  fi
  useradd -m -s /bin/bash "$USERNAME"
}

prepare_dirs() {
  mkdir -p "$SCRIPT_HOME" "$DATA_HOME" "$LOG_DIR"
  touch "$LOG_FILE"
  chown -R "$USERNAME:$USERNAME" "$SCRIPT_HOME" "$DATA_HOME" "$LOG_DIR"
  chmod 755 "$SCRIPT_HOME" "$DATA_HOME" "$LOG_DIR"
  chmod 644 "$LOG_FILE"
}

fetch_or_copy() {
  local name="$1"
  local target_file="${SCRIPT_HOME}/${name}"
  local temp_file="${target_file}.download.$$"
  local header_file="${target_file}.headers.$$"

  log "下载最新脚本: ${name}"
  if [ -n "$MONITOR_SERVER_URL" ] && curl -fsSLG \
      --data-urlencode "path=${name}" \
      "${MONITOR_SERVER_URL%/}/pub/get_client_script" \
      -D "$header_file" \
      -o "$temp_file" && \
      grep -qi '^Content-Type: text/plain' "$header_file" && \
      [ -s "$temp_file" ]; then
    mv -f "$temp_file" "$target_file"
    log "已从云监控服务端获取: ${name}"
  elif wget -O "$temp_file" "${RAW_BASE}/scripts/client/${name}" && [ -s "$temp_file" ]; then
    mv -f "$temp_file" "$target_file"
  else
    rm -f "$temp_file" "$header_file"
    fail "下载 ${name} 失败"
  fi
  rm -f "$temp_file" "$header_file"

  chmod 755 "$target_file"
  chown "$USERNAME:$USERNAME" "$target_file"
}

run_cron_installer() {
  local cron_action="${1:-update}"
  local cron_script="/tmp/${CRON_HELPER_NAME}"
  local temp_file="${cron_script}.download.$$"
  local header_file="${cron_script}.headers.$$"

  log "下载最新定时任务安装脚本: ${CRON_HELPER_NAME}"
  if [ -n "$MONITOR_SERVER_URL" ] && curl -fsSLG \
      --data-urlencode "path=install/${CRON_HELPER_NAME}" \
      "${MONITOR_SERVER_URL%/}/pub/get_client_script" \
      -D "$header_file" \
      -o "$temp_file" && \
      grep -qi '^Content-Type: text/plain' "$header_file" && \
      [ -s "$temp_file" ]; then
    mv -f "$temp_file" "$cron_script"
    log "已从云监控服务端获取: ${CRON_HELPER_NAME}"
  elif wget -O "$temp_file" "${RAW_BASE}/scripts/client/install/${CRON_HELPER_NAME}" && [ -s "$temp_file" ]; then
    mv -f "$temp_file" "$cron_script"
  else
    rm -f "$temp_file" "$header_file"
    fail "下载 ${CRON_HELPER_NAME} 失败"
  fi
  rm -f "$temp_file" "$header_file"

  REPORT_COLLECTOR_USERNAME="$USERNAME" \
  REPORT_COLLECTOR_OUTPUT_DIR="$DATA_DIR" \
  PYTHON_BIN="$PYTHON_BIN" \
  SCRIPT_HOME="$SCRIPT_HOME" \
  DATA_DIR="$DATA_DIR" \
  LOG_DIR="$LOG_DIR" \
  LOG_FILE="$LOG_FILE" \
  CRON_FILE="$CRON_FILE" \
  LOCK_FILE="$LOCK_FILE" \
  bash "$cron_script" "$cron_action"
}

main() {
  case "$ACTION" in
    install|update)
      ensure_python
      ensure_user
      prepare_dirs
      for file_name in $FILES_TO_DEPLOY; do
        fetch_or_copy "$file_name"
      done
      run_cron_installer update
      ;;
    uninstall)
      run_cron_installer uninstall
      ;;
    *)
      fail "不支持的动作: ${ACTION}"
      ;;
  esac
}

main "$@"
