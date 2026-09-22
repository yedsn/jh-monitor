# coding: utf-8

import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for path in (
    ROOT_DIR,
    os.path.join(ROOT_DIR, 'class', 'core'),
    os.path.join(ROOT_DIR, 'class', 'plugin'),
    os.path.join(ROOT_DIR, 'class', 'es', 'model'),
    os.path.join(ROOT_DIR, 'scripts'),
    os.path.join(ROOT_DIR, 'scripts', 'client'),
):
    if path not in sys.path:
        sys.path.insert(0, path)

os.chdir(ROOT_DIR)

import report_analyser
from report_analyser import HostReportAnalyser


def main():
    analyser = HostReportAnalyser.__new__(HostReportAnalyser)
    host_row = {
        'host_id': 'H_TEST',
        'host_name': '机房入口机',
        'ip': '10.0.0.10'
    }
    status_docs = [
        {
            'host': {'host_name': 'old-system-host', 'panel_title': 'old-gateway'},
            'add_timestamp': 100
        },
        {
            'host': {'host_name': 'new-system-host', 'panel_title': 'prod-gateway-01'},
            'add_timestamp': 200
        }
    ]

    resolved = analyser._with_collected_host_name(host_row, status_docs, resolved=True)
    assert resolved['host_name'] == 'prod-gateway-01', resolved
    assert resolved['collected_host_name'] == 'prod-gateway-01', resolved
    assert resolved['host_remark'] == '机房入口机', resolved
    assert host_row['host_name'] == '机房入口机', host_row

    fallback = analyser._with_collected_host_name(host_row, [])
    assert fallback['host_name'] == '', fallback

    analyser.es_available = True
    original_get_latest_status_docs = report_analyser.host_status_service_utils.getLatestStatusDocs
    report_analyser.host_status_service_utils.getLatestStatusDocs = lambda rows: {
        'H_TEST': {
            'host': {
                'host_name': 'latest-system-host',
                'panel_title': 'prod-gateway-latest'
            },
            'add_timestamp': 300
        }
    }
    try:
        resolved_rows = analyser._resolve_report_host_rows(
            [host_row],
            {'H_TEST': {'status': [{
                'host': {
                    'host_name': 'old-window-system-host',
                    'panel_title': 'old-window-name'
                },
                'add_timestamp': 100
            }]}}
        )
    finally:
        report_analyser.host_status_service_utils.getLatestStatusDocs = original_get_latest_status_docs

    assert resolved_rows[0]['host_name'] == 'prod-gateway-latest', resolved_rows
    assert resolved_rows[0]['host_remark'] == '机房入口机', resolved_rows
    assert resolved_rows[0]['_collected_host_name_resolved'] is True

    legacy_only = analyser._with_collected_host_name(host_row, [{
        'host': {'host_name': 'legacy-hostname'},
        'add_timestamp': 400
    }])
    assert legacy_only['host_name'] == '', legacy_only

    monitor_tasks = [{
        'host_id': 'H_TEST',
        'host_name': '旧任务主机名称',
        'status': 'normal',
        'task_name': 'test-task',
        'msg': '',
    }]
    analyser._apply_collected_names_to_monitor_tasks(
        monitor_tasks,
        [analyser._with_collected_host_name(host_row, [], resolved=True)]
    )
    assert monitor_tasks[0]['host_name'] == '', monitor_tasks

    print('report collected host name: ok')


if __name__ == '__main__':
    main()
