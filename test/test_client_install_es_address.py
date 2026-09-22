# coding: utf-8

import os
import json
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'class/core')]

from host_api import host_api
import jh


def main():
    api = host_api()

    remote = api._getClientEsAddresses({
        'addr': 'https://es.example.com:9200, 192.168.10.20'
    }, '10.0.0.8')
    assert remote == [
        'https://es.example.com:9200',
        'http://192.168.10.20:9200'
    ], remote

    local = api._getClientEsAddresses({'addr': 'http://127.0.0.1:9200'}, '10.0.0.8')
    assert local == ['http://10.0.0.8:9200'], local

    ipv6 = api._getClientEsAddresses({'addr': 'https://[fd00::10]:9200'}, '10.0.0.8')
    assert ipv6 == ['https://[fd00::10]:9200'], ipv6

    original_get_host_addr = api._getClientEsAddresses
    original_jh_get_host_addr = jh.getHostAddr
    api._getClientEsAddresses = lambda: ['https://es.example.com:9200']
    jh.getHostAddr = lambda: '127.0.0.1'
    try:
        result = json.loads(api.getClientInstallShellLanApi())
    finally:
        api._getClientEsAddresses = original_get_host_addr
        jh.getHostAddr = original_jh_get_host_addr
    assert result['data']['gitee'] == (
        "wget -O /tmp/install.sh 'http://127.0.0.1:10844/pub/get_client_script?path=install.sh' && "
        'JH_MONITOR_ES_ADDR=https://es.example.com:9200 '
        'bash /tmp/install.sh install http://127.0.0.1:10844 cn'
    ), result

    print('test_client_install_es_address: ok')


if __name__ == '__main__':
    main()
