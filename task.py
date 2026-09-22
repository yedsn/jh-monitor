# coding: utf-8

# ---------------------------------------------------------------------------------
# 江湖云监控
# ---------------------------------------------------------------------------------
# copyright (c) 2018-∞(https://github.com/jianghujs/jh-monitor) All rights reserved.
# ---------------------------------------------------------------------------------
# Author: midoks <midoks@163.com>
# ---------------------------------------------------------------------------------

# ---------------------------------------------------------------------------------
# 计划任务
# ---------------------------------------------------------------------------------

import sys
import os
import json
import time
import threading
import psutil
import traceback
from colorama import init, Fore, Style

# 初始化 colorama
init(autoreset=True)

if sys.version_info[0] == 2:
    reload(sys)
    sys.setdefaultencoding('utf-8')


sys.path.append(os.getcwd() + "/class/core")
sys.path.append(os.getcwd() + "/class/plugin")
import jh
import db
sys.path.append(os.getcwd() + "/scripts")
sys.path.append(os.getcwd() + "/scripts/client")
sys.path.append(os.getcwd() + "/class/es/service")
from report_analyser import HostReportAnalyser
from report_sender import HostReportSender
import host_status_service as host_status_service_utils

# print sys.path

# cmd = 'ls /usr/local/lib/ | grep python  | cut -d \\  -f 1 | awk \'END {print}\''
# info = jh.execShell(cmd)
# p = "/usr/local/lib/" + info[0].strip() + "/site-packages"
# sys.path.append(p)


global pre, timeoutCount, logPath, isTask, oldEdate, isCheck
pre = 0
timeoutCount = 0
isCheck = 0
oldEdate = None

logPath = os.getcwd() + '/tmp/panelExec.log'
isTask = os.getcwd() + '/tmp/panelTask.pl'

if not os.path.exists(os.getcwd() + "/tmp"):
    os.system('mkdir -p ' + os.getcwd() + "/tmp")

if not os.path.exists(logPath):
    os.system("touch " + logPath)


def service_cmd(method):
    cmd = '/etc/init.d/jhm'
    if os.path.exists(cmd):
        execShell(cmd + ' ' + method)
        return

    cmd = jh.getRunDir() + '/scripts/init.d/jhm'
    if os.path.exists(cmd):
        execShell(cmd + ' ' + method)
        return


def jh_async(f):
    def wrapper(*args, **kwargs):
        thr = threading.Thread(target=f, args=args, kwargs=kwargs)
        thr.start()
    return wrapper


@jh_async
def restartPanel():
    time.sleep(1)
    cmd = jh.getRunDir() + '/scripts/init.d/jhm reload &'
    jh.execShell(cmd)


def execShell(cmdstring, cwd=None, timeout=None, shell=True):
    try:
        global logPath
        import shlex
        import datetime
        import subprocess

        if timeout:
            end_time = datetime.datetime.now() + datetime.timedelta(seconds=timeout)

        cmd = cmdstring + ' > ' + logPath + ' 2>&1'
        sub = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, shell=shell, bufsize=4096)
        while sub.poll() is None:
            time.sleep(0.1)

        data = sub.communicate()
        # python3 fix 返回byte数据
        if isinstance(data[0], bytes):
            t1 = str(data[0], encoding='utf-8')

        if isinstance(data[1], bytes):
            t2 = str(data[1], encoding='utf-8')
        # jh.writeFile('/root/1.txt', '执行成功:' + str(t1 + t2))
        return True
    except Exception as e:
        # jh.writeFile('/root/1.txt', '执行失败:' + str(e))
        return False


def downloadFile(url, filename):
    # 下载文件
    try:
        import urllib
        import socket
        socket.setdefaulttimeout(300)

        headers = (
            'User-Agent', 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36')
        opener = urllib.request.build_opener()
        opener.addheaders = [headers]
        urllib.request.install_opener(opener)

        urllib.request.urlretrieve(
            url, filename=filename, reporthook=downloadHook)

        if not jh.isAppleSystem():
            os.system('chown www.www ' + filename)

        writeLogs('done')
    except Exception as e:
        writeLogs(str(e))


def downloadHook(count, blockSize, totalSize):
    # 下载文件进度回调
    global pre
    used = count * blockSize
    pre1 = int((100.0 * used / totalSize))
    if pre == (100 - pre1):
        return
    speed = {'total': totalSize, 'used': used, 'pre': pre1}
    writeLogs(json.dumps(speed))


def writeLogs(logMsg):
    # 写输出日志
    try:
        global logPath
        fp = open(logPath, 'w+')
        fp.write(logMsg)
        fp.close()
    except:
        pass


def runTask():
    global isTask
    try:
        if os.path.exists(isTask):
            sql = db.Sql()
            sql.table('tasks').where(
                "status=?", ('-1',)).setField('status', '0')
            taskArr = sql.table('tasks').where("status=?", ('0',)).field(
                'id,type,execstr').order("id asc").select()
            for value in taskArr:
                start = int(time.time())
                if not sql.table('tasks').where("id=?", (value['id'],)).count():
                    continue
                sql.table('tasks').where("id=?", (value['id'],)).save(
                    'status,start', ('-1', start))
                if value['type'] == 'download':
                    argv = value['execstr'].split('|jh|')
                    downloadFile(argv[0], argv[1])
                elif value['type'] == 'execshell':
                    execStatus = execShell(value['execstr'])
                end = int(time.time())
                sql.table('tasks').where("id=?", (value['id'],)).save(
                    'status,end', ('1', end))

                if(sql.table('tasks').where("status=?", ('0')).count() < 1):
                    os.system('rm -f ' + isTask)

            sql.close()
    except Exception as e:
        print(str(e))

    # 站点过期检查
    siteEdate()


def startTask():
    # 任务队列
    try:
        while True:
            runTask()
            time.sleep(2)
    except Exception as e:
        time.sleep(60)
        startTask()


def siteEdate():
    # 网站到期处理
    global oldEdate
    try:
        if not oldEdate:
            oldEdate = jh.readFile('data/edate.pl')
        if not oldEdate:
            oldEdate = '0000-00-00'
        mEdate = time.strftime('%Y-%m-%d', time.localtime())
        if oldEdate == mEdate:
            return False
        edateSites = jh.M('sites').where('edate>? AND edate<? AND (status=? OR status=?)',
                                         ('0000-00-00', mEdate, 1, '正在运行')).field('id,name').select()
        import site_api
        for site in edateSites:
            site_api.site_api().stop(site['id'], site['name'])
        oldEdate = mEdate
        jh.writeFile('data/edate.pl', mEdate)
    except Exception as e:
        print(str(e))


def getCollectedHostNameFromStatus(status_record):
    if isinstance(status_record, dict):
        host_doc = status_record.get('host') or {}
        collected_host_name = str(host_doc.get('panel_title', '') or '').strip()
        if collected_host_name:
            return collected_host_name
    return ''


def hostGrowthAlarmTask():
    """资源增长预测和告警"""
    try:
        sql = db.Sql()
        
        while True:
            # 读取配置
            config = jh.getGrowthAlarmConfig()
            scan_interval = config.get('scan_interval', 10)
            memory_scan_history_minutes = config.get('memory_scan_history_minutes', 120)
            disk_scan_history_minutes = config.get('disk_scan_history_minutes', 30)
            warning_threshold = config.get('warning_threshold', 80)
            prediction_critical_hours = config.get('prediction_critical_hours', 24)
            prediction_warning_hours = config.get('prediction_warning_hours', 72)
            notify_critical_interval = config.get('notify_critical_interval', 600)
            notify_warning_interval = config.get('notify_warning_interval', 1800)
            enable_memory_monitor = config.get('enable_memory_monitor', False)  # 默认开启内存监控
            enable_disk_monitor = config.get('enable_disk_monitor', False)  # 默认开启磁盘监控
            
            current_time = int(time.time())
            
            print(f"{Fore.BLUE}★ ========= [resourceGrowthAlarm] STARTED - 开始分析资源增长: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(current_time))}{Style.RESET_ALL}")
            
            # 获取主机列表
            host_list = jh.M('host').field('host_id,host_name,ip').select()

            if not isinstance(host_list, list):
                print(f"{Fore.RED}|- 获取主机列表失败，跳过本轮资源增长分析: {host_list}{Style.RESET_ALL}")
                time.sleep(scan_interval)
                continue

            latest_status_map = host_status_service_utils.getLatestStatusDocs(host_list)
            
            for host in host_list:
                if not isinstance(host, dict):
                    print(f"{Fore.RED}|- 跳过格式异常的主机记录: {host}{Style.RESET_ALL}")
                    continue

                host_id = host['host_id']
                host_name = getCollectedHostNameFromStatus(latest_status_map.get(host_id))
                
                # 检查上次告警时间
                last_alarm = sql.table('host_alarm').where('host_id=? AND alarm_type=?', 
                    (host_id, '资源增长预警')).order('id desc').field('alarm_level,addtime').find()
                
                if isinstance(last_alarm, dict):
                    try:
                        last_alarm_time = int(time.mktime(time.strptime(last_alarm['addtime'], '%Y-%m-%d %H:%M:%S')))
                        time_diff = current_time - last_alarm_time

                        if (last_alarm['alarm_level'] == '紧急' and time_diff < notify_critical_interval) or \
                            (last_alarm['alarm_level'] == '警告' and time_diff < notify_warning_interval):
                            continue
                    except (KeyError, TypeError, ValueError):
                        print(f"{Fore.RED}|- 主机 [{host_name}] 的上次资源增长告警记录格式异常，忽略冷却时间: {last_alarm}{Style.RESET_ALL}")
                elif last_alarm:
                    print(f"{Fore.RED}|- 查询主机 [{host_name}] 的上次资源增长告警失败，忽略冷却时间: {last_alarm}{Style.RESET_ALL}")

                print(f"|- 开始分析主机 [{host_name}] 资源增长...")

                history_start = current_time - (max(memory_scan_history_minutes, disk_scan_history_minutes) * 60)
                status_history = host_status_service_utils.getHostStatusHistory(host_id, history_start, current_time)
                if not isinstance(status_history, list):
                    print(f"{Fore.RED}|- 主机 [{host_name}] 的状态历史数据格式异常，跳过本轮分析{Style.RESET_ALL}")
                    continue

                running_history = [
                    item for item in status_history
                    if isinstance(item, dict) and item.get('host_status') == 'Running'
                ]

                if not running_history:
                    continue

                latest_record = running_history[-1]

                # 如果没有最新记录，则跳过
                if not latest_record:
                    continue

                # 分析内存和磁盘
                memory_alarm = None
                disk_alarm = None
                
                if enable_memory_monitor:
                    # 获取内存历史记录
                    memory_history_start = current_time - (memory_scan_history_minutes * 60)
                    memory_history_records = [
                        item for item in running_history
                        if int(item.get('addtime', 0)) >= memory_history_start
                    ]
                    
                    if memory_history_records and len(memory_history_records) >= 2:
                        memory_alarm = jh.analyze_resource_growth(
                            host_id, host_name, latest_record, memory_history_records, 
                            'memory', 'mem_info', warning_threshold, 
                            prediction_critical_hours, prediction_warning_hours,
                            notify_critical_interval, notify_warning_interval,
                            current_time, memory_scan_history_minutes
                        )
                
                if enable_disk_monitor:
                    # 获取磁盘历史记录
                    disk_history_start = current_time - (disk_scan_history_minutes * 60)
                    disk_history_records = [
                        item for item in running_history
                        if int(item.get('addtime', 0)) >= disk_history_start
                    ]
                    
                    if disk_history_records and len(disk_history_records) >= 2:
                        disk_alarm = jh.analyze_resource_growth(
                            host_id, host_name, latest_record, disk_history_records, 
                            'disk', 'disk_info', warning_threshold, 
                            prediction_critical_hours, prediction_warning_hours,
                            notify_critical_interval, notify_warning_interval,
                            current_time, disk_scan_history_minutes
                        )
                
                # 合并告警信息
                final_alarm = {
                    'level': None,
                    'content': '',
                    'notify_interval': 0
                }
                
                for alarm in [memory_alarm, disk_alarm]:
                    if alarm and alarm['level']:
                        # 更新告警级别（取最高级别）
                        if final_alarm['level'] is None or (alarm['level'] == 'critical' and final_alarm['level'] == 'warning'):
                            final_alarm['level'] = alarm['level']
                            final_alarm['notify_interval'] = alarm['notify_interval']
                        
                        # 追加告警内容
                        if final_alarm['content'] and alarm['content']:
                            final_alarm['content'] += '<hr>'
                        final_alarm['content'] += alarm['content']
                
                # 如果有告警，发送通知
                if final_alarm['level']:
                    alarm_level_map = {
                        'critical': '紧急',
                        'warning': '警告'
                    }
                    
                    # 添加告警记录
                    sql.table('host_alarm').add(
                        'host_id,host_name,alarm_type,alarm_level,alarm_content,addtime',
                        (host_id, host_name, '资源增长预警', alarm_level_map[final_alarm['level']], final_alarm['content'], time.strftime('%Y-%m-%d %H:%M:%S'))
                    )

                    print(f"|- 添加主机 [{host_name}] 资源增长预警 - {alarm_level_map[final_alarm['level']]}，告警主体")
                    
                    # 发送通知消息
                    panel_title = jh.getConfig('title')
                    ip = jh.getHostAddr()
                    now_time = jh.getDateFromNow()
                    
                    # 根据告警级别设置不同的颜色
                    level_color = '#FF4500' if final_alarm['level'] == 'critical' else '#FFA500'
                    
                    html_msg = f"""
                    <div style="font-family: Arial, sans-serif; padding: 15px; background-color: #f5f5f5; border-radius: 5px;">
                        <div style="border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 10px;">
                            <span style="color: #333; font-size: 14px;">{now_time}</span> 
                        </div>
                        <div style="margin-bottom: 15px;">
                            <span style="font-weight: bold; color: {level_color};">【{alarm_level_map[final_alarm['level']]}】</span>
                            <span style="font-weight: bold;">主机 [{host_name}]</span>
                        </div>
                        <div style="background-color: #fff; padding: 10px; border-left: 4px solid {level_color}; border-radius: 3px;">
                            {final_alarm['content']}
                        </div>
                    </div>
                    """
                    
                    jh.notifyMessage(
                        title=f'资源增长预警-{alarm_level_map[final_alarm["level"]]}：{host_name} {now_time}',
                        msg=html_msg, 
                        msgtype='html',
                        stype='资源增长预警', 
                        trigger_time=0
                    )
            
            print(f"{Fore.GREEN}★ ========= [resourceGrowthAlarm] SUCCESS - 完成资源增长分析: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(time.time())))}{Style.RESET_ALL}")
            
            # 休眠至下次执行
            time.sleep(scan_interval)
    
    except Exception as ex:
        traceback.print_exc()
        jh.writeFile('logs/resource_growth_interrupt.pl', str(ex))
        print(f"{Fore.RED}★ ========= [resourceGrowthAlarm] ERROR：{str(ex)} {Style.RESET_ALL}")
        
        notify_msg = jh.generateCommonNotifyMessage("资源增长预测异常：" + str(ex))
        jh.notifyMessage(title='资源增长预测异常通知：{} {}'.format(jh.getConfig('title'), jh.getDateFromNow()), msg=notify_msg, stype='资源增长预测', trigger_time=3600)
        
        time.sleep(300)  # 出错后等待5分钟再重试
        hostGrowthAlarmTask()  # 递归重启


# --------------------------------------Host Report Notify Start   --------------------------------------------- #
def hostReportPipelineTask():
    try:
        while True:
            try:
                now_ts = int(time.time())
                host_report_logger = lambda message: print(f"{Fore.CYAN}★ ========= [hostReportPipelineTask] {message}{Style.RESET_ALL}")
                analyser = HostReportAnalyser(now_ts=now_ts, logger=host_report_logger)
                sender = HostReportSender(now_ts=now_ts, logger=host_report_logger, es_client=analyser._es)
                report_date = time.strftime('%Y-%m-%d', time.localtime(now_ts))
                report_window = analyser.get_report_window(report_date)
                report_config, enabled_rows, due_rows = analyser.get_schedule_state()
                if not enabled_rows or not due_rows:
                    time.sleep(31)
                    continue
                
                print(f"{Fore.BLUE}★ ========= [hostReportPipelineTask] STARTED - 报告日期: {report_window.get('report_date')} 待分析主机数: {len(enabled_rows)} 触发主机数: {len(due_rows)}{Style.RESET_ALL}")

                analysis_result = analyser.run_analysis(enabled_rows, report_date=report_date)
                print(f"{Fore.GREEN}★ ========= [hostReportPipelineTask] ANALYSIS - 日期: {analysis_result.get('report_date')} ready={analysis_result.get('single_ready')}/{analysis_result.get('single_total')} abnormal={analysis_result.get('single_abnormal')} overview_ready={analysis_result.get('overview_ready')}{Style.RESET_ALL}")

                result = sender.run_delivery(
                    due_rows,
                    report_config,
                    report_date=report_date,
                    enabled_rows=enabled_rows,
                    overview_document=analysis_result.get('overview_document'),
                    single_documents=analysis_result.get('single_documents')
                )
                status = result.get('status')
                if status == 'ok':
                    print(f"{Fore.GREEN}★ ========= [hostReportPipelineTask] SUCCESS - 日期: {result.get('report_date')} overview={result.get('overview_sent')} single_success={result.get('single_success')} single_skipped={result.get('single_skipped')}{Style.RESET_ALL}")
                elif status in ('partial', 'blocked', 'failed', 'skipped'):
                    print(f"{Fore.YELLOW}★ ========= [hostReportPipelineTask] {status.upper()} - {result}{Style.RESET_ALL}")
            except Exception as ex:
                traceback.print_exc()
                print(f"{Fore.RED}★ ========= [hostReportPipelineTask] ERROR：{str(ex)} {Style.RESET_ALL}")
            time.sleep(31)
    except Exception:
        traceback.print_exc()


# --------------------------------------Host Report Notify End   --------------------------------------------- #
  

# --------------------------------------Panel Restart Start   --------------------------------------------- #
def restartService():
    restartTip = 'data/restart.pl'
    while True:
        if os.path.exists(restartTip):
            os.remove(restartTip)
            service_cmd('restart')
        time.sleep(1)

def restartPanelService():
    restartPanelTip = 'data/restart_panel.pl'
    while True:
        if os.path.exists(restartPanelTip):
            os.remove(restartPanelTip)
            service_cmd('restart_panel')
        time.sleep(1)
# --------------------------------------Panel Restart End   --------------------------------------------- #


# --------------------------------------Debounce Commands Start   --------------------------------------------- #
debounce_commands_pool_file = 'data/debounce_commands_pool.json'
def read_debounce_commands_pool():
    if not os.path.exists(debounce_commands_pool_file):
        write_debounce_commands_pool([])
        return []
    try:
        with open(debounce_commands_pool_file, 'r') as file:
            return json.load(file)
    except:
        # 往文件写入[]
        write_debounce_commands_pool([])
        return []
    
def write_debounce_commands_pool(debounce_commands_pool):
    with open(debounce_commands_pool_file, 'w') as file:
        json.dump(debounce_commands_pool, file)

def debounceCommandsService():
    while True:
      if not os.path.exists(debounce_commands_pool_file):
        write_debounce_commands_pool([])
      # 倒计时并执行命令
      debounce_commands_pool = read_debounce_commands_pool()
      debounce_commands_to_remove = []
      for debounce_commands_info in debounce_commands_pool:
        debounce_commands_info['seconds_to_run'] -= 1
        if debounce_commands_info['seconds_to_run'] < 0:
          command = debounce_commands_info.get('command', '')
          debounce_commands_to_remove.append(debounce_commands_info)
          if command:
            jh.execShell(command)
      # 删除已经执行的命令
      for debounce_commands_info in debounce_commands_to_remove:
        debounce_commands_pool.remove(debounce_commands_info)
      # 写回文件
      write_debounce_commands_pool(debounce_commands_pool)
      time.sleep(1)

# --------------------------------------Debounce Commands End   --------------------------------------------- #


def setDaemon(t):
    if sys.version_info.major == 3 and sys.version_info.minor >= 10:
        t.daemon = True
    else:
        t.setDaemon(True)
    return t

if __name__ == "__main__":
    # 资源增长告警
    hga = threading.Thread(target=hostGrowthAlarmTask)
    hga = setDaemon(hga)
    hga.start()

    # 主机报告流水线
    hrp = threading.Thread(target=hostReportPipelineTask)
    hrp = setDaemon(hrp)
    hrp.start()

    # Panel Restart Start
    rps = threading.Thread(target=restartPanelService)
    rps = setDaemon(rps)
    rps.start()

    # Restart Start
    rs = threading.Thread(target=restartService)
    rs = setDaemon(rs)
    rs.start()

    # Debounce Commands
    dcs = threading.Thread(target=debounceCommandsService)
    dcs = setDaemon(dcs)
    dcs.start()


    startTask()
