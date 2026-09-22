# coding: utf-8

import json
import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT_DIR, 'class', 'es', 'mapper'))
sys.path.insert(0, os.path.join(ROOT_DIR, 'class', 'plugin'))

import host_status_mapper


def main():
    host_row = {
        'host_id': 'H_TEST',
        'host_name': '机房入口机',
        'ip': '10.0.0.10'
    }
    status_doc = {
        'host': {
            'host_id': 'H_TEST',
            'host_name': 'system-hostname',
            'panel_title': 'prod-gateway-01',
            'host_ip': '10.0.0.10',
            'host_status': 'running',
            'system_type': 'debian'
        },
        'add_time': '2026-09-19 12:00:00',
        'add_timestamp': 1789790400
    }

    detail = host_status_mapper.buildHostDetailFromStatusDoc(host_row, status_doc)
    host_info = json.loads(detail['host_info'])

    assert detail['host_name'] == 'prod-gateway-01', detail
    assert detail['host_remark'] == '机房入口机', detail
    assert host_info['hostName'] == 'prod-gateway-01', host_info

    empty_detail = host_status_mapper.buildHostDetailFromStatusDoc(host_row, None)
    assert empty_detail['host_name'] == '', empty_detail
    assert empty_detail['host_remark'] == '机房入口机', empty_detail

    print('host status name mapping: ok')


if __name__ == '__main__':
    main()
