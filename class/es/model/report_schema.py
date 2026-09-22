# coding: utf-8

DATE_TIME_FORMAT = 'yyyy-MM-dd HH:mm:ss||strict_date_optional_time'
DATE_ONLY_FORMAT = 'yyyy-MM-dd||strict_date_optional_time'

REPORT_INDEXES = {
    'host-debian-system-status': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'host': {
                    'properties': {
                        'host_id': {'type': 'keyword'},
                        'host_name': {'type': 'keyword'},
                        'panel_title': {'type': 'keyword'},
                        'host_ip': {'type': 'ip'},
                        'host_group': {'type': 'keyword'},
                        'host_status': {'type': 'keyword'},
                        'system_type': {'type': 'keyword'}
                    }
                },
                'system': {
                    'properties': {
                        'cpu': {'type': 'float'},
                        'memory': {'type': 'float'},
                        'load': {
                            'properties': {
                                'pro': {'type': 'float'},
                                'one': {'type': 'float'},
                                'five': {'type': 'float'},
                                'fifteen': {'type': 'float'}
                            }
                        },
                        'disks': {'type': 'nested'}
                    }
                },
                'site': {'type': 'nested'},
                'jianghujs': {'type': 'nested'},
                'docker': {'type': 'nested'},
                'mysql': {'type': 'object', 'dynamic': True},
                'lsync': {'type': 'object', 'dynamic': True},
                'rsync': {'type': 'nested'},
                'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'add_timestamp': {'type': 'double'}
            }
        }
    },
    'host-pve-system-status': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'host': {
                    'properties': {
                        'host_id': {'type': 'keyword'},
                        'host_name': {'type': 'keyword'},
                        'panel_title': {'type': 'keyword'},
                        'host_ip': {'type': 'ip'},
                        'host_group': {'type': 'keyword'},
                        'host_status': {'type': 'keyword'},
                        'system_type': {'type': 'keyword'}
                    }
                },
                'system': {
                    'properties': {
                        'cpu': {'type': 'float'},
                        'memory': {'type': 'float'},
                        'load': {
                            'properties': {
                                'pro': {'type': 'float'},
                                'one': {'type': 'float'},
                                'five': {'type': 'float'},
                                'fifteen': {'type': 'float'}
                            }
                        },
                        'disks': {'type': 'nested'}
                    }
                },
                'pve': {
                    'type': 'object',
                    'dynamic': True,
                    'properties': {
                        'data': {
                            'type': 'object',
                            'dynamic': True,
                            'properties': {
                                'cpu': {
                                    'type': 'object',
                                    'dynamic': True,
                                    'properties': {
                                        'usage': {'type': 'float'},
                                        'load': {'type': 'float'},
                                        'top_processes': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'user': {'type': 'keyword'},
                                                'pid': {'type': 'keyword'},
                                                'cpu': {'type': 'float'},
                                                'mem': {'type': 'float'},
                                                'command': {'type': 'text'}
                                            }
                                        }
                                    }
                                },
                                'memory': {
                                    'type': 'object',
                                    'dynamic': True,
                                    'properties': {
                                        'usage_percent': {'type': 'float'}
                                    }
                                },
                                'disk': {
                                    'type': 'object',
                                    'dynamic': True,
                                    'properties': {
                                        'filesystems': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'use_percent': {'type': 'float'}
                                            }
                                        },
                                        'large_disks': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'use_percent': {'type': 'float'}
                                            }
                                        }
                                    }
                                },
                                'sensors': {
                                    'type': 'object',
                                    'dynamic': True,
                                    'properties': {
                                        'temperatures': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'name': {'type': 'keyword'},
                                                'value': {'type': 'float'},
                                                'unit': {'type': 'keyword'}
                                            }
                                        },
                                        'fans': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'name': {'type': 'keyword'},
                                                'value': {'type': 'float'},
                                                'unit': {'type': 'keyword'}
                                            }
                                        },
                                        'voltages': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'name': {'type': 'keyword'},
                                                'value': {'type': 'float'},
                                                'unit': {'type': 'keyword'}
                                            }
                                        }
                                    }
                                },
                                'smart': {
                                    'type': 'object',
                                    'dynamic': True,
                                    'properties': {
                                        'devices': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'temperature': {'type': 'float'},
                                                'health_score': {'type': 'float'},
                                                'attributes': {
                                                    'type': 'nested',
                                                    'dynamic': True,
                                                    'properties': {
                                                        'value': {'type': 'float'},
                                                        'worst': {'type': 'float'},
                                                        'threshold': {'type': 'float'},
                                                        'raw_int': {'type': 'float'}
                                                    }
                                                }
                                            }
                                        }
                                    }
                                },
                                'io': {
                                    'type': 'object',
                                    'dynamic': True,
                                    'properties': {
                                        'devices': {
                                            'type': 'nested',
                                            'dynamic': True,
                                            'properties': {
                                                'rrqm_s': {'type': 'float'},
                                                'wrqm_s': {'type': 'float'},
                                                'r_s': {'type': 'float'},
                                                'w_s': {'type': 'float'},
                                                'rkB_s': {'type': 'float'},
                                                'wkB_s': {'type': 'float'},
                                                'avgrq_sz': {'type': 'float'},
                                                'avgqu_sz': {'type': 'float'},
                                                'await': {'type': 'float'},
                                                'r_await': {'type': 'float'},
                                                'w_await': {'type': 'float'},
                                                'svctm': {'type': 'float'},
                                                'util': {'type': 'float'}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'add_timestamp': {'type': 'double'}
            }
        }
    },
    'host-debian-xtrabackup': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'host_id': {'type': 'keyword'},
                'host_name': {'type': 'keyword'},
                'host_ip': {'type': 'ip'},
                'id': {'type': 'keyword'},
                'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'add_timestamp': {'type': 'double'},
                'size': {'type': 'keyword'},
                'size_bytes': {'type': 'double'},
                'collector_source': {'type': 'keyword'}
            }
        }
    },
    'host-debian-xtrabackup-inc': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'host_id': {'type': 'keyword'},
                'host_name': {'type': 'keyword'},
                'host_ip': {'type': 'ip'},
                'id': {'type': 'keyword'},
                'backup_type': {'type': 'keyword'},
                'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'add_timestamp': {'type': 'double'},
                'size': {'type': 'keyword'},
                'size_bytes': {'type': 'double'},
                'collector_source': {'type': 'keyword'}
            }
        }
    },
    'host-debian-backup': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'host_id': {'type': 'keyword'},
                'host_name': {'type': 'keyword'},
                'host_ip': {'type': 'ip'},
                'type': {'type': 'keyword'},
                'filename': {'type': 'keyword'},
                'path': {'type': 'keyword'},
                'size': {'type': 'keyword'},
                'size_bytes': {'type': 'double'},
                'message': {'type': 'text'},
                'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'collector_source': {'type': 'keyword'}
            }
        }
    },
    'host-report-single': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'report_type': {'type': 'keyword'},
                'report_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                'report_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'start_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'end_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'start_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                'end_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                'host_id': {'type': 'keyword'},
                'host_name': {'type': 'keyword'},
                'host_ip': {'type': 'ip'},
                'summary_tips': {'type': 'text'},
                'error_tips': {'type': 'text'},
                'html_content': {'type': 'text'},
                'validation': {
                    'properties': {
                        'is_complete': {'type': 'boolean'},
                        'status': {'type': 'keyword'},
                        'errors': {'type': 'keyword'}
                    }
                },
                'delivery': {
                    'properties': {
                        'status': {'type': 'keyword'},
                        'last_sent_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                        'recipients': {'type': 'keyword'},
                        'retry_count': {'type': 'integer'},
                        'last_error': {'type': 'text'}
                    }
                },
                'extra_info': {'type': 'object', 'enabled': False}
            }
        }
    },
    'host-report-overview': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'report_type': {'type': 'keyword'},
                'report_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                'report_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'start_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'end_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                'title': {'type': 'text'},
                'html_content': {'type': 'text'},
                'host_overview_info': {'type': 'object', 'dynamic': True},
                'host_overview_tips': {'type': 'nested'},
                'exception_host_summary_tips': {'type': 'nested'},
                'single_host_report_list': {'type': 'nested'},
                'validation': {
                    'properties': {
                        'is_complete': {'type': 'boolean'},
                        'status': {'type': 'keyword'},
                        'errors': {'type': 'keyword'}
                    }
                },
                'delivery': {
                    'properties': {
                        'status': {'type': 'keyword'},
                        'last_sent_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                        'recipients': {'type': 'keyword'},
                        'retry_count': {'type': 'integer'},
                        'last_error': {'type': 'text'}
                    }
                },
                'extra_info': {'type': 'object', 'enabled': False}
            }
        }
    }
}

REPORT_DATA_STREAMS = {
    'single_prefix': 'host-report-single',
    'overview_prefix': 'host-report-overview',
}


REPORT_INDEX_TEMPLATES = {
    'host-debian-system-status-template': {
        'index_patterns': ['host-debian-*-system-status-*'],
        'priority': 500,
        'template': {
            'settings': {
                'number_of_shards': 1,
                'number_of_replicas': 0
            },
            'mappings': {
                'dynamic': True,
                'dynamic_templates': [
                    {
                        'size_bytes_as_double': {
                            'path_match': '*.size_bytes',
                            'match_mapping_type': 'long',
                            'mapping': {'type': 'double'}
                        }
                    },
                    {
                        'total_size_bytes_as_double': {
                            'path_match': '*.total_size_bytes',
                            'match_mapping_type': 'long',
                            'mapping': {'type': 'double'}
                        }
                    },
                    {
                        'last_backup_size_bytes_as_double': {
                            'path_match': '*.last_backup_size_bytes',
                            'match_mapping_type': 'long',
                            'mapping': {'type': 'double'}
                        }
                    }
                ],
                'properties': {
                    'host': {
                        'dynamic': True,
                        'properties': {
                            'host_id': {'type': 'keyword'},
                            'host_name': {'type': 'keyword'},
                            'panel_title': {'type': 'keyword'},
                            'host_ip': {'type': 'ip'},
                            'host_group': {'type': 'keyword'},
                            'host_status': {'type': 'keyword'},
                            'system_type': {'type': 'keyword'}
                        }
                    },
                    'system': {
                        'dynamic': True,
                        'properties': {
                            'cpu': {'type': 'float'},
                            'memory': {'type': 'float'},
                            'load': {
                                'dynamic': True,
                                'properties': {
                                    'pro': {'type': 'float'},
                                    'one': {'type': 'float'},
                                    'five': {'type': 'float'},
                                    'fifteen': {'type': 'float'}
                                }
                            },
                            'disks': {'type': 'nested'}
                        }
                    },
                    'site': {'type': 'nested'},
                    'jianghujs': {'type': 'nested'},
                    'docker': {'type': 'nested'},
                    'mysql': {
                        'type': 'object',
                        'dynamic': True,
                        'properties': {
                            'total_size_bytes': {'type': 'double'},
                            'tables': {
                                'type': 'object',
                                'dynamic': True,
                                'properties': {
                                    'size_bytes': {'type': 'double'}
                                }
                            }
                        }
                    },
                    'backup': {
                        'type': 'object',
                        'dynamic': True
                    },
                    'lsync': {
                        'type': 'object',
                        'dynamic': True
                    },
                    'rsync': {'type': 'nested'},
                    'collector': {
                        'dynamic': True,
                        'properties': {
                            'source': {'type': 'keyword'},
                            'version': {'type': 'keyword'}
                        }
                    },
                    'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'add_timestamp': {'type': 'double'}
                }
            }
        },
        'data_stream': {}
    },
    'host-pve-system-status-template': {
        'index_patterns': ['host-pve-*-system-status-*'],
        'priority': 500,
        'template': {
            'settings': {
                'number_of_shards': 1,
                'number_of_replicas': 0
            },
            'mappings': {
                'dynamic': True,
                'properties': {
                    'host': {
                        'dynamic': True,
                        'properties': {
                            'host_id': {'type': 'keyword'},
                            'host_name': {'type': 'keyword'},
                            'panel_title': {'type': 'keyword'},
                            'host_ip': {'type': 'ip'},
                            'host_group': {'type': 'keyword'},
                            'host_status': {'type': 'keyword'},
                            'system_type': {'type': 'keyword'}
                        }
                    },
                    'system': {
                        'dynamic': True,
                        'properties': {
                            'cpu': {'type': 'float'},
                            'memory': {'type': 'float'},
                            'load': {'type': 'object', 'enabled': False},
                            'disks': {'type': 'object', 'enabled': False}
                        }
                    },
                    'pve': {'type': 'object', 'enabled': False},
                    'collector': {
                        'dynamic': True,
                        'properties': {
                            'source': {'type': 'keyword'},
                            'version': {'type': 'keyword'}
                        }
                    },
                    'add_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'add_timestamp': {'type': 'double'}
                }
            }
        },
        'data_stream': {}
    },
    'host-report-single-ds-template': {
        'index_patterns': ['host-report-single-*'],
        'priority': 600,
        'template': {
            'settings': {
                'number_of_shards': 1,
                'number_of_replicas': 0
            },
            'mappings': {
                'dynamic': True,
                'properties': {
                    '@timestamp': {'type': 'date'},
                    'report_run_id': {'type': 'keyword'},
                    'report_type': {'type': 'keyword'},
                    'report_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                    'report_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'start_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'end_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'start_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                    'end_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                    'host_id': {'type': 'keyword'},
                    'host_name': {'type': 'keyword'},
                    'host_ip': {'type': 'ip'},
                    'title': {'type': 'text'},
                    'is_abnormal': {'type': 'boolean'},
                    'summary_tips': {'type': 'text'},
                    'error_tips': {'type': 'text'},
                    'html_content': {'type': 'text'},
                    'validation': {
                        'properties': {
                            'is_complete': {'type': 'boolean'},
                            'status': {'type': 'keyword'},
                            'errors': {'type': 'keyword'}
                        }
                    },
                    'delivery': {
                        'properties': {
                            'status': {'type': 'keyword'},
                            'last_sent_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                            'recipients': {'type': 'keyword'},
                            'retry_count': {'type': 'integer'},
                            'last_error': {'type': 'text'}
                        }
                    },
                    'extra_info': {'type': 'object', 'enabled': False}
                }
            }
        },
        'data_stream': {}
    },
    'host-report-overview-ds-template': {
        'index_patterns': ['host-report-overview-*'],
        'priority': 600,
        'template': {
            'settings': {
                'number_of_shards': 1,
                'number_of_replicas': 0
            },
            'mappings': {
                'dynamic': True,
                'properties': {
                    '@timestamp': {'type': 'date'},
                    'report_run_id': {'type': 'keyword'},
                    'report_type': {'type': 'keyword'},
                    'report_date': {'type': 'date', 'format': DATE_ONLY_FORMAT},
                    'report_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'start_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'end_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    'title': {'type': 'text'},
                    'html_content': {'type': 'text'},
                    'host_overview_info': {'type': 'object', 'dynamic': True},
                    'host_overview_tips': {'type': 'nested'},
                    'exception_host_summary_tips': {'type': 'nested'},
                    'single_host_report_list': {'type': 'nested'},
                    'validation': {
                        'properties': {
                            'is_complete': {'type': 'boolean'},
                            'status': {'type': 'keyword'},
                            'errors': {'type': 'keyword'}
                        }
                    },
                    'delivery': {
                        'properties': {
                            'status': {'type': 'keyword'},
                            'last_sent_time': {'type': 'date', 'format': DATE_TIME_FORMAT},
                            'recipients': {'type': 'keyword'},
                            'retry_count': {'type': 'integer'},
                            'last_error': {'type': 'text'}
                        }
                    },
                    'extra_info': {'type': 'object', 'enabled': False}
                }
            }
        },
        'data_stream': {}
    }
}


__all__ = [
    'DATE_TIME_FORMAT',
    'DATE_ONLY_FORMAT',
    'REPORT_INDEXES',
    'REPORT_DATA_STREAMS',
    'REPORT_INDEX_TEMPLATES',
    'TASK_EVENT_INDEXES',
    'TASK_EVENT_INDEX_TEMPLATES',
]


TASK_EVENT_INDEXES = {
    'host-monitor-task-event': {
        'settings': {
            'number_of_shards': 1,
            'number_of_replicas': 0
        },
        'mappings': {
            'dynamic': True,
            'properties': {
                'task_id': {'type': 'keyword'},
                'task_name': {'type': 'keyword'},
                'host_id': {'type': 'keyword'},
                'host_ip': {'type': 'ip'},
                'log_path': {'type': 'keyword'},
                'status': {'type': 'keyword'},
                'msg': {'type': 'text'},
                'run_at': {'type': 'date', 'format': DATE_TIME_FORMAT},
                '@timestamp': {'type': 'date'},
                'collector_source': {'type': 'keyword'},
            }
        }
    }
}

TASK_EVENT_INDEX_TEMPLATES = {
    'host-monitor-task-event-template': {
        'index_patterns': ['host-monitor-task-event*'],
        'priority': 500,
        'template': {
            'settings': {
                'number_of_shards': 1,
                'number_of_replicas': 0
            },
            'mappings': {
                'dynamic': True,
                'properties': {
                    'task_id': {'type': 'keyword'},
                    'task_name': {'type': 'keyword'},
                    'host_id': {'type': 'keyword'},
                    'host_ip': {'type': 'ip'},
                    'log_path': {'type': 'keyword'},
                    'status': {'type': 'keyword'},
                    'msg': {'type': 'text'},
                    'run_at': {'type': 'date', 'format': DATE_TIME_FORMAT},
                    '@timestamp': {'type': 'date'},
                    'collector_source': {'type': 'keyword'},
                }
            }
        }
    }
}
