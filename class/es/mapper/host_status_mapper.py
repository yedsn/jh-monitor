# coding: utf-8

import os
import sys

sys.path.append(os.getcwd() + "/class/plugin")
import value_tool as value_utils


def getCollectedHostName(status_doc):
    host_doc = value_utils.getNested(status_doc or {}, ['host'], {})
    return str(host_doc.get('panel_title', '') or '').strip()


def estimateCpuCount(status_doc):
    load_avg = value_utils.getNested(status_doc or {}, ['system', 'load'], {})
    load_one = value_utils.safeFloat(load_avg.get('one'), 0)
    load_pro = value_utils.safeFloat(load_avg.get('pro'), 0)
    if load_one > 0 and load_pro > 0:
        cpu_count = int(round(load_one * 100.0 / load_pro))
        if cpu_count > 0:
            return cpu_count
    return 1


def buildHostInfoFromStatus(host_row, status_doc):
    host_info = {
        'hostName': getCollectedHostName(status_doc),
        'platform': host_row.get('os', '') or '',
        'platformFamily': '',
        'platformVersion': '',
        'procs': 0,
        'upTime': '',
        'upTimeStr': '',
        'cpuModel': '',
        'lastBootTime': '',
        'isJHPanel': value_utils.safeBool(host_row.get('is_jhpanel')),
        'jhPanelUrl': '',
        'isPVE': value_utils.safeBool(host_row.get('is_pve')),
        'pvePanelUrl': ''
    }

    host_doc = value_utils.getNested(status_doc or {}, ['host'], {})
    if host_info['platform'] == '':
        system_type = str(host_doc.get('system_type', '') or '').strip().lower()
        if system_type == 'pve':
            host_info['platform'] = 'PVE'
        elif system_type != '':
            host_info['platform'] = system_type

    cpu_count = estimateCpuCount(status_doc)
    host_info['procs'] = cpu_count
    host_info['isPVE'] = host_info['isPVE'] or str(host_doc.get('system_type', '') or '').strip().lower() == 'pve'
    if host_info['isPVE'] and host_row.get('ip'):
        host_info['pvePanelUrl'] = 'https://{0}:8006'.format(host_row.get('ip'))

    collector = value_utils.getNested(status_doc or {}, ['collector'], {})
    host_info['jhMonitorVersion'] = collector.get('version', '')
    return host_info


def buildCpuInfoFromStatus(host_row, status_doc):
    system_doc = value_utils.getNested(status_doc or {}, ['system'], {})
    cpu_count = estimateCpuCount(status_doc)
    cpu_label = host_row.get('os', '') or ('PVE' if value_utils.safeBool(host_row.get('is_pve')) else 'Linux')
    return {
        'cpuCount': cpu_count,
        'logicalCores': cpu_count,
        'modelName': '{0} * {1}'.format(cpu_label, cpu_count),
        'percent': round(value_utils.safeFloat(system_doc.get('cpu'), 0), 2)
    }


def buildMemInfoFromStatus(status_doc):
    system_doc = value_utils.getNested(status_doc or {}, ['system'], {})
    pve_doc = value_utils.getNested(status_doc or {}, ['pve', 'data', 'memory'], {})

    total_mb = round(value_utils.safeFloat(pve_doc.get('total'), 0) / (1024.0 * 1024.0), 2)
    used_mb = round(value_utils.safeFloat(pve_doc.get('used'), 0) / (1024.0 * 1024.0), 2)
    free_mb = round(value_utils.safeFloat(pve_doc.get('available'), 0) / (1024.0 * 1024.0), 2)
    used_percent = round(value_utils.safeFloat(system_doc.get('memory'), 0), 2)

    if total_mb > 0 and used_mb > 0 and used_percent <= 0:
        used_percent = round((used_mb / total_mb) * 100, 2)

    return {
        'total': total_mb,
        'used': used_mb,
        'free': free_mb,
        'usedPercent': used_percent,
        'percent': used_percent,
        'buffers': 0,
        'cached': 0,
        'swapTotal': 0,
        'swapUsed': 0,
        'swapFree': 0,
        'swapUsedPercent': 0
    }


def buildDiskInfoFromStatus(status_doc):
    system_doc = value_utils.getNested(status_doc or {}, ['system'], {})
    disk_io_doc = system_doc.get('disk_io') or {}
    fallback_read_speed = value_utils.safeFloat(disk_io_doc.get('read_bytes'), 0)
    fallback_write_speed = value_utils.safeFloat(disk_io_doc.get('write_bytes'), 0)
    disk_rows = []
    for index, disk in enumerate(system_doc.get('disks', []) or []):
        size_list = disk.get('size') or []
        total = value_utils.parseSizeToBytes(size_list[0] if len(size_list) > 0 else 0)
        used = value_utils.parseSizeToBytes(size_list[1] if len(size_list) > 1 else 0)
        free = value_utils.parseSizeToBytes(size_list[2] if len(size_list) > 2 else 0)
        used_percent = value_utils.parsePercent(size_list[3] if len(size_list) > 3 else 0)
        read_speed = value_utils.safeFloat(
            disk.get('read_speed_bytes', disk.get('readSpeed')),
            0
        )
        write_speed = value_utils.safeFloat(
            disk.get('write_speed_bytes', disk.get('writeSpeed')),
            0
        )
        if used_percent <= 0 and total > 0 and used > 0:
            used_percent = round((float(used) / float(total)) * 100, 2)
        if index == 0 and read_speed <= 0 and fallback_read_speed > 0:
            read_speed = fallback_read_speed
        if index == 0 and write_speed <= 0 and fallback_write_speed > 0:
            write_speed = fallback_write_speed

        disk_rows.append({
            'total': total,
            'used': used,
            'free': free,
            'usedPercent': used_percent,
            'fstype': disk.get('fstype', ''),
            'name': disk.get('device', ''),
            'mountpoint': disk.get('path', ''),
            'readSpeed': int(round(read_speed)),
            'writeSpeed': int(round(write_speed))
        })
    return disk_rows


def buildLoadAvgFromStatus(status_doc):
    system_doc = value_utils.getNested(status_doc or {}, ['system'], {})
    load_doc = system_doc.get('load') or {}
    cpu_count = estimateCpuCount(status_doc)
    return {
        'pro': round(value_utils.safeFloat(load_doc.get('pro'), 0), 2),
        '1min': round(value_utils.safeFloat(load_doc.get('one'), 0), 2),
        '5min': round(value_utils.safeFloat(load_doc.get('five'), 0), 2),
        '15min': round(value_utils.safeFloat(load_doc.get('fifteen'), 0), 2),
        'max': max(cpu_count * 2, 1)
    }


def buildNetInfoFromStatus(status_doc):
    system_doc = value_utils.getNested(status_doc or {}, ['system'], {})
    network_doc = system_doc.get('network') or {}
    pve_network_doc = value_utils.getNested(status_doc or {}, ['pve', 'data', 'network'], {})

    up_total = value_utils.safeInt(network_doc.get('upTotal'), 0)
    down_total = value_utils.safeInt(network_doc.get('downTotal'), 0)
    up_packets = value_utils.safeInt(network_doc.get('upPackets'), 0)
    down_packets = value_utils.safeInt(network_doc.get('downPackets'), 0)

    if up_total <= 0 and isinstance(pve_network_doc, dict):
        for iface in pve_network_doc.get('interfaces', []) or []:
            up_total += value_utils.safeInt(iface.get('tx_bytes'), 0)
            down_total += value_utils.safeInt(iface.get('rx_bytes'), 0)
            up_packets += value_utils.safeInt(iface.get('tx_packets'), 0)
            down_packets += value_utils.safeInt(iface.get('rx_packets'), 0)

    up_kb = value_utils.safeFloat(network_doc.get('up'), 0)
    down_kb = value_utils.safeFloat(network_doc.get('down'), 0)
    up_bytes = value_utils.safeInt(network_doc.get('upBytes'), 0)
    down_bytes = value_utils.safeInt(network_doc.get('downBytes'), 0)

    if up_bytes <= 0 and up_kb > 0:
        up_bytes = int(round(up_kb * 1024))
    if down_bytes <= 0 and down_kb > 0:
        down_bytes = int(round(down_kb * 1024))
    if up_kb <= 0 and up_bytes > 0:
        up_kb = round(float(up_bytes) / 1024.0, 2)
    if down_kb <= 0 and down_bytes > 0:
        down_kb = round(float(down_bytes) / 1024.0, 2)

    return {
        'upTotal': up_total,
        'downTotal': down_total,
        'up': round(up_kb, 2),
        'down': round(down_kb, 2),
        'upBytes': up_bytes,
        'downBytes': down_bytes,
        'downPackets': down_packets,
        'upPackets': up_packets
    }


def normalizeESResponseBody(response):
    if hasattr(response, "body"):
        return response.body
    if hasattr(response, "to_dict"):
        return response.to_dict()
    return response or {}


def buildLatestStatusMapFromMsearch(host_rows, response):
    response_body = normalizeESResponseBody(response)
    responses = response_body.get("responses", [])

    status_map = {}
    miss_hosts = []
    for idx, item in enumerate(responses):
        if idx >= len(host_rows):
            break

        hits = item.get("hits", {}).get("hits", [])
        if len(hits) == 0:
            if len(miss_hosts) < 10:
                miss_hosts.append({
                    'host_id': host_rows[idx].get('host_id', ''),
                    'ip': host_rows[idx].get('ip', ''),
                    'error': item.get('error')
                })
            continue

        host_id = str(host_rows[idx].get('host_id', '') or '').strip()
        if host_id == '':
            continue

        status_map[host_id] = hits[0].get('_source', {})

    return {
        'response_count': len(responses),
        'status_map': status_map,
        'miss_hosts': miss_hosts
    }


def buildStatusDocHitSample(status_map, limit=5):
    return [
        {
            'host_id': host_id,
            'source_host': (doc.get('host') or {}),
            'add_time': doc.get('add_time', ''),
            'add_timestamp': doc.get('add_timestamp', 0)
        } for host_id, doc in list(status_map.items())[:limit]
    ]


def buildHostMetaFromStatusDoc(status_doc):
    host_doc = status_doc.get('host') or {}
    return {
        'host_id': host_doc.get('host_id', ''),
        'host_name': host_doc.get('panel_title', ''),
        'host_remark': '',
        'ip': host_doc.get('host_ip', ''),
        'os': host_doc.get('system_type', ''),
        'is_pve': str(host_doc.get('system_type', '')).strip().lower() == 'pve',
        'is_jhpanel': False
    }


def buildHostDetailFromStatusDoc(host_row, status_doc):
    add_timestamp = value_utils.safeInt((status_doc or {}).get('add_timestamp'), 0)
    add_time = (status_doc or {}).get('add_time', '')
    host_remark = host_row.get('host_remark')
    if host_remark is None:
        host_remark = host_row.get('host_name', '')
    return {
        'id': add_timestamp,
        'host_id': host_row.get('host_id', ''),
        'host_name': getCollectedHostName(status_doc),
        'host_remark': host_remark,
        'host_status': value_utils.parseHostStatus(
            value_utils.getNested(status_doc or {}, ['host', 'host_status'], '')
        ),
        'uptime': '',
        'host_info': value_utils.safeJsonText(buildHostInfoFromStatus(host_row, status_doc), {}),
        'cpu_info': value_utils.safeJsonText(buildCpuInfoFromStatus(host_row, status_doc), {}),
        'mem_info': value_utils.safeJsonText(buildMemInfoFromStatus(status_doc), {}),
        'disk_info': value_utils.safeJsonText(buildDiskInfoFromStatus(status_doc), []),
        'net_info': value_utils.safeJsonText(buildNetInfoFromStatus(status_doc), {}),
        'load_avg': value_utils.safeJsonText(buildLoadAvgFromStatus(status_doc), {}),
        'firewall_info': value_utils.safeJsonText({}, {}),
        'port_info': value_utils.safeJsonText({}, {}),
        'backup_info': value_utils.safeJsonText({}, {}),
        'temperature_info': value_utils.safeJsonText({}, {}),
        'ssh_user_list': value_utils.safeJsonText([], []),
        'last_update': add_time,
        'addtime': add_timestamp
    }


def buildHistoryDetailsFromStatusDocs(docs):
    history = []
    for doc in docs:
        host_meta = buildHostMetaFromStatusDoc(doc)
        history.append(buildHostDetailFromStatusDoc(host_meta, doc))
    return history


def buildHostDetailMapFromStatusDocs(host_rows, status_docs):
    detail_map = {}
    for row in host_rows:
        host_id = str(row.get('host_id', '') or '').strip()
        if host_id == '':
            continue
        detail_map[host_id] = buildHostDetailFromStatusDoc(row, status_docs.get(host_id))
    return detail_map
