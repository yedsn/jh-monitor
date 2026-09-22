#!/bin/bash

# 安装脚本：bash /www/server/jh-monitor/scripts/client/install.sh install http://192.168.7.73:10844 [cn]

PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

USERNAME="ansible_user"
SSH_DIR="/home/$USERNAME/.ssh"
AUTHORIZED_KEYS="$SSH_DIR/authorized_keys"
DATA_DIR="/home/$USERNAME/jh-monitor-data"
HOST_ID_FILE="${DATA_DIR}/host_id"
DEFAULT_RAW_BASE="https://raw.githubusercontent.com/jianghujs/jh-monitor/master"
CN_RAW_BASE="https://gitee.com/jianghujs/jh-monitor/raw/master"

prompt()
{
  tip=$1
  local _resultvar=$2
  local default_choice=$3
  echo -ne "\033[1;32m?\033[0m \033[1m${tip}\033[0m"
  read choice
  choice=${choice:-$default_choice}
  eval $_resultvar="'$choice'"
}

show_error()
{
  tip=$1
  echo -e "\033[1;31m× ${tip}\033[0m"
}

check_command_exist() {
    command -v "$@" >/dev/null 2>&1
}

confirm_action() {
    local current_action="$1"
    local current_url="$2"


    echo "-----------------------"
    echo "即将执行江湖云监控客户端配置，包含内容如下："
    echo "1. 创建或复用 ${USERNAME} 用户"
    echo "2. 配置 ${USERNAME} 的目录与权限"
    echo "3. 初始化 Python 运行环境"
    echo "4. 配置服务端 SSH 公钥访问"
    echo "5. 通知服务端添加当前主机并保存 host_id"
    echo "6. 安装或更新数据收集定时任务"
    echo "7. 为 PVE 主机安装传感器依赖"
    echo "8. 配置数据收集定时任务"
    echo "9. 配置 filebeat"
    echo "-----------------------"
    echo "云监控地址: ${current_url:-未提供}"
    echo "当前操作: ${current_action}"
    echo "-----------------------"
    prompt "确认执行吗？（默认y）[y/n]: " confirm_choice "y"
    if [ "$confirm_choice" != "y" ]; then
        echo "已取消执行"
        exit 0
    fi
}

install_pve_sensor_tools() {
    if [ ! -d /etc/pve ]; then
        echo "未检测到 PVE 环境，跳过传感器依赖安装。"
        return 0
    fi

    echo "检测到 PVE 环境，开始安装传感器依赖（lm-sensors、ipmitool）..."

    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq
        apt-get install -y lm-sensors ipmitool
        sensors-detect --auto >/dev/null 2>&1 || true
        modprobe ipmi_devintf >/dev/null 2>&1 || true
        modprobe ipmi_si >/dev/null 2>&1 || true
        echo "PVE 传感器依赖安装完成。"
        return 0
    fi

    if command -v dnf >/dev/null 2>&1; then
        dnf install -y lm_sensors ipmitool
        sensors-detect --auto >/dev/null 2>&1 || true
        modprobe ipmi_devintf >/dev/null 2>&1 || true
        modprobe ipmi_si >/dev/null 2>&1 || true
        echo "PVE 传感器依赖安装完成。"
        return 0
    fi

    if command -v yum >/dev/null 2>&1; then
        yum install -y lm_sensors ipmitool
        sensors-detect --auto >/dev/null 2>&1 || true
        modprobe ipmi_devintf >/dev/null 2>&1 || true
        modprobe ipmi_si >/dev/null 2>&1 || true
        echo "PVE 传感器依赖安装完成。"
        return 0
    fi

    echo "未找到可用包管理器，跳过 PVE 传感器依赖安装。"
    return 0
}

add_ansible_user(){
    if id "$USERNAME" &>/dev/null; then
        echo "用户 $USERNAME 已经存在。"
    else
        useradd -m -s /bin/bash "$USERNAME"
        echo "用户 $USERNAME 创建成功。"
    fi
}

config_ansible_user() {
    if ! command -v sudo >/dev/null 2>&1; then
        if command -v apt >/dev/null 2>&1; then
            echo "未检测到 sudo，开始安装..."
            apt update && apt install sudo -y
            echo "已安装 sudo"
        else
            echo "未检测到 sudo，且无 apt，跳过安装"
        fi
    fi
    echo "开始配置 $USERNAME 权限..."
    # 创建脚本执行目录
    mkdir -p /home/${USERNAME}/jh-monitor-scripts/
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/jh-monitor-scripts/
    echo "已配置脚本目录权限: /home/${USERNAME}/jh-monitor-scripts/"
    # 默认日志输出目录（避免写系统目录）
    mkdir -p /home/${USERNAME}/jh-monitor-logs/
    chown -R ${USERNAME}:${USERNAME} /home/${USERNAME}/jh-monitor-logs/
    echo "已配置日志目录权限: /home/${USERNAME}/jh-monitor-logs/"
    
    # 日志目录读写权限
    mkdir -p /www/server/log
    if command -v setfacl >/dev/null 2>&1; then
        setfacl -m u:${USERNAME}:rwX /www/server/log
        setfacl -d -m u:${USERNAME}:rwX /www/server/log
        echo "已设置 /www/server/log ACL 读写权限"
    else
        chown -R ${USERNAME}:${USERNAME} /www/server/log
        echo "已设置 /www/server/log 目录归属为 $USERNAME"
    fi

    # 面板目录读取权限
    if [ -d /www/server/jh-panel ]; then
        if command -v setfacl >/dev/null 2>&1; then
            setfacl -m u:${USERNAME}:rx /www/server/jh-panel
            setfacl -R -m u:${USERNAME}:rX /www/server/jh-panel/class /www/server/jh-panel/data /www/server/jh-panel/logs 2>/dev/null
            setfacl -d -m u:${USERNAME}:rX /www/server/jh-panel/data /www/server/jh-panel/logs 2>/dev/null
            echo "已设置 /www/server/jh-panel 相关目录 ACL 读取权限"
        else
            echo "未找到 setfacl，跳过 /www/server/jh-panel ACL 配置"
        fi
    else
        echo "未找到 /www/server/jh-panel，跳过面板目录权限配置"
    fi

    # 报告日志写入权限
    touch /var/log/jhpanel_report.log
    if command -v setfacl >/dev/null 2>&1; then
        setfacl -m u:${USERNAME}:rw /var/log/jhpanel_report.log
        echo "已设置 /var/log/jhpanel_report.log ACL 读写权限"
    else
        chown ${USERNAME}:${USERNAME} /var/log/jhpanel_report.log
        echo "已设置 /var/log/jhpanel_report.log 归属为 $USERNAME"
    fi

    # 只读命令 sudo 权限
    mkdir -p /etc/sudoers.d/
    rm -f /etc/sudoers.d/ansible_user
    cat > /etc/sudoers.d/ansible_user <<EOF
Cmnd_Alias JH_MONITOR_READ = /sbin/iptables -L, /sbin/iptables -L *, /usr/sbin/iptables -L, /usr/sbin/iptables -L *, /usr/sbin/smartctl --scan, /usr/sbin/smartctl -a /dev/*, /usr/bin/smartctl --scan, /usr/bin/smartctl -a /dev/*, /usr/bin/sensors, /usr/bin/sensors *, /usr/bin/ipmitool sensor, /usr/bin/ipmitool chassis status
${USERNAME} ALL=(ALL) NOPASSWD: JH_MONITOR_READ
EOF
    chmod 0440 /etc/sudoers.d/ansible_user
    if command -v visudo >/dev/null 2>&1; then
        if ! visudo -cf /etc/sudoers.d/ansible_user >/dev/null 2>&1; then
            rm -f /etc/sudoers.d/ansible_user
            show_error "sudoers 校验失败，已移除 /etc/sudoers.d/ansible_user"
            exit 1
        fi
    fi
    echo "已配置只读命令 sudo 权限"
    
}

config_run_env() {
    echo "开始下载最新 Python 环境初始化脚本..."
    if ! wget -O /tmp/install_ensure_run_env.sh "${RAW_BASE}/scripts/client/install/ensure_run_env.sh"; then
        show_error "下载 Python 环境初始化脚本失败"
        exit 1
    fi
    if ! bash /tmp/install_ensure_run_env.sh "$net_env_cn"; then
        show_error "Python 环境初始化失败"
        exit 1
    fi
}

add_server_ssh_cert(){
    if [ ! -d "$SSH_DIR" ]; then
        mkdir -p "$SSH_DIR"
        echo ".ssh 目录创建成功。"
    fi

    chown "$USERNAME:$USERNAME" "$SSH_DIR"
    chmod 700 "$SSH_DIR"

    echo "正在从服务端 $monitor_url/pub/get_pub_key 获取公钥..."

    PUBLIC_KEY_DATA=$(curl -s "$monitor_url/pub/get_pub_key")
    echo $PUBLIC_KEY_DATA

    PUBLIC_KEY_DATA_STATUS=$(echo $PUBLIC_KEY_DATA | awk -F 'status":' '{print $2}' | awk -F ',' '{print $1}'  | sed 's/ //g')
    if [ "$PUBLIC_KEY_DATA_STATUS" == "true" ]; then
        PUBLIC_KEY=$(echo $PUBLIC_KEY_DATA | awk -F 'data":' '{print $2}' | awk -F '"' '{print $2}')
        
        if ! grep -Fxq "$PUBLIC_KEY" $AUTHORIZED_KEYS; then
          echo $PUBLIC_KEY >> $AUTHORIZED_KEYS
          chown "$USERNAME:$USERNAME" "$AUTHORIZED_KEYS"
          chmod 600 "$AUTHORIZED_KEYS"
          echo "公钥添加成功。"
        fi

    else
        echo "获取公钥失败"
        exit 1
    fi
}

resolve_monitor_server_env() {
    if [ -n "$SERVER_IP" ]; then
        export SERVER_IP
        export SERVER_PORT
        return 0
    fi

    if [ -n "$monitor_url" ]; then
        SERVER_IP=$(echo "${monitor_url}" | cut -d'/' -f3 | cut -d':' -f1)
        SERVER_PORT=$(echo "${monitor_url}" | awk -F ":" '{print $3}')
        export SERVER_IP
        export SERVER_PORT
        echo "已从云监控地址解析ELK服务端: ${SERVER_IP}${SERVER_PORT:+:${SERVER_PORT}}"
    fi
}


config_filebeat() {
    resolve_monitor_server_env
    export JH_MONITOR_HOST_ID_FILE="$HOST_ID_FILE"
    export MONITOR_SERVER_URL="$monitor_url"
    local monitor_installer="/tmp/install_filebeat.monitor.$$"
    local monitor_headers="/tmp/install_filebeat.headers.$$"
    echo "开始下载最新 filebeat 安装脚本..."
    if [ -n "$monitor_url" ] && curl -fsSLG \
        --data-urlencode "path=install/filebeat/install.sh" \
        "${monitor_url%/}/pub/get_client_script" \
        -D "$monitor_headers" \
        -o "$monitor_installer" && \
        grep -qi '^Content-Type: text/plain' "$monitor_headers" && \
        [ -s "$monitor_installer" ]; then
        mv -f "$monitor_installer" /tmp/install_filebeat.sh
        echo "已从云监控服务端获取 filebeat 安装脚本。"
    elif ! wget -O /tmp/install_filebeat.sh "${RAW_BASE}/scripts/client/install/filebeat/install.sh"; then
        rm -f "$monitor_installer" "$monitor_headers"
        return 1
    fi
    rm -f "$monitor_installer" "$monitor_headers"

    if [ -s /tmp/install_filebeat.sh ]; then
        MONITOR_SERVER_URL="$monitor_url" bash /tmp/install_filebeat.sh "$net_env_cn"
        return $?
    fi
    return 1
}

read_json_value() {
    local json_text="$1"
    local field_path="$2"
    python3 -c '
import json
import sys

field_path = sys.argv[1].split(".")
raw = sys.argv[2].strip()
if not raw:
    sys.exit(0)

try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

current = data
for key in field_path:
    if isinstance(current, dict):
        current = current.get(key, "")
    else:
        current = ""
        break

if current is None:
    current = ""
print(str(current))
' "$field_path" "$json_text"
}

persist_client_host_id() {
    local host_id="$1"
    if [ -z "$host_id" ]; then
        return 1
    fi

    mkdir -p "$DATA_DIR"
    printf "%s" "$host_id" > "$HOST_ID_FILE"
    chown "${USERNAME}:${USERNAME}" "$HOST_ID_FILE" 2>/dev/null || true
    chmod 644 "$HOST_ID_FILE"
    export JH_MONITOR_HOST_ID="$host_id"
    export JH_MONITOR_HOST_ID_FILE="$HOST_ID_FILE"
    echo "已保存当前主机 host_id: $host_id -> $HOST_ID_FILE"
    return 0
}

install_report_collector() {
    export REPORT_COLLECTOR_USERNAME="$USERNAME"
    export MONITOR_RAW_BASE="$RAW_BASE"
    export MONITOR_SERVER_URL="$monitor_url"
    local monitor_installer="/tmp/install_report_collector.monitor.$$"
    local monitor_headers="/tmp/install_report_collector.headers.$$"

    echo "开始下载最新 report collector 安装脚本..."
    if [ -n "$monitor_url" ] && curl -fsSLG \
        --data-urlencode "path=install/debian.sh" \
        "${monitor_url%/}/pub/get_client_script" \
        -D "$monitor_headers" \
        -o "$monitor_installer" && \
        grep -qi '^Content-Type: text/plain' "$monitor_headers" && \
        [ -s "$monitor_installer" ]; then
        mv -f "$monitor_installer" /tmp/install_report_collector.sh
        echo "已从云监控服务端获取 report collector 安装脚本。"
    elif ! wget -O /tmp/install_report_collector.sh "${RAW_BASE}/scripts/client/install/debian.sh"; then
        rm -f "$monitor_installer" "$monitor_headers"
        return 1
    fi
    rm -f "$monitor_installer" "$monitor_headers"

    if [ -s /tmp/install_report_collector.sh ]; then
        REPORT_COLLECTOR_USERNAME="$USERNAME" \
        MONITOR_RAW_BASE="$RAW_BASE" \
        MONITOR_SERVER_URL="$monitor_url" \
        bash /tmp/install_report_collector.sh update
        return $?
    fi
    return 1
}

notify_server_add_host(){
    
    default_client_ip=$(hostname -I | awk '{print $1}')
    prompt "请输入服务端连接到当前机器的IP（默认为：${default_client_ip}）：" client_ip $default_client_ip
    if [ -z "$client_ip" ]; then
      show_error "错误:未指定本地IP地址"
      exit 1
    fi

    sys_default_ssh_port=22
    default_client_ssh_port=$(grep -E "^Port [0-9]+" /etc/ssh/sshd_config | awk '{print $2}')
    if [ -z "$default_client_ssh_port" ]; then
        default_client_ssh_port=$sys_default_ssh_port
    fi
    prompt "请输入服务端连接到当前机器的SSH端口（默认为：${default_client_ssh_port}）：" client_ssh_port $default_client_ssh_port
    if [ -z "$client_ssh_port" ]; then
      show_error "错误:未指定本地SSH端口"
      exit 1
    fi

    # 获取客户端名称
    default_client_name=$(hostname -s)
    prompt "请输入客户端名称（默认为：${default_client_name}）：" client_name $default_client_name
    if [ -z "$client_name" ]; then
      show_error "错误:未指定客户端名称"
      exit 1
    fi

    local existing_host_id=""
    if [ -s "$HOST_ID_FILE" ]; then
        existing_host_id=$(tr -d '\r\n[:space:]' < "$HOST_ID_FILE")
        if [ -n "$existing_host_id" ]; then
            echo "检测到本地已保存 host_id: $existing_host_id"
        fi
    fi

    echo "开始请求服务端添加主机..."
    add_res=$(curl -s -X POST "$monitor_url/pub/add_host" \
        -d "host_name=$client_name" \
        -d "ip=$client_ip" \
        -d "port=$client_ssh_port" \
        -d "host_id=$existing_host_id")
    echo $add_res

    local add_res_status
    local add_res_host_id
    local add_res_msg
    add_res_status=$(read_json_value "$add_res" "status")
    add_res_host_id=$(read_json_value "$add_res" "data.host_id")
    add_res_msg=$(read_json_value "$add_res" "msg")
    echo "add_host 返回: status=${add_res_status}, msg=${add_res_msg}, host_id=${add_res_host_id}"

    if [ "$add_res_status" = "True" ] || [ "$add_res_status" = "true" ]; then
        persist_client_host_id "$add_res_host_id"
        echo "添加主机成功"
        return 0
    fi

    if echo "${add_res_msg}" | grep -q "主机已经存在"; then
        if [ -n "$add_res_host_id" ]; then
            persist_client_host_id "$add_res_host_id"
            echo "主机已存在，复用服务端返回的 host_id: $add_res_host_id"
        elif [ -n "$existing_host_id" ]; then
            persist_client_host_id "$existing_host_id"
            echo "主机已存在，复用本地已有 host_id: $existing_host_id"
        else
            echo "主机已存在，但服务端未返回 host_id，本地也没有旧 host_id，继续执行后续安装流程"
        fi
        echo "主机已存在，继续执行后续安装/更新流程"
        return 0
    fi

    echo -e "添加主机失败，${add_res_msg:-未知错误}"
    exit 1
}

action="${1}"
monitor_url="${2}"
net_env_cn="${3}"
RAW_BASE="$DEFAULT_RAW_BASE"
if [ "$net_env_cn" == "cn" ]; then
  RAW_BASE="$CN_RAW_BASE"
fi

if [ "$action" == "uninstall" ]; then
    confirm_action "$action" "$monitor_url"
    echo "卸载逻辑待实现"
elif [ "$action" == "install" ]; then
    confirm_action "$action" "$monitor_url"
    resolve_monitor_server_env

    # 添加ansible用户
    add_ansible_user

    # 配置ansible用户权限
    config_ansible_user

    # 配置客户端python环境
    config_run_env

    # 配置服务端访问权限
    add_server_ssh_cert

    # 通知服务端添加主机
    notify_server_add_host

    # 为 PVE 主机安装传感器依赖
    install_pve_sensor_tools

    # 安装或更新日报采集脚本与 cron
    install_report_collector

    # 配置filebeat
    config_filebeat
elif [ "$action" == "update" ]; then
    confirm_action "$action" "$monitor_url"
    resolve_monitor_server_env

    # 为 PVE 主机安装传感器依赖
    install_pve_sensor_tools

    # 更新日报采集脚本与 cron
    install_report_collector

    # 更新 filebeat 配置
    config_filebeat
elif [ "$action" == "set_user_permission" ]; then
    confirm_action "$action" "$monitor_url"
    # 仅初始化ansible_user权限相关设置
    add_ansible_user
    config_ansible_user
fi
