# coding: utf-8

# ---------------------------------------------------------------------------------
# 江湖云监控
# ---------------------------------------------------------------------------------
# copyright (c) 2018-∞(https://github.com/jianghujs/jh-monitor) All rights reserved.
# ---------------------------------------------------------------------------------
# Author: midoks <midoks@163.com>
# ---------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------
# 主机管理
# ---------------------------------------------------------------------------------

import time
import os
import sys
from urllib.parse import urlparse
import jh
import re
import json
import shutil
import psutil


from flask import request


from flask import Flask, request, jsonify, Response, send_file
import jh
import time

from config_api import config_api
c_api = config_api()

app = Flask(__name__)

class pub_api:
    CLIENT_SCRIPT_FILES = {
        'install.sh',
        'install/debian.sh',
        'install/report_collector_cron.sh',
        'install/filebeat/install.sh',
        'install/filebeat/config/filebeat.debian.yml',
        'install/filebeat/config/filebeat.pve.yml',
        'install/filebeat/config/inputs.d/host-debian.yml',
        'install/filebeat/config/inputs.d/host-pve.yml',
        'report_collector.py',
        'get_debian_system_status.py',
        'get_pve_system_status.py',
        'get_host_usage.py',
        'get_host_info.py',
        'get_pve_hardware_report.py',
    }

    def _getClientScriptPath(self, relative_path):
        relative_path = str(relative_path or '').strip().lstrip('/')
        if relative_path not in self.CLIENT_SCRIPT_FILES:
            return ''
        script_root = os.path.realpath(os.path.join(os.getcwd(), 'scripts', 'client'))
        script_path = os.path.realpath(os.path.join(script_root, relative_path))
        if not script_path.startswith(script_root + os.sep) or not os.path.isfile(script_path):
            return ''
        return script_path

    def getClientScriptApi(self):
        script_path = self._getClientScriptPath(request.args.get('path', ''))
        if script_path == '':
            return jh.returnJson(False, '客户端脚本不存在'), 404
        return send_file(script_path, mimetype='text/plain')

    def getPubKeyApi(self):
        if os.path.exists('/root/.ssh/id_rsa.pub'):
            return jh.returnJson(True, 'ok', jh.readFile('/root/.ssh/id_rsa.pub'))
        return jh.returnJson(True, 'ok', '')
    
    
    def addHostApi(self):
        host_name = request.form.get('host_name', '10')
        ip = request.form.get('ip', '')
        port = request.form.get('port', '10022')
        host_id = request.form.get('host_id', '').strip()
        if host_id == '':
            host_id = 'H_' + host_name + '_' + jh.getRandomString(4)
        host_group_id = 'default'
        host_group_name = ''

        exist_host = jh.M('host').where('ip=?', (ip,)).field('host_id,ip').find()
        if len(exist_host) > 0:
            return jh.returnJson(False, '主机已经存在!', {'host_id': exist_host.get('host_id', '')})

        exist_host_by_id = jh.M('host').where('host_id=?', (host_id,)).field('host_id').find()
        if len(exist_host_by_id) > 0:
            return jh.returnJson(False, 'host_id 已存在!', {'host_id': host_id})
        
        # 添加主机
        jh.M('host').add("host_id,host_name,host_group_id,host_group_name,ip,ssh_port,addtime", (host_id,host_name,host_group_id,host_group_name,ip,port,time.strftime('%Y-%m-%d %H:%M:%S')))
        # 添加到host文件
        with open('/etc/ansible/hosts', 'r+') as f:
            lines = f.readlines()
            existing_ips = set(line.strip() for line in lines)
            ip_conf = f"{ip} ansible_ssh_user=ansible_user ansible_ssh_port={port}"
            if ip_conf not in existing_ips:
                f.write(f"{ip_conf}\n")

        # 配置新主机的报告计划任务
        try:
            c_api.applyReportScheduleForNewHost(host_id)
        except Exception:
            pass

        return jh.returnJson(True, '主机添加成功!', {'host_id': host_id})
    
    def getHostAddrApi(self):
        return jh.returnJson(True, 'ok', jh.getHostAddr())

    def getMonitorTaskInstallScriptApi(self):
        script_path = os.path.join(os.getcwd(), 'scripts', 'client', 'install', 'monitor_task.sh')
        content = jh.readFile(script_path)
        if content is False:
            return jh.returnJson(False, '安装脚本不存在')
        return Response(content, mimetype='text/x-shellscript')

    def registerMonitorTaskApi(self):
        try:
            from monitor_task_api import monitor_task_api
            api = monitor_task_api()
            task_data = {
                'task_id': request.form.get('task_id', '').strip(),
                'task_name': request.form.get('task_name', '').strip(),
                'host_id': request.form.get('host_id', '').strip(),
                'enabled': request.form.get('enabled', '1').strip(),
                'install_status': 'pending'
            }
            ok, msg, row = api.upsertTaskFromSetup(task_data)
            if not ok:
                return jh.returnJson(False, msg)
            return jh.returnJson(True, '注册成功', row)
        except Exception as e:
            return jh.returnJson(False, '注册失败:' + str(e))

    def updateMonitorTaskInstallStatusApi(self):
        try:
            from monitor_task_api import monitor_task_api
            api = monitor_task_api()
            task_id = request.form.get('task_id', '').strip()
            install_status = request.form.get('install_status', '').strip()
            install_msg = request.form.get('install_msg', '').strip()
            if not task_id:
                return jh.returnJson(False, 'task_id不能为空')
            if not api.getTaskById(task_id):
                return jh.returnJson(False, '监控任务不存在')
            if not api.updateInstallStatus(task_id, install_status, install_msg):
                return jh.returnJson(False, '安装状态更新失败')
            return jh.returnJson(True, '安装状态已更新')
        except Exception as e:
            return jh.returnJson(False, '安装状态更新失败:' + str(e))
