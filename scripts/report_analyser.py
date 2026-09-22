# coding: utf-8

import datetime
import os
import sys
import time
import copy
import re

from jinja2 import Environment, FileSystemLoader

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
CORE_DIR = os.path.join(ROOT_DIR, 'class', 'core')
PLUGIN_DIR = os.path.join(ROOT_DIR, 'class', 'plugin')
ES_MODEL_DIR = os.path.join(ROOT_DIR, 'class', 'es', 'model')
CLIENT_DIR = os.path.join(ROOT_DIR, 'scripts', 'client')

if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)
if ES_MODEL_DIR not in sys.path:
    sys.path.insert(0, ES_MODEL_DIR)
if CLIENT_DIR not in sys.path:
    sys.path.insert(0, CLIENT_DIR)

import jh
import value_tool
from log_tool import LogTool
from config_api import config_api
from get_pve_hardware_report import (
    DEFAULT_THRESHOLDS as DEFAULT_PVE_THRESHOLDS,
    NVME_SPARE_CRIT,
    NVME_SPARE_WARN,
    NVME_USED_CRIT,
    NVME_USED_WARN,
    SMART_LIFE_CRIT,
    SMART_LIFE_WARN,
    all_fans_stopped,
    get_fan_alert_state,
    determine_status,
    to_float,
    to_int,
)
from host_api import host_api
from report_state import build_delivery_state, build_validation_state, normalize_delivery_state

ES_SERVICE_DIR = os.path.join(ROOT_DIR, 'class', 'es', 'service')
if ES_SERVICE_DIR not in sys.path:
    sys.path.insert(0, ES_SERVICE_DIR)
import host_status_service as host_status_service_utils
import monitor_task_event_service as monitor_task_event_service_utils

try:
    from monitor_task_api import monitor_task_api
except Exception:
    monitor_task_api = None

try:
    from ha_api import ha_api
except Exception:
    ha_api = None

h_api = host_api()
c_api = config_api()

REPORT_CONFIG_PATH = os.path.join(ROOT_DIR, 'data', 'report_config.json')
OVERVIEW_TEMPLATE_DIR = os.path.join(ROOT_DIR, 'route', 'templates', 'report')

DEFAULT_REPORT_THRESHOLDS = {
    'cpu': 80,
    'memory': 80,
    'disk': 80,
    'ssl_cert': 14,
    'ha_enabled': True,
}

RAW_STATUS_INDEX = 'host-*-system-status-*'
RAW_XTRABACKUP_INDEX = 'host-*-xtrabackup-*'
RAW_XTRABACKUP_INC_INDEX = 'host-*-xtrabackup-inc-*'
RAW_BACKUP_INDEX = 'host-*-backup-*'
SINGLE_REPORT_INDEX = 'host-report-single'
OVERVIEW_REPORT_INDEX = 'host-report-overview'
SINGLE_REPORT_DATA_STREAM_PREFIX = 'host-report-single'
OVERVIEW_REPORT_DATA_STREAM_PREFIX = 'host-report-overview'

ANALYSIS_STALE_SECONDS = 15 * 60
PAGE_SIZE = 500


def _sensor_name(value):
    return str(value or '').strip()


def _sensor_number(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == '' or value.upper() == 'N/A':
            return None
    try:
        return float(value)
    except Exception:
        return None


def _is_obvious_temperature_noise(temp):
    name = _sensor_name(temp.get('name', '')) if isinstance(temp, dict) else ''
    normalized_name = name.lower()
    value = _sensor_number(temp.get('value')) if isinstance(temp, dict) else None
    if value is None:
        return True
    if normalized_name.startswith('auxtin') and value >= 100:
        return True
    if value == 127:
        return True
    if value <= -40:
        return True
    if normalized_name.startswith('pch_') and value == 0:
        return True
    return False


def _is_zero_default_fan_noise(fan):
    if not isinstance(fan, dict):
        return False
    name = _sensor_name(fan.get('name', ''))
    value = _sensor_number(fan.get('value'))
    return bool(re.match(r'^fan\d+$', name.lower())) and value == 0


def _is_intrusion_sensor_noise(item):
    if not isinstance(item, dict):
        return False
    name = _sensor_name(item.get('name', ''))
    return name.lower() in ('intrusion0', 'intrusion1')


def _is_zero_range_voltage_alarm_noise(volt):
    if not isinstance(volt, dict):
        return False
    name = _sensor_name(volt.get('name', ''))
    if not re.match(r'^in\d+$', name.lower()):
        return False
    min_value = _sensor_number(volt.get('min'))
    max_value = _sensor_number(volt.get('max'))
    alarm_text = '{0} {1} {2}'.format(volt.get('status', ''), volt.get('alarm', ''), volt.get('flags', ''))
    return min_value == 0 and max_value == 0 and 'ALARM' in alarm_text.upper()


def _issue_mentions_any(issue, names):
    if not isinstance(issue, dict):
        return False
    text = '{0} {1} {2}'.format(issue.get('category', ''), issue.get('message', ''), issue.get('detail', '')).lower()
    for name in names:
        if name and name.lower() in text:
            return True
    return False


def _is_obvious_sensor_noise_issue(issue, removed_names):
    if not isinstance(issue, dict):
        return False
    category = str(issue.get('category', '') or '').strip()
    text = '{0} {1} {2}'.format(category, issue.get('message', ''), issue.get('detail', '')).lower()
    if _issue_mentions_any(issue, removed_names):
        return True
    removed_default_fan = any(re.match(r'^fan\d+$', str(name or '').lower()) for name in removed_names)
    if category == '风扇' and removed_default_fan and 'cpu' not in text and ('风扇停转' in text or 'fan' in text):
        return True
    if 'intrusion0' in text or 'intrusion1' in text:
        return True
    if re.search(r'\bin\d+\b', text) and 'alarm' in text and re.search(r'min\s*[:=]\s*0', text) and re.search(r'max\s*[:=]\s*0', text):
        return True
    return False


def filter_obvious_sensor_noise(sensors, issues=None):
    """过滤 lm-sensors 中明显无效或未接传感器读数，保留真实硬件指标。"""
    if not isinstance(sensors, dict):
        sensors = {}
    cleaned = copy.deepcopy(sensors)
    removed_names = set()

    temperatures = []
    for temp in cleaned.get('temperatures', []) or []:
        if _is_obvious_temperature_noise(temp):
            removed_names.add(_sensor_name(temp.get('name', '')))
            continue
        temperatures.append(temp)
    cleaned['temperatures'] = temperatures

    fans = []
    for fan in cleaned.get('fans', []) or []:
        if _is_zero_default_fan_noise(fan):
            removed_names.add(_sensor_name(fan.get('name', '')))
            continue
        fans.append(fan)
    cleaned['fans'] = fans

    voltages = []
    for volt in cleaned.get('voltages', []) or []:
        if _is_zero_range_voltage_alarm_noise(volt):
            removed_names.add(_sensor_name(volt.get('name', '')))
            continue
        voltages.append(volt)
    cleaned['voltages'] = voltages

    for key in ('intrusions', 'intrusion'):
        if key in cleaned and isinstance(cleaned.get(key), list):
            kept_items = []
            for item in cleaned.get(key, []) or []:
                if _is_intrusion_sensor_noise(item):
                    removed_names.add(_sensor_name(item.get('name', '')))
                    continue
                kept_items.append(item)
            cleaned[key] = kept_items

    if not isinstance(issues, list):
        return cleaned, [] if issues is not None else issues

    cleaned_issues = []
    for issue in issues:
        if _is_obvious_sensor_noise_issue(issue, removed_names):
            continue
        cleaned_issues.append(issue)
    return cleaned, cleaned_issues



class HostReportAnalyser(object):
    def __init__(self, now_ts=None, logger=None, es_client=None):
        """初始化流水线运行上下文与可注入依赖。"""
        self.now_ts = int(now_ts or time.time())
        self.logger = logger
        self.log_tool = LogTool('report', callback=self.logger)
        self._es = es_client or jh.getES()
        self.es_available = True
        self.es_skip_reason = ''
        self._last_schedule_debug_rows = []
        self._overview_env = Environment(
            loader=FileSystemLoader(OVERVIEW_TEMPLATE_DIR),
            autoescape=False
        )
        self.thresholds = self.load_thresholds()

    def log(self, message):
        try:
            self.log_tool.info(str(message))
        except Exception:
            if self.logger:
                try:
                    self.logger(message)
                    return
                except Exception:
                    pass
            print(message)

    def load_thresholds(self):
        """读取报告阈值配置，并补齐默认值。"""
        data = jh.readJsonFile(REPORT_CONFIG_PATH, DEFAULT_REPORT_THRESHOLDS, auto_create=True)
        if not isinstance(data, dict):
            data = dict(DEFAULT_REPORT_THRESHOLDS)
        thresholds = dict(DEFAULT_REPORT_THRESHOLDS)
        for key in thresholds.keys():
            try:
                thresholds[key] = int(data.get(key, thresholds[key]))
            except Exception:
                thresholds[key] = DEFAULT_REPORT_THRESHOLDS[key]
        return thresholds

    def is_ha_report_enabled(self):
        if hasattr(self, 'ha_report_enabled_override'):
            return bool(self.ha_report_enabled_override)
        data = jh.readJsonFile(REPORT_CONFIG_PATH, DEFAULT_REPORT_THRESHOLDS, auto_create=True)
        if not isinstance(data, dict):
            data = {}
        return str(data.get('ha_enabled', True)).lower() not in ('0', 'false', 'no', 'off')

    def get_schedule_state(self):
        """计算已启用主机、到期主机以及对应的发送配置。"""
        dispatch_config = c_api.getReportDispatchConfigData() or {}
        report_enabled = bool(dispatch_config.get('enabled'))
        report_cron = dispatch_config.get('cron', c_api.getDefaultReportCronData())
        report_host_ids = dispatch_config.get('report_host_ids', []) or []
        report_config = {}
        for host_id in report_host_ids:
            report_config[host_id] = {
                'enabled': report_enabled,
                'cron': dict(report_cron)
            }
        self._last_schedule_debug_rows = []
        enabled_host_ids = []
        for host_id, cfg in report_config.items():
            if isinstance(cfg, dict) and cfg.get('enabled'):
                enabled_host_ids.append(host_id)

        if len(enabled_host_ids) == 0:
            return report_config, [], []

        host_rows = jh.M('view01_host').field(h_api.host_field).select()
        if isinstance(host_rows, str) or host_rows is None:
            host_rows = []

        enabled_rows = []
        for row in host_rows:
            host_id = row.get('host_id')
            if host_id in enabled_host_ids:
                enabled_rows.append(row)

        due_rows = []
        for row in enabled_rows:
            host_id = row.get('host_id')
            cfg = report_config.get(host_id, {})
            cron = dict(report_cron)
            host_due = jh.cronShouldRun(cron, 0, self.now_ts)
            self._last_schedule_debug_rows.append({
                'host_id': host_id,
                'host_name': row.get('host_name', ''),
                'is_due': host_due,
                'cron': cron,
                'reason': 'due' if host_due else 'cron_not_due'
            })
            if host_due:
                due_rows.append(row)
        return report_config, enabled_rows, due_rows

    def get_schedule_debug_rows(self):
        """返回最近一次排期计算的调试信息。"""
        return list(self._last_schedule_debug_rows)

    def get_report_window(self, report_date=None):
        """生成报告时间窗口，默认统计最近 24 小时。"""
        now_dt = datetime.datetime.fromtimestamp(self.now_ts)
        if report_date:
            if isinstance(report_date, datetime.date):
                target_date = report_date
            else:
                target_date = datetime.datetime.strptime(str(report_date), '%Y-%m-%d').date()
            if target_date == now_dt.date():
                end_dt = now_dt
            else:
                end_dt = datetime.datetime.combine(target_date, datetime.time(23, 59, 59))
        else:
            end_dt = now_dt

        start_dt = end_dt - datetime.timedelta(hours=24)
        return {
            'report_date': end_dt.strftime('%Y-%m-%d'),
            'report_time': now_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'start_date': start_dt.strftime('%Y-%m-%d'),
            'end_date': end_dt.strftime('%Y-%m-%d'),
            'start_time': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'start_timestamp': int(start_dt.timestamp()),
            'end_timestamp': int(end_dt.timestamp()),
        }

    def _get_collected_host_name(self, status_docs):
        """从最新系统状态文档读取采集端上报的主机名称。"""
        sorted_docs = sorted(
            [doc for doc in (status_docs or []) if isinstance(doc, dict)],
            key=lambda item: value_tool.safeInt(
                item.get('add_timestamp', 0),
                value_tool.parseTime(item.get('add_time', ''))
            )
        )
        for status_doc in reversed(sorted_docs):
            host_name = str(value_tool.getNested(status_doc, ['host', 'panel_title'], '') or '').strip()
            if host_name:
                return host_name
        return ''

    def _with_collected_host_name(self, host_row, status_docs=None, resolved=False):
        """复制主机数据，并将 host_name 替换为采集名称。"""
        report_host_row = dict(host_row or {})
        host_remark = report_host_row.get('host_remark')
        if host_remark is None:
            host_remark = report_host_row.get('host_name', '')
        report_host_row['host_remark'] = host_remark
        collected_host_name = self._get_collected_host_name(status_docs)
        report_host_row['collected_host_name'] = collected_host_name
        report_host_row['host_name'] = collected_host_name
        report_host_row['_collected_host_name_resolved'] = bool(resolved)
        return report_host_row

    def _resolve_report_host_rows(self, host_rows, raw_groups=None):
        """每次生成日报前，统一读取 ES 最新状态中的主机名称。"""
        latest_status_map = host_status_service_utils.getLatestStatusDocs(host_rows or [])

        resolved_rows = []
        for host_row in host_rows or []:
            host_id = str(host_row.get('host_id', '') or '').strip()
            latest_status_doc = latest_status_map.get(host_id)
            resolved_rows.append(self._with_collected_host_name(
                host_row,
                [latest_status_doc] if latest_status_doc else [],
                resolved=True
            ))
        return resolved_rows

    def _get_doc(self, index_name, doc_id):
        """兼容旧脚本：统一读取并返回 ES 文档的 _source。"""
        document = self._es.get(index_name, doc_id)
        if isinstance(document, dict):
            return document.get('_source', document)
        return document

    def _update_doc(self, index_name, doc_id, document):
        """兼容旧脚本：统一回写 ES 文档。"""
        self._es.index(index_name, doc_id, document=document)
        return True

    def _get_es_error_message(self):
        """提取 ES 客户端最近一次错误，便于向上层返回准确原因。"""
        try:
            if hasattr(self._es, 'getError'):
                error = self._es.getError()
                if error:
                    return str(error)
        except Exception:
            pass
        return ''

    def _save_report_document(self, index_name, doc_id, document):
        """保存报告文档，并立即回读确认已经成功写入 ES。"""
        result = self._es.index(index_name, doc_id, document=document)
        if not result:
            error_message = self._get_es_error_message() or 'unknown_es_index_error'
            raise RuntimeError('保存报告到ES失败 index={0} doc_id={1} error={2}'.format(index_name, doc_id, error_message))

        saved_document = self._get_doc(index_name, doc_id)
        if not isinstance(saved_document, dict):
            error_message = self._get_es_error_message() or 'document_not_found_after_index'
            raise RuntimeError('保存报告后回读失败 index={0} doc_id={1} error={2}'.format(index_name, doc_id, error_message))
        return saved_document

    def _build_report_run_id(self, window):
        """为同一次分析生成统一的运行ID，便于数据流关联单机与总览报告。"""
        return '{0}-{1}-{2}'.format(window['report_date'], self.now_ts, os.getpid())

    def _get_report_month_text(self, report_date=''):
        """将报告日期转换为 YYYY-MM，用于按月路由数据流。"""
        raw_text = str(report_date or '').strip()
        if raw_text == '':
            raw_text = datetime.datetime.fromtimestamp(self.now_ts).strftime('%Y-%m-%d')
        return datetime.datetime.strptime(raw_text, '%Y-%m-%d').strftime('%Y-%m')

    def _get_single_report_data_stream_name(self, report_date=''):
        return '{0}-{1}'.format(SINGLE_REPORT_DATA_STREAM_PREFIX, self._get_report_month_text(report_date))

    def _get_overview_report_data_stream_name(self, report_date=''):
        return '{0}-{1}'.format(OVERVIEW_REPORT_DATA_STREAM_PREFIX, self._get_report_month_text(report_date))

    def _format_data_stream_timestamp(self, time_text):
        """将面板常用时间字符串转成 ES 数据流可接受的 ISO 时间。"""
        local_tz = datetime.datetime.now().astimezone().tzinfo
        if isinstance(time_text, datetime.datetime):
            if time_text.tzinfo is None:
                time_text = time_text.replace(tzinfo=local_tz)
            return time_text.isoformat()

        raw_text = str(time_text or '').strip()
        if raw_text == '':
            return datetime.datetime.now(local_tz).isoformat()

        try:
            parsed_time = datetime.datetime.strptime(raw_text, '%Y-%m-%d %H:%M:%S')
            return parsed_time.replace(tzinfo=local_tz).isoformat()
        except Exception:
            return raw_text.replace(' ', 'T')

    def _format_es_datetime(self, time_text):
        """将本地时间字符串转成带时区的 ES 日期时间字段。"""
        return self._format_data_stream_timestamp(time_text)

    def _build_data_stream_document(self, document, report_run_id):
        """把普通索引文档转换为可写入数据流的事件文档。"""
        ds_document = copy.deepcopy(document)
        ds_document['@timestamp'] = self._format_data_stream_timestamp(document.get('report_time'))
        ds_document['report_run_id'] = report_run_id
        return ds_document

    def _append_report_data_stream_document(self, data_stream_name, document, report_run_id):
        """将报告事件追加写入数据流。"""
        ds_document = self._build_data_stream_document(document, report_run_id)
        result = self._es.appendDocument(data_stream_name, document=ds_document)
        if not result:
            error_message = self._get_es_error_message() or 'unknown_es_append_error'
            raise RuntimeError('保存报告到数据流失败 data_stream={0} report_run_id={1} error={2}'.format(
                data_stream_name,
                report_run_id,
                error_message
            ))
        return ds_document

    def _try_save_report_outputs(self, index_name, doc_id, data_stream_name, document, report_run_id):
        """ES 可用时保存报告；ES 不可用时记录并跳过，不阻断日报生成。"""
        if not self.es_available:
            self.log('[report-analysis] skip es save index={0} doc_id={1} reason={2}'.format(index_name, doc_id, self.es_skip_reason or 'ES不可用'))
            return False
        try:
            self._save_report_document(index_name, doc_id, document)
            self._append_report_data_stream_document(data_stream_name, document, report_run_id)
            return True
        except Exception as e:
            self.es_available = False
            self.es_skip_reason = 'ES保存报告失败，已跳过ES落库：{0}'.format(str(e))
            self.log('[report-analysis] skip es save index={0} doc_id={1} reason={2}'.format(index_name, doc_id, self.es_skip_reason))
            return False

    def _analyze_series(self, docs, extractor, threshold):
        """统计监控序列的平均值、当前值和超阈次数。"""
        values = []
        for doc in sorted(docs, key=lambda item: value_tool.safeInt(item.get('add_timestamp', 0), value_tool.parseTime(item.get('add_time', '')))):
            timestamp = value_tool.safeInt(doc.get('add_timestamp', 0), value_tool.parseTime(doc.get('add_time', '')))
            metric_value = value_tool.safeFloat(extractor(doc), 0.0)
            values.append({'value': metric_value, 'timestamp': timestamp})

        if len(values) == 0:
            return {'average': 0.0, 'over_count': 0, 'current': 0.0}

        last_alarm_ts = None
        over_count = 0
        total = 0.0
        for item in values:
            total += item['value']
            if threshold != -1 and item['value'] > threshold:
                if last_alarm_ts is None or (item['timestamp'] - last_alarm_ts) >= 300:
                    over_count += 1
                    last_alarm_ts = item['timestamp']

        return {
            'average': round(total / float(len(values)), 2),
            'over_count': over_count,
            'current': round(values[-1]['value'], 2)
        }

    def _build_percent_span(self, value, threshold, suffix='%'):
        """根据阈值生成带颜色的百分比 HTML。"""
        color = 'auto'
        if threshold != -1 and value > threshold:
            color = 'red'
        elif threshold != -1 and value > (threshold * 0.8):
            color = 'orange'
        if isinstance(value, float):
            value_text = '{0:.2f}'.format(value).rstrip('0').rstrip('.')
        else:
            value_text = str(value)
        return "<span style='color: {0}'>{1}{2}</span>".format(color, value_text, suffix)

    def _build_status_window_query(self, host_ids, window):
        """构造系统状态索引的窗口查询条件。"""
        return {
            'bool': {
                'filter': [
                    {
                        'bool': {
                            'should': [
                                {'terms': {'host.host_id.keyword': host_ids}},
                                {'terms': {'host.host_id': host_ids}},
                                {'terms': {'host_id.keyword': host_ids}},
                                {'terms': {'host_id': host_ids}},
                            ],
                            'minimum_should_match': 1
                        }
                    },
                    {'range': {'add_timestamp': {'gte': window['start_timestamp'], 'lte': window['end_timestamp']}}}
                ]
            }
        }

    def _build_simple_window_query(self, host_ids, window):
        """构造按 host_id + 时间窗口过滤的通用查询。"""
        return {
            'bool': {
                'filter': [
                    {
                        'bool': {
                            'should': [
                                {'terms': {'host_id.keyword': host_ids}},
                                {'terms': {'host_id': host_ids}},
                                {'terms': {'host.host_id.keyword': host_ids}},
                                {'terms': {'host.host_id': host_ids}},
                            ],
                            'minimum_should_match': 1
                        }
                    },
                    {'range': {'add_timestamp': {'gte': window['start_timestamp'], 'lte': window['end_timestamp']}}}
                ]
            }
        }

    def _build_host_only_query(self, host_ids, field_name='host_id'):
        """构造只按主机过滤的查询条件。"""
        keyword_field_name = '{0}.keyword'.format(field_name)
        return {
            'bool': {
                'filter': [
                    {
                        'bool': {
                            'should': [
                                {'terms': {keyword_field_name: host_ids}},
                                {'terms': {field_name: host_ids}}
                            ],
                            'minimum_should_match': 1
                        }
                    }
                ]
            }
        }

    def _is_doc_in_window(self, doc, window):
        """判断文档时间是否落在报告窗口内。"""
        timestamp = value_tool.safeInt(doc.get('add_timestamp', 0))
        if timestamp <= 0:
            timestamp = value_tool.parseTime(doc.get('add_time', ''))
        if timestamp <= 0:
            return False
        return window['start_timestamp'] <= timestamp <= window['end_timestamp']

    def load_raw_groups(self, host_rows, window):
        """加载并按 host_id 聚合原始监控与备份数据。"""
        host_ids = [row.get('host_id') for row in host_rows if row.get('host_id')]
        if len(host_ids) == 0:
            return {}

        def timed_search(label, index_name, body):
            start_ts = time.time()
            self.log('[report-analysis] es search start label={0} index={1} host_total={2} page_size={3}'.format(
                label,
                index_name,
                len(host_ids),
                PAGE_SIZE
            ))
            docs = self._es.searchAll(
                index=index_name,
                body=body,
                page_size=PAGE_SIZE,
                scroll='1m'
            )
            doc_count = len(docs) if isinstance(docs, list) else 'invalid'
            self.log('[report-analysis] es search done label={0} index={1} docs={2} cost={3:.3f}s'.format(
                label,
                index_name,
                doc_count,
                time.time() - start_ts
            ))
            return docs

        grouped = {}
        for row in host_rows:
            grouped[row.get('host_id')] = {
                'status': [],
                'xtrabackup': [],
                'xtrabackup_inc': [],
                'backup': []
            }

        try:
            status_docs = timed_search('system_status', RAW_STATUS_INDEX, {'query': self._build_status_window_query(host_ids, window)})
            xtrabackup_docs = timed_search('xtrabackup', RAW_XTRABACKUP_INDEX, {'query': self._build_simple_window_query(host_ids, window)})
            xtrabackup_inc_docs = timed_search('xtrabackup_inc', RAW_XTRABACKUP_INC_INDEX, {'query': self._build_simple_window_query(host_ids, window)})
            backup_docs = timed_search('backup', RAW_BACKUP_INDEX, {'query': self._build_simple_window_query(host_ids, window)})
        except Exception as e:
            self.es_available = False
            self.es_skip_reason = 'ES连接失败，已跳过主机运行数据：{0}'.format(str(e))
            self.log('[report-analysis] skip es raw docs report_date={0} reason={1}'.format(window['report_date'], self.es_skip_reason))
            return grouped

        if not isinstance(status_docs, list) or not isinstance(xtrabackup_docs, list) or not isinstance(xtrabackup_inc_docs, list) or not isinstance(backup_docs, list):
            self.es_available = False
            self.es_skip_reason = 'ES查询返回异常，已跳过主机运行数据：{0}'.format(self._get_es_error_message() or 'empty_or_invalid_response')
            self.log('[report-analysis] skip es raw docs report_date={0} reason={1}'.format(window['report_date'], self.es_skip_reason))
            return grouped

        backup_docs = [doc for doc in backup_docs if self._is_doc_in_window(doc, window)]
        self.log(
            '[report-analysis] raw docs loaded report_date={0} status_index={1} status={2} xtrabackup={3} xtrabackup_inc={4} backup={5}'.format(
                window['report_date'],
                RAW_STATUS_INDEX,
                len(status_docs),
                len(xtrabackup_docs),
                len(xtrabackup_inc_docs),
                len(backup_docs)
            )
        )
        for doc in status_docs:
            host_id = value_tool.getNested(doc, ['host', 'host_id'], '') or doc.get('host_id', '')
            if host_id in grouped:
                grouped[host_id]['status'].append(doc)

        for doc in xtrabackup_docs:
            host_id = doc.get('host_id', '')
            if host_id in grouped:
                grouped[host_id]['xtrabackup'].append(doc)

        for doc in xtrabackup_inc_docs:
            host_id = doc.get('host_id', '')
            if host_id in grouped:
                grouped[host_id]['xtrabackup_inc'].append(doc)

        for doc in backup_docs:
            host_id = doc.get('host_id', '')
            if host_id in grouped:
                grouped[host_id]['backup'].append(doc)

        for row in host_rows:
            host_id = row.get('host_id')
            current_group = grouped.get(host_id, {})
            self.log(
                '[report-analysis] raw docs grouped report_date={0} host_id={1} host_name={2} status={3} xtrabackup={4} xtrabackup_inc={5} backup={6}'.format(
                    window['report_date'],
                    host_id,
                    row.get('host_name', ''),
                    len(current_group.get('status', []) or []),
                    len(current_group.get('xtrabackup', []) or []),
                    len(current_group.get('xtrabackup_inc', []) or []),
                    len(current_group.get('backup', []) or [])
                )
            )

        return grouped

    def _summarize_backup_rows(self, rows):
        """从备份原始记录中提炼最新时间与统计信息。"""
        if len(rows) == 0:
            return {
                'last_backup_time': None,
                'last_backup_timestamp': 0,
                'count_in_timeframe': 0,
                'last_backup_size': '无',
                'last_backup_size_bytes': 0
            }

        rows = sorted(rows, key=lambda item: value_tool.safeInt(item.get('add_timestamp', 0), value_tool.parseTime(item.get('add_time', ''))))
        last_row = rows[-1]
        return {
            'last_backup_time': last_row.get('add_time'),
            'last_backup_timestamp': value_tool.safeInt(last_row.get('add_timestamp', 0), value_tool.parseTime(last_row.get('add_time', ''))),
            'count_in_timeframe': len(rows),
            'last_backup_size': last_row.get('size', '无'),
            'last_backup_size_bytes': value_tool.safeInt(last_row.get('size_bytes', 0)),
        }

    def _merge_backup_summary(self, runtime_summary, raw_summary):
        """合并运行时备份摘要与 ES 原始备份摘要。"""
        runtime_summary = runtime_summary or {}
        merged = dict(runtime_summary)
        if not merged.get('last_backup_time') and raw_summary.get('last_backup_time'):
            merged['last_backup_time'] = raw_summary.get('last_backup_time')
        if value_tool.safeInt(merged.get('last_backup_timestamp', 0)) <= 0:
            merged['last_backup_timestamp'] = raw_summary.get('last_backup_timestamp', 0)
        if value_tool.safeInt(merged.get('count_in_timeframe', 0)) <= 0:
            merged['count_in_timeframe'] = raw_summary.get('count_in_timeframe', 0)
        if not merged.get('last_backup_size'):
            merged['last_backup_size'] = raw_summary.get('last_backup_size', '无')
        if value_tool.safeInt(merged.get('last_backup_size_bytes', 0)) <= 0:
            merged['last_backup_size_bytes'] = raw_summary.get('last_backup_size_bytes', 0)
        return merged

    def _build_system_section(self, status_docs, window, validation_errors):
        """生成 CPU、内存、磁盘等系统资源报告段落。"""
        sysinfo_tips = []
        summary_error_keys = []
        error_tips = []
        latest_doc = status_docs[-1] if status_docs else {}
        latest_ts = value_tool.safeInt(latest_doc.get('add_timestamp', 0), value_tool.parseTime(latest_doc.get('add_time', '')))

        cpu_stats = self._analyze_series(status_docs, lambda doc: value_tool.getNested(doc, ['system', 'cpu'], 0), self.thresholds['cpu'])
        mem_stats = self._analyze_series(status_docs, lambda doc: value_tool.getNested(doc, ['system', 'memory'], 0), self.thresholds['memory'])
        load_stats = self._analyze_series(status_docs, lambda doc: value_tool.getNested(doc, ['system', 'load', 'pro'], 0), self.thresholds['cpu'])

        cpu_desc = '平均使用率{0}<br/>当前CPU使用率：{1}'.format(
            self._build_percent_span(cpu_stats['average'], self.thresholds['cpu']),
            self._build_percent_span(cpu_stats['current'], self.thresholds['cpu'])
        )
        if self.thresholds['cpu'] != -1 and cpu_stats['over_count'] > 0:
            cpu_desc += '，<span style="color: red">异常（使用率超过{0}%）{1}次</span>'.format(self.thresholds['cpu'], cpu_stats['over_count'])
        sysinfo_tips.append({'name': 'CPU', 'desc': cpu_desc})
        if self.thresholds['cpu'] != -1 and cpu_stats['average'] > self.thresholds['cpu']:
            summary_error_keys.append('CPU')

        mem_desc = '平均使用率{0}<br/>当前内存使用率：{1}'.format(
            self._build_percent_span(mem_stats['average'], self.thresholds['memory']),
            self._build_percent_span(mem_stats['current'], self.thresholds['memory'])
        )
        if self.thresholds['memory'] != -1 and mem_stats['over_count'] > 0:
            mem_desc += '，<span style="color: red">异常（使用率超过{0}%）{1}次</span>'.format(self.thresholds['memory'], mem_stats['over_count'])
        sysinfo_tips.append({'name': '内存', 'desc': mem_desc})
        if self.thresholds['memory'] != -1 and mem_stats['average'] > self.thresholds['memory']:
            summary_error_keys.append('内存')

        load_desc = '平均使用率{0}'.format(self._build_percent_span(load_stats['average'], self.thresholds['cpu']))
        if self.thresholds['cpu'] != -1 and load_stats['over_count'] > 0:
            load_desc += '，<span style="color: red">异常（使用率超过{0}%）{1}次</span>'.format(self.thresholds['cpu'], load_stats['over_count'])
        sysinfo_tips.append({'name': '资源使用率', 'desc': load_desc})
        if self.thresholds['cpu'] != -1 and load_stats['average'] > self.thresholds['cpu']:
            summary_error_keys.append('资源使用率')

        latest_disks = value_tool.getNested(latest_doc, ['system', 'disks'], []) or []
        for disk in latest_disks:
            size_info = disk.get('size', []) or []
            used_percent_text = ''
            used_text = ''
            total_text = ''
            if len(size_info) >= 4:
                total_text = size_info[0]
                used_text = size_info[1]
                used_percent_text = size_info[3]
            used_percent = value_tool.safeInt(str(used_percent_text).replace('%', ''), 0)
            sysinfo_tips.append({
                'name': '磁盘（{0}）'.format(disk.get('path', '未知路径')),
                'desc': '已使用{0}（{1}/{2}）'.format(
                    self._build_percent_span(used_percent, self.thresholds['disk']),
                    used_text or '0B',
                    total_text or '0B'
                )
            })
            if self.thresholds['disk'] != -1 and used_percent > self.thresholds['disk']:
                disk_name = '磁盘（{0}）'.format(disk.get('path', '未知路径'))
                summary_error_keys.append(disk_name)
                error_tips.append(disk_name + '使用率过高')

        last_monitor_text = latest_doc.get('add_time', '')
        last_monitor_desc = value_tool.escapeHtml(last_monitor_text or '无数据')
        if latest_ts and latest_ts < (window['end_timestamp'] - ANALYSIS_STALE_SECONDS):
            validation_errors.append('stale_system_status')
            last_monitor_desc = "<span style='color: red'>{0}</span>".format(last_monitor_desc)
        else:
            last_monitor_desc = "<span style='color: auto'>{0}</span>".format(last_monitor_desc)
        sysinfo_tips.append({'name': '最后监控时间', 'desc': last_monitor_desc})

        summary_tips = []
        if len(summary_error_keys) > 0:
            summary_text = '、'.join(summary_error_keys) + '平均使用率过高，有服务中断停机风险'
            summary_tips.append("<span style='color: red;'>{0}</span>".format(summary_text))
            error_tips.append(summary_text)
        if latest_ts and latest_ts < (window['end_timestamp'] - ANALYSIS_STALE_SECONDS):
            summary_tips.append("<span style='color: red;'>系统异常监控状态异常，异常情况通知可能不及时</span>")
            error_tips.append('系统监控状态异常')

        return {
            'tips': sysinfo_tips,
            'summary_tips': summary_tips,
            'error_tips': error_tips,
            'latest_doc': latest_doc,
            'latest_timestamp': latest_ts,
            'cpu_stats': cpu_stats,
            'mem_stats': mem_stats,
            'load_stats': load_stats,
        }

    def _get_latest_rsyncd_check_doc(self, rsyncd_check_docs):
        if not rsyncd_check_docs:
            return None
        return sorted(
            rsyncd_check_docs,
            key=lambda item: value_tool.safeInt(item.get('add_timestamp', 0), value_tool.parseTime(item.get('add_time', '')))
        )[-1]

    def _build_rsyncd_check_section(self, rsyncd_check_docs, window, validation_errors):
        """基于 collector 执行 tool_check.py 的结果生成 Rsyncd 报告段落。"""
        latest_check = self._get_latest_rsyncd_check_doc(rsyncd_check_docs)
        if not latest_check:
            return {
                'tips': [],
                'summary_tips': [],
                'summary_names': [],
                'error_tips': []
            }

        check_status = str(latest_check.get('status', '') or '')
        message = latest_check.get('message', '') or ''
        add_time = latest_check.get('add_time', '') or '无'
        execute_ok = bool(latest_check.get('execute_ok'))
        result = latest_check.get('result') if isinstance(latest_check.get('result'), dict) else {}

        desc_parts = [
            '检查时间：{0}'.format(value_tool.escapeHtml(add_time)),
            '执行状态：{0}'.format(
                '<span style="color: green">成功</span>' if execute_ok else '<span style="color: red">异常</span>'
            )
        ]
        if message:
            color = 'auto' if check_status in ('normal', 'skipped') else 'red'
            desc_parts.append('说明：<span style="color: {0}">{1}</span>'.format(color, value_tool.escapeHtml(message)))

        summary_names = []
        summary_tips = []
        error_tips = []
        if check_status == 'abnormal' or (latest_check.get('tool_check_exists') is False and latest_check.get('rsyncd_server_exists')):
            summary_names.append('Rsyncd')
            error_tips.append('Rsyncd检查异常：' + (message or 'tool_check.py 执行异常'))
            validation_errors.append('rsyncd_tool_check_abnormal')

        if execute_ok and isinstance(result, dict):
            send_count = value_tool.safeInt(result.get('send_count', 0))
            open_count = value_tool.safeInt(result.get('send_open_count', 0))
            realtime_delays = value_tool.safeInt(result.get('realtime_delays', 0))
            desc_parts.append('任务数量：启用 {0} / 总数 {1}'.format(open_count, send_count))
            desc_parts.append('实时同步延迟文件数：{0}'.format(
                '<span style="color: orange">{0}</span>'.format(realtime_delays) if realtime_delays > 0 else str(realtime_delays)
            ))
            if realtime_delays > 0:
                summary_tips.append("<span style='color: orange;'>实时备份文件延迟{0}个</span>".format(realtime_delays))

            realtime_ok = result.get('realtime_format_ok', True)
            realtime_reason = result.get('realtime_format_reason', '') or ''
            if realtime_ok is False:
                desc_parts.append('实时同步状态：<span style="color: red">异常（{0}）</span>'.format(value_tool.escapeHtml(realtime_reason)))
                summary_names.append('实时备份')
                error_tips.append('实时同步状态异常：' + realtime_reason)
                validation_errors.append('rsyncd_realtime_abnormal')
            else:
                desc_parts.append('实时同步状态：<span style="color: auto">正常</span>')

            fixtime_abnormal_tasks = result.get('fixtime_abnormal_tasks', []) or []
            if len(fixtime_abnormal_tasks) > 0:
                names = []
                details = []
                for task in fixtime_abnormal_tasks:
                    task_name = str(task.get('name', '') or '')
                    reason = str(task.get('reason', '') or '')
                    names.append(task_name)
                    details.append('{0}（{1}）'.format(task_name, reason))
                desc_parts.append('定时同步异常：<span style="color: red">{0}</span>'.format(value_tool.escapeHtml('、'.join(details))))
                summary_names.extend([name for name in names if name])
                error_tips.append('定时同步状态异常：' + '；'.join(details))
                validation_errors.append('rsyncd_fixtime_abnormal')
            else:
                desc_parts.append('定时同步状态：<span style="color: auto">正常</span>')

            for item in result.get('send_open_fixtime_list', []) or []:
                item_name = str(item.get('name', '') or '')
                last_sync_at = str(item.get('last_sync_at', '') or '无')
                reason = str(item.get('log_format_reason', '') or '')
                line = '- {0}：{1}'.format(value_tool.escapeHtml(item_name), value_tool.escapeHtml(last_sync_at))
                if item.get('log_format_ok') is False:
                    line += ' <span style="color: red">[同步异常：{0}]</span>'.format(value_tool.escapeHtml(reason))
                desc_parts.append(line)

        return {
            'tips': [{'name': 'Rsyncd', 'desc': '<br/>'.join(desc_parts)}],
            'summary_tips': summary_tips,
            'summary_names': summary_names,
            'error_tips': error_tips
        }

    def _build_backup_section(self, latest_doc, xtrabackup_docs, xtrabackup_inc_docs, backup_docs, window, validation_errors):
        """生成备份状态段落，并校验备份证据是否完整。"""
        backup_tips = []
        summary_tips = []
        summary_names = []
        error_tips = []
        runtime_backup = latest_doc.get('backup', {}) if isinstance(latest_doc, dict) else {}
        rsyncd_check_docs = [
            doc for doc in backup_docs
            if str(doc.get('collector_source', '') or '') == 'jh-panel-rsyncd-tool-check'
        ]
        normal_backup_docs = [
            doc for doc in backup_docs
            if str(doc.get('collector_source', '') or '') != 'jh-panel-rsyncd-tool-check'
        ]

        xtrabackup_runtime = runtime_backup.get('xtrabackup', {}) if isinstance(runtime_backup, dict) else {}
        xtrabackup_summary = self._merge_backup_summary(xtrabackup_runtime, self._summarize_backup_rows(xtrabackup_docs))
        xtrabackup_enabled = bool(xtrabackup_runtime.get('enabled'))
        xtrabackup_visible = xtrabackup_enabled or len(xtrabackup_docs) > 0 or bool(xtrabackup_summary.get('last_backup_time'))
        if xtrabackup_visible:
            last_time = xtrabackup_summary.get('last_backup_time') or '无'
            count_in_window = value_tool.safeInt(xtrabackup_summary.get('count_in_timeframe', 0))
            desc = '状态：{0}<br/>最后成功时间：{1}<br/>窗口内备份次数：{2}'.format(
                '<span style="color: auto">已启用</span>' if xtrabackup_enabled else '<span style="color: #999">未启用</span>',
                last_time,
                count_in_window
            )
            backup_tips.append({'name': 'Xtrabackup', 'desc': desc})
            last_ts = value_tool.safeInt(xtrabackup_summary.get('last_backup_timestamp', 0), value_tool.parseTime(last_time))
            if xtrabackup_enabled and (count_in_window <= 0 or last_ts < window['start_timestamp']):
                summary_names.append('Xtrabackup')
                validation_errors.append('missing_xtrabackup_evidence')

        inc_full_docs = []
        inc_inc_docs = []
        for doc in xtrabackup_inc_docs:
            backup_type = str(doc.get('backup_type', '')).lower()
            if backup_type == 'full':
                inc_full_docs.append(doc)
            else:
                inc_inc_docs.append(doc)
        xtrabackup_inc_runtime = runtime_backup.get('xtrabackup_inc', {}) if isinstance(runtime_backup, dict) else {}
        inc_full_runtime = xtrabackup_inc_runtime.get('full', {}) if isinstance(xtrabackup_inc_runtime, dict) else {}
        inc_inc_runtime = xtrabackup_inc_runtime.get('inc', {}) if isinstance(xtrabackup_inc_runtime, dict) else {}
        inc_full_summary = self._merge_backup_summary(inc_full_runtime, self._summarize_backup_rows(inc_full_docs))
        inc_inc_summary = self._merge_backup_summary(inc_inc_runtime, self._summarize_backup_rows(inc_inc_docs))
        xtrabackup_inc_enabled = bool(xtrabackup_inc_runtime.get('enabled'))
        xtrabackup_inc_visible = xtrabackup_inc_enabled or len(xtrabackup_inc_docs) > 0 or bool(inc_full_summary.get('last_backup_time')) or bool(inc_inc_summary.get('last_backup_time'))
        if xtrabackup_inc_visible:
            full_time = inc_full_summary.get('last_backup_time') or '无'
            inc_time = inc_inc_summary.get('last_backup_time') or '无'
            desc = '状态：{0}<br/>全量：{1}<br/>增量：{2}<br/>窗口内全量/增量次数：{3}/{4}'.format(
                '<span style="color: auto">已启用</span>' if xtrabackup_inc_enabled else '<span style="color: #999">未启用</span>',
                full_time,
                inc_time,
                value_tool.safeInt(inc_full_summary.get('count_in_timeframe', 0)),
                value_tool.safeInt(inc_inc_summary.get('count_in_timeframe', 0))
            )
            backup_tips.append({'name': 'Xtrabackup增量', 'desc': desc})
            full_ok = value_tool.safeInt(inc_full_summary.get('count_in_timeframe', 0)) > 0 and value_tool.safeInt(inc_full_summary.get('last_backup_timestamp', 0), value_tool.parseTime(full_time)) >= window['start_timestamp']
            inc_ok = value_tool.safeInt(inc_inc_summary.get('count_in_timeframe', 0)) > 0 and value_tool.safeInt(inc_inc_summary.get('last_backup_timestamp', 0), value_tool.parseTime(inc_time)) >= window['start_timestamp']
            if xtrabackup_inc_enabled and not (full_ok and inc_ok):
                summary_names.append('Xtrabackup增量')
                validation_errors.append('missing_xtrabackup_inc_evidence')

        mysql_dump_runtime = runtime_backup.get('mysql_dump', {}) if isinstance(runtime_backup, dict) else {}
        mysql_dump_enabled = bool(mysql_dump_runtime.get('enabled'))
        mysql_dump_visible = mysql_dump_enabled or bool(mysql_dump_runtime.get('last_backup_time'))
        if mysql_dump_visible:
            last_dump_time = mysql_dump_runtime.get('last_backup_time') or '无'
            dump_count = value_tool.safeInt(mysql_dump_runtime.get('count_in_timeframe', 0))
            abnormal_dump_files = value_tool.safeInt(mysql_dump_runtime.get('abnormal_files_in_timeframe', 0))
            desc = '状态：{0}<br/>最后成功时间：{1}<br/>窗口内备份次数：{2}'.format(
                '<span style="color: auto">已启用</span>' if mysql_dump_enabled else '<span style="color: #999">未启用</span>',
                last_dump_time,
                dump_count
            )
            if abnormal_dump_files > 0:
                desc += '<br/><span style="color: orange">异常备份文件：{0}个</span>'.format(abnormal_dump_files)
            backup_tips.append({'name': 'MySQL Dump', 'desc': desc})
            if mysql_dump_enabled and dump_count <= 0:
                summary_names.append('MySQL Dump')
                validation_errors.append('missing_mysql_dump_evidence')

        rsyncd_section = self._build_rsyncd_check_section(rsyncd_check_docs, window, validation_errors)
        backup_tips.extend(rsyncd_section.get('tips', []))
        summary_tips.extend(rsyncd_section.get('summary_tips', []))
        summary_names.extend(rsyncd_section.get('summary_names', []))
        error_tips.extend(rsyncd_section.get('error_tips', []))

        if len(normal_backup_docs) > 0:
            latest_backup_event = sorted(normal_backup_docs, key=lambda item: value_tool.parseTime(item.get('add_time', '')))[-1]
            event_message = latest_backup_event.get('message', '') or latest_backup_event.get('filename', '') or latest_backup_event.get('path', '') or '存在备份事件记录'
            backup_tips.append({
                'name': '备份事件',
                'desc': '窗口内事件数：{0}<br/>{1}'.format(len(normal_backup_docs), value_tool.escapeHtml(event_message))
            })

        if len(backup_tips) == 0:
            backup_tips.append({
                'name': '备份状态',
                'desc': '<span style="color: #999">未检测到已启用备份任务或 rsyncd 检查数据</span>'
            })

        if len(summary_names) > 0:
            summary_text = '、'.join(summary_names) + '备份状态异常'
            summary_tips.append("<span style='color: red;'>{0}</span>".format(summary_text))
            error_tips.append(summary_text)

        return {
            'tips': backup_tips,
            'summary_tips': summary_tips,
            'error_tips': error_tips,
            'runtime_backup': runtime_backup,
        }

    def _build_site_section(self, latest_doc):
        """生成站点运行状态与证书有效期段落。"""
        site_tips = []
        summary_tips = []
        error_tips = []
        site_warning_names = []
        site_rows = latest_doc.get('site', []) if isinstance(latest_doc, dict) else []
        for site in site_rows:
            site_name = site.get('name', '') or '未命名站点'
            is_enabled = str(site.get('status', '')) == '1'
            site_status = '<span>运行中</span>' if is_enabled else '<span style="color: #999">已停止</span>'
            cert_data = site.get('ssl_data') or {}
            ssl_type = site.get('ssl_type') or ''
            cert_status = '未配置'
            if cert_data:
                cert_not_after = cert_data.get('notAfter', '0000-00-00')
                cert_endtime = value_tool.safeInt(cert_data.get('endtime', 0))
                if cert_endtime < 0:
                    if is_enabled:
                        cert_status = '{0}到期，已过期<span style="color: red">{1}</span>天'.format(cert_not_after, abs(cert_endtime))
                        site_warning_names.append(site_name)
                    else:
                        cert_status = '{0}到期，已过期{1}天'.format(cert_not_after, abs(cert_endtime))
                else:
                    if is_enabled:
                        color = 'auto'
                        if cert_endtime < 3:
                            color = 'red'
                        elif cert_endtime < self.thresholds['ssl_cert']:
                            color = 'orange'
                        cert_status = '将于{0}到期，还有<span style="color: {1}">{2}</span>天{3}'.format(
                            cert_not_after,
                            color,
                            cert_endtime,
                            '，到期后将自动续签' if ssl_type in ('lets', 'acme') else ''
                        )
                        if ssl_type not in ('lets', 'acme') and cert_endtime < self.thresholds['ssl_cert']:
                            site_warning_names.append(site_name)
                    else:
                        cert_status = '将于{0}到期，还有{1}天{2}'.format(
                            cert_not_after,
                            cert_endtime,
                            '，到期后将自动续签' if ssl_type in ('lets', 'acme') else ''
                        )
            site_tips.append({'name': site_name, 'desc': '{0}（SSL证书{1}）'.format(site_status, cert_status)})
        if len(site_warning_names) > 0:
            summary_text = '、'.join(site_warning_names) + '域名证书需要及时更新'
            summary_tips.append("<span style='color: red;'>{0}</span>".format(summary_text))
            error_tips.append(summary_text)
        return {
            'tips': site_tips,
            'summary_tips': summary_tips,
            'error_tips': error_tips,
        }

    def _build_runtime_service_section(self, latest_doc, key_name, section_title, stop_color):
        """生成 JianghuJS、Docker 等运行服务状态段落。"""
        tips = []
        rows = latest_doc.get(key_name, []) if isinstance(latest_doc, dict) else []
        for item in rows:
            status_text = '<span>已启动</span>' if str(item.get('status', '')) == 'start' else '<span style="color: {0}">已停止</span>'.format(stop_color)
            tips.append({'name': item.get('name', '') or section_title, 'desc': status_text})
        return tips

    def _build_mysql_section(self, status_docs):
        """生成数据库容量变化与 Top 表信息段落。"""
        mysqlinfo_tips = []
        if len(status_docs) == 0:
            return mysqlinfo_tips
        first_doc = status_docs[0]
        latest_doc = status_docs[-1]
        first_mysql = first_doc.get('mysql', {}) if isinstance(first_doc, dict) else {}
        latest_mysql = latest_doc.get('mysql', {}) if isinstance(latest_doc, dict) else {}

        total_size = latest_mysql.get('total_size', '0B')
        total_size_bytes = value_tool.safeInt(latest_mysql.get('total_size_bytes', 0))
        first_total_size_bytes = value_tool.safeInt(first_mysql.get('total_size_bytes', 0))
        total_change = total_size_bytes - first_total_size_bytes
        total_change_text = jh.toSize(abs(total_change))
        if total_change > 0:
            total_change_text = '+{0}'.format(total_change_text)
        elif total_change == 0:
            total_change_text = '0B'
        mysqlinfo_tips.append({
            'name': '数据库总大小',
            'desc': '变化：{0}<br/>总大小：{1}'.format(total_change_text, total_size)
        })

        first_table_map = {}
        for item in first_mysql.get('tables', []) or []:
            first_table_map[item.get('table_name', '')] = value_tool.safeInt(item.get('size_bytes', 0))

        latest_tables = latest_mysql.get('tables', []) or []
        latest_tables = sorted(latest_tables, key=lambda item: value_tool.safeInt(item.get('size_bytes', 0)), reverse=True)
        for item in latest_tables[:20]:
            table_name = item.get('table_name', '')
            size_bytes = value_tool.safeInt(item.get('size_bytes', 0))
            change_bytes = size_bytes - value_tool.safeInt(first_table_map.get(table_name, 0))
            change_text = jh.toSize(abs(change_bytes))
            if change_bytes > 0:
                change_text = '+{0}'.format(change_text)
            elif change_bytes == 0:
                change_text = '0B'
            mysqlinfo_tips.append({
                'name': table_name,
                'desc': '变化：{0}<br/>总大小：{1}'.format(change_text, item.get('size', jh.toSize(size_bytes)))
            })
        return mysqlinfo_tips

    def _is_pve_status_doc(self, status_doc):
        if not isinstance(status_doc, dict):
            return False
        if str(status_doc.get('log_index', '') or '') == 'host-pve-system-status':
            return True
        if str(value_tool.getNested(status_doc, ['system', 'system_type'], '') or '').lower() == 'pve':
            return True
        if isinstance(status_doc.get('pve'), dict):
            return True
        return False

    def _is_pve_host(self, host_row, status_docs=None):
        if value_tool.safeBool(host_row.get('is_pve')):
            return True
        for status_doc in status_docs or []:
            if self._is_pve_status_doc(status_doc):
                return True
        return False

    def _format_pve_bytes(self, value):
        try:
            return jh.toSize(int(float(value or 0)))
        except Exception:
            return '0B'

    def _format_pve_issue_summary(self, issues):
        summary_tips = []
        error_tips = []
        issue_groups = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            category = issue.get('category', '未知')
            issue_groups.setdefault(category, []).append(issue)

        for category, items in issue_groups.items():
            has_critical = any(item.get('severity') == 'critical' for item in items)
            color = 'red' if has_critical else 'orange'
            messages = [item.get('message', '') for item in items if str(item.get('message', '')).strip() != '']
            if messages:
                summary_tips.append("<span style='color: {0};'>{1}: {2}</span>".format(color, category, ', '.join(messages)))
            if has_critical:
                for item in items:
                    if item.get('severity') == 'critical' and str(item.get('message', '')).strip() != '':
                        error_tips.append('{0}: {1}'.format(category, item.get('message', '')))
        return summary_tips, error_tips

    def _build_pve_report_payload(self, host_row, latest_doc, window, validation_errors):
        host_name = host_row.get('host_name', '')
        host_ip = host_row.get('ip', '')
        pve_status = latest_doc.get('pve', {}) if isinstance(latest_doc, dict) else {}
        if not isinstance(pve_status, dict):
            pve_status = {}

        pve_data = pve_status.get('data', {}) or {}
        if not isinstance(pve_data, dict):
            pve_data = {}
        pve_issues = pve_status.get('issues', []) or []
        if not isinstance(pve_issues, list):
            pve_issues = []
        thresholds = dict(DEFAULT_PVE_THRESHOLDS)
        if isinstance(pve_status.get('thresholds'), dict):
            thresholds.update(pve_status.get('thresholds'))
        collect_error = str(pve_status.get('error', '')).strip()

        sysinfo_tips = []
        network_tips = []
        smart_tips = []
        io_tips = []
        sensor_tips = []
        power_tips = []
        summary_tips = []
        error_tips = []
        collect_errors = []

        if not pve_status or not pve_data:
            validation_errors.append('missing_pve_system_status')
            summary_tips.append("<span style='color: red;'>PVE系统原始数据缺失，报告未生成完整</span>")
            error_tips.append('PVE系统原始数据缺失')

        cpu = pve_data.get('cpu', {})
        if cpu.get('error'):
            collect_errors.append('CPU：' + str(cpu.get('error')))
        else:
            usage = cpu.get('usage', 0)
            load = cpu.get('load', [0, 0, 0]) or [0, 0, 0]
            while len(load) < 3:
                load.append(0)
            color = 'red' if usage >= thresholds['cpu_crit'] else 'orange' if usage >= thresholds['cpu_warn'] else 'auto'
            cpu_desc = "当前使用率：<span style='color: {0}'>{1}%</span><br/>负载: {2}, {3}, {4} (1/5/15分钟)".format(
                color,
                usage,
                load[0],
                load[1],
                load[2]
            )
            top_procs = cpu.get('top_processes', [])
            if top_procs:
                cpu_desc += "<br/>TOP5进程:<br/>" + "<br/>".join([
                    "{0}. {1}: {2}% (PID: {3})".format(
                        index + 1,
                        proc.get('command', '')[:50],
                        proc.get('cpu', 0),
                        proc.get('pid', '')
                    )
                    for index, proc in enumerate(top_procs[:5])
                ])
            sysinfo_tips.append({'name': 'CPU', 'desc': cpu_desc})

        mem = pve_data.get('memory', {})
        if mem.get('error'):
            collect_errors.append('内存：' + str(mem.get('error')))
        else:
            usage_percent = mem.get('usage_percent', 0)
            color = 'red' if usage_percent >= thresholds['mem_crit'] else 'orange' if usage_percent >= thresholds['mem_warn'] else 'auto'
            mem_desc = "总内存: {0}<br/>已使用: {1} (<span style='color: {2}'>{3}%</span>)<br/>可用: {4}".format(
                self._format_pve_bytes(mem.get('total', 0)),
                self._format_pve_bytes(mem.get('used', 0)),
                color,
                usage_percent,
                self._format_pve_bytes(mem.get('available', 0))
            )
            sysinfo_tips.append({'name': '内存', 'desc': mem_desc})

        disk = pve_data.get('disk', {})
        if disk.get('error'):
            collect_errors.append('磁盘容量：' + str(disk.get('error')))
        else:
            for fs in disk.get('filesystems', []):
                use_percent = fs.get('use_percent', 0)
                color = 'red' if use_percent >= thresholds['disk_crit'] else 'orange' if use_percent >= thresholds['disk_warn'] else 'auto'
                sysinfo_tips.append({
                    'name': '磁盘({0})'.format(fs.get('mountpoint', '-')),
                    'desc': "已使用<span style='color: {0}'>{1}%</span>（{2}/{3}）".format(
                        color,
                        use_percent,
                        fs.get('used', '-'),
                        fs.get('size', '-')
                    )
                })

        sysinfo_tips.append({
            'name': '最后监控时间',
            'desc': value_tool.escapeHtml(latest_doc.get('add_time', '') if isinstance(latest_doc, dict) else '') or '无'
        })

        net = pve_data.get('network', {})
        if net.get('error'):
            collect_errors.append('网络：' + str(net.get('error')))
        else:
            for iface in net.get('interfaces', []):
                state = iface.get('state', 'UNKNOWN')
                state_color = 'red' if state == 'DOWN' else 'orange' if state == 'UNKNOWN' else 'auto'
                err_count = iface.get('rx_errors', 0) + iface.get('tx_errors', 0)
                err_color = 'red' if err_count > 0 else 'auto'
                network_tips.append({
                    'name': '网络({0})'.format(iface.get('name', '-')),
                    'desc': "状态: <span style='color: {0}'>{1}</span><br/>接收: {2} ({3} 包, <span style='color: {4}'>{5} 错误</span>)<br/>发送: {6} ({7} 包, <span style='color: {4}'>{8} 错误</span>)".format(
                        state_color,
                        state,
                        self._format_pve_bytes(iface.get('rx_bytes', 0)),
                        iface.get('rx_packets', 0),
                        err_color,
                        iface.get('rx_errors', 0),
                        self._format_pve_bytes(iface.get('tx_bytes', 0)),
                        iface.get('tx_packets', 0),
                        iface.get('tx_errors', 0)
                    )
                })

        smart = pve_data.get('smart', {})
        if smart.get('error'):
            collect_errors.append('磁盘SMART：' + str(smart.get('error')))
        else:
            for dev in smart.get('devices', []):
                health = dev.get('health', 'unknown')
                health_color = 'green' if health == 'passed' else 'red' if health == 'failed' else 'orange'
                desc_parts = [
                    '型号: {0}'.format(dev.get('model', '未知')),
                    '类型: {0}'.format(dev.get('type', '未知')),
                    "健康状态: <span style='color: {0}'>{1}</span>".format(health_color, str(health).upper())
                ]
                if dev.get('serial') and dev.get('serial') != '未知':
                    desc_parts.append('序列号: {0}'.format(dev.get('serial')))
                if dev.get('capacity') and dev.get('capacity') != '未知':
                    desc_parts.append('容量: {0}'.format(dev.get('capacity')))
                if dev.get('health_score') is not None:
                    desc_parts.append('健康度: {0}%'.format(dev.get('health_score')))
                temp = dev.get('temperature')
                if temp is not None:
                    temp_status = determine_status(temp, thresholds['temp_warn'], thresholds['temp_crit'])
                    temp_color = 'red' if temp_status == 'critical' else 'orange' if temp_status == 'warning' else 'auto'
                    desc_parts.append("温度: <span style='color: {0}'>{1}°C</span>".format(temp_color, temp))
                if dev.get('is_nvme'):
                    nvme = dev.get('nvme', {})
                    spare = to_float(nvme.get('available_spare'))
                    if spare:
                        spare_status = determine_status(spare, NVME_SPARE_WARN, NVME_SPARE_CRIT, reverse=True)
                        spare_color = 'red' if spare_status == 'critical' else 'orange' if spare_status == 'warning' else 'auto'
                        desc_parts.append("备用空间: <span style='color: {0}'>{1}%</span>".format(spare_color, spare))
                    used = to_float(nvme.get('percentage_used'))
                    if used:
                        used_status = determine_status(used, NVME_USED_WARN, NVME_USED_CRIT)
                        used_color = 'red' if used_status == 'critical' else 'orange' if used_status == 'warning' else 'auto'
                        desc_parts.append("已用寿命: <span style='color: {0}'>{1}%</span>".format(used_color, used))
                    media_errors = to_int(nvme.get('media_and_data_integrity_errors'))
                    if media_errors:
                        desc_parts.append("媒体错误: <span style='color: red'>{0}</span>".format(media_errors))
                else:
                    attrs = {attr.get('id'): attr for attr in dev.get('attributes', [])}
                    life_attr = attrs.get('231')
                    if life_attr:
                        life_raw = life_attr.get('raw_int', 0)
                        life_val = life_attr.get('value', 0)
                        life = life_raw if life_raw > 0 else life_val
                        life_status = determine_status(life, SMART_LIFE_WARN, SMART_LIFE_CRIT, reverse=True)
                        life_color = 'red' if life_status == 'critical' else 'orange' if life_status == 'warning' else 'auto'
                        desc_parts.append("剩余寿命: <span style='color: {0}'>{1}%</span>".format(life_color, life))
                smart_tips.append({
                    'name': 'SMART({0})'.format(dev.get('device', '-')),
                    'desc': '<br/>'.join(desc_parts)
                })

        io = pve_data.get('io', {})
        if io.get('error'):
            collect_errors.append('磁盘IO：' + str(io.get('error')))
        else:
            for dev in io.get('devices', []):
                io_tips.append({
                    'name': 'IO({0})'.format(dev.get('device', '-')),
                    'desc': '读取: {0:.2f} r/s, {1:.2f} kB/s<br/>写入: {2:.2f} w/s, {3:.2f} kB/s<br/>平均等待时间: {4:.2f} ms<br/>使用率: {5:.2f}%'.format(
                        float(dev.get('r_s', 0) or 0),
                        float(dev.get('rkB_s', 0) or 0),
                        float(dev.get('w_s', 0) or 0),
                        float(dev.get('wkB_s', 0) or 0),
                        float(dev.get('await', 0) or 0),
                        float(dev.get('util', 0) or 0)
                    )
                })

        sensors = pve_data.get('sensors', {})
        sensors, pve_issues = filter_obvious_sensor_noise(sensors, pve_issues)
        if sensors.get('error'):
            collect_errors.append('传感器：' + str(sensors.get('error')))
        else:
            temps = sensors.get('temperatures', [])
            if temps:
                temp_lines = []
                for temp in temps:
                    status = determine_status(temp.get('value', 0), thresholds['temp_warn'], thresholds['temp_crit'])
                    color = 'red' if status == 'critical' else 'orange' if status == 'warning' else 'auto'
                    temp_lines.append("{0}: <span style='color: {1}'>{2}{3}</span>".format(
                        temp.get('name', '-'),
                        color,
                        temp.get('value', 0),
                        temp.get('unit', '')
                    ))
                sensor_tips.append({'name': '温度传感器', 'desc': '<br/>'.join(temp_lines)})

            fans = sensors.get('fans', [])
            temp_alert_state = 'normal'
            for temp in temps:
                temp_status = determine_status(temp.get('value', 0), thresholds['temp_warn'], thresholds['temp_crit'])
                if temp_status == 'critical':
                    temp_alert_state = 'critical'
                    break
                if temp_status == 'warning':
                    temp_alert_state = 'warning'
            fan_alert_state = get_fan_alert_state(fans, temp_alert_state)
            if fan_alert_state != 'normal':
                fan_lines = []
                for fan in fans:
                    value = fan.get('value', 0)
                    if fan_alert_state == 'critical':
                        color = 'red'
                    elif value == 0:
                        color = 'orange'
                    elif value < 500:
                        color = 'orange'
                    else:
                        color = 'auto'
                    fan_lines.append("{0}: <span style='color: {1}'>{2} {3}</span>".format(
                        fan.get('name', '-'),
                        color,
                        value,
                        fan.get('unit', '')
                    ))
                sensor_tips.append({'name': '风扇传感器', 'desc': '<br/>'.join(fan_lines)})

            volts = sensors.get('voltages', [])
            if volts:
                volt_lines = []
                for volt in volts:
                    volt_lines.append('{0}: {1}{2}'.format(volt.get('name', '-'), volt.get('value', 0), volt.get('unit', '')))
                sensor_tips.append({'name': '电压传感器', 'desc': '<br/>'.join(volt_lines)})

        power = pve_data.get('power', {})
        if power.get('error'):
            collect_errors.append('电源：' + str(power.get('error')))
        elif power.get('warning'):
            power_tips.append({'name': '电源', 'desc': "<span style='color: orange'>{0}</span>".format(power.get('warning'))})
        else:
            supplies = power.get('supplies', [])
            if supplies:
                lines = []
                for supply in supplies:
                    if 'info' in supply:
                        lines.append(supply.get('info'))
                    elif 'power' in supply:
                        lines.append('功率: {0:.2f} {1}'.format(float(supply.get('power', 0) or 0), supply.get('unit', '')))
                power_tips.append({'name': '电源', 'desc': '<br/>'.join(lines)})

        issue_summary_tips, issue_error_tips = self._format_pve_issue_summary(pve_issues)
        summary_tips.extend(issue_summary_tips)
        error_tips.extend(issue_error_tips)

        if collect_error != '':
            validation_errors.append('pve_system_status_collect_error')
            collect_errors.append('PVE采集：' + collect_error)

        for err in collect_errors:
            summary_tips.append("<span style='color: red;'>数据采集异常: {0}</span>".format(value_tool.escapeHtml(err)))
            error_tips.append(err)

        if len(summary_tips) == 0:
            summary_tips.append("<span style='color: green;'>服务运行正常，继续保持！</span>")

        return {
            'title': host_name,
            'ip': host_ip,
            'report_time': latest_doc.get('add_time', '') if isinstance(latest_doc, dict) and latest_doc.get('add_time') else window['report_time'],
            'start_time': window['start_time'],
            'end_time': window['end_time'],
            'start_date': window['start_date'],
            'end_date': window['end_date'],
            'summary_tips': summary_tips,
            'error_tips': error_tips,
            'sysinfo_tips': sysinfo_tips,
            'network_tips': network_tips,
            'smart_tips': smart_tips,
            'io_tips': io_tips,
            'sensor_tips': sensor_tips,
            'power_tips': power_tips,
            'is_abnormal': len(error_tips) > 0,
        }, error_tips

    def _classify_monitor_task_status(self, task_row, latest_event, now_ts):
        """根据最新任务事件、检查周期和宽限时间判定任务状态。

        返回 (status, msg, run_at_ts)：
        - 没有 event -> error/"未发现任务日志"
        - 事件 run_at + check_interval + grace_seconds < now -> error/"任务超时未执行"
        - 事件 status -> 映射到 normal/warning/error，unknown 当 error 处理
        """
        check_interval = value_tool.safeInt(task_row.get('check_interval', 0), 0)
        grace_seconds = value_tool.safeInt(task_row.get('grace_seconds', 0), 0)

        if not latest_event:
            return 'error', '未发现任务日志', 0

        raw_run_at = latest_event.get('run_at') or latest_event.get('@timestamp') or ''
        run_at_ts = value_tool.parseTime(raw_run_at)
        event_status = str(latest_event.get('status', '') or '').strip().lower()
        event_msg = str(latest_event.get('msg', '') or '').strip()

        if run_at_ts <= 0:
            # 无法解析运行时间，视为异常以触发关注
            return 'error', event_msg or '任务运行时间无法解析', run_at_ts

        deadline = run_at_ts + check_interval + grace_seconds
        if now_ts > deadline:
            return 'error', '任务超时未执行（最近运行：{0}）'.format(raw_run_at), run_at_ts

        if event_status == 'success':
            return 'normal', event_msg or '任务执行成功', run_at_ts
        if event_status == 'warning':
            return 'warning', event_msg or '任务执行告警', run_at_ts
        if event_status == 'error':
            return 'error', event_msg or '任务执行失败', run_at_ts
        if event_status == 'normal':
            return 'normal', event_msg or '任务执行正常', run_at_ts
        # unknown / 其它 -> 按 error 处理以便被发现
        return 'error', event_msg or '任务状态未知（{0}）'.format(event_status or 'unknown'), run_at_ts

    def _format_monitor_task_time(self, value):
        """Format monitor task time from text, unix seconds, or unix milliseconds."""
        raw = str(value or '').strip()
        if raw == '':
            return ''
        try:
            ts = value_tool.safeInt(raw, 0)
            if ts > 0 and raw.replace('.', '', 1).isdigit():
                if ts > 100000000000:
                    ts = int(ts / 1000)
                return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
        except Exception:
            pass
        parsed_ts = value_tool.parseTime(raw, 0)
        if parsed_ts > 0:
            return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(parsed_ts))
        return raw

    def _parse_monitor_task_time(self, value):
        """Parse monitor task time as unix seconds for ES long fields."""
        raw = str(value or '').strip()
        if raw == '':
            return 0
        if raw.replace('.', '', 1).isdigit():
            ts = value_tool.safeInt(raw, 0)
            if ts > 100000000000:
                ts = int(ts / 1000)
            return ts
        return value_tool.parseTime(raw, 0)

    def _build_monitor_task_section(self, host_row, now_ts):
        """分析该主机所有启用的监控任务，回写状态并生成报告片段。"""
        host_id = str(host_row.get('host_id', '') or '')
        summary_tips = []
        error_tips = []
        results = []
        if not host_id:
            return {'summary_tips': summary_tips, 'error_tips': error_tips, 'monitor_task_results': results}

        try:
            task_rows = jh.M('monitor_task').where('host_id=? and enabled=?', (host_id, 1)).field(
                'task_id,task_name,host_id,host_name,host_ip,log_path,check_interval,grace_seconds,enabled'
            ).select()
        except Exception as e:
            summary_tips.append("<span style='color: red;'>监控任务读取失败：{0}</span>".format(value_tool.escapeHtml(str(e))))
            error_tips.append('监控任务读取失败')
            return {'summary_tips': summary_tips, 'error_tips': error_tips, 'monitor_task_results': results}

        if not isinstance(task_rows, list) or len(task_rows) == 0:
            return {'summary_tips': summary_tips, 'error_tips': error_tips, 'monitor_task_results': results}

        for task_row in task_rows:
            if not isinstance(task_row, dict):
                continue
            task_id = str(task_row.get('task_id', '') or '')
            task_name = str(task_row.get('task_name', '') or task_id)
            if not task_id:
                continue

            latest_event = {}
            try:
                latest_event = monitor_task_event_service_utils.getLatestTaskEvent(task_id, host_id, es_client=self._es) or {}
            except Exception as e:
                self.es_available = False
                self.es_skip_reason = 'ES查询任务事件失败，已跳过任务事件状态：{0}'.format(str(e))
                status = 'skipped'
                msg = self.es_skip_reason
                run_at_ts = 0
            else:
                if not self.es_available and not latest_event:
                    status, msg, run_at_ts = 'skipped', self.es_skip_reason or 'ES不可用，已跳过任务事件状态', 0
                else:
                    status, msg, run_at_ts = self._classify_monitor_task_status(task_row, latest_event, now_ts)

            result = {
                'task_id': task_id,
                'task_name': task_name,
                'log_path': str(task_row.get('log_path', '') or ''),
                'status': status,
                'msg': msg,
                'last_run_at': run_at_ts,
                'has_event': bool(latest_event),
            }
            results.append(result)

            # 回写分析状态到 SQLite
            try:
                update_fields = {
                    'last_status': status,
                    'last_msg': msg[:500],
                    'last_run_at': run_at_ts,
                    'last_event_at': value_tool.parseTime(latest_event.get('@timestamp', '')) if latest_event else 0,
                    'last_analyse_at': now_ts,
                    'update_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts)),
                }
                jh.M('monitor_task').where('task_id=?', (task_id,)).save(update_fields)
            except Exception:
                pass

            if status == 'skipped':
                continue
            if status == 'error':
                summary_tips.append("<span style='color: red;'>任务【{0}】异常：{1}</span>".format(
                    value_tool.escapeHtml(task_name), value_tool.escapeHtml(msg)))
                error_tips.append('任务【{0}】异常：{1}'.format(task_name, msg))
            elif status == 'warning':
                summary_tips.append("<span style='color: orange;'>任务【{0}】告警：{1}</span>".format(
                    value_tool.escapeHtml(task_name), value_tool.escapeHtml(msg)))

        return {'summary_tips': summary_tips, 'error_tips': error_tips, 'monitor_task_results': results}

    def _build_monitor_task_overview(self, now_ts):
        """实时查询 ES 最新任务事件，生成监控任务总览并回写 SQLite 状态。"""
        monitor_task_overview = []
        try:
            all_task_rows = jh.M('monitor_task').where('enabled=?', (1,)).field(
                'task_id,task_name,host_id,host_name,host_ip,log_path,check_interval,grace_seconds,last_status,last_msg,last_run_at,last_event_at,last_analyse_at'
            ).order('id desc').select()
        except Exception:
            return monitor_task_overview

        if not isinstance(all_task_rows, list) or len(all_task_rows) == 0:
            return monitor_task_overview

        task_host_pairs = []
        for row in all_task_rows:
            if not isinstance(row, dict):
                continue
            task_id = str(row.get('task_id', '') or '').strip()
            host_id = str(row.get('host_id', '') or '').strip()
            if task_id and host_id:
                task_host_pairs.append((task_id, host_id))

        latest_event_map = {}
        try:
            latest_event_map = monitor_task_event_service_utils.getLatestTaskEventsBatch(task_host_pairs, es_client=self._es) or {}
        except Exception as e:
            self.es_available = False
            self.es_skip_reason = 'ES查询任务事件失败，已跳过任务事件状态：{0}'.format(str(e))
            self.log('[report-analysis] skip es monitor task events reason={0}'.format(self.es_skip_reason))
            latest_event_map = {}

        for t in all_task_rows:
            if not isinstance(t, dict):
                continue
            task_id = str(t.get('task_id', '') or '').strip()
            host_id = str(t.get('host_id', '') or '').strip()
            latest_event = latest_event_map.get(task_id, {}) if task_id else {}
            if not self.es_available and not latest_event:
                status, msg, run_at = 'skipped', self.es_skip_reason or 'ES不可用，已跳过任务事件状态', 0
            else:
                status, msg, run_at = self._classify_monitor_task_status(t, latest_event, now_ts)
            event_at = value_tool.parseTime(latest_event.get('@timestamp', '')) if latest_event else 0

            try:
                update_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts))
                jh.M('monitor_task').where('task_id=?', (task_id,)).save(
                    'last_status,last_msg,last_run_at,last_event_at,last_analyse_at,update_time',
                    (status, msg[:500], run_at, event_at, now_ts, update_time)
                )
            except Exception:
                pass

            monitor_task_overview.append({
                'task_id': task_id,
                'task_name': str(t.get('task_name', '') or ''),
                'host_id': host_id,
                'host_name': str(t.get('host_name', '') or ''),
                'host_ip': str(t.get('host_ip', '') or ''),
                'log_path': str(t.get('log_path', '') or ''),
                'status': status,
                'msg': msg,
                'last_run_at': run_at,
                'last_run_at_text': self._format_monitor_task_time(run_at),
                'last_event_at': event_at,
                'last_event_at_text': self._format_monitor_task_time(event_at),
                'last_analyse_at': now_ts,
            })

        return monitor_task_overview

    def _ha_status_text(self, status):
        return {
            'normal': '正常',
            'warning': '提醒',
            'danger': '异常',
            'switching': '切换中',
            'unknown': '待上报'
        }.get(str(status or ''), str(status or '') or '未知')

    def _build_ha_management_overview(self):
        """汇总当前主备管理状态，判断逻辑复用主备管理页面。"""
        overview = {
            'total': 0,
            'normal': 0,
            'abnormal': 0,
            'warning': 0,
            'danger': 0,
            'switching': 0,
            'unknown': 0,
            'items': [],
            'abnormal_items': [],
            'danger_items': [],
            'warning_items': []
        }
        if ha_api is None:
            return overview
        try:
            api = ha_api()
            api.ensureHaSchema()
            rows = jh.M('ha_pair').where('local_type=?', (api.PAIR_TYPE,)).field(api.PAIR_FIELDS).order('sort_id asc,id desc').select()
        except Exception:
            return overview
        if not isinstance(rows, list):
            return overview
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                pair = api._normalizePair(row)
            except Exception:
                pair = dict(row)
                pair['status'] = row.get('status') or 'unknown'
                pair['status_text'] = row.get('status_text') or '状态读取失败'
                pair['host'] = None
            status = str(pair.get('status') or 'unknown')
            status_text = str(pair.get('status_text') or self._ha_status_text(status))
            host = pair.get('host') or {}
            hosts_text = '暂无主机上报'
            if host:
                hosts_text = '{0}({1}) {2}'.format(host.get('host_name') or host.get('host_id') or '未知主机', host.get('host_ip') or '--', host.get('role') or '--')
            item = {
                'pair_id': pair.get('pair_id') or row.get('pair_id') or '',
                'pair_name': pair.get('pair_name') or row.get('pair_name') or pair.get('pair_id') or row.get('pair_id') or '未知主备',
                'status': status,
                'status_label': self._ha_status_text(status),
                'status_text': status_text,
                'hosts_text': hosts_text,
                'last_report_at': pair.get('last_report_at') or row.get('last_report_at') or ''
            }
            overview['items'].append(item)
            overview['total'] += 1
            if status == 'normal':
                overview['normal'] += 1
            else:
                overview['abnormal'] += 1
                overview['abnormal_items'].append(item)
                if status == 'danger':
                    overview['danger_items'].append(item)
                else:
                    overview['warning_items'].append(item)
                if status in overview:
                    overview[status] += 1
                else:
                    overview['unknown'] += 1
        return overview

    def build_single_host_report(self, host_row, host_group, window):
        """基于单台主机原始数据生成单机报告文档。"""
        if not host_row.get('_collected_host_name_resolved'):
            host_row = self._resolve_report_host_rows([host_row])[0]
        host_id = host_row.get('host_id', '')

        host_name = host_row.get('host_name', '')
        host_ip = host_row.get('ip', '')
        status_docs = sorted(host_group.get('status', []) or [], key=lambda item: value_tool.safeInt(item.get('add_timestamp', 0), value_tool.parseTime(item.get('add_time', ''))))
        xtrabackup_docs = host_group.get('xtrabackup', []) or []
        xtrabackup_inc_docs = host_group.get('xtrabackup_inc', []) or []
        backup_docs = host_group.get('backup', []) or []
        validation_errors = []
        if self.es_available and len(status_docs) == 0:
            validation_errors.append('missing_system_status')

        is_pve_host = self._is_pve_host(host_row, status_docs)
        if is_pve_host:
            latest_doc = status_docs[-1] if status_docs else {}
            report_payload, error_tips = self._build_pve_report_payload(host_row, latest_doc, window, validation_errors)
            summary_tips = report_payload.get('summary_tips', [])
            backup_tips = []
            siteinfo_tips = []
            jianghujsinfo_tips = []
            dockerinfo_tips = []
            mysqlinfo_tips = []
        else:
            system_section = self._build_system_section(status_docs, window, validation_errors)
            latest_doc = system_section.get('latest_doc', {})
            backup_section = self._build_backup_section(latest_doc, xtrabackup_docs, xtrabackup_inc_docs, backup_docs, window, validation_errors)
            site_section = self._build_site_section(latest_doc)
            jianghujsinfo_tips = self._build_runtime_service_section(latest_doc, 'jianghujs', 'JianghuJS', 'orange')
            dockerinfo_tips = self._build_runtime_service_section(latest_doc, 'docker', 'Docker', 'red')
            mysqlinfo_tips = self._build_mysql_section(status_docs)

            summary_tips = []
            error_tips = []
            summary_tips.extend(system_section.get('summary_tips', []))
            summary_tips.extend(backup_section.get('summary_tips', []))
            summary_tips.extend(site_section.get('summary_tips', []))
            error_tips.extend(system_section.get('error_tips', []))
            error_tips.extend(backup_section.get('error_tips', []))
            error_tips.extend(site_section.get('error_tips', []))

            if not self.es_available:
                summary_tips.append("<span style='color: orange;'>ES 不可用，已跳过主机运行数据</span>")
            elif len(status_docs) == 0:
                summary_tips.append("<span style='color: red;'>系统监控原始数据缺失，报告未生成完整</span>")
                error_tips.append('系统监控原始数据缺失')

            if len(summary_tips) == 0:
                summary_tips.append("<span style='color: green;'>服务运行正常，继续保持！</span>")

            report_payload = {
                'title': jh.getConfig('title'),
                'ip': host_ip,
                'report_time': window['report_time'],
                'start_time': window['start_time'],
                'end_time': window['end_time'],
                'start_date': window['start_date'],
                'end_date': window['end_date'],
                'summary_tips': summary_tips,
                'error_tips': error_tips,
                'sysinfo_tips': system_section.get('tips', []),
                'backup_tips': backup_section.get('tips', []),
                'siteinfo_tips': site_section.get('tips', []),
                'jianghujsinfo_tips': jianghujsinfo_tips,
                'dockerinfo_tips': dockerinfo_tips,
                'mysqlinfo_tips': mysqlinfo_tips,
                'is_abnormal': len(error_tips) > 0,
            }
            backup_tips = report_payload.get('backup_tips', [])
            siteinfo_tips = report_payload.get('siteinfo_tips', [])

        # 监控任务只单独展示，不参与主机报告异常/提醒判定。
        monitor_task_section = self._build_monitor_task_section(host_row, self.now_ts)
        monitor_task_results = monitor_task_section.get('monitor_task_results', [])

        render_host_row = dict(host_row)
        render_host_row['is_pve'] = 1 if is_pve_host else 0
        html_content = h_api.buildHostReportMessage(render_host_row, report_payload)
        if not html_content or '暂无报告内容' in html_content:
            validation_errors.append('empty_html_content')

        validation_errors = sorted(list(set(validation_errors)))
        validation = build_validation_state(
            is_complete=len(validation_errors) == 0,
            status='ready' if len(validation_errors) == 0 else 'incomplete',
            errors=validation_errors
        )

        doc_id = '{0}:{1}'.format(window['report_date'], host_id)
        existing_doc = {}
        if self.es_available:
            try:
                existing_doc = self._es.get(SINGLE_REPORT_INDEX, doc_id)
                if isinstance(existing_doc, dict):
                    existing_doc = existing_doc.get('_source', existing_doc)
            except Exception as e:
                self.es_available = False
                self.es_skip_reason = 'ES读取历史报告失败，已跳过ES回读：{0}'.format(str(e))
                self.log('[report-analysis] skip es get single doc_id={0} reason={1}'.format(doc_id, self.es_skip_reason))
        delivery_state = normalize_delivery_state(existing_doc.get('delivery')) if isinstance(existing_doc, dict) and existing_doc.get('delivery') else build_delivery_state()

        single_is_abnormal = len(error_tips) > 0
        # 仅提醒：summary_tips 中含橙色提示且没有严重异常
        single_is_warning = (
            not single_is_abnormal
            and any('color: orange' in str(tip) for tip in summary_tips)
        )
        if single_is_abnormal:
            single_icon = '🔴'
        elif single_is_warning:
            single_icon = '🟠'
        else:
            single_icon = '🟢'
        site_title = jh.getConfig('title')
        document = {
            'report_type': 'single',
            'host_report_type': 'pve' if is_pve_host else 'panel',
            'is_pve': is_pve_host,
            'title': '{0} {1}-{2}({3})-{4}'.format(
                single_icon,
                site_title,
                host_name,
                host_ip,
                'PVE硬件健康报告' if is_pve_host else '服务器运行报告'
            ),
            'report_date': window['report_date'],
            'report_time': self._format_es_datetime(window['report_time']),
            'report_time_text': window['report_time'],
            'start_time': self._format_es_datetime(window['start_time']),
            'start_time_text': window['start_time'],
            'end_time': self._format_es_datetime(window['end_time']),
            'end_time_text': window['end_time'],
            'start_date': window['start_date'],
            'end_date': window['end_date'],
            'host_id': host_id,
            'host_name': host_name,
            'host_ip': host_ip,
            'summary_tips': summary_tips,
            'error_tips': error_tips,
            'html_content': html_content,
            'sysinfo_tips': report_payload.get('sysinfo_tips', []),
            'backup_tips': backup_tips,
            'siteinfo_tips': siteinfo_tips,
            'jianghujsinfo_tips': jianghujsinfo_tips,
            'dockerinfo_tips': dockerinfo_tips,
            'mysqlinfo_tips': mysqlinfo_tips,
            'network_tips': report_payload.get('network_tips', []),
            'smart_tips': report_payload.get('smart_tips', []),
            'io_tips': report_payload.get('io_tips', []),
            'sensor_tips': report_payload.get('sensor_tips', []),
            'power_tips': report_payload.get('power_tips', []),
            'validation': validation,
            'delivery': delivery_state,
            'is_abnormal': single_is_abnormal,
            'is_warning': single_is_warning,
            'extra_info': {
                'raw_counts': {
                    'status': len(status_docs),
                    'xtrabackup': len(xtrabackup_docs),
                    'xtrabackup_inc': len(xtrabackup_inc_docs),
                    'backup': len(backup_docs),
                },
                'latest_status_time': latest_doc.get('add_time', '') if isinstance(latest_doc, dict) else '',
                'monitor_task_results': monitor_task_results,
                'es_available': self.es_available,
                'es_skip_reason': self.es_skip_reason,
            }
        }
        return doc_id, document

    def _build_host_label(self, document):
        """生成用于总览展示的主机标签文本。"""
        host_ip = document.get('host_ip', '')
        host_name = document.get('host_name', '')
        if host_ip and host_name:
            return '{0}（{1}）'.format(host_ip, host_name)
        return host_ip or host_name or '未知主机'

    def _format_host_summary(self, documents):
        """把多台主机摘要压缩成适合邮件展示的短文本。"""
        labels = [self._build_host_label(doc) for doc in documents]
        if len(labels) == 0:
            return '无'
        if len(labels) <= 3:
            return '、'.join(labels)
        return '{0}等 {1} 台'.format('、'.join(labels[:3]), len(labels))

    def _apply_collected_names_to_monitor_tasks(self, monitor_task_overview, host_rows):
        collected_host_map = {
            str(row.get('host_id', '') or ''): str(row.get('host_name', '') or '')
            for row in host_rows
            if row.get('host_id')
        }
        for task_item in monitor_task_overview:
            task_host_id = str(task_item.get('host_id', '') or '')
            if task_host_id in collected_host_map:
                task_item['host_name'] = collected_host_map[task_host_id]
        return monitor_task_overview

    def build_overview_report(self, host_rows, single_documents, window):
        """汇总所有单机报告，生成全局概览文档。"""
        online_count = 0
        abnormal_documents = []
        warning_documents = []
        normal_documents = []
        offline_documents = []

        doc_map = {}
        for doc in single_documents:
            doc_map[doc.get('host_id')] = doc

        for row in host_rows:
            current_doc = doc_map.get(row.get('host_id'))
            if not current_doc:
                offline_documents.append({
                    'host_id': row.get('host_id'),
                    'host_name': row.get('host_name'),
                    'host_ip': row.get('ip'),
                    'summary_tips': ['缺少单机报告'],
                    'validation': {'errors': ['missing_single_report']},
                    'html_content': ''
                })
                continue
            validation = current_doc.get('validation', {}) or {}
            latest_status_time = value_tool.getNested(current_doc, ['extra_info', 'latest_status_time'], '')
            if latest_status_time:
                online_count += 1
            if current_doc.get('is_abnormal') or not validation.get('is_complete', False):
                abnormal_documents.append(current_doc)
            elif current_doc.get('is_warning'):
                warning_documents.append(current_doc)
            else:
                normal_documents.append(current_doc)

        host_total = len(host_rows)
        host_offline = max(host_total - online_count, 0)
        host_error = len(abnormal_documents)
        host_warning = len(warning_documents)

        host_overview_tips = [
            {
                'name': '正常主机',
                'desc': self._format_host_summary(normal_documents)
            },
            {
                'name': '异常主机',
                'desc': self._format_host_summary(abnormal_documents) if abnormal_documents else '无'
            },
            {
                'name': '提醒主机',
                'desc': self._format_host_summary(warning_documents) if warning_documents else '无'
            }
        ]
        if host_offline > 0:
            host_overview_tips.append({
                'name': '离线主机',
                'desc': self._format_host_summary(offline_documents)
            })

        exception_host_summary_tips = []
        for doc in abnormal_documents + offline_documents:
            summary_text = '；'.join(doc.get('error_tips', []) or [])
            if summary_text == '':
                validation_errors = value_tool.getNested(doc, ['validation', 'errors'], []) or []
                summary_text = '；'.join(validation_errors) if validation_errors else '报告不完整'
            exception_host_summary_tips.append({
                'name': self._build_host_label(doc),
                'desc': summary_text
            })

        warning_host_summary_tips = []
        for doc in warning_documents:
            summary_text = '；'.join(doc.get('summary_tips', []) or [])
            if summary_text == '':
                summary_text = '有提醒项需要关注'
            warning_host_summary_tips.append({
                'name': self._build_host_label(doc),
                'desc': summary_text
            })

        # 监控任务总览：生成报告时实时查询 ES 最新事件，避免发送旧的 SQLite 状态。
        monitor_task_overview = self._build_monitor_task_overview(self.now_ts)
        self._apply_collected_names_to_monitor_tasks(monitor_task_overview, host_rows)
        ha_overview = self._build_ha_management_overview() if self.is_ha_report_enabled() else {}

        overview_summary_messages = []
        if not self.es_available:
            overview_summary_messages.append({'level': 'info', 'text': self.es_skip_reason or 'ES 不可用，已跳过 ES 相关信息'})

        def append_grouped_summary(rows, level, subject, status_text, default_desc):
            grouped = {}
            for row in rows:
                desc = str(row.get('desc', '') or default_desc).strip() or default_desc
                name = str(row.get('name', '') or '未知{0}'.format(subject)).strip()
                grouped.setdefault(desc, []).append(name)
            for desc, names in grouped.items():
                overview_summary_messages.append({
                    'level': level,
                    'text': '{0}{1}{2}：{3}'.format('、'.join(names), subject, status_text, desc)
                })

        append_grouped_summary(exception_host_summary_tips, 'error', '主机', '有异常', '报告异常')
        append_grouped_summary(warning_host_summary_tips, 'warning', '主机', '有提醒', '有提醒项需要关注')

        error_tasks = []
        warning_tasks = []
        for task in monitor_task_overview:
            task_status = str(task.get('status', '') or '').lower()
            if task_status not in ('error', 'warning'):
                continue
            task_name = str(task.get('task_name', '') or task.get('task_id', '') or '未知任务')
            desc = str(task.get('msg', '') or '').strip()
            run_at_text = str(task.get('last_run_at_text', '') or '').strip()
            if run_at_text:
                desc = (desc + '；' if desc else '') + '日志时间：' + run_at_text
            item = {'name': task_name, 'desc': desc or '需要关注'}
            if task_status == 'error':
                error_tasks.append(item)
            else:
                warning_tasks.append(item)
        append_grouped_summary(error_tasks, 'error', '任务', '异常', '需要关注')
        append_grouped_summary(warning_tasks, 'warning', '任务', '有提醒', '需要关注')
        if ha_overview.get('abnormal'):
            ha_desc = '共 {0} 个，正常 {1} 个，异常/提醒 {2} 个'.format(ha_overview.get('total', 0), ha_overview.get('normal', 0), ha_overview.get('abnormal', 0))
            overview_summary_messages.append({'level': 'warning', 'text': '主备管理：' + ha_desc})
            for item in ha_overview.get('danger_items') or []:
                overview_summary_messages.append({'level': 'error', 'text': '主备异常：{0} {1}'.format(item.get('pair_name') or item.get('pair_id'), item.get('status_text') or item.get('status_label'))})
            for item in ha_overview.get('warning_items') or []:
                overview_summary_messages.append({'level': 'warning', 'text': '主备提醒：{0} {1}'.format(item.get('pair_name') or item.get('pair_id'), item.get('status_text') or item.get('status_label'))})

        title_alert_parts = []
        ha_danger_count = len([x for x in ha_overview.get('abnormal_items') or [] if x.get('status') == 'danger'])
        ha_warning_count = max(len(ha_overview.get('abnormal_items') or []) - ha_danger_count, 0)
        title_error_count = len(exception_host_summary_tips) + len(error_tasks) + ha_danger_count
        title_warning_count = len(warning_host_summary_tips) + len(warning_tasks) + ha_warning_count
        if title_error_count > 0:
            title_alert_parts.append('❌{0}异常'.format(title_error_count))
        if title_warning_count > 0:
            title_alert_parts.append('⚠️{0}提醒'.format(title_warning_count))
        title_alert_prefix = '（{0}）'.format(' '.join(title_alert_parts)) if len(title_alert_parts) > 0 else ''

        single_host_report_list = []
        for doc in single_documents:
            validation = doc.get('validation', {}) or {}
            is_error = bool(doc.get('is_abnormal')) or not validation.get('is_complete', False)
            summary_tips = doc.get('summary_tips', []) or []
            single_host_report_list.append({
                'host_id': doc.get('host_id', ''),
                'host_name': doc.get('host_name', ''),
                'host_ip': doc.get('host_ip', ''),
                'is_error': is_error,
                'summary_tips': summary_tips,
                'html_content': doc.get('html_content', ''),
            })

        host_normal = len(normal_documents)
        title_prefix = '📊 {0}-全部主机概览报告'.format(jh.getConfig('title'))
        title = title_prefix
        title = title_alert_prefix + title
        overview_payload = {
            'title': title,
            'title_prefix': title_prefix,
            'host_normal': host_normal,
            'host_warning': host_warning,
            'host_error': host_error,
            'report_time': window['report_time'],
            'start_time': window['start_time'],
            'end_time': window['end_time'],
            'report_date': window['report_date'],
            'host_overview_info': {
                'host_total': host_total,
                'host_online': online_count,
                'host_offline': host_offline,
                'host_error': host_error,
                'host_warning': host_warning,
            },
            'host_overview_tips': host_overview_tips,
            'exception_host_summary_tips': exception_host_summary_tips,
            'warning_host_summary_tips': warning_host_summary_tips,
            'overview_summary_messages': overview_summary_messages,
            'monitor_task_overview': monitor_task_overview,
            'ha_overview': ha_overview,
            'single_host_report_list': single_host_report_list,
        }

        template = self._overview_env.get_template('host_overview_report.html')
        html_content = template.render(**overview_payload)

        validation_errors = []
        if host_total == 0:
            validation_errors.append('missing_enabled_hosts')
        if len(single_documents) == 0:
            validation_errors.append('missing_single_reports')
        if not html_content:
            validation_errors.append('empty_html_content')

        validation = build_validation_state(
            is_complete=len(validation_errors) == 0,
            status='ready' if len(validation_errors) == 0 else 'incomplete',
            errors=validation_errors
        )

        doc_id = window['report_date']
        existing_doc = {}
        if self.es_available:
            try:
                existing_doc = self._es.get(OVERVIEW_REPORT_INDEX, doc_id)
                if isinstance(existing_doc, dict):
                    existing_doc = existing_doc.get('_source', existing_doc)
            except Exception as e:
                self.es_available = False
                self.es_skip_reason = 'ES读取总览历史报告失败，已跳过ES回读：{0}'.format(str(e))
                self.log('[report-analysis] skip es get overview doc_id={0} reason={1}'.format(doc_id, self.es_skip_reason))
        delivery_state = normalize_delivery_state(existing_doc.get('delivery')) if isinstance(existing_doc, dict) and existing_doc.get('delivery') else build_delivery_state()

        document = {
            'report_type': 'overview',
            'title': title,
            'report_date': window['report_date'],
            'report_time': self._format_es_datetime(window['report_time']),
            'report_time_text': window['report_time'],
            'start_time': self._format_es_datetime(window['start_time']),
            'start_time_text': window['start_time'],
            'end_time': self._format_es_datetime(window['end_time']),
            'end_time_text': window['end_time'],
            'html_content': html_content,
            'host_overview_info': overview_payload['host_overview_info'],
            'host_overview_tips': host_overview_tips,
            'exception_host_summary_tips': exception_host_summary_tips,
            'warning_host_summary_tips': warning_host_summary_tips,
            'overview_summary_messages': overview_summary_messages,
            'single_host_report_list': single_host_report_list,
            'validation': validation,
            'delivery': delivery_state,
            'monitor_task_overview': monitor_task_overview,
            'ha_overview': ha_overview,
            'extra_info': {
                'normal_host_count': len(normal_documents),
                'offline_host_count': host_offline,
                'error_host_ids': [doc.get('host_id') for doc in abnormal_documents],
                'ha_overview': ha_overview,
                'es_available': self.es_available,
                'es_skip_reason': self.es_skip_reason,
            }
        }
        return doc_id, document

    def run_analysis(self, host_rows=None, report_date=None):
        """执行分析阶段：生成并落库单机与总览报告。"""
        window = self.get_report_window(report_date)
        if host_rows is None:
            _, host_rows, _ = self.get_schedule_state()
        if len(host_rows) == 0:
            self.log('[report-analysis] skipped no enabled hosts for report_date={0}'.format(window['report_date']))
            return {'status': 'skipped', 'reason': 'no_enabled_hosts', 'report_date': window['report_date']}

        self.log('[report-analysis] start report_date={0} host_total={1}'.format(window['report_date'], len(host_rows)))
        report_run_id = self._build_report_run_id(window)
        load_raw_start_ts = time.time()
        self.log('[report-analysis] load raw groups start report_date={0} host_total={1}'.format(window['report_date'], len(host_rows)))
        raw_groups = self.load_raw_groups(host_rows, window)
        host_rows = self._resolve_report_host_rows(host_rows, raw_groups)
        self.log('[report-analysis] load raw groups done report_date={0} host_total={1} cost={2:.3f}s'.format(
            window['report_date'],
            len(host_rows),
            time.time() - load_raw_start_ts
        ))
        single_documents = []
        single_data_stream_name = self._get_single_report_data_stream_name(window['report_date'])
        overview_data_stream_name = self._get_overview_report_data_stream_name(window['report_date'])
        for index, row in enumerate(host_rows):
            host_id = row.get('host_id')
            host_group = raw_groups.get(host_id, {'status': [], 'xtrabackup': [], 'xtrabackup_inc': [], 'backup': []})
            single_start_ts = time.time()
            self.log('[report-analysis] single report build start report_date={0} progress={1}/{2} host_id={3} host_name={4}'.format(
                window['report_date'],
                index + 1,
                len(host_rows),
                host_id,
                row.get('host_name', '')
            ))
            doc_id, document = self.build_single_host_report(row, host_group, window)
            self.log('[report-analysis] single report save start doc_id={0} host_id={1}'.format(doc_id, host_id))
            saved_to_es = self._try_save_report_outputs(SINGLE_REPORT_INDEX, doc_id, single_data_stream_name, document, report_run_id)
            single_documents.append(document)
            self.log(
                '[report-analysis] single report built doc_id={0} host_id={1} validation={2} abnormal={3} raw_counts={4} report_run_id={5} data_stream={6} saved_to_es={7} cost={8:.3f}s'.format(
                    doc_id,
                    host_id,
                    value_tool.getNested(document, ['validation', 'status'], ''),
                    bool(document.get('is_abnormal')),
                    value_tool.getNested(document, ['extra_info', 'raw_counts'], {}),
                    report_run_id,
                    single_data_stream_name,
                    saved_to_es,
                    time.time() - single_start_ts
                )
            )

        overview_start_ts = time.time()
        self.log('[report-analysis] overview build start report_date={0} single_total={1}'.format(window['report_date'], len(single_documents)))
        overview_doc_id, overview_document = self.build_overview_report(host_rows, single_documents, window)
        self.log('[report-analysis] overview save start doc_id={0}'.format(overview_doc_id))
        overview_saved_to_es = self._try_save_report_outputs(OVERVIEW_REPORT_INDEX, overview_doc_id, overview_data_stream_name, overview_document, report_run_id)

        ready_count = len([doc for doc in single_documents if value_tool.getNested(doc, ['validation', 'is_complete'], False)])
        abnormal_count = len([doc for doc in single_documents if doc.get('is_abnormal')])
        self.log(
            '[report-analysis] overview built doc_id={0} validation={1} host_total={2} ready={3} abnormal={4} report_run_id={5} data_stream={6} saved_to_es={7} cost={8:.3f}s'.format(
                overview_doc_id,
                value_tool.getNested(overview_document, ['validation', 'status'], ''),
                len(host_rows),
                ready_count,
                abnormal_count,
                report_run_id,
                overview_data_stream_name,
                overview_saved_to_es,
                time.time() - overview_start_ts
            )
        )
        return {
            'status': 'ok',
            'report_date': window['report_date'],
            'report_run_id': report_run_id,
            'single_data_stream': single_data_stream_name,
            'overview_data_stream': overview_data_stream_name,
            'single_total': len(single_documents),
            'single_ready': ready_count,
            'single_abnormal': abnormal_count,
            'overview_ready': bool(value_tool.getNested(overview_document, ['validation', 'is_complete'], False)),
            'es_available': self.es_available,
            'es_skipped': not self.es_available,
            'es_skip_reason': self.es_skip_reason,
            'overview_document': overview_document,
            'single_documents': single_documents,
        }



__all__ = [
    'HostReportAnalyser',
    'HostReportAnalysePipeline',
    'build_validation_state',
    'build_delivery_state',
    'DEFAULT_REPORT_THRESHOLDS',
    'RAW_STATUS_INDEX',
    'RAW_XTRABACKUP_INDEX',
    'RAW_XTRABACKUP_INC_INDEX',
    'RAW_BACKUP_INDEX',
    'SINGLE_REPORT_INDEX',
    'OVERVIEW_REPORT_INDEX',
    'SINGLE_REPORT_DATA_STREAM_PREFIX',
    'OVERVIEW_REPORT_DATA_STREAM_PREFIX',
    'ANALYSIS_STALE_SECONDS',
    'PAGE_SIZE',
]


HostReportAnalysePipeline = HostReportAnalyser
