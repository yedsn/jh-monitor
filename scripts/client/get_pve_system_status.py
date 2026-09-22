#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import socket
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from get_host_info import get_host_display_name, get_host_ip, is_pve_machine
from get_host_usage import get_net_info
from get_pve_hardware_report import DEFAULT_THRESHOLDS, HardwareReporter

DEFAULT_OUTPUT_DIR = os.environ.get(
    'REPORT_COLLECTOR_OUTPUT_DIR',
    '/home/ansible_user/jh-monitor-data'
)


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def append_text(path, content):
    output_dir = os.path.dirname(path) or '.'
    ensure_dir(output_dir)
    with open(path, 'a') as fp:
        fp.write(content)
        fp.flush()
        os.fsync(fp.fileno())


def append_ndjson(path, rows):
    if not rows:
        return
    content = '\n'.join([json.dumps(row, ensure_ascii=False) for row in rows]) + '\n'
    append_text(path, content)


def export_system_status(output_dir, payload):
    file_date = datetime.datetime.now().strftime('%Y%m%d')
    output_path = os.path.join(output_dir, 'host-pve-system-status-%s.json' % file_date)
    append_ndjson(output_path, [payload])
    return output_path


def format_pve_disks(filesystems, disk_io=None):
    disk_io = disk_io or {}
    read_bytes = int(float(disk_io.get('read_bytes', 0) or 0))
    write_bytes = int(float(disk_io.get('write_bytes', 0) or 0))
    disks = []
    for fs in filesystems or []:
        disks.append({
            'path': fs.get('mountpoint', ''),
            'size': [
                fs.get('size', '0B'),
                fs.get('used', '0B'),
                fs.get('available', '0B'),
                '{0}%'.format(int(float(fs.get('use_percent', 0) or 0)))
            ],
            'inodes': ['', '', '', ''],
            'fstype': '',
            'device': fs.get('filesystem', ''),
            'read_speed_bytes': read_bytes,
            'write_speed_bytes': write_bytes
        })
    return disks


def enrich_network_info(net_info):
    network = dict(net_info or {})
    up_kb = float(network.get('up', 0) or 0)
    down_kb = float(network.get('down', 0) or 0)
    network['upBytes'] = int(round(up_kb * 1024))
    network['downBytes'] = int(round(down_kb * 1024))
    return network


def summarize_pve_disk_io(pve_data):
    io_devices = {}
    if isinstance(pve_data, dict):
        io_devices = (pve_data.get('io') or {}).get('devices', []) or []

    read_bytes = 0.0
    write_bytes = 0.0
    for item in io_devices:
        try:
            read_bytes += float(item.get('rkB_s', 0) or 0) * 1024.0
        except Exception:
            pass
        try:
            write_bytes += float(item.get('wkB_s', 0) or 0) * 1024.0
        except Exception:
            pass

    return {
        'read_bytes': int(round(read_bytes)),
        'write_bytes': int(round(write_bytes))
    }



def _force_float_sensor_values(pve_data):
    """Ensure all sensor numeric values are float, preventing ES mapping conflicts.

    Filebeat flattens arrays so `sensors.temperatures[*].value` collapses into one
    ES field `pve.data.sensors.temperatures.value`. If first event has int 24 and
    later one has float 56.2, ES locks the field as `long` and rejects the float.
    """
    if not isinstance(pve_data, dict):
        return pve_data
    sensors = pve_data.get('sensors')
    if not isinstance(sensors, dict):
        return pve_data
    for key in ('temperatures', 'fans', 'voltages'):
        items = sensors.get(key) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and 'value' in item:
                try:
                    item['value'] = float(item['value'])
                except Exception:
                    item['value'] = 0.0
    # Also normalize SMART per-device temperature to float for consistency
    smart = pve_data.get('smart')
    if isinstance(smart, dict):
        for dev in smart.get('devices', []) or []:
            if isinstance(dev, dict) and dev.get('temperature') is not None:
                try:
                    dev['temperature'] = float(dev['temperature'])
                except Exception:
                    pass
    return pve_data


def build_system_status(host_meta=None):
    if host_meta is None:
        panel_title = get_host_display_name()
        host_meta = {
            'host_id': socket.gethostname(),
            'host_name': panel_title,
            'panel_title': panel_title,
            'host_ip': get_host_ip() or '127.0.0.1'
        }

    now = datetime.datetime.now()
    add_time = now.strftime('%Y-%m-%d %H:%M:%S')
    add_timestamp = now.timestamp()

    reporter = HardwareReporter(DEFAULT_THRESHOLDS, None, False, enable_log=False)
    collect_error = ''
    pve_data = {}
    pve_issues = []
    thresholds = dict(DEFAULT_THRESHOLDS)

    if not is_pve_machine():
        collect_error = 'not_pve_machine'
    else:
        try:
            reporter.collect_all()
            reporter._analyze_all_and_collect_issues()
            pve_data = _force_float_sensor_values(reporter.report_data or {})
            pve_issues = reporter.issues or []
            thresholds = reporter.thresholds or dict(DEFAULT_THRESHOLDS)
        except Exception as ex:
            collect_error = str(ex)

    cpu_data = pve_data.get('cpu', {}) if isinstance(pve_data, dict) else {}
    memory_data = pve_data.get('memory', {}) if isinstance(pve_data, dict) else {}
    disk_data = pve_data.get('disk', {}) if isinstance(pve_data, dict) else {}
    net_info = enrich_network_info(get_net_info())
    disk_io = summarize_pve_disk_io(pve_data)
    load_data = cpu_data.get('load', [0.0, 0.0, 0.0]) or [0.0, 0.0, 0.0]
    while len(load_data) < 3:
        load_data.append(0.0)
    cpu_count = os.cpu_count() or 1
    load_one = float(load_data[0] or 0.0)

    return {
        'host': {
            'host_id': host_meta['host_id'],
            'host_name': host_meta['host_name'],
            'panel_title': host_meta.get('panel_title', ''),
            'host_ip': host_meta['host_ip'],
            'host_group': '',
            'host_status': 'running',
            'system_type': 'pve'
        },
        'system': {
            'cpu': round(float(cpu_data.get('usage', 0) or 0), 2),
            'memory': round(float(memory_data.get('usage_percent', 0) or 0), 2),
            'load': {
                'pro': round((load_one / float(cpu_count)) * 100, 2),
                'one': round(load_one, 2),
                'five': round(float(load_data[1] or 0), 2),
                'fifteen': round(float(load_data[2] or 0), 2)
            },
            'network': net_info,
            'disk_io': disk_io,
            'disks': format_pve_disks(disk_data.get('filesystems', []), disk_io)
        },
        'pve': {
            'data': pve_data,
            'issues': pve_issues,
            'thresholds': thresholds,
            'error': collect_error
        },
        'add_time': add_time,
        'add_timestamp': add_timestamp,
        'collector': {
            'source': 'get_pve_system_status.py',
            'version': '1.0.0'
        }
    }


def main():
    parser = argparse.ArgumentParser(description='Collect PVE system status.')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--stdout-json', action='store_true')
    args = parser.parse_args()

    payload = build_system_status()
    if args.stdout_json:
        print(json.dumps(payload, ensure_ascii=False))
        return

    output_path = export_system_status(args.output_dir, payload)
    print(output_path)


if __name__ == '__main__':
    main()
