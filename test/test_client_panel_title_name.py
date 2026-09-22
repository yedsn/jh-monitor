# coding: utf-8

import json
import os
import sys
import tempfile


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CLIENT_DIR = os.path.join(ROOT_DIR, 'scripts', 'client')
if CLIENT_DIR not in sys.path:
    sys.path.insert(0, CLIENT_DIR)

import get_host_info


def main():
    original_config_file = get_host_info.JH_PANEL_CONFIG_FILE
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as fp:
        json.dump({'title': 'BK100-Panel'}, fp)
        config_file = fp.name

    try:
        get_host_info.JH_PANEL_CONFIG_FILE = config_file
        assert get_host_info.get_jh_panel_title() == 'BK100-Panel'
        assert get_host_info.get_host_display_name() == 'BK100-Panel'

        with open(config_file, 'w') as fp:
            fp.write('{}')
        assert get_host_info.get_jh_panel_title() == ''
        assert get_host_info.get_host_display_name() == ''
    finally:
        get_host_info.JH_PANEL_CONFIG_FILE = original_config_file
        os.unlink(config_file)

    print('client panel title name: ok')


if __name__ == '__main__':
    main()
