# coding: utf-8

import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
os.chdir(ROOT_DIR)

from task import getCollectedHostNameFromStatus


def main():
    assert getCollectedHostNameFromStatus(
        {
            'host': {
                'host_name': 'system-db-01',
                'panel_title': 'prod-db-01'
            }
        }
    ) == 'prod-db-01'
    assert getCollectedHostNameFromStatus(
        {
            'host': {
                'host_name': 'system-db-01',
                'panel_title': 'prod-db-01'
            }
        },
        '数据库主机'
    ) == '数据库主机'
    assert getCollectedHostNameFromStatus({}, '旧机器备注') == '旧机器备注'
    assert getCollectedHostNameFromStatus({}) == ''
    assert getCollectedHostNameFromStatus(None) == ''
    assert getCollectedHostNameFromStatus({
        'host': {'host_name': 'legacy-system-hostname'}
    }) == ''
    print('growth alarm collected host name: ok')


if __name__ == '__main__':
    main()
