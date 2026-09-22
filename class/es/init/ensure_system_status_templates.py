#!/usr/bin/env python3
# coding: utf-8

import copy
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ES_DIR = os.path.dirname(CURRENT_DIR)
ROOT_DIR = os.path.dirname(os.path.dirname(ES_DIR))
ES_MODEL_DIR = os.path.join(ES_DIR, 'model')
for path in (ES_DIR, ES_MODEL_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from index_manager import IndexManager
from report_schema import REPORT_INDEX_TEMPLATES


SYSTEM_STATUS_TEMPLATE_NAMES = (
    'host-debian-system-status-template',
    'host-pve-system-status-template',
)


def main():
    manager = IndexManager()
    definitions = {
        name: copy.deepcopy(REPORT_INDEX_TEMPLATES[name])
        for name in SYSTEM_STATUS_TEMPLATE_NAMES
    }
    for result in manager.ensure_index_templates(definitions):
        print('{template}: {action}'.format(**result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
