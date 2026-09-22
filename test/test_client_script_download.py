# coding: utf-8

import os
import sys


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path[:0] = [ROOT_DIR, os.path.join(ROOT_DIR, 'class', 'core')]
os.chdir(ROOT_DIR)

from pub_api import pub_api


def main():
    api = pub_api()
    script_path = api._getClientScriptPath('get_host_info.py')
    assert script_path == os.path.join(ROOT_DIR, 'scripts', 'client', 'get_host_info.py'), script_path
    assert api._getClientScriptPath('install/debian.sh').endswith('/scripts/client/install/debian.sh')
    assert api._getClientScriptPath('install/filebeat/install.sh').endswith('/scripts/client/install/filebeat/install.sh')
    assert api._getClientScriptPath('../../data/default.db') == ''
    assert api._getClientScriptPath('unknown.py') == ''
    print('client script download: ok')


if __name__ == '__main__':
    main()
