# 安装filebeat
DEFAULT_RAW_BASE="https://raw.githubusercontent.com/jianghujs/jh-monitor/master"
CN_RAW_BASE="https://gitee.com/jianghujs/jh-monitor/raw/master"
RAW_BASE="$DEFAULT_RAW_BASE"
MONITOR_SERVER_URL="${MONITOR_SERVER_URL:-}"
if [ "$1" == "cn" ]; then
  RAW_BASE="$CN_RAW_BASE"
fi
USERNAME="${REPORT_COLLECTOR_USERNAME:-ansible_user}"
DATA_DIR="${DATA_DIR:-/home/${USERNAME}/jh-monitor-data}"
HOST_ID_FILE="${JH_MONITOR_HOST_ID_FILE:-${DATA_DIR}/host_id}"

_SEP_LONG='========================================'
_SEP_SHORT='----------------------------------------'
_ICON_OK='☑️'
_ICON_FAIL='❌'

_log() { echo "[filebeat-install] $*"; }
_log_sep() { _log "$_SEP_LONG"; }
_log_sep_short() { _log "$_SEP_SHORT"; }
_log_start() { _log "$_ICON_OK $*"; }
_log_done() { _log "$_ICON_OK $*"; }
_log_fail() { _log "$_ICON_FAIL $*"; }
_log_step() { _log "|- $*"; }
_log_detail() { _log "|--- $*"; }

resolve_host_id() {
  if [ -n "$JH_MONITOR_HOST_ID" ]; then
    printf "%s" "$JH_MONITOR_HOST_ID"
    return 0
  fi

  if [ -s "$HOST_ID_FILE" ]; then
    tr -d '\r\n[:space:]' < "$HOST_ID_FILE"
    return 0
  fi

  if [ -s /etc/machine-id ]; then
    tr -d '\r\n[:space:]' < /etc/machine-id
    return 0
  fi

  hostname
  return 0
}

normalize_host_id_for_index() {
  local raw="$1"
  local normalized
  normalized="$(printf "%s" "$raw" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g')"
  if [ -z "$normalized" ]; then
    normalized="host"
  fi
  printf "%s" "$normalized"
}

build_filebeat_endpoint() {
  local raw_endpoints="$1"
  local mode="$2"

  python3 - "$raw_endpoints" "$mode" <<'PY_ENDPOINT'
import re
import sys
from urllib.parse import urlparse

raw_endpoints, mode = sys.argv[1], sys.argv[2]
endpoints = []

for item in re.split(r'[\n,]+', raw_endpoints):
    endpoint = item.strip()
    if not endpoint:
        continue
    if '://' not in endpoint:
        endpoint = 'http://' + endpoint
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        continue

    scheme = parsed.scheme or 'http'
    default_port = 443 if scheme == 'https' else 9200
    host = parsed.hostname
    if ':' in host:
        host = '[' + host + ']'
    endpoints.append('{0}://{1}:{2}'.format(scheme, host, parsed.port or default_port))

if not endpoints:
    raise SystemExit(1)

if mode == 'kibana':
    endpoint = urlparse(endpoints[0])
    host = endpoint.hostname
    if ':' in host:
        host = '[' + host + ']'
    print('{0}://{1}:5601'.format(endpoint.scheme, host))
else:
    print(', '.join('"{0}"'.format(endpoint) for endpoint in endpoints))
PY_ENDPOINT
}

resolve_filebeat_endpoints() {
  local raw_endpoints="${JH_MONITOR_ES_ADDR:-${SERVER_IP:-}}"
  if [ -z "$raw_endpoints" ]; then
    read -p "请输入ELK服务端地址: " raw_endpoints
  fi
  if [ -z "$raw_endpoints" ]; then
    _log_fail "未指定ELK服务端地址"
    exit 1
  fi

  FILEBEAT_ES_ENDPOINTS="$(build_filebeat_endpoint "$raw_endpoints" elasticsearch)" || {
    _log_fail "ELK服务端地址格式不正确" address="$raw_endpoints"
    exit 1
  }
  FILEBEAT_KIBANA_ENDPOINT="$(build_filebeat_endpoint "$raw_endpoints" kibana)" || {
    _log_fail "Kibana服务端地址生成失败" address="$raw_endpoints"
    exit 1
  }
  _log_detail "已解析ELK服务端地址" elasticsearch="$FILEBEAT_ES_ENDPOINTS" kibana="$FILEBEAT_KIBANA_ENDPOINT"
}

escape_sed_replacement() {
  printf "%s" "$1" | sed -e 's/[\/&]/\\&/g'
}

download_config_file() {
  local relative_path="$1"
  local fallback_url="$2"
  local target_file="$3"
  local temp_file="${target_file}.download.$$"
  local header_file="${target_file}.headers.$$"

  if [ -n "$MONITOR_SERVER_URL" ] && curl -fsSLG \
      --data-urlencode "path=${relative_path}" \
      "${MONITOR_SERVER_URL%/}/pub/get_client_script" \
      -D "$header_file" \
      -o "$temp_file" && \
      grep -qi '^Content-Type: text/plain' "$header_file" && \
      [ -s "$temp_file" ]; then
    mv -f "$temp_file" "$target_file"
    _log_detail "已从云监控服务端获取配置" path="$relative_path"
  elif wget -O "$temp_file" "$fallback_url" && [ -s "$temp_file" ]; then
    mv -f "$temp_file" "$target_file"
  else
    rm -f "$temp_file" "$header_file"
    return 1
  fi
  rm -f "$temp_file" "$header_file"
}

_log_sep
_log_start "开始安装 filebeat" version="8.11.3"

# wget -O /tmp/filebeat.deb "${RAW_BASE}/scripts/client/install/filebeat/filebeat.deb" && dpkg -i /tmp/filebeat.deb
FILEBEAT_VERSION="8.11.3"
FILEBEAT_DEB="filebeat-${FILEBEAT_VERSION}-amd64.deb"
FILEBEAT_URL="https://artifacts.elastic.co/downloads/beats/filebeat/${FILEBEAT_DEB}"
if [ "$1" == "cn" ]; then
  FILEBEAT_URL="https://mirrors.huaweicloud.com/filebeat/${FILEBEAT_VERSION}/${FILEBEAT_DEB}"
fi

INSTALLED_FILEBEAT_VERSION="$(dpkg-query -W -f='${Version}' filebeat 2>/dev/null || true)"
if echo "$INSTALLED_FILEBEAT_VERSION" | grep -q "^${FILEBEAT_VERSION}"; then
  _log_step "filebeat 已安装，跳过" version="$INSTALLED_FILEBEAT_VERSION"
else
  _log_step "下载并安装 filebeat deb" url="$FILEBEAT_URL"
  wget -O /tmp/filebeat.deb "${FILEBEAT_URL}" && dpkg -i /tmp/filebeat.deb
fi

# 配置filebeat
config_type="debian"
if [ -d /etc/pve ]; then
  config_type="pve"
fi

_log_step "下载主配置" type="$config_type" file="filebeat.${config_type}.yml"
download_config_file \
  "install/filebeat/config/filebeat.${config_type}.yml" \
  "${RAW_BASE}/scripts/client/install/filebeat/config/filebeat.${config_type}.yml" \
  /tmp/filebeat.yml
if [ ! -s /tmp/filebeat.yml ]; then
  _log_fail "下载主配置失败" type="$config_type"
  exit 1
fi
mv /tmp/filebeat.yml /etc/filebeat/filebeat.yml
chmod 644 /etc/filebeat/filebeat.yml
_log_detail "主配置已写入" path="/etc/filebeat/filebeat.yml"

resolve_filebeat_endpoints
_log_step "替换配置占位符" elasticsearch="$FILEBEAT_ES_ENDPOINTS" kibana="$FILEBEAT_KIBANA_ENDPOINT"
ESCAPED_ES_ENDPOINTS="$(escape_sed_replacement "$FILEBEAT_ES_ENDPOINTS")"
ESCAPED_KIBANA_ENDPOINT="$(escape_sed_replacement "$FILEBEAT_KIBANA_ENDPOINT")"
sed -i "s/<esEndpoints>/$ESCAPED_ES_ENDPOINTS/g" /etc/filebeat/filebeat.yml
sed -i "s/<kibanaEndpoint>/$ESCAPED_KIBANA_ENDPOINT/g" /etc/filebeat/filebeat.yml

# 兼容尚未更新的旧模板；旧模板只有 <serverIp> 占位符。
FIRST_ES_HOST="${FILEBEAT_ES_ENDPOINTS%%,*}"
FIRST_ES_HOST="${FIRST_ES_HOST#\"}"
FIRST_ES_HOST="${FIRST_ES_HOST%\"}"
FIRST_ES_HOST="${FIRST_ES_HOST#*://}"
ESCAPED_FIRST_ES_HOST="$(escape_sed_replacement "$FIRST_ES_HOST")"
sed -i "s/<serverIp>/$ESCAPED_FIRST_ES_HOST/g" /etc/filebeat/filebeat.yml

HOST_ID="$(resolve_host_id)"
if [ -n "$HOST_ID" ]; then
  HOST_ID_INDEX="$(normalize_host_id_for_index "$HOST_ID")"
  ESCAPED_HOST_ID="$(escape_sed_replacement "$HOST_ID")"
  ESCAPED_HOST_ID_INDEX="$(escape_sed_replacement "$HOST_ID_INDEX")"
  sed -i "s/<hostId>/$ESCAPED_HOST_ID/g" /etc/filebeat/filebeat.yml
  sed -i "s/<hostIdIndex>/$ESCAPED_HOST_ID_INDEX/g" /etc/filebeat/filebeat.yml
  _log_detail "已写入 host_id" hostId="$HOST_ID" hostIdIndex="$HOST_ID_INDEX"
else
  _log_detail "未获取到 host_id，配置将保留占位符"
fi


# 下载主机 inputs 配置到 /etc/filebeat/inputs.d/
INPUTS_DIR="/etc/filebeat/inputs.d"
mkdir -p "$INPUTS_DIR"
HOST_INPUT_FILE="${INPUTS_DIR}/host-${config_type}.yml"
_log_step "下载主机 inputs 配置" type="$config_type" file="host-${config_type}.yml"
download_config_file \
  "install/filebeat/config/inputs.d/host-${config_type}.yml" \
  "${RAW_BASE}/scripts/client/install/filebeat/config/inputs.d/host-${config_type}.yml" \
  /tmp/host-inputs.yml
if [ ! -s /tmp/host-inputs.yml ]; then
  _log_fail "下载主机 inputs 配置失败" type="$config_type"
  exit 1
fi
mv /tmp/host-inputs.yml "$HOST_INPUT_FILE"
chmod 644 "$HOST_INPUT_FILE"
if [ -n "$HOST_ID" ]; then
  sed -i "s/<hostId>/$ESCAPED_HOST_ID/g" "$HOST_INPUT_FILE"
  _log_detail "已写入 host inputs host_id" hostId="$HOST_ID"
fi
_log_detail "主机 inputs 配置完成" path="$HOST_INPUT_FILE"

validate_filebeat_config() {
  _log_step "校验 filebeat 配置"
  if command -v filebeat >/dev/null 2>&1; then
    _log_detail "执行 filebeat test config"
    filebeat test config -c /etc/filebeat/filebeat.yml >/tmp/filebeat_test.log 2>&1 || {
      cat /tmp/filebeat_test.log
      _log_fail "filebeat 配置校验失败"
      exit 1
    }
    _log_detail "配置校验通过"
  else
    _log_detail "未找到 filebeat 命令，跳过校验"
  fi
}

validate_filebeat_config

run_filebeat_setup() {
  local setup_log_file="/tmp/filebeat_setup.log"
  if ! command -v filebeat >/dev/null 2>&1; then
    _log_step "未找到 filebeat 命令，跳过 setup"
    return 0
  fi

  _log_step "执行 filebeat setup" log="$setup_log_file"
  : > "${setup_log_file}"
  if ! filebeat setup -e >"${setup_log_file}" 2>&1; then
    cat "${setup_log_file}"
    _log_fail "filebeat setup 失败" log="$setup_log_file"
    return 1
  fi
  _log_detail "filebeat setup 完成"
}

if ! run_filebeat_setup; then
  _log_step "filebeat setup 未完成，继续重启采集服务" log="/tmp/filebeat_setup.log"
fi

_log_step "启动 filebeat 服务"
service filebeat restart
systemctl enable filebeat

_log_done "filebeat 配置完成"
_log_sep
