# coding: utf-8

# ---------------------------------------------------------------------------------
# 江湖云监控
# ---------------------------------------------------------------------------------
# copyright (c) 2018-∞(https://github.com/jianghujs/jh-monitor) All rights reserved.
# ---------------------------------------------------------------------------------
# Author: midoks <midoks@163.com>
# ---------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------
# 配置操作
# ---------------------------------------------------------------------------------

import psutil
import time
import os
import sys
import jh
import re
import json
import pwd
import tempfile

from flask import session
from flask import request

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

    
from host_api import host_api
h_api = host_api()
sys.path.append(os.getcwd() + "/class/es/service")
import host_status_service as host_status_service_utils


class config_api:

    __version = '1.1.12'
    __api_addr = 'data/api.json'
    __report_config_addr = 'data/report_config.json'
    __es_config_addr = 'data/es.json'

    def __init__(self):
        pass

    def getVersion(self):
        return self.__version

    def _getDefaultEsConfig(self):
        return {
            'addr': 'http://127.0.0.1:9200',
            'username': 'elastic',
            'password': 'changeme',
            'hosts': [
                {'host': '127.0.0.1', 'port': 9200, 'scheme': 'http'}
            ]
        }

    def _getDefaultReportConfig(self):
        return {
            'cpu': 80,
            'memory': 80,
            'disk': 80,
            'ssl_cert': 14,
            'ha_enabled': True
        }

    def _getDefaultReportCron(self):
        return {
            'type': 'day',
            'where1': '',
            'hour': 0,
            'minute': 0,
            'week': ''
        }

    def getDefaultReportCronData(self):
        return dict(self._getDefaultReportCron())

    def _getDefaultReportScheduleConfig(self):
        return {
            'enabled': False,
            'report_host_ids': [],
            'cron': self._getDefaultReportCron()
        }

    def _ensureJsonConfigFile(self, path):
        config_dir = os.path.dirname(path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir)
        if not os.path.exists(path):
            self._writeJsonConfig(path, {})
        return True

    def _readJsonConfig(self, path):
        self._ensureJsonConfigFile(path)
        try:
            content = jh.readFile(path)
            if not content:
                return {}
            return json.loads(content)
        except Exception:
            self._writeJsonConfig(path, {})
            return {}

    def _writeJsonConfig(self, path, data):
        config_dir = os.path.dirname(path) or '.'
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

        fd, temp_path = tempfile.mkstemp(prefix='.tmp_', dir=config_dir)
        try:
            with os.fdopen(fd, 'w') as fp:
                fp.write(json.dumps(data))
                fp.flush()
                os.fsync(fp.fileno())
            os.chmod(temp_path, 384)
            os.replace(temp_path, path)
            os.chmod(path, 384)
            return True
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _validateThresholdField(self, field_name, raw_value, min_value, max_value):
        value = str(raw_value).strip()
        if value == '':
            return False, field_name + '不能为空!', None
        if not re.match(r'^\d+$', value):
            return False, field_name + '必须是整数!', None
        value = int(value)
        if value < min_value or value > max_value:
            return False, field_name + '范围不正确!', None
        return True, 'ok', value

    def _toBool(self, value):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    def _getRawReportConfig(self):
        data = self._readJsonConfig(self.__report_config_addr)
        if not isinstance(data, dict):
            data = {}
        return data

    def _normalizeReportHostIds(self, raw_host_ids, valid_host_ids=None):
        host_ids = []
        seen = set()

        if isinstance(raw_host_ids, list):
            candidates = raw_host_ids
        elif isinstance(raw_host_ids, tuple):
            candidates = list(raw_host_ids)
        else:
            candidates = str(raw_host_ids or '').replace('\n', ',').split(',')

        for item in candidates:
            host_id = str(item).strip()
            if host_id == '' or host_id in seen:
                continue
            if valid_host_ids is not None and host_id not in valid_host_ids:
                continue
            seen.add(host_id)
            host_ids.append(host_id)
        return host_ids

    def _getReportHostOptions(self):
        data = h_api.getHostMetaRows()
        detail_map = host_status_service_utils.getLatestHostDetailMap(data)

        options = []
        for item in data:
            host_id = str(item.get('host_id', '')).strip()
            if host_id == '':
                continue
            host_status = detail_map.get(host_id, {}).get('host_status', 'Stopped')
            options.append({
                'host_id': host_id,
                'host_name': item.get('host_name', ''),
                'ip': item.get('ip', ''),
                'host_status': host_status
            })
        return options

    def _normalizeReportCron(self, cron_form):
        default_cron = self._getDefaultReportCron()
        cron_type = str(cron_form.get('type', default_cron['type'])).strip() or default_cron['type']
        allowed_types = ('day', 'day-n', 'hour', 'hour-n', 'minute-n', 'week', 'month')
        if cron_type not in allowed_types:
            return False, '服务器报告频率类型不正确!', None

        ok, msg, hour = self._validateThresholdField('小时', cron_form.get('hour', default_cron['hour']), 0, 23)
        if not ok:
            return False, msg, None

        ok, msg, minute = self._validateThresholdField('分钟', cron_form.get('minute', default_cron['minute']), 0, 59)
        if not ok:
            return False, msg, None

        where1 = ''
        week = ''

        if cron_type == 'day-n':
            ok, msg, where1 = self._validateThresholdField('N天', cron_form.get('where1', ''), 1, 31)
            if not ok:
                return False, msg, None
        elif cron_type == 'hour-n':
            ok, msg, where1 = self._validateThresholdField('N小时', cron_form.get('where1', ''), 1, 23)
            if not ok:
                return False, msg, None
        elif cron_type == 'minute-n':
            interval_value = cron_form.get('where1', cron_form.get('minute', ''))
            ok, msg, where1 = self._validateThresholdField('N分钟', interval_value, 1, 59)
            if not ok:
                return False, msg, None
            minute = where1
        elif cron_type == 'month':
            ok, msg, where1 = self._validateThresholdField('每月日期', cron_form.get('where1', ''), 1, 31)
            if not ok:
                return False, msg, None
        elif cron_type == 'week':
            week_value = cron_form.get('week', '')
            if str(week_value).strip() == '':
                week_value = cron_form.get('where1', default_cron['week'])
            ok, msg, week = self._validateThresholdField('星期', week_value, 0, 6)
            if not ok:
                return False, msg, None
            where1 = week

        return True, 'ok', {
            'type': cron_type,
            'where1': where1,
            'hour': hour,
            'minute': minute,
            'week': week
        }

    def _getReportConfigData(self):
        report_config = self._getRawReportConfig()
        default_report_config = self._getDefaultReportConfig()
        data = {}
        data['cpu'] = report_config.get('cpu', default_report_config.get('cpu', ''))
        data['memory'] = report_config.get('memory', default_report_config.get('memory', ''))
        data['disk'] = report_config.get('disk', default_report_config.get('disk', ''))
        data['ssl_cert'] = report_config.get('ssl_cert', default_report_config.get('ssl_cert', ''))
        data['ha_enabled'] = self._toBool(report_config.get('ha_enabled', default_report_config.get('ha_enabled', True)))
        return data

    def _getReportScheduleConfigData(self):
        report_config = self._getRawReportConfig()
        default_schedule = self._getDefaultReportScheduleConfig()
        options = self._getReportHostOptions()
        valid_host_ids = set(item['host_id'] for item in options)

        data = {
            'enabled': self._toBool(report_config.get('enabled', default_schedule['enabled'])),
            'report_host_ids': self._normalizeReportHostIds(
                report_config.get('report_host_ids', default_schedule['report_host_ids']),
                valid_host_ids
            ),
            'cron': dict(default_schedule['cron'])
        }

        ok, msg, cron_config = self._normalizeReportCron(report_config.get('cron', default_schedule['cron']))
        if ok:
            data['cron'] = cron_config

        return data

    def getReportDispatchConfigData(self):
        report_config = self._getRawReportConfig()
        schedule_config = self._getReportScheduleConfigData()
        options = self._getReportHostOptions()
        valid_host_ids = set(item['host_id'] for item in options)
        has_schedule_key = False
        for key in ('enabled', 'report_host_ids', 'cron'):
            if key in report_config:
                has_schedule_key = True
                break

        if not has_schedule_key:
            return {
                'enabled': False,
                'report_host_ids': [],
                'cron': dict(self._getDefaultReportCron())
            }

        return {
            'enabled': bool(schedule_config.get('enabled')),
            'report_host_ids': self._normalizeReportHostIds(
                schedule_config.get('report_host_ids', []),
                valid_host_ids
            ),
            'cron': dict(schedule_config.get('cron', self._getDefaultReportCron()))
        }

    def saveReportDispatchConfigData(self, enabled, report_host_ids, cron_config):
        report_config = self._getRawReportConfig()
        normalized_ids = self._normalizeReportHostIds(report_host_ids)
        ok, msg, normalized_cron = self._normalizeReportCron(cron_config or self._getDefaultReportCron())
        if not ok:
            normalized_cron = self._getDefaultReportCron()

        report_config['enabled'] = bool(enabled)
        report_config['report_host_ids'] = normalized_ids
        report_config['cron'] = normalized_cron
        report_config.pop('report_last_sent_at', None)
        self._writeJsonConfig(self.__report_config_addr, report_config)
        return {
            'enabled': bool(enabled),
            'report_host_ids': normalized_ids,
            'cron': normalized_cron
        }

    def applyReportScheduleForNewHost(self, host_id):
        host_id = str(host_id).strip()
        if host_id == '':
            return False

        schedule_config = self._getReportScheduleConfigData()
        report_host_ids = list(schedule_config.get('report_host_ids', []))
        if host_id not in report_host_ids:
            report_host_ids.append(host_id)

        self.saveReportDispatchConfigData(
            schedule_config.get('enabled', False),
            report_host_ids,
            schedule_config.get('cron', self._getDefaultReportCron())
        )
        return True

    def _normalizeReportConfig(self, report_config):
        checks = [
            ('cpu', 'CPU阈值', 0, 100),
            ('memory', '内存阈值', 0, 100),
            ('disk', '磁盘阈值', 0, 100),
            ('ssl_cert', 'SSL证书到期阈值', 0, 3650),
        ]

        normalized = {}
        for field, title, min_value, max_value in checks:
            ok, msg, value = self._validateThresholdField(
                title, report_config.get(field, ''), min_value, max_value)
            if not ok:
                return False, msg, None
            normalized[field] = value
        return True, 'ok', normalized

    def _parseEsHosts(self, address_text):
        addr_text = str(address_text).strip()
        if addr_text == '':
            return False, 'ES地址不能为空!', None

        raw_list = re.split(r'[\n,]+', addr_text)
        hosts = []
        for item in raw_list:
            current = item.strip()
            if current == '':
                continue
            if '://' not in current:
                current = 'http://' + current

            parsed = urlparse(current)
            if not parsed.hostname:
                return False, 'ES地址格式不正确!', None

            scheme = parsed.scheme or 'http'
            if scheme not in ['http', 'https']:
                return False, 'ES地址协议仅支持http或https!', None

            host_data = {
                'host': parsed.hostname,
                'port': parsed.port or (443 if scheme == 'https' else 9200),
                'scheme': scheme
            }
            hosts.append(host_data)

        if len(hosts) == 0:
            return False, 'ES地址不能为空!', None
        return True, 'ok', hosts

    def _getEsConfigData(self):
        es_config = self._readJsonConfig(self.__es_config_addr)
        default_es_config = self._getDefaultEsConfig()
        data = {}
        data['addr'] = es_config.get('addr', default_es_config.get('addr', ''))
        data['username'] = es_config.get('username', default_es_config.get('username', ''))
        data['password'] = es_config.get('password', default_es_config.get('password', ''))
        data['hosts'] = es_config.get('hosts', default_es_config.get('hosts', []))
        return data

    def _saveReportThresholdConfig(self, report_form):
        ok, msg, report_config = self._normalizeReportConfig(report_form)
        if not ok:
            return False, msg
        current_config = self._getRawReportConfig()
        current_config.update(report_config)
        current_config['ha_enabled'] = self._toBool(request.form.get('ha_enabled', current_config.get('ha_enabled', True)))
        self._writeJsonConfig(self.__report_config_addr, current_config)
        return True, '服务器报告阈值保存成功!'

    def _saveEsConfig(self, es_form):
        ok, msg, es_config = self._normalizeEsConfig(es_form)
        if not ok:
            return False, msg
        self._writeJsonConfig(self.__es_config_addr, es_config)
        return True, 'ES配置保存成功!'

    def _normalizeEsConfig(self, es_config):
        addr = es_config.get('addr', '')
        username = es_config.get('username', '').strip()
        password = es_config.get('password', '')

        ok, msg, hosts = self._parseEsHosts(addr)
        if not ok:
            return False, msg, None

        if username == '' and str(password).strip() != '':
            return False, 'ES用户名不能为空!', None

        normalized = {
            'addr': str(addr).strip(),
            'username': username,
            'password': password,
            'hosts': hosts
        }
        return True, 'ok', normalized

    def _testEsConnection(self, es_config):
        try:
            from elasticsearch import Elasticsearch

            client_kwargs = {
                'hosts': es_config.get('hosts', []),
                'request_timeout': 5,
                'verify_certs': False
            }
            if es_config.get('username', '') != '':
                client_kwargs['basic_auth'] = (
                    es_config.get('username', ''),
                    es_config.get('password', '')
                )

            es_client = Elasticsearch(**client_kwargs)
            if not es_client.ping():
                return False, 'ES连接失败，请检查地址或认证信息!', None

            cluster_info = es_client.info()
            info = {
                'cluster_name': cluster_info.get('cluster_name', ''),
                'version': cluster_info.get('version', {}).get('number', '')
            }
            return True, 'ES连接成功!', info
        except Exception as e:
            return False, 'ES连接失败: ' + str(e), None

    def _getReportScriptsDir(self):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(current_dir))
        return os.path.join(root_dir, 'scripts')

    def _buildTestReportHostRows(self, raw_host_ids=None):
        if raw_host_ids is None:
            dispatch_config = self.getReportDispatchConfigData() or {}
            report_host_ids = self._normalizeReportHostIds(dispatch_config.get('report_host_ids', []))
        else:
            host_options = self._getReportHostOptions()
            valid_host_ids = set(item['host_id'] for item in host_options)
            report_host_ids = self._normalizeReportHostIds(raw_host_ids, valid_host_ids)
        if len(report_host_ids) == 0:
            return False, '请先在服务器报告配置中选择报告主机!', None, None

        host_rows = jh.M('view01_host').field(h_api.host_field).select()
        if isinstance(host_rows, str) or host_rows is None:
            host_rows = []

        host_row_map = {}
        for row in host_rows:
            host_id = str(row.get('host_id', '')).strip()
            if host_id != '':
                host_row_map[host_id] = row

        selected_rows = []
        missing_host_ids = []
        for host_id in report_host_ids:
            if host_id in host_row_map:
                selected_rows.append(host_row_map[host_id])
            else:
                missing_host_ids.append(host_id)

        if len(selected_rows) == 0:
            return False, '选中的报告主机不存在或已被删除，请重新选择!', None, None
        return True, 'ok', selected_rows, missing_host_ids

    def _isEmailNotifyReady(self):
        recipients = []
        enabled = False
        try:
            notify_data = jh.getNotifyData(True)
            if isinstance(notify_data, dict):
                email_data = notify_data.get('email', {}) or {}
                enabled = bool(email_data.get('enable'))
                config_data = email_data.get('data', {}) if isinstance(email_data, dict) else {}
                raw_recipients = config_data.get('to_mail_addr', '')
                if isinstance(raw_recipients, list):
                    recipients = [str(item).strip() for item in raw_recipients if str(item).strip() != '']
                else:
                    for item in str(raw_recipients).replace(';', ',').split(','):
                        item = item.strip()
                        if item != '':
                            recipients.append(item)
        except Exception:
            enabled = False
            recipients = []
        return enabled, recipients

    ##### ----- start ----- ###

    # 取面板列表
    def getPanelListApi(self):
        data = jh.M('panel').field(
            'id,title,url,username,password,click,addtime').order('click desc').select()
        return jh.getJson(data)

    def addPanelInfoApi(self):
        title = request.form.get('title', '')
        url = request.form.get('url', '')
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        # 校验是还是重复
        isAdd = jh.M('panel').where(
            'title=? OR url=?', (title, url)).count()
        if isAdd:
            return jh.returnJson(False, '备注或面板地址重复!')
        isRe = jh.M('panel').add('title,url,username,password,click,addtime',
                                 (title, url, username, password, 0, int(time.time())))
        if isRe:
            return jh.returnJson(True, '添加成功!')
        return jh.returnJson(False, '添加失败!')

    # 删除面板资料
    def delPanelInfoApi(self):
        mid = request.form.get('id', '')
        isExists = jh.M('panel').where('id=?', (mid,)).count()
        if not isExists:
            return jh.returnJson(False, '指定面板资料不存在!')
        jh.M('panel').where('id=?', (mid,)).delete()
        return jh.returnJson(True, '删除成功!')

     # 修改面板资料
    def setPanelInfoApi(self):
        title = request.form.get('title', '')
        url = request.form.get('url', '')
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        mid = request.form.get('id', '')
        # 校验是还是重复
        isSave = jh.M('panel').where(
            '(title=? OR url=?) AND id!=?', (title, url, mid)).count()
        if isSave:
            return jh.returnJson(False, '备注或面板地址重复!')

        # 更新到数据库
        isRe = jh.M('panel').where('id=?', (mid,)).save(
            'title,url,username,password', (title, url, username, password))
        if isRe:
            return jh.returnJson(True, '修改成功!')
        return jh.returnJson(False, '修改失败!')

    def syncDateApi(self):
        if jh.isAppleSystem():
            return jh.returnJson(True, '开发系统不必同步时间!')

        data = jh.execShell('ntpdate -s time.nist.gov')
        if data[0] == '':
            return jh.returnJson(True, '同步成功!')
        return jh.returnJson(False, '同步失败:' + data[0])

    def setPasswordApi(self):
        password1 = request.form.get('password1', '')
        password2 = request.form.get('password2', '')
        if password1 != password2:
            return jh.returnJson(False, '两次输入的密码不一致，请重新输入!')
        if len(password1) < 5:
            return jh.returnJson(False, '用户密码不能小于5位!')
        jh.M('users').where("username=?", (session['username'],)).setField(
            'password', jh.md5(password1.strip()))
        return jh.returnJson(True, '密码修改成功!')

    def setNameApi(self):
        name1 = request.form.get('name1', '')
        name2 = request.form.get('name2', '')
        if name1 != name2:
            return jh.returnJson(False, '两次输入的用户名不一致，请重新输入!')
        if len(name1) < 3:
            return jh.returnJson(False, '用户名长度不能少于3位')

        jh.M('users').where("username=?", (session['username'],)).setField(
            'username', name1.strip())

        session['username'] = name1
        return jh.returnJson(True, '用户修改成功!')

    def setWebnameApi(self):
        webname = request.form.get('webname', '')
        if webname != jh.getConfig('title'):
            jh.setConfig('title', webname)
        return jh.returnJson(True, '面板别名保存成功!')

    def setPortApi(self):
        port = request.form.get('port', '')
        if port != jh.getHostPort():
            import system_api
            import firewall_api

            sysCfgDir = jh.systemdCfgDir()
            if os.path.exists(sysCfgDir + "/firewalld.service"):
                if not firewall_api.firewall_api().getFwStatus():
                    return jh.returnJson(False, 'firewalld必须先启动!')

            jh.setHostPort(port)

            msg = jh.getInfo('放行端口[{1}]成功', (port,))
            jh.writeLog("防火墙管理", msg)
            addtime = time.strftime('%Y-%m-%d %X', time.localtime())
            jh.M('firewall').add('port,ps,addtime', (port, "配置修改", addtime))

            firewall_api.firewall_api().addAcceptPort(port)
            firewall_api.firewall_api().firewallReload()

            system_api.system_api().restartMw()

        return jh.returnJson(True, '端口保存成功!')

    def setIpApi(self):
        host_ip = request.form.get('host_ip', '')
        if host_ip != jh.getHostAddr():
            jh.setHostAddr(host_ip)
        return jh.returnJson(True, 'IP保存成功!')

    def setWwwDirApi(self):
        sites_path = request.form.get('sites_path', '')
        if sites_path != jh.getWwwDir():
            jh.setWwwDir(sites_path)
        return jh.returnJson(True, '修改默认建站目录成功!')

    def setBackupDirApi(self):
        backup_path = request.form.get('backup_path', '')
        if backup_path != jh.getBackupDir():
            jh.setBackupDir(backup_path)
        return jh.returnJson(True, '修改默认备份目录成功!')

    def getReportConfigApi(self):
        data = {
            'report_config': self._getReportConfigData(),
            'es_config': self._getEsConfigData(),
            'report_schedule_config': self._getReportScheduleConfigData(),
            'report_host_options': self._getReportHostOptions()
        }
        return jh.returnJson(True, '获取成功!', data)

    def saveReportConfigApi(self):
        report_form = {
            'cpu': request.form.get('cpu', '').strip(),
            'memory': request.form.get('memory', '').strip(),
            'disk': request.form.get('disk', '').strip(),
            'ssl_cert': request.form.get('ssl_cert', '').strip(),
        }
        ok, msg, report_config = self._normalizeReportConfig(report_form)
        if not ok:
            return jh.returnJson(False, msg)

        es_form = {
            'addr': request.form.get('es_addr', '').strip(),
            'username': request.form.get('es_username', '').strip(),
            'password': request.form.get('es_password', ''),
        }
        ok, msg, es_config = self._normalizeEsConfig(es_form)
        if not ok:
            return jh.returnJson(False, msg)

        current_config = self._getRawReportConfig()
        current_config.update(report_config)
        self._writeJsonConfig(self.__report_config_addr, current_config)
        self._writeJsonConfig(self.__es_config_addr, es_config)
        return jh.returnJson(True, '服务器报告配置保存成功!')

    def saveReportThresholdApi(self):
        report_form = {
            'cpu': request.form.get('cpu', '').strip(),
            'memory': request.form.get('memory', '').strip(),
            'disk': request.form.get('disk', '').strip(),
            'ssl_cert': request.form.get('ssl_cert', '').strip(),
        }
        ok, msg = self._saveReportThresholdConfig(report_form)
        if ok:
            report_config = self._getRawReportConfig()
            report_config['ha_enabled'] = self._toBool(request.form.get('ha_enabled', report_config.get('ha_enabled', True)))
            self._writeJsonConfig(self.__report_config_addr, report_config)
        return jh.returnJson(ok, msg)

    def saveReportScheduleApi(self):
        host_options = self._getReportHostOptions()
        valid_host_ids = set(item['host_id'] for item in host_options)
        report_host_ids = request.form.getlist('report_host_ids[]')
        if len(report_host_ids) == 0:
            report_host_ids = request.form.getlist('report_host_ids')
        if len(report_host_ids) == 0:
            report_host_ids = self._normalizeReportHostIds(request.form.get('report_host_ids', ''), valid_host_ids)
        else:
            report_host_ids = self._normalizeReportHostIds(report_host_ids, valid_host_ids)

        enabled = self._toBool(request.form.get('enabled', '0'))
        cron_form = {
            'type': request.form.get('type', '').strip(),
            'where1': request.form.get('where1', '').strip(),
            'hour': request.form.get('hour', '').strip(),
            'minute': request.form.get('minute', '').strip(),
            'week': request.form.get('week', '').strip()
        }
        ok, msg, cron_config = self._normalizeReportCron(cron_form)
        if not ok:
            return jh.returnJson(False, msg)

        threshold_form = {
            'cpu': request.form.get('cpu', '').strip(),
            'memory': request.form.get('memory', '').strip(),
            'disk': request.form.get('disk', '').strip(),
            'ssl_cert': request.form.get('ssl_cert', '').strip(),
        }
        ok, msg, threshold_config = self._normalizeReportConfig(threshold_form)
        if not ok:
            return jh.returnJson(False, msg)

        report_config = self._getRawReportConfig()
        report_config.update(threshold_config)
        report_config['ha_enabled'] = self._toBool(request.form.get('ha_enabled', report_config.get('ha_enabled', True)))
        self._writeJsonConfig(self.__report_config_addr, report_config)
        self.saveReportDispatchConfigData(
            enabled,
            report_host_ids,
            cron_config
        )

        return jh.returnJson(True, '服务器报告配置保存成功!', {
            'enabled': enabled,
            'report_host_ids': report_host_ids,
            'cron': cron_config
        })

    def saveReportEsApi(self):
        es_form = {
            'addr': request.form.get('es_addr', '').strip(),
            'username': request.form.get('es_username', '').strip(),
            'password': request.form.get('es_password', ''),
        }
        ok, msg = self._saveEsConfig(es_form)
        return jh.returnJson(ok, msg, self._getEsConfigData() if ok else None)

    def testReportEsApi(self):
        es_form = {
            'addr': request.form.get('es_addr', '').strip(),
            'username': request.form.get('es_username', '').strip(),
            'password': request.form.get('es_password', ''),
        }
        ok, msg, es_config = self._normalizeEsConfig(es_form)
        if not ok:
            return jh.returnJson(False, msg)

        ok, msg, data = self._testEsConnection(es_config)
        return jh.returnJson(ok, msg, data)

    def resetReportEsApi(self):
        default_es_config = self._getDefaultEsConfig()
        self._writeJsonConfig(self.__es_config_addr, default_es_config)
        return jh.returnJson(True, 'ES配置已重置为本地默认配置!', default_es_config)

    def resetReportThresholdApi(self):
        default_report_config = self._getDefaultReportConfig()
        report_config = self._getRawReportConfig()
        report_config.update(default_report_config)
        self._writeJsonConfig(self.__report_config_addr, report_config)
        return jh.returnJson(True, '服务器报告阈值已重置为默认配置!', default_report_config)

    def testSendReportMailApi(self):
        email_enabled, recipients = self._isEmailNotifyReady()
        if not email_enabled:
            return jh.returnJson(False, '请先开启邮件通知后再测试发送服务器报告!')
        if len(recipients) == 0:
            return jh.returnJson(False, '请先在邮件通知中配置至少一个收件人后再测试发送!')

        report_host_ids = request.form.getlist('report_host_ids[]')
        if len(report_host_ids) == 0:
            report_host_ids = request.form.getlist('report_host_ids')
        if len(report_host_ids) == 0:
            report_host_ids = request.form.get('report_host_ids', None)

        ok, msg, host_rows, missing_host_ids = self._buildTestReportHostRows(report_host_ids)
        if not ok:
            return jh.returnJson(False, msg)

        threshold_form = {
            'cpu': request.form.get('cpu', '').strip(),
            'memory': request.form.get('memory', '').strip(),
            'disk': request.form.get('disk', '').strip(),
            'ssl_cert': request.form.get('ssl_cert', '').strip(),
        }
        if threshold_form['cpu'] == '' and threshold_form['memory'] == '' and threshold_form['disk'] == '' and threshold_form['ssl_cert'] == '':
            threshold_config = self._getReportConfigData()
        else:
            ok, msg, threshold_config = self._normalizeReportConfig(threshold_form)
            if not ok:
                return jh.returnJson(False, msg)

        scripts_dir = self._getReportScriptsDir()
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        try:
            from report_analyser import HostReportAnalyser
            from report_sender import HostReportSender

            now_ts = int(time.time())
            logger = lambda message: print('[config.testSendReportMailApi] {0}'.format(message))
            analyser = HostReportAnalyser(now_ts=now_ts, logger=logger)
            analyser.thresholds = dict(threshold_config)
            analyser.ha_report_enabled_override = self._toBool(request.form.get('ha_enabled', self._getReportConfigData().get('ha_enabled', True)))
            sender = HostReportSender(now_ts=now_ts, logger=logger, es_client=analyser._es)
            sender.thresholds = dict(threshold_config)
            report_date = time.strftime('%Y-%m-%d', time.localtime(now_ts))
            report_config = {}
            dispatch_config = self.getReportDispatchConfigData() or {}
            for row in host_rows:
                host_id = row.get('host_id')
                report_config[host_id] = {
                    'enabled': True,
                    'cron': dispatch_config.get('cron', self.getDefaultReportCronData())
                }

            analysis_result = analyser.run_analysis(host_rows=host_rows, report_date=report_date)
            delivery_result = sender.run_delivery(
                due_rows=host_rows,
                report_config=report_config,
                report_date=report_date,
                enabled_rows=host_rows,
                force_send=True,
                overview_document=analysis_result.get('overview_document'),
                single_documents=analysis_result.get('single_documents')
            )
        except Exception as ex:
            return jh.returnJson(False, '测试发送服务器报告失败: ' + str(ex))

        delivery_status = delivery_result.get('status')
        if delivery_status not in ('ok', 'partial'):
            error_msg = delivery_result.get('error') or delivery_result.get('reason') or 'unknown'
            retained_message = '报告数据已生成并保留'
            if analysis_result.get('status') != 'ok':
                retained_message = '报告生成未完成'
            safe_analysis_result = dict(analysis_result)
            safe_analysis_result.pop('overview_document', None)
            safe_analysis_result.pop('single_documents', None)
            return jh.returnJson(
                False,
                '{0}，但发送失败: {1}'.format(retained_message, error_msg),
                {
                    'analysis_result': safe_analysis_result,
                    'delivery_result': delivery_result,
                    'missing_host_ids': missing_host_ids,
                    'recipients': recipients
                }
            )

        message = '测试发送完成! 报告日期: {0}，概览发送: {1}，异常单机发送成功: {2}，跳过: {3}'.format(
            delivery_result.get('report_date', ''),
            '是' if delivery_result.get('overview_sent') else '否',
            delivery_result.get('single_success', 0),
            delivery_result.get('single_skipped', 0)
        )
        if len(missing_host_ids) > 0:
            message += '；以下主机未找到，已跳过: {0}'.format(', '.join(missing_host_ids))

        return jh.returnJson(True, message, {
            'analysis_result': analysis_result,
            'delivery_result': delivery_result,
            'missing_host_ids': missing_host_ids,
            'recipients': recipients
        })

    def setBasicAuthApi(self):
        basic_user = request.form.get('basic_user', '').strip()
        basic_pwd = request.form.get('basic_pwd', '').strip()
        basic_open = request.form.get('is_open', '').strip()

        salt = '_md_salt'
        path = 'data/basic_auth.json'
        is_open = True

        if basic_open == 'false':
            if os.path.exists(path):
                os.remove(path)
            return jh.returnJson(True, '删除BasicAuth成功!')

        if basic_user == '' or basic_pwd == '':
            return jh.returnJson(True, '用户和密码不能为空!')

        ba_conf = None
        if os.path.exists(path):
            try:
                ba_conf = json.loads(public.readFile(path))
            except:
                os.remove(path)

        if not ba_conf:
            ba_conf = {
                "basic_user": jh.md5(basic_user + salt),
                "basic_pwd": jh.md5(basic_pwd + salt),
                "open": is_open
            }
        else:
            ba_conf['basic_user'] = jh.md5(basic_user + salt)
            ba_conf['basic_pwd'] = jh.md5(basic_pwd + salt)
            ba_conf['open'] = is_open

        jh.writeFile(path, json.dumps(ba_conf))
        os.chmod(path, 384)
        jh.writeLog('面板设置', '设置BasicAuth状态为: %s' % is_open)

        jh.restartMw()
        return jh.returnJson(True, '设置成功!')

    def setApi(self):
        webname = request.form.get('webname', '')
        port = request.form.get('port', '')
        host_ip = request.form.get('host_ip', '')
        domain = request.form.get('domain', '')
        sites_path = request.form.get('sites_path', '')
        backup_path = request.form.get('backup_path', '')

        if domain != '':
            reg = "^([\w\-\*]{1,100}\.){1,4}(\w{1,10}|\w{1,10}\.\w{1,10})$"
            if not re.match(reg, domain):
                return jh.returnJson(False, '主域名格式不正确')

        if int(port) >= 65535 or int(port) < 100:
            return jh.returnJson(False, '端口范围不正确!')

        if webname != jh.getConfig('title'):
            jh.setConfig('title', webname)

        if sites_path != jh.getWwwDir():
            jh.setWwwDir(sites_path)

        if backup_path != jh.getWwwDir():
            jh.setBackupDir(backup_path)

        if port != jh.getHostPort():
            import system_api
            import firewall_api

            sysCfgDir = jh.systemdCfgDir()
            if os.path.exists(sysCfgDir + "/firewalld.service"):
                if not firewall_api.firewall_api().getFwStatus():
                    return jh.returnJson(False, 'firewalld必须先启动!')

            jh.setHostPort(port)

            msg = jh.getInfo('放行端口[{1}]成功', (port,))
            jh.writeLog("防火墙管理", msg)
            addtime = time.strftime('%Y-%m-%d %X', time.localtime())
            jh.M('firewall').add('port,ps,addtime', (port, "配置修改", addtime))

            firewall_api.firewall_api().addAcceptPort(port)
            firewall_api.firewall_api().firewallReload()

            system_api.system_api().restartMw()

        if host_ip != jh.getHostAddr():
            jh.setHostAddr(host_ip)

        mhost = jh.getHostAddr()
        info = {
            'uri': '/config',
            'host': mhost + ':' + port
        }
        return jh.returnJson(True, '保存成功!', info)

    def setAdminPathApi(self):
        admin_path = request.form.get('admin_path', '').strip()
        admin_path_checks = ['/', '/close', '/login',
                             '/do_login', '/site', '/sites',
                             '/download_file', '/control', '/crontab',
                             '/firewall', '/files', 'config',
                             '/soft', '/system', '/code',
                             '/ssl', '/plugins', '/hook']
        if admin_path == '':
            admin_path = '/'
        if admin_path != '/':
            if len(admin_path) < 6:
                return jh.returnJson(False, '安全入口地址长度不能小于6位!')
            if admin_path in admin_path_checks:
                return jh.returnJson(False, '该入口已被面板占用,请使用其它入口!')
            if not re.match("^/[\w\./-_]+$", admin_path):
                return jh.returnJson(False, '入口地址格式不正确,示例: /jh_rand')
        # else:
        #     domain = jh.readFile('data/bind_domain.pl')
        #     if not domain:
        #         domain = ''
        #     limitip = jh.readFile('data/bind_limitip.pl')
        #     if not limitip:
        #         limitip = ''
        #     if not domain.strip() and not limitip.strip():
        # return jh.returnJson(False,
        # '警告，关闭安全入口等于直接暴露你的后台地址在外网，十分危险，至少开启以下一种安全方式才能关闭：<a
        # style="color:red;"><br>1、绑定访问域名<br>2、绑定授权IP</a>')

        admin_path_file = 'data/admin_path.pl'
        admin_path_old = '/'
        if os.path.exists(admin_path_file):
            admin_path_old = jh.readFile(admin_path_file).strip()

        if admin_path_old != admin_path:
            jh.writeFile(admin_path_file, admin_path)
            jh.restartMw()
        return jh.returnJson(True, '修改成功!')

    def closePanelApi(self):
        filename = 'data/close.pl'
        if os.path.exists(filename):
            os.remove(filename)
            return jh.returnJson(True, '开启成功')
        jh.writeFile(filename, 'True')
        jh.execShell("chmod 600 " + filename)
        jh.execShell("chown root.root " + filename)
        return jh.returnJson(True, '面板已关闭!')

    def openDebugApi(self):
        filename = 'data/debug.pl'
        if os.path.exists(filename):
            os.remove(filename)
            return jh.returnJson(True, '开发模式关闭!')
        jh.writeFile(filename, 'True')
        return jh.returnJson(True, '开发模式开启!')

    def setIpv6StatusApi(self):
        ipv6_file = 'data/ipv6.pl'
        if os.path.exists('data/ipv6.pl'):
            os.remove(ipv6_file)
            jh.writeLog('面板设置', '关闭面板IPv6兼容!')
        else:
            jh.writeFile(ipv6_file, 'True')
            jh.writeLog('面板设置', '开启面板IPv6兼容!')
        jh.restartMw()
        return jh.returnJson(True, '设置成功!')

    def setEnvToCnApi(self):
        net_env_cn_file = 'data/net_env_cn.pl'
        if os.path.exists('data/net_env_cn.pl'):
            os.remove(net_env_cn_file)
            jh.writeLog('面板设置', '切换国际源成功!')
            jh.restartMw()
            return jh.returnJson(True, '切换国际源成功!')
        else:
            jh.writeFile(net_env_cn_file, 'True')
            jh.writeLog('面板设置', '切换中国源成功!')
            jh.restartMw()
            return jh.returnJson(True, '切换中国源成功!')

    # 获取面板证书
    def getPanelSslApi(self):
        cert = {}

        keyPath = 'ssl/private.pem'
        certPath = 'ssl/cert.pem'

        if not os.path.exists(certPath):
            jh.createSSL()

        cert['privateKey'] = jh.readFile(keyPath)
        cert['certPem'] = jh.readFile(certPath)
        cert['rep'] = os.path.exists('ssl/input.pl')
        cert['info'] = jh.getCertName(certPath)
        return jh.getJson(cert)

    # 保存面板证书
    def savePanelSslApi(self):
        keyPath = 'ssl/private.pem'
        certPath = 'ssl/cert.pem'
        checkCert = '/tmp/cert.pl'

        certPem = request.form.get('certPem', '').strip()
        privateKey = request.form.get('privateKey', '').strip()

        if(privateKey.find('KEY') == -1):
            return jh.returnJson(False, '秘钥错误，请检查!')
        if(certPem.find('CERTIFICATE') == -1):
            return jh.returnJson(False, '证书错误，请检查!')

        jh.writeFile(checkCert, certPem)
        if privateKey:
            jh.writeFile(keyPath, privateKey)
        if certPem:
            jh.writeFile(certPath, certPem)
        if not jh.checkCert(checkCert):
            return jh.returnJson(False, '证书错误,请检查!')
        jh.writeFile('ssl/input.pl', 'True')
        return jh.returnJson(True, '证书已保存!')

    def setPanelDomainApi(self):
        domain = request.form.get('domain', '')

        panel_tpl = jh.getRunDir() + "/data/tpl/nginx_panel.conf"
        dst_panel_path = jh.getServerDir() + "/web_conf/nginx/vhost/panel.conf"

        cfg_domain = 'data/bind_domain.pl'
        if domain == '':
            os.remove(cfg_domain)
            os.remove(dst_panel_path)
            jh.restartWeb()
            return jh.returnJson(True, '清空域名成功!')

        reg = r"^([\w\-\*]{1,100}\.){1,4}(\w{1,10}|\w{1,10}\.\w{1,10})$"
        if not re.match(reg, domain):
            return jh.returnJson(False, '主域名格式不正确')

        op_dir = jh.getServerDir() + "/openresty"
        if not os.path.exists(op_dir):
            return jh.returnJson(False, '依赖OpenResty,先安装启动它!')

        content = jh.readFile(panel_tpl)
        content = content.replace("{$PORT}", "80")
        content = content.replace("{$SERVER_NAME}", domain)
        content = content.replace("{$PANAL_PORT}", jh.readFile('data/port.pl'))
        content = content.replace("{$LOGPATH}", jh.getRunDir() + '/logs')
        content = content.replace("{$PANAL_ADDR}", jh.getRunDir())
        jh.writeFile(dst_panel_path, content)
        jh.restartWeb()

        jh.writeFile(cfg_domain, domain)
        return jh.returnJson(True, '设置域名成功!')

     # 设置面板SSL
    def setPanelSslApi(self):
        sslConf = jh.getRunDir() + '/data/ssl.pl'

        panel_tpl = jh.getRunDir() + "/data/tpl/nginx_panel.conf"
        dst_panel_path = jh.getServerDir() + "/web_conf/nginx/vhost/panel.conf"
        if os.path.exists(sslConf):
            os.system('rm -f ' + sslConf)

            conf = jh.readFile(dst_panel_path)
            if conf:
                rep = "\s+ssl_certificate\s+.+;\s+ssl_certificate_key\s+.+;"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_protocols\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_ciphers\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_prefer_server_ciphers\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_session_cache\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_session_timeout\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_ecdh_curve\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_session_tickets\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_stapling\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl_stapling_verify\s+.+;\n"
                conf = re.sub(rep, '', conf)
                rep = "\s+ssl\s+on;"
                conf = re.sub(rep, '', conf)
                rep = "\s+error_page\s497.+;"
                conf = re.sub(rep, '', conf)
                rep = "\s+if.+server_port.+\n.+\n\s+\s*}"
                conf = re.sub(rep, '', conf)
                rep = "\s+listen\s+443.*;"
                conf = re.sub(rep, '', conf)
                rep = "\s+listen\s+\[\:\:\]\:443.*;"
                conf = re.sub(rep, '', conf)
                jh.writeFile(dst_panel_path, conf)

            jh.writeLog('面板配置', '面板SSL关闭成功!')
            jh.restartMw(True)
            return jh.returnJson(True, 'SSL已关闭，即将跳转http协议访问面板!')
        else:
            try:
                if not os.path.exists('ssl/input.ssl'):
                    jh.createSSL()
                jh.writeFile(sslConf, 'True')

                keyPath = jh.getRunDir() + '/ssl/private.pem'
                certPath = jh.getRunDir() + '/ssl/cert.pem'

                conf = jh.readFile(dst_panel_path)
                if conf:
                    if conf.find('ssl_certificate') == -1:
                        sslStr = """#error_page 404/404.html;
    ssl_certificate    %s;
    ssl_certificate_key  %s;
    ssl_protocols TLSv1 TLSv1.1 TLSv1.2;
    ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:HIGH:!aNULL:!MD5:!RC4:!DHE;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    error_page 497  https://$host$request_uri;""" % (certPath, keyPath)
                    if(conf.find('ssl_certificate') != -1):
                        return jh.returnJson(True, 'SSL开启成功!')

                    conf = conf.replace('#error_page 404/404.html;', sslStr)

                    rep = "listen\s+([0-9]+)\s*[default_server]*;"
                    tmp = re.findall(rep, conf)
                    if not jh.inArray(tmp, '443'):
                        listen = re.search(rep, conf).group()
                        http_ssl = "\n\tlisten 443 ssl http2;"
                        http_ssl = http_ssl + "\n\tlisten [::]:443 ssl http2;"
                        conf = conf.replace(listen, listen + http_ssl)

                    jh.backFile(dst_panel_path)
                    jh.writeFile(dst_panel_path, conf)
                    isError = jh.checkWebConfig()
                    if(isError != True):
                        jh.restoreFile(dst_panel_path)
                        return jh.returnJson(False, '证书错误: <br><a style="color:red;">' + isError.replace("\n", '<br>') + '</a>')
            except Exception as ex:
                return jh.returnJson(False, '开启失败:' + str(ex))
            jh.restartMw(True)
            return jh.returnJson(True, '开启SSL成功，即将跳转https协议访问面板!')

    # 更新面板SSL证书
    def updatePanelSslApi(self):
        jh.execShell('rm -f %s/ssl/input.pl' % jh.getRunDir())
        jh.createSSL()
        return jh.returnJson(True, '更新SSL证书成功!')

    def getApi(self):
        data = {}
        return jh.getJson(data)
    ##### ----- end ----- ###

    # 获取临时登录列表
    def getTempLoginApi(self):
        if 'tmp_login_expire' in session:
            return jh.returnJson(False, '没有权限')
        limit = request.form.get('limit', '10').strip()
        p = request.form.get('p', '1').strip()
        tojs = request.form.get('tojs', '').strip()

        tempLoginM = jh.M('temp_login')
        tempLoginM.where('state=? and expire<?',
                         (0, int(time.time()))).setField('state', -1)

        start = (int(p) - 1) * (int(limit))
        vlist = tempLoginM.limit(str(start) + ',' + str(limit)).order('id desc').field(
            'id,addtime,expire,login_time,login_addr,state').select()

        data = {}
        data['data'] = vlist

        count = tempLoginM.count()
        page_args = {}
        page_args['count'] = count
        page_args['tojs'] = 'get_temp_login'
        page_args['p'] = p
        page_args['row'] = limit

        data['page'] = jh.getPage(page_args)
        return jh.getJson(data)

    # 删除临时登录
    def removeTempLoginApi(self):
        if 'tmp_login_expire' in session:
            return jh.returnJson(False, '没有权限')
        sid = request.form.get('id', '10').strip()
        if jh.M('temp_login').where('id=?', (sid,)).delete():
            jh.writeLog('面板设置', '删除临时登录连接')
            return jh.returnJson(True, '删除成功')
        return jh.returnJson(False, '删除失败')

    def setTempLoginApi(self):
        if 'tmp_login_expire' in session:
            return jh.returnJson(False, '没有权限')
        s_time = int(time.time())
        jh.M('temp_login').where(
            'state=? and expire>?', (0, s_time)).delete()
        token = jh.getRandomString(48)
        salt = jh.getRandomString(12)

        pdata = {
            'token': jh.md5(token + salt),
            'salt': salt,
            'state': 0,
            'login_time': 0,
            'login_addr': '',
            'expire': s_time + 3600,
            'addtime': s_time
        }

        if not jh.M('temp_login').count():
            pdata['id'] = 101

        if jh.M('temp_login').insert(pdata):
            jh.writeLog('面板设置', '生成临时连接,过期时间:{}'.format(
                jh.formatDate(times=pdata['expire'])))
            return jh.getJson({'status': True, 'msg': "临时连接已生成", 'token': token, 'expire': pdata['expire']})
        return jh.returnJson(False, '连接生成失败')

    def getTempLoginLogsApi(self):
        if 'tmp_login_expire' in session:
            return jh.returnJson(False, '没有权限')

        logs_id = request.form.get('id', '').strip()
        logs_id = int(logs_id)
        data = jh.M('logs').where(
            'uid=?', (logs_id,)).order('id desc').field(
            'id,type,uid,log,addtime').select()
        return jh.returnJson(False, 'ok', data)

    def checkPanelToken(self):
        api_file = self.__api_addr
        if not os.path.exists(api_file):
            return False, ''

        tmp = jh.readFile(api_file)
        data = json.loads(tmp)
        if data['open']:
            return True, data
        else:
            return False, ''

    def getPanelTokenApi(self):
        api_file = self.__api_addr

        tmp = jh.readFile(api_file)
        if not os.path.exists(api_file):
            ready_data = {"open": False, "token": "", "limit_addr": []}
            jh.writeFile(api_file, json.dumps(ready_data))
            jh.execShell("chmod 600 " + api_file)
            tmp = jh.readFile(api_file)
        data = json.loads(tmp)

        if not 'key' in data:
            data['key'] = jh.getRandomString(16)
            jh.writeFile(api_file, json.dumps(data))

        if 'token_crypt' in data:
            data['token'] = jh.deCrypt(data['token'], data['token_crypt'])
        else:
            token = jh.getRandomString(32)
            data['token'] = jh.md5(token)
            data['token_crypt'] = jh.enCrypt(
                data['token'], token).decode('utf-8')
            jh.writeFile(api_file, json.dumps(data))
            data['token'] = "***********************************"

        data['limit_addr'] = '\n'.join(data['limit_addr'])

        del(data['key'])
        return jh.returnJson(True, 'ok', data)
    
    def getNotifyApi(self):
        # 获取
        data = jh.getNotifyData(True)
        return jh.returnData(True, 'ok', data)

    def setNotifyApi(self):
        tag = request.form.get('tag', '').strip()
        data = request.form.get('data', '').strip()

        cfg = jh.getNotifyData(False)

        crypt_data = jh.enDoubleCrypt(tag, data)
        if tag in cfg:
            cfg[tag]['cfg'] = crypt_data
        else:
            t = {'cfg': crypt_data}
            cfg[tag] = t

        jh.writeNotify(cfg)
        return jh.returnData(True, '设置成功')

    def setNotifyTestApi(self):
        # 异步通知验证
        tag = request.form.get('tag', '').strip()
        tag_data = request.form.get('data', '').strip()

        if tag == 'tgbot':
            t = json.loads(tag_data)
            test_bool = jh.tgbotNotifyTest(t['app_token'], t['chat_id'])
            if test_bool:
                return jh.returnData(True, '验证成功')
            return jh.returnData(False, '验证失败')

        if tag == 'email':
            t = json.loads(tag_data)
            test_bool = jh.emailNotifyTest(t)
            if test_bool:
                return jh.returnData(True, '验证成功')
            return jh.returnData(False, '验证失败')

        return jh.returnData(False, '暂时未支持该验证')

    def setNotifyEnableApi(self):
        # 异步通知验证
        tag = request.form.get('tag', '').strip()
        tag_enable = request.form.get('enable', '').strip()

        data = jh.getNotifyData(False)
        op_enable = True
        op_action = '开启'
        if tag_enable != 'true':
            op_enable = False
            op_action = '关闭'

        if tag in data:
            data[tag]['enable'] = op_enable

        jh.writeNotify(data)

        return jh.returnData(True, op_action + '成功')


    def setPanelTokenApi(self):
        op_type = request.form.get('op_type', '').strip()

        api_file = self.__api_addr
        tmp = jh.readFile(api_file)
        data = json.loads(tmp)

        if op_type == '1':
            token = jh.getRandomString(32)
            data['token'] = jh.md5(token)
            data['token_crypt'] = jh.enCrypt(
                data['token'], token).decode('utf-8')
            jh.writeLog('API配置', '重新生成API-Token')
            jh.writeFile(api_file, json.dumps(data))
            return jh.returnJson(True, 'ok', token)

        elif op_type == '2':
            data['open'] = not data['open']
            stats = {True: '开启', False: '关闭'}
            if not 'token_crypt' in data:
                token = jh.getRandomString(32)
                data['token'] = jh.md5(token)
                data['token_crypt'] = jh.enCrypt(
                    data['token'], token).decode('utf-8')

            token = stats[data['open']] + '成功!'
            jh.writeLog('API配置', '%sAPI接口' % stats[data['open']])
            jh.writeFile(api_file, json.dumps(data))
            return jh.returnJson(not not data['open'], token)

        elif op_type == '3':
            limit_addr = request.form.get('limit_addr', '').strip()
            data['limit_addr'] = limit_addr.split('\n')
            jh.writeLog('API配置', '变更IP限制为[%s]' % limit_addr)
            jh.writeFile(api_file, json.dumps(data))
            return jh.returnJson(True, '保存成功!')

    def get(self):

        data = {}
        data['title'] = jh.getConfig('title')
        data['site_path'] = jh.getWwwDir()
        data['backup_path'] = jh.getBackupDir()
        sformat = 'date +"%Y-%m-%d %H:%M:%S %Z %z"'
        data['systemdate'] = jh.execShell(sformat)[0].strip()

        data['port'] = jh.getHostPort()
        data['ip'] = jh.getHostAddr()

        admin_path_file = 'data/admin_path.pl'
        if not os.path.exists(admin_path_file):
            data['admin_path'] = '/'
        else:
            data['admin_path'] = jh.readFile(admin_path_file)

        ipv6_file = 'data/ipv6.pl'
        if os.path.exists(ipv6_file):
            data['ipv6'] = 'checked'
        else:
            data['ipv6'] = ''
        
        net_env_cn_file = 'data/net_env_cn.pl'
        if os.path.exists(net_env_cn_file):
            data['net_env_cn'] = 'checked'
        else:
            data['net_env_cn'] = ''

        debug_file = 'data/debug.pl'
        if os.path.exists(debug_file):
            data['debug'] = 'checked'
        else:
            data['debug'] = ''

        ssl_file = 'data/ssl.pl'
        if os.path.exists('data/ssl.pl'):
            data['ssl'] = 'checked'
        else:
            data['ssl'] = ''

        basic_auth = 'data/basic_auth.json'
        if os.path.exists(basic_auth):
            bac = jh.readFile(basic_auth)
            bac = json.loads(bac)
            if bac['open']:
                data['basic_auth'] = 'checked'
        else:
            data['basic_auth'] = ''

        cfg_domain = 'data/bind_domain.pl'
        if os.path.exists(cfg_domain):
            domain = jh.readFile(cfg_domain)
            data['bind_domain'] = domain.strip()
        else:
            data['bind_domain'] = ''

        api_token = self.__api_addr
        if os.path.exists(api_token):
            bac = jh.readFile(api_token)
            bac = json.loads(bac)
            if bac['open']:
                data['api_token'] = 'checked'
        else:
            data['api_token'] = ''

        data['site_count'] = jh.M('sites').count()

        data['username'] = jh.M('users').where(
            "id=?", (1,)).getField('username')

        data['hook_tag'] = request.args.get('tag', '')

        # databases hook
        database_hook_file = 'data/hook_database.json'
        if os.path.exists(database_hook_file):
            df = jh.readFile(database_hook_file)
            df = json.loads(df)
            data['hook_database'] = df
        else:
            data['hook_database'] = []

        # menu hook
        menu_hook_file = 'data/hook_menu.json'
        if os.path.exists(menu_hook_file):
            df = jh.readFile(menu_hook_file)
            df = json.loads(df)
            data['hook_menu'] = df
        else:
            data['hook_menu'] = []

        # global_static hook
        global_static_hook_file = 'data/hook_global_static.json'
        if os.path.exists(global_static_hook_file):
            df = jh.readFile(global_static_hook_file)
            df = json.loads(df)
            data['hook_global_static'] = df
        else:
            data['hook_global_static'] = []

        # notiy config
        notify_data = jh.getNotifyData(True)
        notify_tag_list = ['tgbot', 'email']
        for tag in notify_tag_list:
            new_tag = 'notify_' + tag + '_enable'
            data[new_tag] = ''
            if tag in notify_data and 'enable' in notify_data[tag]:
                if notify_data[tag]['enable']:
                    data[new_tag] = 'checked'

        return data
