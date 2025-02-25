#!/usr/bin/python3
"""
date: 20250224-01
RutilVM Assistor

메뉴 항목 순서:
  1. Virtual Machines
  2. Data Centers
  3. Clusters
  4. Hosts
  5. Networks
  6. Storage Domains
  7. Storage Disks
  8. Users
  9. Certificate         ← (추후 구현: placeholder)
  10. Events
  
"""

# =============================================================================
# Section 1: Imports and Common Utility Functions
# =============================================================================

import os               # OS 관련 함수 사용
import sys              # 시스템 종료 등 사용
import getpass          # 비밀번호 입력
import curses           # 터미널 UI 구현
import subprocess       # 외부 프로세스 실행
import unicodedata      # 유니코드 문자 폭 계산
import requests         # HTTP 요청 전송
import xml.etree.ElementTree as ET  # XML 파싱
import urllib3          # HTTPS 경고 제어
import re               # 정규 표현식 사용
import pickle           # 세션 저장/불러오기
import signal           # 시그널 핸들링
import textwrap         # 텍스트 자동 줄바꿈
import time             # 시간 관련 함수
import threading        # ← 추가된 threading 모듈
from datetime import datetime, timezone  # 날짜/시간 처리
from ovirtsdk4.types import Host, VmStatus, Ip, IpVersion  # oVirt SDK 타입
from ovirtsdk4 import Connection, Error  # oVirt SDK 연결 및 오류 처리
from requests.auth import HTTPBasicAuth  # HTTP 기본 인증
import socket           # 네트워크 연결 확인
import math             # 수학 관련 함수, 상수 등을 사용
import ovirtsdk4.types as types  # oVirt SDK 타입 사용
import locale
import shlex
import pexpect
from urllib.parse import urlparse
from requests.auth import HTTPBasicAuth
locale.setlocale(locale.LC_ALL, '')

# HTTPS 경고 메시지 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----- 유틸리티 함수들 -----

def truncate_with_ellipsis(value, max_width):
    """문자열의 길이가 max_width보다 길면 생략 부호(...)를 추가하여 잘라 반환"""
    value = str(value) if value else "-"
    if len(value) > max_width:
        return value[:max_width - 2] + ".."
    return value

def get_network_speed(interface):
    """
    ethtool을 사용하여 네트워크 인터페이스의 실제 속도를 확인하는 함수.
    실패 시 "N/A"를 반환.
    """
    try:
        result = subprocess.run(['ethtool', interface],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True)
        for line in result.stdout.splitlines():
            if "Speed:" in line:
                return line.split(":")[1].strip()
    except Exception as e:
        print(f"Error getting speed for {interface}: {e}")
    return "N/A"

def get_display_width(text, max_width):
    """
    문자열의 출력 폭을 계산하여, max_width를 초과하면 잘라서 반환.
    동아시아 문자(F, W)는 2칸으로 계산.
    """
    display_width = sum(2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1 for c in text)
    if display_width > max_width:
        truncated = ""
        current_width = 0
        for char in text:
            char_width = 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1
            if current_width + char_width > max_width - 2:
                truncated += ".."
                break
            truncated += char
            current_width += char_width
        return truncated.ljust(max_width)
    return text.ljust(max_width - (display_width - len(text)))

def adjust_column_width(text, width):
    """테이블 열에 맞게 텍스트에 공백을 추가하여 맞춤 처리"""
    text = text if text else "-"
    text_width = sum(2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1 for c in text)
    padding = max(0, width - text_width)
    return text + " " * padding

def ensure_non_empty(value):
    """값이 비어 있으면 '-'를, 그렇지 않으면 원래 값을 반환"""
    return "-" if not value or str(value).strip() == "N/A" else value

def draw_table(stdscr, start_y, headers, col_widths, data, row_func, current_row=-1):
    """
    curses 화면에 테이블을 그리는 함수.
      - headers: 각 열의 제목
      - col_widths: 각 열의 너비
      - data: 데이터 리스트
      - row_func: 각 데이터 항목을 리스트 형태로 반환하는 함수
      - current_row: 현재 선택된 행(강조 처리)
    """
    header_line = "┌" + "┬".join("─" * w for w in col_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in col_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in col_widths) + "┘"
    stdscr.addstr(start_y, 1, header_line)
    stdscr.addstr(start_y + 1, 1, "│" + "│".join(get_display_width(h, w) for h, w in zip(headers, col_widths)) + "│")
    stdscr.addstr(start_y + 2, 1, divider_line)
    if not data:
        empty_row = "│" + "│".join(get_display_width("-", w) for w in col_widths) + "│"
        stdscr.addstr(start_y + 3, 1, empty_row)
    else:
        for idx, item in enumerate(data):
            row_y = start_y + 3 + idx
            row_data = [ensure_non_empty(d) for d in row_func(item)]
            row_text = "│" + "│".join(get_display_width(d, w) for d, w in zip(row_data, col_widths)) + "│"
            if idx == current_row:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(row_y, 1, row_text)
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(row_y, 1, row_text)
    stdscr.addstr(start_y + 3 + max(len(data), 1), 1, footer_line)

def check_ip_reachable(ip, port=443, timeout=5):
    """
    주어진 IP에 port(기본 443)로 timeout(기본 5초) 내에 연결 시도.
    연결 가능하면 True, 아니면 False를 반환.
    """
    try:
        sock = socket.create_connection((ip, port), timeout)
        sock.close()
        return True
    except Exception:
        return False

# =============================================================================
# Section 2: Session and Connection Management Functions
# =============================================================================

def get_fqdn_from_config():
    """
    /etc/ovirt-hosted-engine/hosted-engine.conf 파일에서
    fqdn 값을 읽어 반환하는 함수.
    """
    config_path = "/etc/ovirt-hosted-engine/hosted-engine.conf"
    try:
        with open(config_path, "r") as file:
            for line in file:
                match = re.match(r"^fqdn=(.+)$", line.strip())
                if match:
                    return match.group(1)
    except FileNotFoundError:
        print(f"Error: {config_path} not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading {config_path}: {e}")
        sys.exit(1)
    return None

def get_ip_from_hosts(fqdn):
    """
    /etc/hosts 파일에서 fqdn과 매칭되는 IP 주소를 찾아 반환.
    """
    hosts_path = "/etc/hosts"
    try:
        with open(hosts_path, "r") as file:
            for line in file:
                line = line.split("#")[0].strip()
                if fqdn in line:
                    parts = line.split()
                    if len(parts) >= 2 and fqdn in parts[1:]:
                        return parts[0]
    except FileNotFoundError:
        print("You must run deploy first")
        sys.exit(1)
    except Exception:
        print("You must run deploy first")
        sys.exit(1)
    print("You must run deploy first")
    sys.exit(1)

TERMINAL_SESSION_ID = os.environ.get("SSH_CONNECTION", "local_session").replace(" ", "_")
SESSION_FILE = f"/tmp/ovirt_session_{TERMINAL_SESSION_ID}.pkl"
session_data = None
delete_session_on_exit = False

def load_session():
    global session_data
    if session_data:
        return session_data
    if os.path.exists(SESSION_FILE) and os.path.getsize(SESSION_FILE) > 0:
        try:
            with open(SESSION_FILE, "rb") as file:
                session_data = pickle.load(file)
                return session_data
        except Exception:
            return None
    return None

def save_session(username, password, url):
    global session_data
    session_data = {"username": username, "password": password, "url": url}
    with open(SESSION_FILE, "wb") as file:
        pickle.dump(session_data, file)

def clear_session():
    global session_data
    if delete_session_on_exit:
        session_data = None
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)

def signal_handler(sig, frame):
    global delete_session_on_exit
    delete_session_on_exit = False
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGHUP, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# =============================================================================
# Section 3: Main Menu Function
# =============================================================================

def main_menu(stdscr, connection):
    """
    메인 메뉴를 표시하고 사용자의 키 입력에 따라 각 메뉴 항목의 기능을 호출.
    메뉴 항목은 아래 순서로 구성:
      1. Virtual Machines
      2. Data Centers
      3. Clusters
      4. Hosts
      5. Networks           ← 추후 구현 (placeholder)
      6. Storage Domains    ← 추후 구현 (placeholder)
      7. Storage Disks      ← 추후 구현 (placeholder)
      8. Users              ← 추후 구현 (placeholder)
      9. Certificate        ← 추후 구현 (placeholder)
      10. Events
    """
    curses.curs_set(0)
    curses.cbreak()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)
    stdscr.timeout(50)

    menu = [
        "Virtual Machines",
        "Data Centers",
        "Clusters",
        "Hosts",
        "Networks",
        "Storage Domains",
        "Storage Disks",
        "Users",
        "Certificate",
        "Events"
    ]
    current_row = 0

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 20 or width < 50:
            stdscr.addstr(0, 0, "Resize the terminal to at least 50x20.", curses.color_pair(2))
            stdscr.noutrefresh()
            curses.doupdate()
            continue

        stdscr.addstr(1, 1, "RutilVM Assistor", curses.A_BOLD)
        for idx, row in enumerate(menu):
            y, x = 4 + idx, 1
            if idx == current_row:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y, x, f"> {row} ")
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.attron(curses.color_pair(2))
                stdscr.addstr(y, x, f"  {row} ")
                stdscr.attroff(curses.color_pair(2))
        stdscr.addstr(height - 2, 1, "▲/▼=Navigate | ENTER=Select | Q=Quit", curses.color_pair(2))
        stdscr.noutrefresh()
        curses.doupdate()

        key = stdscr.getch()
        if key == curses.KEY_UP:
            current_row = (current_row - 1) % len(menu)
        elif key == curses.KEY_DOWN:
            current_row = (current_row + 1) % len(menu)
        elif key == ord('q'):
            break
        elif key == 10:  # Enter
            stdscr.erase()
            stdscr.noutrefresh()
            curses.doupdate()
            if menu[current_row] == "Virtual Machines":
                show_virtual_machines(stdscr, connection)
            elif menu[current_row] == "Data Centers":
                show_data_centers(stdscr, connection)
            elif menu[current_row] == "Clusters":
                show_clusters(stdscr, connection)
            elif menu[current_row] == "Hosts":
                show_hosts(stdscr, connection)
            elif menu[current_row] == "Networks":
                show_networks(stdscr, connection)
            elif menu[current_row] == "Storage Domains":
                show_storage_domains(stdscr, connection)
            elif menu[current_row] == "Storage Disks":
                show_storage_disks(stdscr, connection)
            elif menu[current_row] == "Users":
                show_users(stdscr, connection)
            elif menu[current_row] == "Certificate":
                show_certificates(stdscr, connection)
            elif menu[current_row] == "Events":
                show_events(stdscr, connection)

# =============================================================================
# Section 4: Virtual Machines Section
# =============================================================================

def show_virtual_machines(stdscr, connection):
    """
    Virtual Machines 목록을 표시하고, 선택된 VM에 대해 시작/중지/재시작, 마이그레이션 및 상세 정보를 제공.
    """
    # 터미널 화면의 현재 크기(행, 열)를 가져옴.
    height, width = stdscr.getmaxyx()
    
    # VM 목록 테이블의 헤더와 각 열의 너비를 정의.
    header = ["VM Name", "Status", "Host Name", "Uptime"]
    column_widths = [31, 31, 37, 18]
    
    # 테이블의 상단, 중간, 하단 선 생성 (Unicode box drawing 문자 사용)
    header_line = "┌" + "┬".join("─" * w for w in column_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in column_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in column_widths) + "┘"
    
    # oVirt API를 통한 VM, 호스트, 클러스터 데이터를 불러옴.
    try:
        vms_service = connection.system_service().vms_service()
        hosts_service = connection.system_service().hosts_service()
        clusters_service = connection.system_service().clusters_service()
        # 모든 호스트 정보를 리스트로 가져옴.
        hosts = hosts_service.list()
        # 호스트 id를 키로, 호스트 이름을 값으로 하는 딕셔너리 생성
        hosts_map = {host.id: host.name for host in hosts}
        # 모든 VM 정보를 리스트로 가져옴.
        vms = vms_service.list()
    except Exception as e:
        # 데이터 로딩에 실패하면 에러 메시지를 화면에 출력하고, 사용자의 입력을 기다린 후 함수를 종료.
        stdscr.addstr(7, 1, f"Failed to fetch VM data: {e}", curses.color_pair(4))
        stdscr.refresh()
        stdscr.getch()
        return

    # 한 페이지에 표시할 VM 행의 개수를 설정.
    rows_per_page = 20
    # 전체 VM 개수를 기준으로 총 페이지 수를 계산.
    total_pages = (len(vms) + rows_per_page - 1) // rows_per_page
    current_page = 0  # 현재 표시 중인 페이지 번호
    selected_vms = set()         # 사용자가 선택한 VM의 인덱스를 저장하는 집합
    pending_start_vms = set()    # 시작 명령 후 상태가 변경되는 중인 VM 인덱스를 저장하는 집합
    current_row = 0              # 현재 페이지 내에서 선택된(강조된) 행의 인덱스
    
    # VM과 호스트의 상태를 주기적으로 폴링하는 간격(초)
    vm_poll_interval = 1.0
    host_poll_interval = 1.0
    last_vm_poll = time.time()   # 마지막 VM 상태 폴링 시각
    last_host_poll = 0           # 마지막 호스트 상태 폴링 시각
    cached_hosts = hosts       # 호스트 정보를 캐싱 (업데이트 시 사용)
    cached_usage = {}          # 호스트 리소스 사용량 정보를 캐싱 (CPU, 메모리 등)
    
    # 키 입력 대기 시간을 50ms로 설정.
    stdscr.timeout(50)

    # 메인 이벤트 루프: 사용자의 입력에 따라 화면을 업데이트하고 동작을 수행.
    while True:
        now = time.time()
        # 주기적으로 VM 상태를 업데이트.
        if now - last_vm_poll >= vm_poll_interval:
            try:
                new_vms = vms_service.list()  # 최신 VM 목록을 가져옴.
                # pending_start_vms에 있는 각 VM에 대해 상태를 확인하고, 시작 중이 아니면 pending 상태에서 제거.
                for vm_index in list(pending_start_vms):
                    current_status = new_vms[vm_index].status.value if new_vms[vm_index].status else "N/A"
                    if current_status not in ["wait_for_launch", "powering_up"]:
                        pending_start_vms.remove(vm_index)
                vms = new_vms  # 전체 VM 목록을 최신 상태로 업데이트
            except Exception:
                # 에러 발생 시 무시하고 넘어감.
                pass
            last_vm_poll = now

        # 화면 전체를 지움.
        stdscr.erase()
        # 제목을 굵은 글씨로 표시.
        stdscr.addstr(1, 1, "Virtual Machines", curses.A_BOLD)
        
        # 현재 페이지에 해당하는 VM 목록의 시작과 끝 인덱스 계산
        start_idx = current_page * rows_per_page
        end_idx = min(start_idx + rows_per_page, len(vms))
        displayed_vm_count = end_idx - start_idx
        total_vm_count = len(vms)
        
        # 페이지 정보와 VM 개수를 표시.
        stdscr.addstr(3, 1, f"- VM LIST ({displayed_vm_count}/{total_vm_count})")
        stdscr.addstr(4, 1, header_line)  # 테이블 상단 선
        # 헤더 행(열 제목들)을 표시.
        stdscr.addstr(5, 1, "│" + "│".join(f"{header[i]:<{column_widths[i]}}" for i in range(len(header))) + "│")
        stdscr.addstr(6, 1, divider_line)  # 헤더와 데이터 사이의 구분선

        # 현재 페이지에 해당하는 각 VM에 대해 테이블 행을 출력.
        for idx, vm in enumerate(vms[start_idx:end_idx]):
            vm_index = start_idx + idx  # 전체 VM 목록에서의 인덱스
            # 선택되었는지 여부에 따라 체크박스 표시
            is_selected = "[x]" if vm_index in selected_vms else "[ ]"
            name = f"{is_selected} {vm.name}"  # 체크박스와 VM 이름을 결합하여 표시
            status = vm.status.value if vm.status else "N/A"
            # 만약 해당 VM이 pending_start_vms 집합에 있다면, 상태 문자열에 추가 설명을 붙임
            if vm_index in pending_start_vms:
                status += " (starting...)"
            # VM의 호스트 이름을 매핑에서 가져옴. (호스트 정보가 없으면 "N/A")
            host = hosts_map.get(vm.host.id, "N/A") if vm.host else "N/A"
            uptime = "N/A"
            # VM이 시작되었으면 현재 시간과 start_time의 차이로 업타임을 계산.
            if hasattr(vm, 'start_time') and vm.start_time:
                current_time = datetime.now(timezone.utc)
                uptime_seconds = (current_time - vm.start_time).total_seconds()
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                uptime = f"{days}d {hours}h {minutes}m"
            # 한 행에 출력할 데이터 리스트 생성
            row = [name, status, host, uptime]
            y = 7 + idx  # 데이터 행의 y좌표 (테이블 시작은 행 7부터)
            if idx == current_row:
                # 현재 선택된 행은 강조 색상(curses.color_pair(1))으로 출력
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y, 1, "│" + "│".join(f"{str(row[i]):<{column_widths[i]}}" for i in range(len(row))) + "│")
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(y, 1, "│" + "│".join(f"{str(row[i]):<{column_widths[i]}}" for i in range(len(row))) + "│")
                
        # 테이블 하단 선을 출력.
        stdscr.addstr(7 + (end_idx - start_idx), 1, footer_line)
        stdscr.addstr(7 + (end_idx - start_idx), 1, footer_line)  # (중복 출력된 것처럼 보이나, 기존 코드 그대로 유지)

        # ---------------------------
        # Hosts Resource Usage 섹션
        # ---------------------------
        # 호스트 자원 사용 정보를 표시하는 테이블의 헤더, 열 너비 및 선을 정의.
        host_header = ["Host Name", "CPU Usage", "Memory Usage", "Data Center", "Cluster"]
        host_column_widths = [31, 13, 17, 28, 27]
        host_header_line = "┌" + "┬".join("─" * w for w in host_column_widths) + "┐"
        host_divider_line = "├" + "┼".join("─" * w for w in host_column_widths) + "┤"
        host_footer_line = "└" + "┴".join("─" * w for w in host_column_widths) + "┘"
        
        # 주기적으로 호스트 리소스 사용량을 업데이트.
        if now - last_host_poll >= host_poll_interval:
            try:
                cached_hosts = hosts_service.list()
                usage = {}
                # 각 호스트에 대해 통계를 조회하여 CPU, 메모리 사용률, 클러스터 및 데이터 센터 정보를 가져옴.
                for host in cached_hosts:
                    try:
                        host_service = hosts_service.host_service(host.id)
                        statistics = host_service.statistics_service().list()
                        # CPU 사용률: "cpu.utilization" 항목을 우선 사용, 없으면 "cpu.load.avg" 항목 사용
                        cpu_usage = next((s.values[0].datum for s in statistics if 'cpu.utilization' in s.name.lower()), "N/A")
                        if cpu_usage == "N/A":
                            cpu_usage = next((s.values[0].datum for s in statistics if 'cpu.load.avg' in s.name.lower()), "N/A")
                        memory_used = next((s.values[0].datum for s in statistics if 'memory.used' in s.name.lower()), 0)
                        memory_total = next((s.values[0].datum for s in statistics if 'memory.total' in s.name.lower()), 0)
                        # 메모리 사용률 계산 (퍼센트)
                        memory_usage = (memory_used / memory_total) * 100 if memory_total > 0 else "N/A"
                        cluster_name = 'N/A'
                        data_center_name = 'N/A'
                        try:
                            # 해당 호스트의 클러스터 정보를 가져옴.
                            cluster = clusters_service.cluster_service(host.cluster.id).get()
                            cluster_name = cluster.name if cluster and hasattr(cluster, 'name') else 'N/A'
                            data_center_id = cluster.data_center.id if cluster and hasattr(cluster, 'data_center') else None
                            if data_center_id:
                                data_center = connection.system_service().data_centers_service().data_center_service(data_center_id).get()
                                data_center_name = data_center.name if data_center and hasattr(data_center, 'name') else 'N/A'
                        except Exception:
                            cluster_name = 'N/A'
                            data_center_name = 'N/A'
                        usage[host.name] = {
                            'cpu': round(cpu_usage, 2) if isinstance(cpu_usage, (float, int)) else "N/A",
                            'memory': round(memory_usage, 2) if isinstance(memory_usage, (float, int)) else "N/A",
                            'data_center': data_center_name if data_center_name else 'N/A',
                            'cluster': cluster_name if cluster_name else 'N/A'
                        }
                    except Exception:
                        usage[host.name] = {'cpu': "N/A", 'memory': "N/A", 'data_center': "N/A", 'cluster': "N/A"}
                cached_usage = usage
            except Exception:
                pass
            last_host_poll = now

        # 호스트 리소스 사용 테이블의 페이지 처리 (10행씩)
        x_margin = 1
        total_host_count = len(cached_hosts)
        host_rows_per_page = 10
        total_host_pages = (total_host_count + host_rows_per_page - 1) // host_rows_per_page
        host_page = min(current_row, total_host_pages - 1)
        start_idx_hosts = host_page * host_rows_per_page
        end_idx_hosts = min(start_idx_hosts + host_rows_per_page, total_host_count)
        displayed_host_count = max(0, end_idx_hosts - start_idx_hosts)
        
        base_line = 9 + (end_idx - start_idx)
        stdscr.addstr(base_line, x_margin, f"- HOST RESOURCE USAGE ({displayed_host_count}/{total_host_count})")
        
        # 테이블 상단 선 및 헤더 행 출력
        stdscr.addstr(base_line + 1, x_margin, "┌" + "─" * 31 + "┬" + "─" * 13 + "┬" + "─" * 17 + "┬" + "─" * 28 + "┬" + "─" * 27 + "┐")
        stdscr.addstr(base_line + 2, x_margin, f"│{'Host Name':<31}│{'CPU Usage':<13}│{'Memory Usage':<17}│{'Data Center':<28}│{'Cluster':<27}│")
        stdscr.addstr(base_line + 3, x_margin, "├" + "─" * 31 + "┼" + "─" * 13 + "┼" + "─" * 17 + "┼" + "─" * 28 + "┼" + "─" * 27 + "┤")
        # 각 호스트의 리소스 사용 정보를 출력.
        for idx, host in enumerate(cached_hosts[start_idx_hosts:end_idx_hosts]):
            host_name = host.name
            cpu = cached_usage.get(host_name, {}).get('cpu', "N/A")
            memory = cached_usage.get(host_name, {}).get('memory', "N/A")
            data_center = cached_usage.get(host_name, {}).get('data_center', "N/A")
            cluster = cached_usage.get(host_name, {}).get('cluster', "N/A")
            row_str = f"│{host_name:<31}│{str(cpu) + '%':<13}│{str(memory) + '%':<17}│{data_center:<28}│{cluster:<27}│"
            stdscr.addstr(base_line + 4 + idx, x_margin, row_str)
        # 테이블 하단 선 출력
        stdscr.addstr(base_line + 4 + (end_idx_hosts - start_idx_hosts), x_margin, "└" + "─" * 31 + "┴" + "─" * 13 + "┴" + "─" * 17 + "┴" + "─" * 28 + "┴" + "─" * 27 + "┘")
        
        # 하단 내비게이션 메시지 출력 (현재 페이지, 명령어 안내)
        stdscr.addstr(height - 2, 1,
                      f"Page {current_page + 1}/{total_pages} | N=Next page | P=Previous page | SPACE=Select | S=Start | D=Stop | R=Restart | M=Migrate | ESC=Go back | Q=Quit",
                      curses.color_pair(2))
        stdscr.refresh()
        
        # 사용자 키 입력 처리
        key = stdscr.getch()
        if key == ord('q'):
            exit(0)
        elif key == 27:
            break 
        elif key == curses.KEY_UP:
            # 위 방향키: 현재 페이지 내의 선택 행을 위로 이동
            if (end_idx - start_idx) > 0:
                current_row = (current_row - 1) % (end_idx - start_idx)
        elif key == curses.KEY_DOWN:
            # 아래 방향키: 현재 페이지 내의 선택 행을 아래로 이동
            if (end_idx - start_idx) > 0:
                current_row = (current_row + 1) % (end_idx - start_idx)
        elif key == ord('n') and current_page < total_pages - 1:
            # 'n' 키: 다음 페이지로 이동
            current_page += 1
            current_row = 0
        elif key == ord('p') and current_page > 0:
            # 'p' 키: 이전 페이지로 이동
            current_page -= 1
            current_row = 0
        elif key == ord(' '):
            # SPACE 키: 현재 선택된 행의 VM을 선택/해제
            vm_index = start_idx + current_row
            if vm_index in selected_vms:
                selected_vms.remove(vm_index)
            else:
                selected_vms.add(vm_index)
        elif key == ord('s'):
            # 's' 키: 선택한 VM에 대해 start 명령 실행
            for vm_index in selected_vms:
                if start_idx <= vm_index < end_idx:
                    vm_status = vms[vm_index].status.value.lower()
                    if vm_status == "up":
                        continue
                    elif vm_status == "suspended":
                        try:
                            vm_service = vms_service.vm_service(vms[vm_index].id)
                            vm_service.start()
                            time.sleep(1)
                        except Exception:
                            try:
                                vm_service.wake_up()
                            except Exception:
                                pass
                    else:
                        manage_vms([vms[vm_index]], "start", vms_service, stdscr)
                    pending_start_vms.add(vm_index)
            selected_vms.clear()
        elif key == ord('d'):
            # 'd' 키: 선택한 VM에 대해 종료(Stop/Shutdown) 명령 실행
            for vm_index in selected_vms:
                if start_idx <= vm_index < end_idx:
                    vm_status = vms[vm_index].status.value.lower()
                    if vm_status not in ["up", "powering_up", "suspended"]:
                        continue
                    confirm = confirm_shutdown_popup(stdscr, vms[vm_index].name)
                    if confirm:
                        vm_service = vms_service.vm_service(vms[vm_index].id)
                        if vm_status == "suspended":
                            try:
                                vm_service.shutdown(force=True)
                                time.sleep(1)
                            except Exception:
                                pass
                            try:
                                vm_service.stop(force=True)
                            except Exception as e:
                                show_error_popup(stdscr, "Stop Failed", f"Failed to stop VM '{vms[vm_index].name}': {str(e)}")
                        else:
                            manage_vms([vms[vm_index]], "stop", vms_service, stdscr)
                        try:
                            vms = vms_service.list()
                        except Exception:
                            pass
            selected_vms.clear()
        elif key == ord('r'):
            # 'r' 키: 선택한 VM에 대해 재시작 명령 실행
            for vm_index in selected_vms:
                if start_idx <= vm_index < end_idx:
                    manage_vms([vms[vm_index]], "restart", vms_service, stdscr)
            try:
                vms = vms_service.list()
            except Exception:
                pass
            selected_vms.clear()
        elif key == ord('m'):
            # 'm' 키: 선택한 VM에 대해 마이그레이션을 위한 대상 호스트 선택 팝업 표시
            for vm_index in selected_vms:
                if start_idx <= vm_index < end_idx:
                    migrate_vm_popup(vms[vm_index], cached_hosts,
                                     connection.system_service().clusters_service(), stdscr, vms_service)
            try:
                vms = vms_service.list()
            except Exception:
                pass
            selected_vms.clear()
        elif key == 10:
            # ENTER 키: 현재 선택한 VM의 상세 정보 화면을 호출
            if (end_idx - start_idx) > 0:
                vm = vms[start_idx + current_row]
                show_vm_details(stdscr, connection, vm)
                selected_vms.clear()
        
def manage_vms(selected_vms, action, vms_service, stdscr):
    """선택된 VM들에 대해 start, stop, restart 동작을 수행"""
    for vm in selected_vms:
        vm_service = vms_service.vm_service(vm.id)
        try:
            if action == "start":
                if vm.status.value != "down":
                    continue
                vm_service.start()
            elif action == "stop":
                if vm.status.value not in ["up", "powering_up"]:
                    continue
                vm_service.stop()
            elif action == "restart":
                if vm.status.value != "up":
                    continue
                vm_service.reboot()
        except Exception as e:
            error_message = f"Failed to {action} VM '{vm.name}':\n{str(e)}"
            show_error_popup(stdscr, f"Failed to {action} VM", error_message)
        stdscr.refresh()

def migrate_vm_popup(vm, hosts, clusters_service, stdscr, vms_service):
    """VM 마이그레이션을 위한 대상 호스트 선택 팝업"""
    height, width = stdscr.getmaxyx()
    MIN_HEIGHT, MIN_WIDTH = 15, 70
    if height < MIN_HEIGHT or width < MIN_WIDTH:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Terminal too small ({width}x{height}). Resize and retry.")
        stdscr.refresh()
        stdscr.getch()
        return
    popup_height = min(12, height - 2)
    popup_width = min(60, width - 4)
    popup_y = max(0, (height - popup_height) // 2)
    popup_x = max(0, (width - popup_width) // 2)
    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.keypad(True)
    def safe_addstr(window, y, x, text, color=None):
        """팝업 창에 안전하게 문자열을 출력하는 함수"""
        if 0 <= y < popup_height and 0 <= x < popup_width - 1:
            text = text[:popup_width - x - 1]
            try:
                if color:
                    window.attron(color)
                    window.addstr(y, x, text)
                    window.attroff(color)
                else:
                    window.addstr(y, x, text)
            except curses.error:
                pass
    try:
        while True:
            popup.clear()
            popup.border()
            title = f"Select target host for VM '{vm.name}':"
            safe_addstr(popup, 1, 2, title)
            if vm.status.value == "down":
                safe_addstr(popup, 3, 2, "VM is in 'Down' state.")
                safe_addstr(popup, 5, 2, "Press any key to close.")
                popup.refresh()
                popup.getch()
                return
            cluster_id = vm.cluster.id if vm.cluster else None
            if not cluster_id:
                safe_addstr(popup, 3, 2, "No valid cluster found.")
                safe_addstr(popup, 5, 2, "Press any key to close.")
                popup.refresh()
                popup.getch()
                return
            target_hosts = [host for host in hosts if host.cluster.id == cluster_id and host.id != (vm.host.id if vm.host else None)]
            if not target_hosts:
                safe_addstr(popup, 3, 2, "No available hosts in cluster.")
                safe_addstr(popup, 5, 2, "Press any key to close.")
                popup.refresh()
                popup.getch()
                return
            current_row = 0
            max_host_display = popup_height - 5
            for idx, host in enumerate(target_hosts[:max_host_display]):
                row_y = 3 + idx
                host_name = host.name[:popup_width - 4]
                if idx == current_row:
                    safe_addstr(popup, row_y, 2, host_name, curses.color_pair(1))
                else:
                    safe_addstr(popup, row_y, 2, host_name)
            footer = "▲/▼: Navigate | ENTER: Select | ESC: Cancel"
            safe_addstr(popup, popup_height - 2, 2, footer)
            popup.refresh()
            key = popup.getch()
            if key == curses.KEY_UP and current_row > 0:
                current_row -= 1
            elif key == curses.KEY_DOWN and current_row < len(target_hosts) - 1:
                current_row += 1
            elif key == 27:
                return
            elif key == 10:
                target_host = target_hosts[current_row]
                try:
                    vm_service = vms_service.vm_service(vm.id)
                    vm_service.migrate(host=target_host)
                    popup.clear()
                    popup.border()
                    safe_addstr(popup, 3, 2, f"VM '{vm.name}' migrated to '{target_host.name}'.")
                    safe_addstr(popup, 5, 2, "Press any key to close.")
                    popup.refresh()
                    popup.getch()
                    return
                except Exception as e:
                    popup.clear()
                    popup.border()
                    safe_addstr(popup, 3, 2, f"Migration failed: {str(e)}")
                    safe_addstr(popup, 5, 2, "Press any key to close.")
                    popup.refresh()
                    popup.getch()
                    return
    except curses.error as e:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Error rendering popup. Terminal: {width}x{height}")
        stdscr.addstr(1, 0, f"Exception: {str(e)}")
        stdscr.refresh()
        stdscr.getch()

def confirm_shutdown_popup(stdscr, vm_name):
    """
    VM 종료(Shutdown) 전 확인 팝업을 표시하고,
    사용자가 "Yes"를 선택하면 True, "No" 또는 ESC 시 False 반환.
    """
    height, width = stdscr.getmaxyx()
    popup_height = min(12, height - 2)
    popup_width = min(60, width - 4)
    popup_y = max(0, (height - popup_height) // 2)
    popup_x = max(0, (width - popup_width) // 2)
    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.keypad(True)
    options = ["Yes", "No"]
    current_option = 0
    while True:
        popup.erase()
        popup.border()
        title = "Are you sure you want to shutdown?"
        vm_text = f"{vm_name}"
        popup.addstr(2, (popup_width - len(title)) // 2, title, curses.A_BOLD)
        popup.addstr(5, (popup_width - len(vm_text)) // 2, vm_text)
        yes_x = (popup_width // 2) - 8
        no_x = (popup_width // 2) + 4
        button_y = 8
        popup.addstr(button_y, yes_x - 1, "[ Yes ]" if current_option == 0 else "  Yes  ",
                     curses.A_BOLD if current_option == 0 else curses.A_NORMAL)
        popup.addstr(button_y, no_x - 1, "[ No ]" if current_option == 1 else "  No  ",
                     curses.A_BOLD if current_option == 1 else curses.A_NORMAL)
        instructions = "◀/▶: Move | ENTER: Select"
        popup.addstr(popup_height - 2, (popup_width - len(instructions)) // 2, instructions, curses.A_DIM)
        popup.refresh()
        key = popup.getch()
        if key in [curses.KEY_LEFT, curses.KEY_RIGHT]:
            current_option = 1 - current_option
        elif key == 10:
            return options[current_option] == "Yes"
        elif key == 27:
            return False

def show_vm_details(stdscr, connection, vm):
    """
    선택한 VM의 상세 정보를 표시(상태, 네트워크, 디스크, 이벤트 등).
    """
    stdscr.clear()
    # -- VM Details 테이블 --
    stdscr.addstr(1, 1, f"- VM Details for {vm.name}")
    vm_details_header = ["Status", "Uptime", "Operating System", "Chipset/F/W Type",
                           "Defined Memory", "Memory Guaranteed", "Guest CPU Count", "HA"]
    vm_details_widths = [7, 14, 20, 18, 14, 17, 15, 9]
    header_line = "┌" + "┬".join("─" * w for w in vm_details_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in vm_details_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in vm_details_widths) + "┘"
    stdscr.addstr(2, 1, header_line)
    stdscr.addstr(3, 1, "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" 
                                      for h, w in zip(vm_details_header, vm_details_widths)) + "│")
    stdscr.addstr(4, 1, divider_line)
    vm_status = vm.status if vm.status else "N/A"
    if vm.start_time and vm.status == VmStatus.UP:
        uptime_seconds = int(time.time() - vm.start_time.timestamp())
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        uptime_str = f"{days}D {hours}h {minutes}m"
    else:
        uptime_str = "N/A"
    os_type = vm.os.type if vm.os and vm.os.type else "N/A"
    chipset = vm.custom_emulated_machine if vm.custom_emulated_machine else (vm.bios.type if vm.bios and vm.bios.type else "N/A")
    defined_memory = f"{(vm.memory / (1024**3)):.2f} GB" if vm.memory else "N/A"
    memory_guaranteed = f"{(vm.memory_policy.guaranteed / (1024**3)):.2f} GB" if vm.memory_policy and vm.memory_policy.guaranteed else "N/A"
    if vm.cpu and vm.cpu.topology:
        guest_cpu_count = vm.cpu.topology.sockets * vm.cpu.topology.cores
    else:
        guest_cpu_count = "N/A"
    ha_status = "Yes" if vm.high_availability and vm.high_availability.enabled else "No"
    vm_details_row = [str(vm_status), uptime_str, os_type, chipset, defined_memory, memory_guaranteed, str(guest_cpu_count), ha_status]
    row_str = "│" + "│".join(f"{truncate_with_ellipsis(val, w):<{w}}" 
                              for val, w in zip(vm_details_row, vm_details_widths)) + "│"
    stdscr.addstr(5, 1, row_str)
    stdscr.addstr(6, 1, footer_line)
    
    # -- Network Details 테이블 --
    row = 8
    stdscr.addstr(row, 1, f"- Network Details for {vm.name}")
    row += 1
    nic_header = ["NIC Name", "Network Name", "IPv4", "MAC",
                  "Link State", "Interface", "Speed (Mbps)", "Port Mirroring"]
    nic_column_widths = [15, 15, 16, 18, 11, 10, 13, 16]
    nic_header_line = "┌" + "┬".join("─" * w for w in nic_column_widths) + "┐"
    nic_divider_line = "├" + "┼".join("─" * w for w in nic_column_widths) + "┤"
    nic_footer_line = "└" + "┴".join("─" * w for w in nic_column_widths) + "┘"
    stdscr.addstr(row, 1, nic_header_line)
    row += 1
    stdscr.addstr(row, 1, "│" + "│".join(f"{col:<{w}}" for col, w in zip(nic_header, nic_column_widths)) + "│")
    row += 1
    stdscr.addstr(row, 1, nic_divider_line)
    row += 1
    try:
        vm_service = connection.system_service().vms_service().vm_service(vm.id)
        vm_data = vm_service.get()  # 최신 VM 상태
        nics_service = vm_service.nics_service()
        nics = nics_service.list()
        mac_ip_mapping = {}
        if vm_data.status == VmStatus.UP:
            try:
                reported_devices = vm_service.reported_devices_service().list()
                if reported_devices:
                    for device in reported_devices:
                        if device.ips:
                            for ip in device.ips:
                                if ip.version == IpVersion.V4:
                                    mac_ip_mapping[device.mac.address] = ip.address
            except Exception:
                pass
        if not nics:
            placeholder = ["-"] * len(nic_header)
            stdscr.addstr(row, 1, "│" + "│".join(f"{str(col):<{w}}" for col, w in zip(placeholder, nic_column_widths)) + "│")
            row += 1
        else:
            for nic in nics:
                network_name = "-"
                try:
                    if nic.vnic_profile and nic.vnic_profile.id:
                        vnic_profile_service = connection.system_service().vnic_profiles_service()
                        vnic_profile = vnic_profile_service.profile_service(nic.vnic_profile.id).get()
                        if vnic_profile.network:
                            networks_service = connection.system_service().networks_service()
                            network = networks_service.network_service(vnic_profile.network.id).get()
                            network_name = network.name if network.name else "-"
                except Exception:
                    pass
                ipv4 = mac_ip_mapping.get(nic.mac.address, "-")
                nic_row = [
                    nic.name or '-',
                    network_name,
                    ipv4,
                    nic.mac.address if nic.mac else '-',
                    'Yes' if nic.linked else 'No',
                    nic.interface or '-',
                    '-',
                    'Disabled'
                ]
                stdscr.addstr(row, 1, "│" + "│".join(f"{str(col):<{w}}" for col, w in zip(nic_row, nic_column_widths)) + "│")
                row += 1
    except Exception as e:
        stdscr.addstr(row, 1, f"│ Error: {truncate_with_ellipsis(str(e), 50)} │")
        row += 1
    stdscr.addstr(row, 1, nic_footer_line)
    row += 2
    # -- Disk Details 테이블 --
    stdscr.addstr(row, 1, f"- Disk Details for {vm.name}")
    row += 1
    disk_header = ["Alias", "OS", "Size (GB)", "Attached To", "Interface",
                   "Logical Name", "Status", "Type", "Policy", "Storage Domain"]
    disk_column_widths = [19, 5, 11, 14, 12, 12, 6, 7, 9, 17]
    disk_header_line = "┌" + "┬".join("─" * w for w in disk_column_widths) + "┐"
    disk_divider_line = "├" + "┼".join("─" * w for w in disk_column_widths) + "┤"
    disk_footer_line = "└" + "┴".join("─" * w for w in disk_column_widths) + "┘"
    stdscr.addstr(row, 1, disk_header_line)
    row += 1
    stdscr.addstr(row, 1, "│" + "│".join(f"{col:<{w}}" for col, w in zip(disk_header, disk_column_widths)) + "│")
    row += 1
    stdscr.addstr(row, 1, disk_divider_line)
    row += 1
    try:
        vm_service = connection.system_service().vms_service().vm_service(vm.id)
        disk_attachments_service = vm_service.disk_attachments_service()
        disk_attachments = disk_attachments_service.list()
        boot_disk_id = None
        for attachment in disk_attachments:
            if attachment.bootable:
                boot_disk_id = attachment.disk.id
                break
        if not disk_attachments:
            disk_row = ['-'] * len(disk_header)
            stdscr.addstr(row, 1, "│" + "│".join(f"{str(col):<{w}}" for col, w in zip(disk_row, disk_column_widths)) + "│")
            row += 1
        else:
            for attachment in disk_attachments:
                try:
                    logical_name = attachment.logical_name if attachment.logical_name else "(None)"
                    disk = connection.follow_link(attachment.disk)
                    os_field = "Yes" if disk.id == boot_disk_id else "No"
                    storage_domain = "-"
                    if disk.storage_domains:
                        storage_domains = [connection.follow_link(sd).name for sd in disk.storage_domains]
                        storage_domain = ", ".join(storage_domains)
                    disk_row = [
                        truncate_with_ellipsis(disk.alias or '-', disk_column_widths[0]),
                        truncate_with_ellipsis(os_field, disk_column_widths[1]),
                        truncate_with_ellipsis(f"{disk.provisioned_size / (1024**3):.2f}", disk_column_widths[2]),
                        truncate_with_ellipsis(vm.name or '-', disk_column_widths[3]),
                        truncate_with_ellipsis(attachment.interface or '-', disk_column_widths[4]),
                        truncate_with_ellipsis(logical_name, disk_column_widths[5]),
                        truncate_with_ellipsis(disk.status if disk.status else '-', disk_column_widths[6]),
                        truncate_with_ellipsis(getattr(disk, 'storage_type', 'image'), disk_column_widths[7]),
                        truncate_with_ellipsis("Thin" if disk.sparse else "Preallocated", disk_column_widths[8]),
                        truncate_with_ellipsis(storage_domain, disk_column_widths[9]),
                    ]
                    stdscr.addstr(row, 1, "│" + "│".join(f"{str(col):<{disk_column_widths[i]}}" for i, col in enumerate(disk_row)) + "│")
                    row += 1
                except Exception:
                    continue
    except Exception as e:
        stdscr.addstr(row, 1, f"│ Error: {truncate_with_ellipsis(str(e), 50)} │")
        row += 1
    stdscr.addstr(row, 1, disk_footer_line)
    row += 2
    row = show_vm_events(stdscr, connection, vm, row)
    return

def show_vm_events(stdscr, connection, vm, row):
    """
    선택한 VM에 대한 이벤트를 페이지 단위로 표시하는 함수.
    """
    height, width = stdscr.getmaxyx()
    min_width = 120
    min_height = row + 14
    if height < min_height or width < min_width:
        stdscr.addstr(row, 1, f"Terminal too small ({width}x{height}). Resize to at least {min_width}x{min_height}.")
        stdscr.refresh()
        stdscr.getch()
        return row
    event_headers = ["Time", "Severity", "Description"]
    event_widths = [19, 9, 91]
    header_line = "┌" + "┬".join("─" * w for w in event_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in event_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in event_widths) + "┘"
    try:
        events_service = connection.system_service().events_service()
        events = events_service.list(search=f"vm.name={vm.name}", max=50)
        total_events = len(events)
        page_size = 8
        total_pages = max(1, (total_events + page_size - 1) // page_size)
        current_page = 0
        base_row = row
        while True:
            header_text = f"- Events for {vm.name} (Page {current_page + 1}/{total_pages})"
            stdscr.addstr(base_row, 1, header_text)
            table_start_row = base_row + 1
            for i in range(table_start_row, height - 3):
                stdscr.move(i, 1)
                stdscr.clrtoeol()
            stdscr.addstr(table_start_row, 1, header_line)
            stdscr.addstr(table_start_row + 1, 1, "│" + "│".join(
                f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(event_headers, event_widths)
            ) + "│")
            stdscr.addstr(table_start_row + 2, 1, divider_line)
            start_idx = current_page * page_size
            end_idx = min(start_idx + page_size, total_events)
            data_row = table_start_row + 3
            for event in events[start_idx:end_idx]:
                time_str = event.time.strftime("%Y-%m-%d %H:%M:%S") if event.time else "-"
                severity = event.severity.name.lower() if hasattr(event.severity, 'name') else "-"
                description = truncate_with_ellipsis(event.description, event_widths[2]) if event.description else "-"
                row_str = "│" + "│".join(
                    f"{truncate_with_ellipsis(val, w):<{w}}" for val, w in zip([time_str, severity, description], event_widths)
                ) + "│"
                stdscr.addstr(data_row, 1, row_str)
                data_row += 1
            stdscr.addstr(data_row, 1, footer_line)
            data_row += 2
            stdscr.addstr(data_row, 1, "N=Next | P=Prev", curses.A_DIM)
            stdscr.addstr(height - 2, 1, "Page {}/{} | ESC=Go back | Q=Quit".format(current_page+1, total_pages), curses.A_DIM)
            stdscr.refresh()
            key = stdscr.getch()
            if key == ord('n') and current_page < total_pages - 1:
                current_page += 1
            elif key == ord('p') and current_page > 0:
                current_page -= 1
            elif key == 27:  # ESC 키
                return data_row
            elif key == ord('q'):
                exit(0)
    except curses.error:
        stdscr.addstr(base_row, 1, "Screen too small. Please resize and try again.")
        stdscr.refresh()
        stdscr.getch()
    except Exception as e:
        stdscr.addstr(base_row, 1, f"│ Error: {truncate_with_ellipsis(str(e), 50)} │")
        stdscr.refresh()
        stdscr.getch()
    return base_row

def show_error_popup(stdscr, title, message):
    """
    에러 메시지를 팝업 창에 표시하는 함수.
    """
    height, width = stdscr.getmaxyx()
    popup_height = min(10, height - 4)
    popup_width = min(70, width - 4)
    popup_y = (height - popup_height) // 2
    popup_x = (width - popup_width) // 2
    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.keypad(True)
    popup.clear()
    def safe_addstr(window, y, x, text, color=None):
        """팝업 창에 안전하게 문자열을 추가하는 함수"""
        if 0 <= y < popup_height and 0 <= x < popup_width - 1:
            text = text[:popup_width - x - 1]
            try:
                if color:
                    window.attron(color)
                    window.addstr(y, x, text)
                    window.attroff(color)
                else:
                    window.addstr(y, x, text)
            except curses.error:
                pass
    popup.border()
    title_text = f" {title} "
    safe_addstr(popup, 1, (popup_width - len(title_text)) // 2, title_text, curses.A_BOLD)
    wrapped_lines = []
    for line in message.split('\n'):
        wrapped_lines.extend(textwrap.wrap(line, popup_width - 4))
    for i, line in enumerate(wrapped_lines[:popup_height - 4]):
        safe_addstr(popup, 3 + i, 2, line)
    footer_text = "Press any key to close."
    safe_addstr(popup, popup_height - 2, (popup_width - len(footer_text)) // 2, footer_text)
    popup.refresh()
    popup.getch()

# =============================================================================
# Section 5: Data Centers Section
# =============================================================================

def get_data_center_info(connection, data_center):
    """
    데이터 센터와 관련된 클러스터와 호스트 개수를 포함한 정보를 반환.
    """
    clusters_service = connection.system_service().clusters_service()
    hosts_service = connection.system_service().hosts_service()
    clusters = [c for c in clusters_service.list() if c.data_center and c.data_center.id == data_center.id]
    hosts = [h for h in hosts_service.list() if h.cluster and h.cluster.id in [c.id for c in clusters]]
    return {
        "name": ensure_non_empty(data_center.name),
        "comment": adjust_column_width(ensure_non_empty(data_center.comment), 21),
        "status": ensure_non_empty(data_center.status.name if data_center.status else "-"),
        "hosts": ensure_non_empty(str(len(hosts))),
        "clusters": ensure_non_empty(str(len(clusters))),
        "description": adjust_column_width(ensure_non_empty(data_center.description), 23)
    }

def show_related_data(stdscr, connection, data_center, start_y):
    """
    선택한 데이터 센터와 관련된 Storage Domains, Logical Networks, Clusters 정보를 표시.
    """
    data_center_service = connection.system_service().data_centers_service().data_center_service(data_center.id)
    storage_domains_service = data_center_service.storage_domains_service()
    clusters_service = connection.system_service().clusters_service()
    networks_service = connection.system_service().networks_service()

    stdscr.addstr(start_y, 1, f"- Storage Domains For {data_center.name}")
    storage_header = ["Name", "Status", "Free Space (GB)", "Used Space (GB)", "Total Space (GB)", "Description"]
    storage_col_widths = [28, 13, 17, 17, 17, 22]
    storage_domains = storage_domains_service.list()
    draw_table(stdscr, start_y + 1, storage_header, storage_col_widths, storage_domains, lambda sd: [
        sd.name or "N/A",
        str(sd.status) if sd.status else "N/A",
        f"{(sd.available / (1024**3)):.1f}" if hasattr(sd, 'available') and sd.available is not None else "0.0",
        f"{(sd.used / (1024**3)):.1f}" if hasattr(sd, 'used') and sd.used is not None else "0.0",
        f"{(sd.total / (1024**3)):.1f}" if hasattr(sd, 'total') and sd.total is not None else f"{((sd.available or 0) + (sd.used or 0)) / (1024**3):.1f}",
        sd.comment or "N/A"
    ])

    stdscr.addstr(start_y + 6 + max(len(storage_domains), 1), 1, f"- Logical Networks For {data_center.name}")
    network_header = ["Name", "Description"]
    network_col_widths = [28, 90]
    networks = networks_service.list(search=f"datacenter={data_center.name}")
    draw_table(stdscr, start_y + 7 + max(len(storage_domains), 1), network_header, network_col_widths, networks, lambda net: [
        net.name or "N/A",
        net.comment or "N/A"
    ])

    stdscr.addstr(start_y + 12 + max(len(storage_domains), 1) + max(len(networks), 1), 1, f"- Cluster For {data_center.name}")
    cluster_header = ["Name", "Compat Version", "Description"]
    cluster_col_widths = [28, 32, 57]
    clusters = clusters_service.list(search=f"datacenter={data_center.name}")
    draw_table(stdscr, start_y + 13 + max(len(storage_domains), 1) + max(len(networks), 1), cluster_header, cluster_col_widths, clusters, lambda cl: [
        cl.name or "N/A",
        f"{cl.version.major}.{cl.version.minor}" if cl.version and hasattr(cl.version, 'major') and hasattr(cl.version, 'minor') else "N/A",
        cl.comment or "N/A"
    ])

def show_events_data_center(stdscr, connection, data_center):
    """
    선택한 데이터 센터와 관련된 이벤트를 페이지 단위로 표시.
    """
    try:
        events_service = connection.system_service().events_service()
        all_events = events_service.list()
        events = [event for event in all_events if event.data_center and event.data_center.id == data_center.id]
    except Exception as e:
        stdscr.addstr(2, 1, f"Failed to fetch Events: {e}")
        stdscr.refresh()
        stdscr.getch()
        return
    current_page = 0
    rows_per_page = 40
    total_pages = (len(events) + rows_per_page - 1) // rows_per_page
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        stdscr.addstr(1, 1, f"- Events for {data_center.name} (Page {current_page + 1}/{max(total_pages, 1)})")
        header = ["Time", "Severity", "Description"]
        col_widths = [19, 9, 91]
        header_line = "┌" + "┬".join("─" * w for w in col_widths) + "┐"
        divider_line = "├" + "┼".join("─" * w for w in col_widths) + "┤"
        footer_line = "└" + "┴".join("─" * w for w in col_widths) + "┘"
        stdscr.addstr(2, 1, header_line)
        stdscr.addstr(3, 1, "│" + "│".join(get_display_width(h, w) for h, w in zip(header, col_widths)) + "│")
        stdscr.addstr(4, 1, divider_line)
        start_idx = current_page * rows_per_page
        end_idx = min(start_idx + rows_per_page, len(events))
        for idx, event in enumerate(events[start_idx:end_idx]):
            row_y = 5 + idx
            event_time = event.time.strftime('%Y-%m-%d %H:%M:%S') if event.time else "-"
            severity = getattr(event.severity, 'name', "-")
            description = event.description if event.description else "-"
            row_data = [event_time, severity, description]
            row_text = "│" + "│".join(get_display_width(d, w) for d, w in zip(row_data, col_widths)) + "│"
            stdscr.addstr(row_y, 1, row_text)
        stdscr.addstr(5 + len(events[start_idx:end_idx]), 1, footer_line)
        stdscr.addstr(height - 2, 1, "N=Next | P=Prev | ESC=Go Back | Q=Quit", curses.color_pair(2))
        stdscr.refresh()
        key = stdscr.getch()
        if key == ord('n') and current_page < total_pages - 1:
            current_page += 1
        elif key == ord('p') and current_page > 0:
            current_page -= 1
        elif key == ord('q'):
            exit(0)
        elif key == 27:
            break

def show_data_centers(stdscr, connection):
    """
    Data Centers 목록을 표시하고, 선택한 데이터 센터에 대해 관련 정보(스토리지, 네트워크, 클러스터 등)를 보여줌.
    """
    try:
        dcs_service = connection.system_service().data_centers_service()
        dcs = dcs_service.list()
        clusters_service = connection.system_service().clusters_service()
        clusters = clusters_service.list()
        hosts_service = connection.system_service().hosts_service()
        hosts = hosts_service.list()
    except Exception as e:
        stdscr.addstr(2, 1, f"Failed to fetch Data Centers: {e}")
        stdscr.refresh()
        stdscr.getch()
        return

    dc_info_cache = {}
    for dc in dcs:
        dc_clusters = [c for c in clusters if c.data_center and c.data_center.id == dc.id]
        dc_hosts = [h for h in hosts if h.cluster and h.cluster.id in [c.id for c in dc_clusters]]
        dc_info_cache[dc.id] = {
            "name": ensure_non_empty(dc.name),
            "comment": adjust_column_width(ensure_non_empty(dc.comment), 21),
            "status": ensure_non_empty(dc.status.name if dc.status else "-"),
            "hosts": ensure_non_empty(str(len(dc_hosts))),
            "clusters": ensure_non_empty(str(len(dc_clusters))),
            "description": adjust_column_width(ensure_non_empty(dc.description), 23)
        }

    current_row = 0
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    stdscr.timeout(1)
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 40 or width < 120:
            stdscr.addstr(0, 0, "Resize the terminal to at least 120x40.")
            stdscr.refresh()
            continue
        stdscr.addstr(1, 1, "Data Centers", curses.A_BOLD)
        stdscr.addstr(3, 1, "- Data Center List")
        header = ["Data Center Name", "Comment", "Status", "Hosts", "Clusters", "Description"]
        col_widths = [28, 21, 16, 13, 13, 23]
        draw_table(stdscr, 4, header, col_widths, dcs,
                   lambda dc: list(dc_info_cache[dc.id].values()),
                   current_row)
        if dcs:
            selected_dc = dcs[current_row]
            show_related_data(stdscr, connection, selected_dc, 9 + len(dcs))
        stdscr.addstr(height - 2, 1,
                      "▲/▼=Navigate | Enter=View Events | ESC=Go back | Q=Quit",
                      curses.color_pair(2))
        stdscr.refresh()
        key = stdscr.getch()
        if key == curses.KEY_UP:
            current_row = (current_row - 1) % len(dcs)
        elif key == curses.KEY_DOWN:
            current_row = (current_row + 1) % len(dcs)
        elif key == 10:
            show_events_data_center(stdscr, connection, dcs[current_row])
        elif key == 27:
            break
        elif key == ord('q'):
            exit(0)

# =============================================================================
# Section 6: Clusters Section
# =============================================================================

def show_clusters(stdscr, connection):
    """
    Clusters 목록과 함께, 선택한 클러스터에 속한 Logical Networks, Hosts, Virtual Machines 목록을 표시.
    """
    curses.curs_set(0)
    stdscr.timeout(100)  
    try:
        clusters_service = connection.system_service().clusters_service()
        clusters = clusters_service.list()
        hosts_service = connection.system_service().hosts_service()
        hosts = hosts_service.list()
        vms_service = connection.system_service().vms_service()
        all_vms = vms_service.list()
        networks_service = connection.system_service().networks_service()
    except Exception as e:
        stdscr.addstr(2, 1, f"Failed to fetch clusters: {e}")
        stdscr.refresh()
        stdscr.getch()
        return
        
    # Build clusters_info (Cluster List)
    clusters_info = []
    for cluster in clusters:
        cluster_name = cluster.name if cluster.name else "N/A"

        # Data Center 정보
        data_center = "-"
        try:
            if cluster.data_center:
                data_center_obj = connection.follow_link(cluster.data_center)
                data_center = data_center_obj.name if data_center_obj and hasattr(data_center_obj, "name") else "N/A"
        except Exception:
            data_center = "N/A"

        # CPU Type 정보
        cpu_type = "-"
        try:
            if cluster.cpu and hasattr(cluster.cpu, 'type'):
                cpu_type = cluster.cpu.type
            else:
                cpu_type = "N/A"
        except Exception:
            cpu_type = "N/A"

        hosts_count = sum(1 for h in hosts if h.cluster and h.cluster.id == cluster.id)
        vm_count = sum(1 for vm in all_vms if vm.cluster and vm.cluster.id == cluster.id)
        clusters_info.append((cluster, [cluster_name, data_center, cpu_type, str(hosts_count), str(vm_count)]))
    
    current_cluster_index = 0
    vm_page = 0
    rows_per_vm_page = 7
    
    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 40 or width < 120:
            stdscr.addstr(0, 0, "Resize the terminal to at least 120x40.", curses.A_BOLD)
            stdscr.refresh()
            continue
              
        stdscr.addstr(1, 1, "Cluster", curses.A_BOLD)
        stdscr.addstr(3, 1, "- Cluster List")
        cluster_headers = ["Cluster Name", "Data Center", "CPU Type", "Hosts Count", "VM Count"]
        cluster_col_widths = [28, 26, 39, 11, 11]
        def cluster_row_func(item):
            return item[1]
        draw_table(stdscr, 4, cluster_headers, cluster_col_widths, clusters_info, cluster_row_func, current_cluster_index)
        cluster_table_bottom = 4 + 3 + max(len(clusters_info), 1)
        stdscr.addstr(cluster_table_bottom + 1, 1, "")  # 공백 한 줄

        if clusters_info:
            selected_cluster = clusters_info[current_cluster_index][0]
        else:
            selected_cluster = None 

        # Logical Networks 테이블
        detail_start_y = cluster_table_bottom + 2
        stdscr.addstr(detail_start_y, 1, "- Logical Networks")
        ln_headers = ["Name", "Status", "Description"]
        ln_col_widths = [28, 26, 63]
        
        def get_networks_by_cluster(cluster_id, url, username, password):
            """
            특정 클러스터의 네트워크 정보를 가져오는 함수 (REST API 요청)
            """
            full_url = f"{url}/clusters/{cluster_id}/networks"
            auth = HTTPBasicAuth(username, password)
            headers = {"Accept": "application/xml"}
        
            try:
                response = requests.get(full_url, auth=auth, headers=headers, verify=False)
                if response.status_code == 200:
                    root = ET.fromstring(response.text)
                    networks = []
                    for network in root.findall('network'):
                        networks.append({
                            'name': network.find('name').text if network.find('name') is not None else "-",
                            'status': network.find('status').text if network.find('status') is not None else "-",
                            'description': network.find('description').text if network.find('description') is not None else "-"
                        })
                    return networks
                else:
                    print(f"Failed to fetch networks for cluster {cluster_id}: {response.status_code}")
                    return []
            except Exception as e:
                print(f"Error fetching network data: {str(e)}")
                return []
        
        def ln_row_func(net):
            name = net["name"] if "name" in net and net["name"] else "-"
            status = net["status"] if "status" in net and net["status"] else "-"
            description = net["description"] if "description" in net and net["description"] else "-"
            return [name, status, description]
        
        # 여기서 connection.url와 세션 정보를 이용하여 REST API 호출
        logical_networks = []
        if selected_cluster:
            username_from_session = session_data["username"] if session_data and "username" in session_data else ""
            password_from_session = session_data["password"] if session_data and "password" in session_data else ""
            logical_networks = get_networks_by_cluster(selected_cluster.id, connection.url, username_from_session, password_from_session)
        draw_table(stdscr, detail_start_y + 1, ln_headers, ln_col_widths, logical_networks, ln_row_func, -1)
        ln_table_height = 3 + max(len(logical_networks), 1)
        stdscr.addstr(detail_start_y + 1 + ln_table_height + 1, 1, "")
        # Hosts 테이블
        hosts_start_y = detail_start_y + 1 + ln_table_height + 2
        stdscr.addstr(hosts_start_y, 1, "- Hosts")
        cluster_hosts = []
        if selected_cluster:
            cluster_hosts = [host for host in hosts if host.cluster and host.cluster.id == selected_cluster.id]
        hosts_headers = ["Name", "IP Addresses", "Status", "Load"]
        hosts_col_widths = [28, 26, 39, 23]
        def host_row_func(host):
            name = host.name if host.name else "N/A"
            # host.address가 있으면 DNS 조회를 통해 IP 주소로 변환 시도 (실패하면 원래 값을 사용)
            if hasattr(host, "address") and host.address:
                try:
                    ip_addr = socket.gethostbyname(host.address)
                except Exception:
                    ip_addr = host.address
            else:
                ip_addr = "-"
            status = host.status.value if hasattr(host.status, "value") and host.status else "-"
            load_count = sum(1 for vm in all_vms if vm.host and vm.host.id == host.id)
            load = f"{load_count} VMs" if load_count is not None else "-"
            return [name, ip_addr, status, load]
        draw_table(stdscr, hosts_start_y + 1, hosts_headers, hosts_col_widths, cluster_hosts, host_row_func, -1)
        hosts_table_height = 3 + max(len(cluster_hosts), 1)
        stdscr.addstr(hosts_start_y + 1 + hosts_table_height + 1, 1, "")
        # Virtual Machines 테이블
        vm_start_y = hosts_start_y + 1 + hosts_table_height + 2
        if selected_cluster:
            cluster_vms = [vm for vm in all_vms if vm.cluster and vm.cluster.id == selected_cluster.id]
        else:
            cluster_vms = []
        total_vm_pages = max(1, (len(cluster_vms) + rows_per_vm_page - 1) // rows_per_vm_page)
        if vm_page >= total_vm_pages:
            vm_page = total_vm_pages - 1
        stdscr.addstr(vm_start_y, 1, f"- Virtual Machines ({vm_page+1}/{total_vm_pages})")
        vm_table_y = vm_start_y + 1
        vm_headers = ["Name", "Status", "Uptime", "CPU", "Memory", "Network", "IP Addresses"]
        vm_col_widths = [28, 13, 12, 10, 10, 24, 16]
        start_idx = vm_page * rows_per_vm_page
        end_idx = min(start_idx + rows_per_vm_page, len(cluster_vms))
        vm_rows = []
        for vm in cluster_vms[start_idx:end_idx]:
            vm_name = vm.name if vm.name else "N/A"
            vm_status = vm.status.value.lower() if vm.status and hasattr(vm.status, 'value') else "N/A"
            if vm.start_time and vm_status == "up":
                uptime_seconds = int(time.time() - vm.start_time.timestamp())
                days = uptime_seconds // 86400
                hours = (uptime_seconds % 86400) // 3600
                minutes = (uptime_seconds % 3600) // 60
                uptime = f"{days}d {hours}h {minutes}m"
            else:
                uptime = "-"
            if vm.cpu and vm.cpu.topology:
                cpu_count = vm.cpu.topology.sockets * vm.cpu.topology.cores
                cpu_str = str(cpu_count)
            else:
                cpu_str = "-"
            if vm.memory:
                memory_mb = int(vm.memory / (1024**2))
                memory_str = f"{memory_mb} MB"
            else:
                memory_str = "-"
            network_names = "-"
            ip_addresses = "-"
            try:
                vm_service = vms_service.vm_service(vm.id)
                nics = vm_service.nics_service().list()
                if nics:
                    network_names = ", ".join(nic.name for nic in nics if nic.name)
                else:
                    network_names = "-"
                mac_ip_mapping = {}
                if vm_status == "up":
                    try:
                        reported_devices = vm_service.reported_devices_service().list()
                        if reported_devices:
                            for device in reported_devices:
                                if device.ips:
                                    for ip in device.ips:
                                        if ip.version == IpVersion.V4:
                                            mac_ip_mapping[device.mac.address] = ip.address
                    except Exception:
                        pass
                    ips = []
                    for nic in nics:
                        if nic.mac and nic.mac.address in mac_ip_mapping:
                            ips.append(mac_ip_mapping[nic.mac.address])
                    if ips:
                        ip_addresses = ", ".join(ips)
                    else:
                        ip_addresses = "-"
                else:
                    ip_addresses = "-"
            except Exception:
                network_names = "-"
                ip_addresses = "-"
            vm_rows.append([vm_name, vm_status, uptime, cpu_str, memory_str, network_names, ip_addresses])
        def vm_row_func(row):
            return row
        draw_table(stdscr, vm_table_y, vm_headers, vm_col_widths, vm_rows, vm_row_func, -1)
        vm_table_bottom = vm_table_y + 3 + max(len(vm_rows), 1)
        stdscr.addstr(vm_table_bottom, 1, "")
        stdscr.addstr(vm_table_bottom + 1, 1, "N=Next page | P=Prev page", curses.A_DIM)
        stdscr.addstr(height - 2, 1,
                      "▲/▼=Navigate | Enter=View Events | ESC=Go back | Q=Quit",
                      curses.color_pair(2))
        stdscr.refresh()
        key = stdscr.getch()
        if key == -1:
            continue
        if key == ord('q'):
            exit(0)
        elif key == 27:
            break
        elif key == curses.KEY_UP:
            if clusters_info:
                current_cluster_index = (current_cluster_index - 1) % len(clusters_info)
                vm_page = 0
        elif key == curses.KEY_DOWN:
            if clusters_info:
                current_cluster_index = (current_cluster_index + 1) % len(clusters_info)
                vm_page = 0
        elif key == ord('n'):
            if vm_page < total_vm_pages - 1:
                vm_page += 1
        elif key == ord('p'):
            if vm_page > 0:
                vm_page -= 1
        elif key == 10:  # 엔터 키
            if selected_cluster:
                show_cluster_events(stdscr, connection, selected_cluster)
# End of show_clusters

def show_cluster_events(stdscr, connection, cluster):
    """
    선택한 클러스터의 이벤트를 페이지 단위로 표시.
    제목(헤더) 행을 제외하고 한 페이지에 40줄의 이벤트를 보여줌.
    """
    height, width = stdscr.getmaxyx()
    min_width = 120
    min_height = 14
    if height < min_height or width < min_width:
        stdscr.addstr(0, 0, f"Resize terminal to at least {min_width}x{min_height}.")
        stdscr.refresh()
        stdscr.getch()
        return

    event_headers = ["Time", "Severity", "Description"]
    event_widths = [19, 9, 91]
    header_line = "┌" + "┬".join("─" * w for w in event_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in event_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in event_widths) + "┘"
    
    try:
        events_service = connection.system_service().events_service()
        all_events = events_service.list()
        events = [event for event in all_events 
                  if hasattr(event, 'cluster') and event.cluster and event.cluster.id == cluster.id]
    except Exception as e:
        stdscr.addstr(2, 1, f"Failed to fetch events: {e}")
        stdscr.refresh()
        stdscr.getch()
        return

    page_size = 40  # 제목행 제외 40줄의 이벤트를 표시하도록 설정
    total_pages = max(1, (len(events) + page_size - 1) // page_size)
    current_page = 0
    base_row = 1

    while True:
        stdscr.erase()
        stdscr.addstr(base_row, 1, f"- Events for {cluster.name} (Page {current_page+1}/{total_pages})")
        table_start_row = base_row + 1

        # 화면의 이전 줄들을 지움.
        for i in range(table_start_row, height - 3):
            stdscr.move(i, 1)
            stdscr.clrtoeol()

        stdscr.addstr(table_start_row, 1, header_line)
        stdscr.addstr(table_start_row + 1, 1, "│" + "│".join(
            f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(event_headers, event_widths)
        ) + "│")
        stdscr.addstr(table_start_row + 2, 1, divider_line)

        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(events))
        data_row = table_start_row + 3

        for event in events[start_idx:end_idx]:
            time_str = event.time.strftime("%Y-%m-%d %H:%M:%S") if event.time else "-"
            severity = event.severity.name.lower() if hasattr(event.severity, 'name') else "-"
            description = event.description if event.description else "-"
            row_str = "│" + "│".join(
                f"{truncate_with_ellipsis(val, w):<{w}}" for val, w in zip([time_str, severity, description], event_widths)
            ) + "│"
            stdscr.addstr(data_row, 1, row_str)
            data_row += 1

        stdscr.addstr(data_row, 1, footer_line)
        data_row += 2
        stdscr.addstr(data_row, 1, "N=Next | P=Prev", curses.A_DIM)
        stdscr.addstr(height - 2, 1, "Page {}/{} | ESC=Go back | Q=Quit".format(current_page+1, total_pages), curses.A_DIM)
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord('n') and current_page < total_pages - 1:
            current_page += 1
        elif key == ord('p') and current_page > 0:
            current_page -= 1
        elif key == 27:  # ESC 키
            break
        elif key == ord('q'):
            exit(0)

# =============================================================================
# Section 7: Hosts Section
# =============================================================================

def get_engine_status_symbol(host, hosted_engine_host_id, hosted_engine_cluster_id):
    """
    호스트가 HostedEngine과 같은 경우 "▲",
    호스트의 클러스터가 HostedEngine 클러스터와 같으면 "▼",
    아니면 "-" 반환.
    """
    if hosted_engine_host_id and host.id == hosted_engine_host_id:
        return "▲"
    elif hosted_engine_cluster_id and host.cluster and host.cluster.id == hosted_engine_cluster_id:
        return "▼"
    else:
        return "-"

def show_hosts(stdscr, connection):
    """
    Hosts 목록, 선택한 호스트의 상세 정보(리소스 사용량, 네트워크 인터페이스) 및
    해당 호스트에 속한 Virtual Machines 목록을 표시.
    """
    curses.curs_set(0)
    stdscr.timeout(20)
    height, width = stdscr.getmaxyx()
    try:
        hosts_service = connection.system_service().hosts_service()
        vms_service = connection.system_service().vms_service()
        all_hosts = hosts_service.list()
        # VM 목록은 nics.reporteddevices 포함하여 한 번 가져옴.
        all_vms = vms_service.list(follow="nics.reporteddevices")
    except Exception as e:
        stdscr.addstr(2, 1, f"Failed to fetch host data: {e}")
        stdscr.refresh()
        stdscr.getch()
        return
    # HostedEngine 관련 정보 계산
    hosted_engine_vm = next((vm for vm in all_vms if vm.name == "HostedEngine"), None)
    if hosted_engine_vm:
        hosted_engine_host_id = hosted_engine_vm.host.id if hosted_engine_vm.host else None
        hosted_engine_cluster_id = hosted_engine_vm.cluster.id if hosted_engine_vm.cluster else None
    else:
        hosted_engine_host_id = None
        hosted_engine_cluster_id = None

    # Hosts 목록 테이블 구성
    col_headers = ["Engine", "Name", "Cluster", "Status", "VMs", "Memory Usage", "CPU Usage", "IP"]
    col_widths = [7, 20, 20, 19, 6, 12, 13, 15]
    hosts_rows = []
    host_details = {}
    for host in all_hosts:
        # 클러스터 이름
        cluster = "-"
        if hasattr(host, "cluster") and host.cluster:
            try:
                cluster_obj = connection.follow_link(host.cluster)
                cluster = cluster_obj.name if hasattr(cluster_obj, "name") and cluster_obj.name else "-"
            except Exception:
                cluster = "-"
        engine = get_engine_status_symbol(host, hosted_engine_host_id, hosted_engine_cluster_id)
        name = host.name if host.name else "-"
        status = host.status.value if hasattr(host, "status") and host.status else "-"
        vm_count = sum(1 for vm in all_vms if vm.host and vm.host.id == host.id)
        try:
            host_service = hosts_service.host_service(host.id)
            statistics = host_service.statistics_service().list()
            # CPU 사용량 계산
            cpu_usage_str = "-"
            cpu_idle = next((s.values[0].datum for s in statistics if any(key in s.name.lower() for key in ["cpu.idle", "cpu.idle.percent"])), None)
            if cpu_idle is not None:
                try:
                    cpu_idle = float(cpu_idle)
                except Exception:
                    cpu_usage_str = "-"
                else:
                    if cpu_idle <= 1:
                        cpu_idle *= 100
                    cpu_usage = 100 - cpu_idle
                    cpu_usage_str = f"{round(cpu_usage, 2)}%"
            else:
                cpu_util = next((s.values[0].datum for s in statistics if "cpu.utilization" in s.name.lower()), None)
                if cpu_util is not None:
                    try:
                        cpu_util = float(cpu_util)
                    except Exception:
                        cpu_usage_str = "-"
                    else:
                        if cpu_util <= 1:
                            cpu_util *= 100
                        cpu_usage_str = f"{round(cpu_util, 2)}%"
                else:
                    cpu_load = next((s.values[0].datum for s in statistics if "cpu.load.avg" in s.name.lower()), None)
                    if cpu_load is not None:
                        try:
                            cpu_load = float(cpu_load)
                        except Exception:
                            cpu_usage_str = "-"
                        else:
                            cpu_usage_str = f"{round(cpu_load, 2)}%"
                    else:
                        cpu_usage_str = "-"
            memory_used = next((s.values[0].datum for s in statistics if 'memory.used' in s.name.lower()), None)
            memory_total = next((s.values[0].datum for s in statistics if 'memory.total' in s.name.lower()), None)
            if memory_used is not None and memory_total and memory_total > 0:
                mem_percent = f"{round((memory_used/memory_total)*100,1)}%"
            else:
                mem_percent = "-"
        except Exception:
            cpu_usage_str = "-"
            mem_percent = "-"
        # 호스트 IP: host.address가 없으면 NIC 조회
        ip = "-"
        if hasattr(host, "address") and host.address:
            ip = host.address
        if not ip or not ip.replace(".", "").isdigit():
            try:
                nics = hosts_service.host_service(host.id).nics_service().list()
                for nic in nics:
                    if hasattr(nic, "ip") and nic.ip and hasattr(nic.ip, "address"):
                        ip = nic.ip.address
                        break
            except Exception:
                pass
        hosts_rows.append([engine, name, cluster, status, str(vm_count), mem_percent, cpu_usage_str, ip])
        host_details[host.id] = {"statistics": statistics, "host_service": host_service}
    current_host_index = 0
    vm_page = 0
    rows_per_vm_page = 5

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 40 or width < 120:
            stdscr.addstr(0, 0, "Resize the terminal to at least 120x40.", curses.A_BOLD)
            stdscr.refresh()
            continue
        stdscr.addstr(1, 1, "Hosts", curses.A_BOLD)
        stdscr.addstr(3, 1, "- Hosts List")
        table_y = 4
        header_line = "┌" + "┬".join("─" * w for w in col_widths) + "┐"
        divider_line = "├" + "┼".join("─" * w for w in col_widths) + "┤"
        footer_line = "└" + "┴".join("─" * w for w in col_widths) + "┘"
        stdscr.addstr(table_y, 1, header_line)
        header_text = "│" + "│".join(f"{h:<{w}}" for h, w in zip(col_headers, col_widths)) + "│"
        stdscr.addstr(table_y+1, 1, header_text)
        stdscr.addstr(table_y+2, 1, divider_line)
        for idx, row in enumerate(hosts_rows):
            y = table_y + 3 + idx
            row_text = "│" + "│".join(f"{truncate_with_ellipsis(val, w):<{w}}" for val, w in zip(row, col_widths)) + "│"
            if idx == current_host_index:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(y, 1, row_text)
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(y, 1, row_text)
        stdscr.addstr(table_y + 3 + len(hosts_rows), 1, footer_line)
        selected_host = all_hosts[current_host_index]
        details_y = table_y + 4 + len(hosts_rows)
        uptime = "-"
        mem_detail = "-"
        try:
            stat_list = hosts_service.host_service(selected_host.id).statistics_service().list()
            boot_time = None
            memory_total = None
            memory_used = None
            for stat in stat_list:
                if stat.name.lower() == "boot.time":
                    try:
                        boot_time_unix = int(stat.values[0].datum)
                        boot_time = datetime.fromtimestamp(boot_time_unix, timezone.utc)
                    except Exception:
                        boot_time = None
                elif stat.name.lower() == "memory.total":
                    memory_total = int(stat.values[0].datum)
                elif stat.name.lower() == "memory.used":
                    memory_used = int(stat.values[0].datum)
            if boot_time:
                now = datetime.now(timezone.utc)
                delta = now - boot_time
                uptime = f"{delta.days}d {delta.seconds//3600}h {(delta.seconds//60)%60}m"
            if memory_total and memory_used:
                mem_detail = f"{memory_used/(1024**3):.2f}GB / {memory_total/(1024**3):.2f}GB"
        except Exception:
            pass
        host_vms = [vm for vm in all_vms if vm.host and vm.host.id == selected_host.id]
        assigned_vm_cpu = 0
        for vm in host_vms:
            if hasattr(vm, "cpu") and vm.cpu and hasattr(vm.cpu, "topology") and vm.cpu.topology:
                try:
                    assigned_vm_cpu += vm.cpu.topology.sockets * vm.cpu.topology.cores
                except Exception:
                    pass
        host_total_cpu = None
        if hasattr(selected_host, "cpu") and selected_host.cpu and hasattr(selected_host.cpu, "topology") and selected_host.cpu.topology:
            try:
                host_total_cpu = selected_host.cpu.topology.sockets * selected_host.cpu.topology.cores
            except Exception:
                host_total_cpu = None
        if host_total_cpu and host_total_cpu > 0:
            cpu_detail = f"{assigned_vm_cpu}/{host_total_cpu}"
        else:
            cpu_detail = "-"
        wwnn = "-"
        if hasattr(selected_host, "wwnn") and selected_host.wwnn:
            wwnn = selected_host.wwnn
        elif hasattr(selected_host, "wwn") and selected_host.wwn:
            wwnn = selected_host.wwn
        stdscr.addstr(details_y, 1, f"Uptime: {uptime}")
        stdscr.addstr(details_y+1, 1, f"Memory Usage: {mem_detail}")
        stdscr.addstr(details_y+2, 1, f"CPU Usage: {cpu_detail}")
        stdscr.addstr(details_y+3, 1, f"WWNN: {wwnn}")
        net_y = details_y + 5
        stdscr.addstr(net_y, 1, f"- Network Interfaces for {selected_host.name}")
        net_headers = ["Devices", "Network Name", "IP", "Mac Address", "Speed", "VLAN"]
        net_col_widths = [20, 20, 16, 26, 18, 14]
        try:
            nics = hosts_service.host_service(selected_host.id).nics_service().list()
        except Exception:
            nics = []
        nic_list = []
        for nic in nics:
            device = nic.name if hasattr(nic, "name") and nic.name else "-"
            network_name = "-"
            if hasattr(nic, "network") and nic.network:
                try:
                    net_obj = connection.follow_link(nic.network)
                    network_name = net_obj.name if hasattr(net_obj, "name") and net_obj.name else "-"
                except Exception:
                    network_name = "-"
            elif hasattr(nic, "vnic_profile") and nic.vnic_profile:
                try:
                    vp_obj = connection.follow_link(nic.vnic_profile)
                    network_name = vp_obj.name if hasattr(vp_obj, "name") and vp_obj.name else "-"
                except Exception:
                    network_name = "-"
            ip_addr = "-"
            if hasattr(nic, "ip") and nic.ip and hasattr(nic.ip, "address"):
                ip_addr = nic.ip.address
            mac_addr = "-"
            if hasattr(nic, "mac") and nic.mac and hasattr(nic.mac, "address"):
                mac_addr = nic.mac.address
            speed = get_network_speed(device)
            vlan = "-"
            if hasattr(nic, "vlan") and nic.vlan and hasattr(nic.vlan, "id"):
                vlan = nic.vlan.id
            nic_list.append({
                "devices": device,
                "network_name": network_name,
                "ip": ip_addr,
                "mac_address": mac_addr,
                "speed": speed,
                "vlan": vlan
            })
        nics = nic_list if nic_list else []
        net_header_line = "┌" + "┬".join("─" * w for w in net_col_widths) + "┐"
        net_divider_line = "├" + "┼".join("─" * w for w in net_col_widths) + "┤"
        net_footer_line = "└" + "┴".join("─" * w for w in net_col_widths) + "┘"
        stdscr.addstr(net_y+1, 1, net_header_line)
        stdscr.addstr(net_y+2, 1, "│" + "│".join(f"{h:<{w}}" for h, w in zip(net_headers, net_col_widths)) + "│")
        stdscr.addstr(net_y+3, 1, net_divider_line)
        row_y = net_y + 4
        if not nics:
            placeholder = ["-"] * len(net_headers)
            stdscr.addstr(row_y, 1, "│" + "│".join(f"{p:<{w}}" for p, w in zip(placeholder, net_col_widths)) + "│")
            row_y += 1
        else:
            for nic in nics:
                nic_row = [nic["devices"], nic["network_name"], nic["ip"], nic["mac_address"], nic["speed"], nic["vlan"]]
                stdscr.addstr(row_y, 1, "│" + "│".join(f"{truncate_with_ellipsis(val, w):<{w}}" for val, w in zip(nic_row, net_col_widths)) + "│")
                row_y += 1
        stdscr.addstr(row_y, 1, net_footer_line)
        vm_y = row_y + 2
        host_vms = [vm for vm in all_vms if vm.host and vm.host.id == selected_host.id]
        total_vm_pages = max(1, (len(host_vms) + rows_per_vm_page - 1) // rows_per_vm_page)
        if vm_page >= total_vm_pages:
            vm_page = total_vm_pages - 1
        stdscr.addstr(vm_y, 1, f"- Virtual Machines for {selected_host.name} ({vm_page+1}/{total_vm_pages})")
        vm_table_y = vm_y + 1
        vm_headers = ["Name", "Cluster", "IP", "Hostname", "Memory", "CPU", "Status", "Uptime"]
        vm_col_widths = [20, 20, 16, 18, 8, 8, 10, 12]
        vm_header_line = "┌" + "┬".join("─" * w for w in vm_col_widths) + "┐"
        vm_divider_line = "├" + "┼".join("─" * w for w in vm_col_widths) + "┤"
        vm_footer_line = "└" + "┴".join("─" * w for w in vm_col_widths) + "┘"
        stdscr.addstr(vm_table_y, 1, vm_header_line)
        stdscr.addstr(vm_table_y+1, 1, "│" + "│".join(f"{h:<{w}}" for h, w in zip(vm_headers, vm_col_widths)) + "│")
        stdscr.addstr(vm_table_y+2, 1, vm_divider_line)
        data_row = vm_table_y + 3
        if not host_vms:
            empty_row = ["-"] * len(vm_headers)
            stdscr.addstr(data_row, 1, "│" + "│".join(f"{p:<{w}}" for p, w in zip(empty_row, vm_col_widths)) + "│")
            data_row += 1
        else:
            for vm in host_vms[vm_page * rows_per_vm_page : (vm_page+1)*rows_per_vm_page]:
                vm_name = vm.name if vm.name else "-"
                vm_cluster = "-"
                if hasattr(vm, "cluster") and vm.cluster:
                    try:
                        cluster_obj = connection.follow_link(vm.cluster)
                        vm_cluster = cluster_obj.name if hasattr(cluster_obj, "name") and cluster_obj.name else "-"
                    except Exception:
                        vm_cluster = "-"
                vm_ip = "N/A"
                if vm.nics:
                    for nic in vm.nics:
                        if nic.reported_devices:
                            for device in nic.reported_devices:
                                if device.ips:
                                    vm_ip = device.ips[0].address
                                    break
                        if vm_ip != "N/A":
                            break
                hostname = vm.name if vm.name else "-"
                memory_str = f"{int(vm.memory/(1024**3))} GB" if vm.memory else "-"
                if vm.cpu and vm.cpu.topology:
                    cpu_count = vm.cpu.topology.sockets * vm.cpu.topology.cores
                    cpu_str = f"{cpu_count} Cores"
                else:
                    cpu_str = "-"
                vm_status = vm.status.value.lower() if vm.status and hasattr(vm.status, "value") else "-"
                uptime = "-"
                if vm.start_time and vm_status == "up":
                    uptime_seconds = int(time.time() - vm.start_time.timestamp())
                    days = uptime_seconds // 86400
                    hours = (uptime_seconds % 86400) // 3600
                    minutes = (uptime_seconds % 3600) // 60
                    uptime = f"{days}d {hours}h {minutes}m"
                vm_row = [vm_name, vm_cluster, vm_ip, hostname, memory_str, cpu_str, vm_status, uptime]
                stdscr.addstr(data_row, 1, "│" + "│".join(f"{truncate_with_ellipsis(val, w):<{w}}" for val, w in zip(vm_row, vm_col_widths)) + "│")
                data_row += 1
        stdscr.addstr(data_row, 1, vm_footer_line)
        stdscr.addstr(data_row + 1, 1, "N=Next page | P=Prev page", curses.A_DIM)
        stdscr.addstr(height - 2, 1,
                      "▲/▼=Navigate Hosts List | ENTER=View Host Events | N/P=VM Page | ESC=Go back | Q=Quit",
                      curses.color_pair(2))
        stdscr.refresh()
        key = stdscr.getch()
        if key == -1:
            continue
        elif key == ord('q'):
            exit(0)
        elif key == 27:
            break
        elif key == curses.KEY_UP:
            current_host_index = (current_host_index - 1) % len(hosts_rows)
            vm_page = 0
        elif key == curses.KEY_DOWN:
            current_host_index = (current_host_index + 1) % len(hosts_rows)
            vm_page = 0
        elif key == ord('n'):
            if vm_page < total_vm_pages - 1:
                vm_page += 1
        elif key == ord('p'):
            if vm_page > 0:
                vm_page -= 1
        elif key == 10:
            show_host_events(stdscr, connection, selected_host)
    # end while
def show_host_events(stdscr, connection, host):
    """
    선택한 호스트의 이벤트를 페이지 단위로 표시.
    제목(헤더) 행을 제외하고 한 페이지에 40줄의 이벤트를 출력.
    """
    height, width = stdscr.getmaxyx()
    min_width = 120
    min_height = 14
    if height < min_height or width < min_width:
        stdscr.addstr(0, 0, f"Resize terminal to at least {min_width}x{min_height}.")
        stdscr.refresh()
        stdscr.getch()
        return

    # 이벤트 테이블 헤더와 열 너비 설정
    event_headers = ["Time", "Severity", "Description"]
    event_widths = [19, 9, 91]
    header_line = "┌" + "┬".join("─" * w for w in event_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in event_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in event_widths) + "┘"
    
    try:
        # 호스트 이름으로 이벤트 조회 (최대 50개)
        events_service = connection.system_service().events_service()
        events = events_service.list(search=f"host.name={host.name}", max=50)
    except Exception as e:
        stdscr.addstr(2, 1, f"Failed to fetch events: {e}")
        stdscr.refresh()
        stdscr.getch()
        return

    page_size = 40  # 제목(헤더) 제외 40줄의 이벤트를 표시하도록 설정
    total_pages = max(1, (len(events) + page_size - 1) // page_size)
    current_page = 0
    base_row = 1

    while True:
        stdscr.erase()
        stdscr.addstr(base_row, 1, f"- Events for {host.name} (Page {current_page+1}/{total_pages})")
        table_start_row = base_row + 1

        # 화면의 이전 줄들을 지움.
        for i in range(table_start_row, height - 3):
            stdscr.move(i, 1)
            stdscr.clrtoeol()

        stdscr.addstr(table_start_row, 1, header_line)
        stdscr.addstr(table_start_row + 1, 1, "│" + "│".join(
            f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(event_headers, event_widths)
        ) + "│")
        stdscr.addstr(table_start_row + 2, 1, divider_line)

        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(events))
        data_row = table_start_row + 3

        # 이벤트 데이터를 페이지 단위로 출력
        for event in events[start_idx:end_idx]:
            time_str = event.time.strftime("%Y-%m-%d %H:%M:%S") if event.time else "-"
            severity = event.severity.name.lower() if hasattr(event.severity, 'name') else "-"
            description = event.description if event.description else "-"
            row_str = "│" + "│".join(
                f"{truncate_with_ellipsis(val, w):<{w}}" for val, w in zip([time_str, severity, description], event_widths)
            ) + "│"
            stdscr.addstr(data_row, 1, row_str)
            data_row += 1

        stdscr.addstr(data_row, 1, footer_line)
        data_row += 2
        stdscr.addstr(data_row, 1, "N=Next | P=Prev", curses.A_DIM)
        stdscr.addstr(height - 2, 1, "Page {}/{} | ESC=Go back | Q=Quit".format(current_page+1, total_pages), curses.A_DIM)
        stdscr.refresh()

        key = stdscr.getch()
        if key == ord('n') and current_page < total_pages - 1:
            current_page += 1
        elif key == ord('p') and current_page > 0:
            current_page -= 1
        elif key == 27:  # ESC 키
            break
        elif key == ord('q'):
            exit(0)

# =============================================================================
# Section 8: Networks Section
# =============================================================================

def parse_passthrough(val):
    """
    passthrough 값을 처리하여 "True" 또는 "False" 문자열을 반환.
    문자열로 변환 후 소문자로 변환 시 "true"라는 단어가 포함되어 있으면 "True"로 처리.
    """
    return "True" if "true" in str(val).strip().lower() else "False"

def show_event_page(stdscr, connection, network):
    """
    선택된 네트워크의 이벤트 페이지를 표시하며,
    해당 네트워크 + Data Center 정보를 기반으로 필터링한 이벤트를 출력.
    """
    import time

    height, width = stdscr.getmaxyx()
    event_win = curses.newwin(height, width, 0, 0)
    event_win.clear()

    # 선택된 네트워크의 정보
    network_name = network.get("name", "-")
    network_id = network.get("id", "-")
    network_data_center = network.get("data_center", "-")

    # 기존 이벤트를 저장할 리스트 (최대 200개까지만 유지)
    network_events = []
    MAX_EVENTS = 200  # 최대 200개의 이벤트만 유지

    def fetch_events():
        """ 새로운 이벤트를 가져와 기존 이벤트 리스트에 추가하되, 가장 오래된 이벤트를 삭제함 """
        events_service = connection.system_service().events_service()
        new_events = events_service.list(max=100)  # 최신 100개 이벤트 가져오기

        # 필터링: 선택된 네트워크와 관련된 이벤트만 저장
        filtered_events = [
            ev for ev in new_events
            if ev.description and ("network" in ev.description.lower())
            and (network_name in ev.description or network_id in ev.description)
            and (network_data_center in ev.description)
        ]

        # 기존 이벤트와 합치면서 중복 제거 (event.id 기준)
        existing_event_ids = {ev.id for ev in network_events}
        for event in filtered_events:
            if event.id not in existing_event_ids:
                network_events.append(event)

        # 가장 최근 생성된 200개만 유지 (정렬 후 오래된 것 삭제)
        network_events.sort(key=lambda x: x.time, reverse=True)  # 시간 기준 내림차순 정렬
        if len(network_events) > MAX_EVENTS:
            network_events[:] = network_events[:MAX_EVENTS]  # 최신 200개 유지

    # 페이지네이션 설정
    MAX_ROWS = 40  # 한 페이지에 표시할 최대 이벤트 개수
    current_page = 1

    indent = " "  # 앞 공백 한 칸 유지

    def draw_event_page():
        """ 이벤트 페이지를 다시 그리는 함수 """
        event_win.erase()
        total_events = len(network_events)
        max_page = max(1, (total_events + MAX_ROWS - 1) // MAX_ROWS)

        title = indent + f"- Event Page for {network_name} (Data Center: {network_data_center}) ({current_page}/{max_page})"
        event_win.addstr(1, 0, title)

        # 테이블 헤더
        event_headers = ["Time", "Severity", "Description"]
        event_widths = [19, 9, 91]

        if total_events == 0:
            header_line = indent + "┌" + "─" * event_widths[0] + "┬" + "─" * event_widths[1] + "┬" + "─" * event_widths[2] + "┐"
            event_win.addstr(3, 0, header_line)
            
            event_win.addstr(4, 0, indent + "│" + f"{event_headers[0]:<{event_widths[0]}}" + "│" + 
                             f"{event_headers[1]:<{event_widths[1]}}" + "│" + 
                             f"{event_headers[2]:<{event_widths[2]}}" + "│")
        
            divider_line = indent + "├" + "─" * event_widths[0] + "┴" + "─" * (event_widths[1] + event_widths[2] + 1) + "┤"
            event_win.addstr(5, 0, divider_line)
        
            event_win.addstr(6, 0, indent + "│" + " No events found for this network.".ljust(sum(event_widths) + 2) + "│")
        
            # Footer 부분: divider_line과 정확히 정렬되도록 수정
            footer_line = indent + "└" + "─" * event_widths[0] + "┴" + "─" * (event_widths[1] + event_widths[2] + 1) + "┘"
            event_win.addstr(7, 0, footer_line)

        else:
            header_line = indent + "┌" + "┬".join("─" * w for w in event_widths) + "┐"
            event_win.addstr(3, 0, header_line)
            header_row = indent + "│" + "│".join(f"{h:<{w}}" for h, w in zip(event_headers, event_widths)) + "│"
            event_win.addstr(4, 0, header_row)
            divider_line = indent + "├" + "┼".join("─" * w for w in event_widths) + "┤"
            event_win.addstr(5, 0, divider_line)

            start_idx = (current_page - 1) * MAX_ROWS
            end_idx = min(start_idx + MAX_ROWS, total_events)

            for i, event in enumerate(network_events[start_idx:end_idx]):
                time_str = event.time.strftime("%Y-%m-%d %H:%M:%S") if event.time else "-"
                severity = str(event.severity).split(".")[-1]  # ENUM 값에서 문자열 추출
                message = event.description if event.description else "-"

                row = [
                    time_str[:event_widths[0]],
                    severity[:event_widths[1]],
                    message[:event_widths[2]]
                ]

                row_str = indent + "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, event_widths)) + "│"
                event_win.addstr(6 + i, 0, row_str)

            bottom_line = indent + "└" + "┴".join("─" * w for w in event_widths) + "┘"
            event_win.addstr(6 + (end_idx - start_idx), 0, bottom_line)

        # 'N=Next | P=Prev' 문구 위치
        event_win.addstr(8 if total_events == 0 else 7 + (end_idx - start_idx), 0, indent + "N=Next | P=Prev")  
        # 하단 안내 문구
        event_win.addstr(height - 2, 0, indent + "ESC=Go back | Q=Quit")

        event_win.refresh()

    fetch_events()  # 처음 실행 시 이벤트 가져오기
    draw_event_page()  # 이벤트 출력

    while True:
        key = event_win.getch()
        if key == 27:  # ESC 키 (뒤로가기)
            break
        elif key in (ord('q'), ord('Q')):  # 프로그램 종료
            exit(0)
        elif key in (ord('n'), ord('N')) and current_page < (len(network_events) + MAX_ROWS - 1) // MAX_ROWS:
            current_page += 1
            draw_event_page()
        elif key in (ord('p'), ord('P')) and current_page > 1:
            current_page -= 1
            draw_event_page()
        else:
            fetch_events()  # 새로운 이벤트 가져오기
            draw_event_page()  # 화면 업데이트
            time.sleep(5)  # 5초마다 업데이트

def show_event_page(stdscr, connection, network):
    """
    선택된 네트워크의 이벤트 페이지를 표시하며,
    해당 네트워크 + Data Center 정보를 기반으로 필터링한 이벤트를 출력.
    """
    import time

    height, width = stdscr.getmaxyx()
    event_win = curses.newwin(height, width, 0, 0)
    event_win.clear()

    # 선택된 네트워크의 정보
    network_name = network.get("name", "-")
    network_id = network.get("id", "-")
    network_data_center = network.get("data_center", "-")

    # 기존 이벤트를 저장할 리스트 (최대 200개까지만 유지)
    network_events = []
    MAX_EVENTS = 200  # 최대 200개의 이벤트만 유지

    def fetch_events():
        """ 새로운 이벤트를 가져와 기존 이벤트 리스트에 추가하되, 가장 오래된 이벤트를 삭제함 """
        events_service = connection.system_service().events_service()
        new_events = events_service.list(max=100)  # 최신 100개 이벤트 가져오기

        # 필터링: 선택된 네트워크와 관련된 이벤트만 저장
        filtered_events = [
            ev for ev in new_events
            if ev.description and ("network" in ev.description.lower())
            and (network_name in ev.description or network_id in ev.description)
            and (network_data_center in ev.description)
        ]

        # 기존 이벤트와 합치면서 중복 제거 (event.id 기준)
        existing_event_ids = {ev.id for ev in network_events}
        for event in filtered_events:
            if event.id not in existing_event_ids:
                network_events.append(event)

        # 가장 최근 생성된 200개만 유지 (정렬 후 오래된 것 삭제)
        network_events.sort(key=lambda x: x.time, reverse=True)  # 시간 기준 내림차순 정렬
        if len(network_events) > MAX_EVENTS:
            network_events[:] = network_events[:MAX_EVENTS]  # 최신 200개 유지

    # 페이지네이션 설정
    MAX_ROWS = 40  # 한 페이지에 표시할 최대 이벤트 개수
    current_page = 1

    indent = " "  # 앞 공백 한 칸 유지

    def draw_event_page():
        """ 이벤트 페이지를 다시 그리는 함수 """
        event_win.erase()
        total_events = len(network_events)
        max_page = max(1, (total_events + MAX_ROWS - 1) // MAX_ROWS)

        title = indent + f"- Event Page for {network_name} (Data Center: {network_data_center}) ({current_page}/{max_page})"
        event_win.addstr(1, 0, title)

        # 테이블 헤더
        event_headers = ["Time", "Severity", "Description"]
        event_widths = [19, 9, 91]

        if total_events == 0:
            header_line = indent + "┌" + "─" * event_widths[0] + "┬" + "─" * event_widths[1] + "┬" + "─" * event_widths[2] + "┐"
            event_win.addstr(3, 0, header_line)
            
            event_win.addstr(4, 0, indent + "│" + f"{event_headers[0]:<{event_widths[0]}}" + "│" + 
                             f"{event_headers[1]:<{event_widths[1]}}" + "│" + 
                             f"{event_headers[2]:<{event_widths[2]}}" + "│")
        
            divider_line = indent + "├" + "─" * event_widths[0] + "┴" + "─" * (event_widths[1] + event_widths[2] + 1) + "┤"
            event_win.addstr(5, 0, divider_line)
        
            event_win.addstr(6, 0, indent + "│" + " No events found for this network.".ljust(sum(event_widths) + 2) + "│")
        
            # Footer 부분: divider_line과 정확히 정렬되도록 수정
            footer_line = indent + "└" + "─" * event_widths[0] + "─" + "─" * (event_widths[1] + event_widths[2] + 1) + "┘"
            event_win.addstr(7, 0, footer_line)
        else:
            header_line = indent + "┌" + "┬".join("─" * w for w in event_widths) + "┐"
            event_win.addstr(3, 0, header_line)
            event_win.addstr(4, 0, indent + "│" + "│".join(f"{h:<{w}}" for h, w in zip(event_headers, event_widths)) + "│")
            event_win.addstr(5, 0, indent + "├" + "┼".join("─" * w for w in event_widths) + "┤")

            start_idx = (current_page - 1) * MAX_ROWS
            end_idx = min(start_idx + MAX_ROWS, total_events)

            for i, event in enumerate(network_events[start_idx:end_idx]):
                time_str = event.time.strftime("%Y-%m-%d %H:%M:%S") if event.time else "-"
                severity = str(event.severity).split(".")[-1]
                message = event.description if event.description else "-"

                row = [
                    time_str[:event_widths[0]],
                    severity[:event_widths[1]],
                    message[:event_widths[2]]
                ]

                event_win.addstr(6 + i, 0, indent + "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, event_widths)) + "│")

            event_win.addstr(6 + (end_idx - start_idx), 0, indent + "└" + "┴".join("─" * w for w in event_widths) + "┘")

        event_win.addstr(8 if total_events == 0 else 7 + (end_idx - start_idx), 0, indent + "N=Next | P=Prev")  
        event_win.addstr(height - 2, 0, indent + "ESC=Go back | Q=Quit")

        event_win.refresh()

    fetch_events()  # 처음 실행 시 이벤트 가져오기
    draw_event_page()  # 이벤트 출력

    while True:
        key = event_win.getch()
        if key == 27:  # ESC 키 (뒤로가기)
            break
        elif key in (ord('q'), ord('Q')):  # 프로그램 종료
            exit(0)
        elif key in (ord('n'), ord('N')) and current_page < (len(network_events) + MAX_ROWS - 1) // MAX_ROWS:
            current_page += 1
            draw_event_page()
        elif key in (ord('p'), ord('P')) and current_page > 1:
            current_page -= 1
            draw_event_page()
        else:
            fetch_events()  # 새로운 이벤트 가져오기
            draw_event_page()  # 화면 업데이트
            time.sleep(5)  # 5초마다 업데이트


def draw_screen(stdscr, network_info, selected_network_idx, vm_page, MAX_VM_ROWS, vnic_profiles):
    indent = " "
    stdscr.erase()
    height, width = stdscr.getmaxyx()

    # --- 상단 헤더 ---
    try:
        stdscr.addstr(0, 0, indent + " ")
        stdscr.addstr(1, 0, indent + "Networks", curses.A_BOLD)
        stdscr.addstr(2, 0, indent + " ")
        stdscr.addstr(3, 0, indent + "- Network List")
    except curses.error:
        pass

    # --- 네트워크 테이블 ---
    net_table_start = 4
    net_headers = ["Network Name", "Data Center", "Description", "Role", "VLAN Tag", "MTU", "Port Isolation"]
    net_widths = [22, 23, 27, 6, 8, 13, 14]
    try:
        stdscr.addstr(net_table_start, 0, indent + "┌" + "┬".join("─" * w for w in net_widths) + "┐")
        stdscr.addstr(net_table_start + 1, 0, indent + "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(net_headers, net_widths)) + "│")
        stdscr.addstr(net_table_start + 2, 0, indent + "├" + "┼".join("─" * w for w in net_widths) + "┤")
    except curses.error:
        pass
    for idx, net in enumerate(network_info):
        mtu_raw = net.get("mtu", 1500)
        mtu_value = "Default(1500)" if mtu_raw == 1500 else truncate_with_ellipsis(str(mtu_raw), net_widths[5])
        row = [
            truncate_with_ellipsis(net.get("name", "-"), net_widths[0]),
            truncate_with_ellipsis(net.get("data_center", "-"), net_widths[1]),
            truncate_with_ellipsis(net.get("description", "-"), net_widths[2]),
            truncate_with_ellipsis(str(net.get("role", "-")).lower(), net_widths[3]),
            truncate_with_ellipsis(str(net.get("vlan_tag", "-")), net_widths[4]),
            truncate_with_ellipsis(mtu_value, net_widths[5]),
            truncate_with_ellipsis(str(net.get("port_isolation", "-")), net_widths[6]),
        ]
        try:
            color = curses.color_pair(1) if idx == selected_network_idx else 0
            stdscr.addstr(net_table_start + 3 + idx, 0, indent + "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, net_widths)) + "│", color)
        except curses.error:
            pass
    try:
        stdscr.addstr(net_table_start + 3 + len(network_info), 0, indent + "└" + "┴".join("─" * w for w in net_widths) + "┘")
    except curses.error:
        pass

    # --- VNIC Profile 테이블 ---
    vnic_table_start = net_table_start + 3 + len(network_info) + 2
    selected_network = network_info[selected_network_idx]
    try:
        stdscr.addstr(vnic_table_start, 0, indent + f"- VNIC Profile for {selected_network.get('name', '-')}" \
                                                   f" (Data Center: {selected_network.get('data_center', '-')})")
    except curses.error:
        pass
    vnic_table_start += 1
    vnic_headers = ["Name", "Netowrk", "Data Center", "Network Filter", "Port Mirroring", "Passthrough", "Failover vNIC Profile"]
    vnic_widths = [14, 13, 19, 21, 14, 11, 21]
    try:
        stdscr.addstr(vnic_table_start, 0, indent + "┌" + "┬".join("─" * w for w in vnic_widths) + "┐")
        stdscr.addstr(vnic_table_start + 1, 0, indent + "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(vnic_headers, vnic_widths)) + "│")
        stdscr.addstr(vnic_table_start + 2, 0, indent + "├" + "┼".join("─" * w for w in vnic_widths) + "┤")
    except curses.error:
        pass

    selected_net_id = selected_network.get("id", None)
    vnic_profile_list = []
    if selected_net_id:
        for profile in vnic_profiles.values():
            if profile.network is not None and getattr(profile.network, "id", None) == selected_net_id:
                vnic_profile_list.append(profile)
    if not vnic_profile_list:
        vnic_profile_list = [None]
    vnic_row_start = vnic_table_start + 3
    for idx, profile in enumerate(vnic_profile_list):
        if profile is None:
            row = ["-"] * len(vnic_headers)
        else:
            name = getattr(profile, "name", "-") or "-"
            # Netowrk 열: 무조건 선택된 네트워크의 name 사용
            network_name = selected_network.get("name", "-")
            # Data Center 열: profile.data_center가 없으면 선택된 네트워크의 data_center 사용
            if hasattr(profile, "data_center") and getattr(profile, "data_center") is not None:
                dc_obj = getattr(profile, "data_center")
                dc_name = (getattr(dc_obj, "name", None) or selected_network.get("data_center", "-"))
            else:
                dc_name = selected_network.get("data_center", "-")
            # Network Filter 처리
            net_filter_obj = getattr(profile, "network_filter", None)
            if net_filter_obj is None:
                net_filter = "vdsm-no-mac-spoofing"
            elif isinstance(net_filter_obj, str):
                net_filter = net_filter_obj
            elif hasattr(net_filter_obj, "value"):
                net_filter = net_filter_obj.value
            elif hasattr(net_filter_obj, "name"):
                net_filter = (net_filter_obj.name or "vdsm-no-mac-spoofing").lower().replace("_", "-")
            else:
                net_filter = str(net_filter_obj)
            # passthrough 처리: parse_passthrough 사용
            pt_value = getattr(profile, "passthrough", None)
            passthrough = parse_passthrough(pt_value)
            port_mirroring = "True" if getattr(profile, "port_mirroring", False) else "False"
            failover_obj = getattr(profile, "failover_vnic_profile", None)
            failover = getattr(failover_obj, "name", "-") if failover_obj else "-"
            row = [name, network_name, dc_name, net_filter, port_mirroring, passthrough, failover]
        try:
            stdscr.addstr(vnic_row_start + idx, 0, indent + "│" + "│".join(f"{truncate_with_ellipsis(col, w):<{w}}" for col, w in zip(row, vnic_widths)) + "│")
        except curses.error:
            pass
    try:
        stdscr.addstr(vnic_row_start + len(vnic_profile_list), 0, indent + "└" + "┴".join("─" * w for w in vnic_widths) + "┘")
    except curses.error:
        pass

    # --- Virtual Machines 테이블 ---
    vm_table_start = vnic_row_start + len(vnic_profile_list) + 2
    vm_list = selected_network.get("vms", [])
    total_vms = len(vm_list)
    max_vm_page = max(1, math.ceil(total_vms / MAX_VM_ROWS))
    try:
        stdscr.addstr(vm_table_start, 0, indent + f"- Virtual Machines for {selected_network.get('name', '-')}" \
                                                   f" (Data Center: {selected_network.get('data_center', '-')})" \
                                                   f" ({vm_page}/{max_vm_page})")
    except curses.error:
        pass

    vm_table_start += 1
    vm_headers = ["Virtual Machine Name", "Cluster", "IP Addresses", "Host Name", "vNIC Status", "vNIC"]
    vm_widths = [22, 23, 16, 21, 12, 20]
    try:
        stdscr.addstr(vm_table_start, 0, indent + "┌" + "┬".join("─" * w for w in vm_widths) + "┐")
        stdscr.addstr(vm_table_start + 1, 0, indent + "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(vm_headers, vm_widths)) + "│")
        stdscr.addstr(vm_table_start + 2, 0, indent + "├" + "┼".join("─" * w for w in vm_widths) + "┤")
    except curses.error:
        pass

    start_index = (vm_page - 1) * MAX_VM_ROWS
    end_index = start_index + MAX_VM_ROWS
    vms_to_display = vm_list[start_index:end_index]
    if not vms_to_display:
        vms_to_display = [{
            "vm_name": "-",
            "cluster": "-",
            "ip": "-",
            "host_name": "-",
            "vnic_status": "-",
            "vnic": "-"
        }]
    vm_row_start = vm_table_start + 3
    for idx, vm in enumerate(vms_to_display):
        row = [
            truncate_with_ellipsis(vm.get("vm_name", "-"), vm_widths[0]),
            truncate_with_ellipsis(vm.get("cluster", "-"), vm_widths[1]),
            truncate_with_ellipsis(vm.get("ip", "-"), vm_widths[2]),
            truncate_with_ellipsis(vm.get("host_name", "-"), vm_widths[3]),
            truncate_with_ellipsis(vm.get("vnic_status", "-"), vm_widths[4]),
            truncate_with_ellipsis(vm.get("vnic", "-"), vm_widths[5])
        ]
        try:
            stdscr.addstr(vm_row_start + idx, 0, indent + "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, vm_widths)) + "│")
        except curses.error:
            pass
    try:
        stdscr.addstr(vm_row_start + len(vms_to_display), 0, indent + "└" + "┴".join("─" * w for w in vm_widths) + "┘")
        stdscr.addstr(vm_row_start + len(vms_to_display) + 1, 0, indent + "N=Next page | P=Prev page")
    except curses.error:
        pass

    try:
        stdscr.addstr(height - 2, 0, indent + "▲/▼=Navigate Hosts List | ENTER=View Events | N/P=VM Page | ESC=Go back | Q=Quit")
        stdscr.addstr(height - 1, 0, indent + " ")
    except curses.error:
        pass

    stdscr.noutrefresh()

def show_networks(stdscr, connection):
    # 색상 초기화 및 curses 설정
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.curs_set(0)

    system_service = connection.system_service()
    networks_service = system_service.networks_service()
    vms_service = system_service.vms_service()
    clusters_service = system_service.clusters_service()
    data_centers_service = system_service.data_centers_service()
    hosts_service = system_service.hosts_service()
    vnic_profiles_service = system_service.vnic_profiles_service()

    # 미리 조회: 클러스터, 데이터 센터, 호스트, vNIC 프로파일 정보
    clusters = {cluster.id: cluster.name for cluster in clusters_service.list()}
    data_centers = {dc.id: dc.name for dc in data_centers_service.list()}
    hosts = {host.id: host.name for host in hosts_service.list()}
    vnic_profiles = {profile.id: profile for profile in vnic_profiles_service.list()}

    # 네트워크 목록 조회
    networks = networks_service.list()

    # *** 최적화된 VM 정보 조회 (모든 VM을 한 번만 조회) ***
    all_vms = vms_service.list()
    # 네트워크 ID별로 해당하는 VM 정보를 저장할 딕셔너리 (중복 VM은 vm.id 기준으로 집계)
    vm_mapping = {}  # { network_id: { vm_id: vm_detail_dict, ... }, ... }
    for vm in all_vms:
        try:
            vm_service = vms_service.vm_service(vm.id)
            nics = vm_service.nics_service().list()
            for nic in nics:
                if not nic.vnic_profile:
                    continue
                vnic_profile_id = nic.vnic_profile.id
                if vnic_profile_id not in vnic_profiles:
                    continue
                vnic_profile = vnic_profiles[vnic_profile_id]
                # 해당 NIC가 소속된 네트워크 ID가 있는 경우
                if not (vnic_profile.network and getattr(vnic_profile.network, "id", None)):
                    continue
                net_id = vnic_profile.network.id
                # NIC에 해당하는 VM의 상세정보 구성 (IP 조회 등)
                try:
                    reported_devices = vm_service.reported_devices_service().list()
                    ip_addresses = []
                    for device in reported_devices:
                        if device.ips:
                            for ip in device.ips:
                                if ip.version == types.IpVersion.V4:
                                    ip_addresses.append(ip.address)
                    ip_address = ", ".join(ip_addresses) if ip_addresses else "-"
                except Exception:
                    ip_address = "-"

                cluster_name = clusters.get(vm.cluster.id, "-") if vm.cluster else "-"
                host_name = hosts.get(vm.host.id, "-") if (vm.status == types.VmStatus.UP and vm.host) else "-"
                vnic_status = "Up" if vm.status == types.VmStatus.UP else "Down"
                vnic_name = nic.name if nic.name else "-"

                # vm_mapping에 추가 (동일 VM이 여러 NIC를 가진 경우 vnic 정보는 ','로 연결)
                if net_id not in vm_mapping:
                    vm_mapping[net_id] = {}
                if vm.id not in vm_mapping[net_id]:
                    vm_mapping[net_id][vm.id] = {
                        "vm_name": vm.name or "-",
                        "cluster": cluster_name,
                        "ip": ip_address,
                        "host_name": host_name,
                        "vnic_status": vnic_status,
                        "vnic": vnic_name,
                        "id": vm.id
                    }
                else:
                    existing = vm_mapping[net_id][vm.id]["vnic"]
                    if vnic_name not in existing.split(","):
                        vm_mapping[net_id][vm.id]["vnic"] = existing + "," + vnic_name
        except Exception:
            pass

    # 네트워크별 정보 구성 (각 네트워크에 해당하는 VM 정보는 vm_mapping에서 가져옴)
    network_info = []
    for net in networks:
        data_center_name = data_centers.get(net.data_center.id, "-") if net.data_center else "-"
        aggregated_vms = list(vm_mapping.get(net.id, {}).values())
        network_info.append({
            "id": net.id,
            "name": net.name or "-",
            "data_center": data_center_name,
            "description": net.description or "-",
            "role": net.usages[0] if net.usages else "-",
            "vlan_tag": net.vlan.id if net.vlan else "-",
            "mtu": net.mtu if net.mtu and net.mtu > 0 else 1500,
            "port_isolation": getattr(net, "port_isolation", False),
            "vms": aggregated_vms
        })

    # draw_screen()과 네비게이션 부분
    selected_network_idx = 0
    vm_page = 1
    MAX_VM_ROWS = 5

    while True:
        current_vm_list = network_info[selected_network_idx].get("vms", [])
        max_vm_page = max(1, math.ceil(len(current_vm_list) / MAX_VM_ROWS))
        if vm_page > max_vm_page:
            vm_page = max_vm_page

        draw_screen(stdscr, network_info, selected_network_idx, vm_page, MAX_VM_ROWS, vnic_profiles)
        curses.doupdate()
        key = stdscr.getch()
        if key == 27:
            break
        elif key in (ord('q'), ord('Q')):
            exit(0)
        elif key == curses.KEY_UP:
            selected_network_idx = (selected_network_idx - 1) % len(network_info)
            vm_page = 1
        elif key == curses.KEY_DOWN:
            selected_network_idx = (selected_network_idx + 1) % len(network_info)
            vm_page = 1
        elif key in (ord('n'), ord('N')):
            if vm_page < max_vm_page:
                vm_page += 1
        elif key in (ord('p'), ord('P')):
            if vm_page > 1:
                vm_page -= 1
        elif key in (10, 13):  # ENTER 키
            show_event_page(stdscr, connection, network_info[selected_network_idx])
        else:
            time.sleep(0.05)

# =============================================================================
# Section 9: Storage Domains Section
# =============================================================================

def format_status_from_data_center(data_centers_service, domain):
    """Data Center 정보를 기반으로 Cross Data Center Status를 결정"""
    # 모든 데이터 센터 목록을 조회.
    data_centers = data_centers_service.list()
    for data_center in data_centers:
        # 각 데이터 센터에 해당하는 서비스 인스턴스를 얻음.
        data_center_service = data_centers_service.data_center_service(data_center.id)
        # 현재 데이터 센터의 스토리지 도메인 목록을 조회.
        storage_domains = data_center_service.storage_domains_service().list()
        for storage_domain in storage_domains:
            # 입력받은 domain과 같은 id를 가진 스토리지 도메인을 찾으면...
            if storage_domain.id == domain.id:
                # 스토리지 도메인이 'unattached' 상태이면 "-"를 반환.
                if storage_domain.status == "unattached" or getattr(domain, "external_status", "") == "unattached":
                    return "-"
                # 그 외에는 상태를 문자열로 변환하여 첫 글자만 대문자로 반환.
                return str(storage_domain.status).capitalize()
    # domain 객체의 추가 속성에 따라 상태를 "-"로 간주.
    if getattr(domain, "external_status", "") == "unattached" or getattr(domain, "master", True) is False:
        return "-"
    return "-"

def format_gb(size_in_bytes):
    """바이트를 GB로 변환하여 반환"""
    # size_in_bytes 값이 있을 경우 GB 단위로 변환하여 소수점 둘째 자리까지 반올림,
    # 값이 없으면 "-" 문자열을 반환.
    return round(size_in_bytes / (1024 ** 3), 2) if size_in_bytes else "-"

def format_date(date_obj):
    """datetime 객체를 문자열로 변환"""
    # datetime 객체가 존재하면 지정된 포맷으로 문자열화하고, 없으면 "-" 반환
    if date_obj:
        return date_obj.strftime("%Y-%m-%d %H:%M:%S")
    return "-"

def fetch_storage_domains_data(connection):
    """
    기존 연결(connection)을 이용하여 스토리지 도메인, 디스크, 그리고 VM 정보를
    한 번씩 조회한 후, 각 디스크에 연결된 VM 정보를 매핑하여 속도를 개선.
    """
    # 시스템 서비스에서 스토리지 도메인, 데이터 센터, 디스크, 그리고 VM 서비스를 가져옴.
    system_service = connection.system_service()
    storage_domains_service = system_service.storage_domains_service()
    data_centers_service = system_service.data_centers_service()

    # 스토리지 도메인과 데이터 센터 목록 조회
    storage_domains = storage_domains_service.list()
    # 데이터 센터 ID를 키로 하고, 이름을 값으로 하는 딕셔너리를 생성.
    data_centers = {dc.id: dc.name for dc in data_centers_service.list()}

    storage_info = {}
    for domain in storage_domains:
        # 각 스토리지 도메인에 연결된 데이터 센터 이름을 초기값 "-"로 설정.
        data_center_name = "-"
        # 도메인에 _data_centers 속성이 존재하고 값이 있다면 첫 번째 데이터 센터의 이름을 사용.
        if hasattr(domain, "_data_centers") and domain._data_centers:
            first_data_center = domain._data_centers[0]
            data_center_id = first_data_center.id
            data_center_name = data_centers.get(data_center_id, "-")

        # 데이터 센터의 스토리지 도메인 상태를 결정.
        cross_data_center_status = format_status_from_data_center(data_centers_service, domain)
        # 사용 가능한 공간과 사용 중인 공간을 가져와 총 공간을 계산.
        available_space = getattr(domain, 'available', 0) or 0
        used_space = getattr(domain, 'used', 0) or 0
        total_space = available_space + used_space

        # 각 스토리지 도메인에 대한 상세 정보를 딕셔너리에 저장.
        storage_info[domain.name] = {
            'id': domain.id,
            'type': domain.type,
            'storage_type': getattr(domain.storage, 'type', '-') if getattr(domain, 'storage', None) else '-',
            'cross_data_center_status': cross_data_center_status,
            'data_center': data_center_name,
            'total_space': format_gb(total_space),
            'free_space': format_gb(available_space),
            'properties': vars(domain),
            'disks': []  # 이후 디스크 정보를 채워 넣기 위한 빈 리스트
        }

    # --- VM, 디스크, 연결 정보를 한 번만 조회하도록 변경 --- #
    # 디스크와 VM 서비스를 통해 모든 디스크와 VM 목록을 조회.
    disks_service = system_service.disks_service()
    vms_service = system_service.vms_service()
    disks = disks_service.list()
    vms = vms_service.list()

    # 각 VM의 디스크 연결 정보를 조회하여, disk id를 키로 하고 연결된 VM 리스트를 값으로 하는 매핑을 생성.
    disk_to_vms = {}
    vm_creation_dates = {}
    vm_templates = {}
    for vm in vms:
        # 각 VM의 생성일과 템플릿 정보를 저장.
        vm_creation_dates[vm.id] = format_date(vm.creation_time) if hasattr(vm, 'creation_time') else "-"
        vm_templates[vm.id] = vm.original_template.name if getattr(vm, 'original_template', None) else "-"
        # 개별 VM 서비스 인스턴스를 가져와 디스크 첨부 정보를 조회.
        vm_service = vms_service.vm_service(vm.id)
        attachments = vm_service.disk_attachments_service().list()
        for attachment in attachments:
            disk_id = attachment.disk.id
            if disk_id not in disk_to_vms:
                disk_to_vms[disk_id] = []
            disk_to_vms[disk_id].append(vm)

    # 조회된 디스크별로 매핑된 VM 정보를 스토리지 도메인 정보에 추가.
    for disk in disks:
        # 현재 디스크에 연결된 VM 목록을 가져옴.
        attached_vms = disk_to_vms.get(disk.id, [])
        # 디스크가 속한 각 스토리지 도메인을 찾아 해당 도메인의 디스크 리스트에 추가.
        for sd in disk.storage_domains:
            domain_name = next((name for name, info in storage_info.items() if info['id'] == sd.id), None)
            if domain_name:
                storage_info[domain_name]['disks'].append({
                    'vm_name': ', '.join(vm.name for vm in attached_vms if vm.name) if attached_vms else "-",
                    'disk_name': disk.name if disk.name else "-",
                    'disk_size_gb': format_gb(getattr(disk, 'provisioned_size', None)),
                    'actual_size_gb': format_gb(getattr(disk, 'actual_size', None)),
                    'creation_date': ', '.join(vm_creation_dates.get(vm.id, "-") for vm in attached_vms) if attached_vms else "-",
                    'template': ', '.join(vm_templates.get(vm.id) or "-" for vm in attached_vms) if attached_vms else "-",
                    'allocation_policy': "Thin" if disk.sparse else "Preallocated",
                    'status': str(disk.status) if disk.status else "-",
                    'type': str(getattr(disk, 'storage_type', '-'))
                })

    return storage_info

def fetch_data_centers_status(connection):
    """
    각 데이터 센터의 스토리지 도메인 상태를 조회하여,
    데이터 센터 이름과 상태를 dict로 반환.
    (전체 목록 대신, 추후 선택한 스토리지 도메인의 data_center를 참조하여 사용)
    """
    # 시스템 서비스에서 데이터 센터 관련 서비스를 가져옴.
    system_service = connection.system_service()
    data_centers_service = system_service.data_centers_service()
    data_center_status = {}
    # 모든 데이터 센터에 대해 반복하며 각 도메인의 상태를 조회.
    for dc in data_centers_service.list():
        dc_service = data_centers_service.data_center_service(dc.id)
        domains = dc_service.storage_domains_service().list()
        # 각 스토리지 도메인의 상태를 대문자로 변환한 리스트를 생성.
        statuses = [str(domain.status).capitalize() for domain in domains if domain.status]
        if statuses:
            # 하나라도 "Active" 상태가 있으면 데이터 센터 상태를 "Active"로 간주.
            if "Active" in statuses:
                dc_status = "Active"
            else:
                dc_status = statuses[0]
        else:
            dc_status = "-"
        data_center_status[dc.name] = dc_status
    return data_center_status

def draw_storage_domain_list(stdscr, storage_domains, current_idx, storage_info, start_y):
    stdscr.addstr(start_y, 1, "- Storage Domain List")  # 스토리지 도메인 목록 제목 출력
    table_start = start_y + 1
    # 테이블 헤더와 각 열의 너비를 정의.
    headers = ["Domain Name", "Domain Type", "Storage Type", "Cross Data Center Status", 
               "Total Space(GB)", "Free Space(GB)", "Data Center"]
    widths = [24, 12, 12, 25, 15, 15, 12]
    # 테이블의 상단, 구분선, 하단 경계선을 생성.
    header_line = "┌" + "┬".join("─" * w for w in widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in widths) + "┘"
    stdscr.addstr(table_start, 1, header_line, curses.color_pair(2))
    stdscr.addstr(table_start + 1, 1,
                  "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(headers, widths)) + "│", curses.color_pair(2))
    stdscr.addstr(table_start + 2, 1, divider_line, curses.color_pair(2))
    # 스토리지 도메인 리스트의 각 항목을 순서대로 출력.
    for idx, domain in enumerate(storage_domains):
        info = storage_info[domain]
        row = [
            truncate_with_ellipsis(domain, widths[0]),
            truncate_with_ellipsis(str(info['type']), widths[1]),
            truncate_with_ellipsis(str(info['storage_type']), widths[2]),
            truncate_with_ellipsis(info['cross_data_center_status'], widths[3]),
            truncate_with_ellipsis(str(info['total_space']), widths[4]),
            truncate_with_ellipsis(str(info['free_space']), widths[5]),
            truncate_with_ellipsis(info['data_center'], widths[6])
        ]
        row_text = "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, widths)) + "│"
        # 현재 선택된 항목은 색상을 달리하여 하이라이트함.
        if idx == current_idx:
            stdscr.addstr(table_start + 3 + idx, 1, row_text, curses.color_pair(1))
        else:
            stdscr.addstr(table_start + 3 + idx, 1, row_text, curses.color_pair(2))
    last_row = table_start + 3 + len(storage_domains)
    stdscr.addstr(last_row, 1, footer_line, curses.color_pair(2))
    return last_row + 1  # 다음 출력 위치(y 좌표)를 반환

def draw_selected_data_center_table(stdscr, selected_domain, storage_info, data_centers_status, start_y):
    """
    - 선택한 스토리지 도메인이 속한 데이터 센터의 정보를 표시하는 테이블.
    """
    # 제목 출력
    stdscr.addstr(start_y, 0, " " + "- Data Center (for selected Storage Domain)")
    table_start = start_y + 1

    # 헤더 및 열 너비 설정
    headers = ["Name", "Domain status in Data Center"]
    widths = [24, 96]  # 열 너비를 [24, 96]으로 지정
    header_line = "┌" + "┬".join("─" * w for w in widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in widths) + "┘"

    # 테이블 상단 경계선과 헤더 행을 출력.
    stdscr.addstr(table_start, 0, " " + header_line)
    stdscr.addstr(table_start + 1, 0, " " + "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(headers, widths)) + "│")
    stdscr.addstr(table_start + 2, 0, " " + divider_line)
    
    # 선택된 스토리지 도메인에 연결된 데이터 센터 이름과 상태를 가져와 한 행으로 출력.
    dc_name = storage_info[selected_domain].get("data_center", "-")
    dc_status = data_centers_status.get(dc_name, "-")
    data_row = "│" + "│".join([
        f"{truncate_with_ellipsis(dc_name, widths[0]):<{widths[0]}}",
        f"{truncate_with_ellipsis(dc_status, widths[1]):<{widths[1]}}"
    ]) + "│"
    stdscr.addstr(table_start + 3, 0, " " + data_row)
    
    stdscr.addstr(table_start + 4, 0, " " + footer_line)
    return table_start + 5  # 다음 출력 위치 반환

def draw_virtual_machines_table(stdscr, selected_domain, storage_info, vm_page, vm_page_size, start_y):
    """
    - Virtual Machines (디스크) 테이블을 페이지 단위로 그림.
    """
    # 선택된 스토리지 도메인에 속한 디스크 리스트를 가져옴.
    disks = storage_info[selected_domain]["disks"]
    total_disks = len(disks)
    # 총 페이지 수를 계산 (최소 1페이지)
    total_pages = max(1, (total_disks + vm_page_size - 1) // vm_page_size)
    if vm_page >= total_pages:
        vm_page = total_pages - 1
    header_text = f"- Virtual Machines ({vm_page+1}/{total_pages})"
    stdscr.addstr(start_y, 0, " " + header_text)
    table_start = start_y + 1
    # 디스크 정보를 출력할 테이블 헤더와 열 너비를 설정함.
    detail_headers = ["Virtual Machines", "Disk", "Size(GB)", "Actual Size(GB)", "Creation Date", "Template"]
    detail_widths = [24, 37, 8, 15, 20, 12]
    header_line = "┌" + "┬".join("─" * w for w in detail_widths) + "┐"
    divider_line = "├" + "┼".join("─" * w for w in detail_widths) + "┤"
    footer_line = "└" + "┴".join("─" * w for w in detail_widths) + "┘"
    stdscr.addstr(table_start, 0, " " + header_line)
    stdscr.addstr(table_start + 1, 0,
                  " " + "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" for h, w in zip(detail_headers, detail_widths)) + "│")
    stdscr.addstr(table_start + 2, 0, " " + divider_line)
    # 현재 페이지에 해당하는 디스크 목록의 시작과 끝 인덱스를 계산함.
    start_index = vm_page * vm_page_size
    end_index = start_index + vm_page_size
    page_disks = disks[start_index:end_index]
    row_y = table_start + 3

    if page_disks:
        # 각 디스크 정보를 테이블의 한 행으로 출력함.
        for disk in page_disks:
            row = [
                truncate_with_ellipsis(disk.get("vm_name", "-"), detail_widths[0]),
                truncate_with_ellipsis(disk.get("disk_name", "-"), detail_widths[1]),
                truncate_with_ellipsis(str(disk.get("disk_size_gb", "-")), detail_widths[2]),
                truncate_with_ellipsis(str(disk.get("actual_size_gb", "-")), detail_widths[3]),
                truncate_with_ellipsis(disk.get("creation_date", "-"), detail_widths[4]),
                truncate_with_ellipsis(disk.get("template", "-"), detail_widths[5])
            ]
            row_text = "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, detail_widths)) + "│"
            stdscr.addstr(row_y, 0, " " + row_text)
            row_y += 1
    else:
        # 데이터가 없을 경우 각 열에 "-"만 출력하도록 처리함.
        empty_row = "│" + "│".join(f"{'-':<{w}}" for w in detail_widths) + "│"
        stdscr.addstr(row_y, 0, " " + empty_row)
        row_y += 1

    stdscr.addstr(row_y, 0, " " + footer_line)
    row_y += 1
    stdscr.addstr(row_y, 0, " " + "N=Next | P=Prev")
    return row_y + 1  # 다음 출력 위치 반환

def show_storage_domain_details(stdscr, domain_name, domain_info):
    """
    세부 디스크 정보를 페이징 처리하여 출력.
    - 헤더에 "- Details for <domain_name> (Page X/Y)"를 표시하고,
    - 테이블은 제목행을 제외하고 페이지 당 최대 40행의 디스크 정보를 보여줌.
      (해당 페이지에 출력할 데이터 행이 40개 미만이면, 실제 데이터 행만 출력하며,
       데이터가 하나도 없으면 각 셀에 단일 "-"만 보이게 함.)
    - 테이블 하단에는 "N=Next | P=Prev" 문구를, 터미널 맨 아래에는 "ESC=Go back | Q=Quit" 문구를 표시.
    """
    curses.curs_set(0)
    page = 0
    page_size = 40  # 한 페이지에 표시할 디스크 정보 행 수
    disks = domain_info.get("disks", [])
    total_disks = len(disks)
    total_pages = max(1, (total_disks + page_size - 1) // page_size)
    
    while True:
        stdscr.erase()
        # 헤더를 출력 (현재 페이지 정보 포함)
        header_text = f"- Details for {domain_name} (Page {page+1}/{total_pages})"
        stdscr.addstr(1, 0, " " + header_text)
        stdscr.clrtoeol()

        # 테이블 헤더와 각 열의 너비를 설정함.
        detail_headers = ["Disk Name", "Virtual Size(GB)", "Actual Size(GB)", "Allocation Policy", "Storage Domain", "Status", "Type"]
        detail_widths = [32, 16, 15, 17, 17, 9, 9]
        header_line = "┌" + "┬".join("─" * w for w in detail_widths) + "┐"
        divider_line = "├" + "┼".join("─" * w for w in detail_widths) + "┤"
        footer_line = "└" + "┴".join("─" * w for w in detail_widths) + "┘"
        
        # 테이블 상단 경계선과 헤더 행을 출력함.
        stdscr.addstr(2, 0, " " + header_line)
        stdscr.clrtoeol()
        stdscr.addstr(3, 0, " " + "│" + "│".join(f"{truncate_with_ellipsis(h, w):<{w}}" 
                                                 for h, w in zip(detail_headers, detail_widths)) + "│")
        stdscr.clrtoeol()
        stdscr.addstr(4, 0, " " + divider_line)
        stdscr.clrtoeol()
        
        # 현재 페이지에 해당하는 디스크 정보의 시작과 끝 인덱스를 계산함.
        start_index = page * page_size
        end_index = start_index + page_size
        page_disks = disks[start_index:end_index]
        y = 5
        if page_disks:
            # 각 디스크의 정보를 테이블의 한 행으로 출력함.
            for disk in page_disks:
                row = [
                    truncate_with_ellipsis(disk.get("disk_name", "-"), detail_widths[0]),
                    truncate_with_ellipsis(str(disk.get("disk_size_gb", "-")), detail_widths[1]),
                    truncate_with_ellipsis(str(disk.get("actual_size_gb", "-")), detail_widths[2]),
                    truncate_with_ellipsis(disk.get("allocation_policy", "-"), detail_widths[3]),
                    truncate_with_ellipsis(domain_name, detail_widths[4]),
                    truncate_with_ellipsis(str(disk.get("status", "-")), detail_widths[5]),
                    truncate_with_ellipsis(str(disk.get("type", "-")), detail_widths[6])
                ]
                row_text = "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, detail_widths)) + "│"
                stdscr.addstr(y, 0, " " + row_text)
                stdscr.clrtoeol()
                y += 1
        else:
            # 데이터가 없으면 각 셀에 "-"만 출력함.
            empty_row = "│" + "│".join(f"{'-':<{w}}" for w in detail_widths) + "│"
            stdscr.addstr(y, 0, " " + empty_row)
            stdscr.clrtoeol()
            y += 1

        stdscr.addstr(y, 0, " " + footer_line)
        stdscr.clrtoeol()
        y += 1
        stdscr.addstr(y, 0, " " + "N=Next | P=Prev")
        stdscr.clrtoeol()
        y += 1
        
        # 남은 터미널 영역을 공백으로 채우고, 하단에 제어 문구를 출력함.
        height, width = stdscr.getmaxyx()
        for line in range(y, height - 1):
            stdscr.addstr(line, 0, " " * width)
        stdscr.addstr(height - 2, 0, " " + "ESC=Go back | Q=Quit")
        stdscr.clrtoeol()
        stdscr.noutrefresh()
        curses.doupdate()
        
        # 사용자 입력에 따라 페이지 이동 또는 상세보기 종료를 처리함.
        key = stdscr.getch()
        if key in (ord('n'), ord('N')):
            page = (page + 1) % total_pages
        elif key in (ord('p'), ord('P')):
            page = (page - 1) % total_pages
        elif key in (27, ord('q'), ord('Q')):
            break

def main_loop(stdscr, storage_domains, storage_info, data_centers_status):
    # 컬러 모드를 초기화하고, 색상 쌍을 설정함.
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)

    curses.curs_set(0)  # 커서를 숨깁.
    vm_page = 0
    vm_page_size = 10  # VM 테이블에 한 페이지당 표시할 행 수
    current_idx = 0  # 현재 선택된 스토리지 도메인의 인덱스
    while True:
        stdscr.erase()
        y = 1
        # 메인 제목을 출력함.
        stdscr.addstr(y, 1, "Storage Domains", curses.color_pair(2) | curses.A_BOLD)
        y += 2
        # 스토리지 도메인 목록 테이블을 출력함.
        y = draw_storage_domain_list(stdscr, storage_domains, current_idx, storage_info, y)
        y += 1
        # 현재 선택된 스토리지 도메인을 가져와 해당 데이터 센터 정보를 출력함.
        selected_domain = storage_domains[current_idx]
        y = draw_selected_data_center_table(stdscr, selected_domain, storage_info, data_centers_status, y)
        y += 1
        # 선택된 도메인에 속한 VM(디스크) 정보를 페이지 단위로 출력함.
        y = draw_virtual_machines_table(stdscr, selected_domain, storage_info, vm_page, vm_page_size, y)
        y += 1
        height, width = stdscr.getmaxyx()
        nav_text = "▲/▼=Navigate | Enter=View Disks Details | ESC=Go back | Q=Quit"
        stdscr.addstr(height - 2, 1, nav_text, curses.color_pair(2))
        stdscr.noutrefresh()
        curses.doupdate()
        # 사용자 입력에 따라 메뉴 내 항목 선택, 페이지 이동, 상세보기 진입 등을 처리함.
        key = stdscr.getch()
        if key == curses.KEY_UP:
            current_idx = (current_idx - 1) % len(storage_domains)
            vm_page = 0
        elif key == curses.KEY_DOWN:
            current_idx = (current_idx + 1) % len(storage_domains)
            vm_page = 0
        elif key in (ord('n'), ord('N')):
            disks = storage_info[storage_domains[current_idx]]["disks"]
            total_pages_vm = max(1, (len(disks) + vm_page_size - 1) // vm_page_size)
            vm_page = (vm_page + 1) % total_pages_vm
        elif key in (ord('p'), ord('P')):
            disks = storage_info[storage_domains[current_idx]]["disks"]
            total_pages_vm = max(1, (len(disks) + vm_page_size - 1) // vm_page_size)
            vm_page = (vm_page - 1) % total_pages_vm
        elif key in (ord('\n'), 10, 13):
            # Enter 키를 누르면 선택된 스토리지 도메인의 상세 디스크 정보를 보여줌.
            domain_name = storage_domains[current_idx]
            show_storage_domain_details(stdscr, domain_name, storage_info[domain_name])
        elif key in (27,):
            break
        elif key in (ord('q'), ord('Q')):
            sys.exit(0)

def show_storage_domains(stdscr, connection):
    """
    메인 메뉴에서 'Storage Domains' 선택 시 실행되는 화면 함수.
    - oVirt API를 통해 스토리지 도메인, 디스크, VM 정보를 조회하고,
    - 각 스토리지 도메인의 정보와 함께, 선택한 도메인이 속한 Data Center의 정보를 별도 테이블로 출력.
    - 마지막에 main_loop()를 호출하여 키 입력에 따라 화면 전환 및 상세보기 기능을 제공.
    """
    # API를 통해 스토리지 도메인 관련 데이터들을 가져옴.
    storage_info = fetch_storage_domains_data(connection)
    storage_domains = list(storage_info.keys())
    if not storage_domains:
        stdscr.clear()
        stdscr.addstr(0, 0, " " + "No storage domains found. Press any key to go back.")
        stdscr.getch()
        return
    # 데이터 센터의 상태 정보를 조회함.
    data_centers_status = fetch_data_centers_status(connection)
    # 메인 루프에 진입하여 사용자와 상호작용.
    main_loop(stdscr, storage_domains, storage_info, data_centers_status)

# =============================================================================
# Section 10: Storage Disks Section
# =============================================================================

def show_storage_disks(stdscr, connection):
    """
    Storage Disks 화면 – 디스크 목록을 표 형태로 보여줌
    
    """
    # curses 기본 설정
    curses.curs_set(0)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)

    # -------------------------------------------------------------------------
    # 내부 헬퍼 함수: draw_table
    # -------------------------------------------------------------------------
    def draw_table(stdscr, disks, current_idx, page, total_pages, sort_key, reverse_sort):
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        # 상단 헤더 출력
        stdscr.addstr(1, 1, "Disk", curses.A_BOLD)
        stdscr.addstr(3, 1, "- Disk List")

        # 테이블 시작 행 지정
        table_start_row = 4

        # 수정된 열 너비 설정: [51, 13, 27, 26]
        column_widths = [51, 13, 27, 26]
        horizontal_line = "─"
        vertical_line = "│"
        corner_tl = "┌"
        corner_tr = "┐"
        corner_bl = "└"
        corner_br = "┘"
        cross = "┼"
        t_top = "┬"
        t_bottom = "┴"
        t_left = "├"
        t_right = "┤"

        # 테이블 상단 테두리
        header_line = corner_tl + t_top.join([horizontal_line * w for w in column_widths]) + corner_tr
        stdscr.addstr(table_start_row, 1, header_line)

        # 헤더 제목 행 (각 열의 제목 및 지정된 너비로 출력)
        stdscr.addstr(table_start_row + 1, 1,
                      f"{vertical_line}{'Disk Name':<51}{vertical_line}{'Size (GB)':<13}{vertical_line}{'Storage Domain':<27}{vertical_line}{'VM Name':<26}{vertical_line}")

        # 헤더 구분선
        header_divider = t_left + cross.join([horizontal_line * w for w in column_widths]) + t_right
        stdscr.addstr(table_start_row + 2, 1, header_divider)

        # 데이터 영역 시작 행
        data_start_row = table_start_row + 3
        max_disks_per_page = 27
        start_index = page * max_disks_per_page

        # 디스크 정렬: 'size'는 숫자 비교, 그 외는 문자열 비교
        sorted_disks = sorted(disks,
                              key=lambda d: (float(d.get(sort_key, 0)) if sort_key == 'size' else d.get(sort_key, "")),
                              reverse=reverse_sort)
        current_disks = sorted_disks[start_index:start_index + max_disks_per_page]

        # 각 디스크 데이터 행 출력
        for i, disk in enumerate(current_disks):
            disk_name = (disk['name'] or "N/A")[:51]
            disk_size = (str(disk['size']) or "N/A")[:13]
            storage_domain = (disk['storage_domain'] or "N/A")[:27]
            vm_name = (disk['vm_name'] or "N/A")[:26]
            row_str = (f"{vertical_line}{disk_name:<51}{vertical_line}"
                       f"{disk_size:<13}{vertical_line}"
                       f"{storage_domain:<27}{vertical_line}"
                       f"{vm_name:<26}{vertical_line}")
            if i == current_idx:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(data_start_row + i, 1, row_str)
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(data_start_row + i, 1, row_str)

        # 테이블 하단 테두리
        table_bottom_row = data_start_row + len(current_disks)
        bottom_border = corner_bl + t_bottom.join([horizontal_line * w for w in column_widths]) + corner_br
        stdscr.addstr(table_bottom_row, 1, bottom_border)

        # 터미널 맨 아래에 도움말 문구 출력
        help_text = "ESC=Go back | Q=Quit"
        stdscr.addstr(height - 1, 1, help_text)

        stdscr.noutrefresh()
        curses.doupdate()
        return sorted_disks, current_disks

    # -------------------------------------------------------------------------
    # 내부 헬퍼 함수: draw_disk_details
    # -------------------------------------------------------------------------
    def draw_disk_details(stdscr, disk):
        stdscr.clear()
        stdscr.nodelay(False)  # 블로킹 모드로 전환 (키 입력 대기)
        height, width = stdscr.getmaxyx()
    
        # 상단 헤더 출력 (굵은 글씨 속성 제거)
        stdscr.addstr(1, 1, "- Disk Details")
    
        # 테이블 출력 시작 행 지정 (바로 아래, 즉 row 2부터 시작)
        table_start_row = 2
    
        # 테이블에 사용할 고정 열 너비 및 문양 정의
        column_widths = [46, 79]
        horizontal_line = "─"
        vertical_line = "│"
        corner_tl = "┌"
        corner_tr = "┐"
        corner_bl = "└"
        corner_br = "┘"
        cross = "┼"
        t_top = "┬"
        t_bottom = "┴"
        t_left = "├"
        t_right = "┤"
    
        # 테이블 상단 테두리
        header_line = corner_tl + t_top.join([horizontal_line * w for w in column_widths]) + corner_tr
        stdscr.addstr(table_start_row, 1, header_line)
    
        # 헤더 제목 행
        header_row = table_start_row + 1
        stdscr.addstr(header_row, 1,
                      f"{vertical_line}{'Field':<46}{vertical_line}{'Value':<79}{vertical_line}")
    
        # 헤더 구분선
        divider_row = table_start_row + 2
        stdscr.addstr(divider_row, 1, t_left + cross.join([horizontal_line * w for w in column_widths]) + t_right)
    
        # 디스크 상세 정보 (필드, 값) 출력
        details = [
            ("Name", disk['name']),
            ("Size (GB)", disk['size']),
            ("Storage Domain", disk['storage_domain']),
            ("VM Name", disk['vm_name']),
            ("Content Type", disk['content_type']),
            ("ID", disk['id']),
            ("Alias", disk.get('alias', 'N/A')),
            ("Description", disk.get('description', 'N/A')),
            ("Disk Profile", str(disk.get('disk_profile', 'N/A'))),
            ("Wipe After Delete", disk.get('wipe_after_delete', 'N/A')),
            ("Virtual Size (GB)", disk.get('virtual_size', 'N/A')),
            ("Actual Size (GB)", disk.get('actual_size', 'N/A')),
            ("Allocation Policy", disk.get('allocation_policy', 'N/A'))
        ]
    
        for i, (field, value) in enumerate(details):
            stdscr.addstr(divider_row + 1 + i, 1,
                          f"{vertical_line}{field:<46}{vertical_line}{str(value):<79}{vertical_line}")
    
        # 테이블 하단 테두리 출력
        table_bottom_row = divider_row + 1 + len(details)
        bottom_border = corner_bl + t_bottom.join([horizontal_line * w for w in column_widths]) + corner_br
        stdscr.addstr(table_bottom_row, 1, bottom_border)
    
        # 터미널 하단에 도움말 문구 출력 (마지막 행)
        help_text = "ESC=Go back | Q=Quit"
        stdscr.addstr(height - 1, 1, help_text)
    
        stdscr.refresh()
    
        # ESC(27) 또는 'q' 키가 눌릴 때까지 대기
        while True:
            key = stdscr.getch()
            if key in (27, ord('q')):
                break
    
    # -------------------------------------------------------------------------
    # 내부 헬퍼 함수: fetch_disk_data
    # -------------------------------------------------------------------------
    def fetch_disk_data(connection):
        disks_service = connection.system_service().disks_service()
        vms_service = connection.system_service().vms_service()
        storage_domains_service = connection.system_service().storage_domains_service()

        disks = disks_service.list()
        data = []

        # VM 정보 캐싱 (디스크가 첨부된 VM 이름)
        vm_disk_map = {}
        for vm in vms_service.list():
            vm_name = vm.name
            try:
                attachments = vms_service.vm_service(vm.id).disk_attachments_service().list()
            except Exception:
                attachments = []
            for attachment in attachments:
                vm_disk_map[attachment.disk.id] = vm_name

        for disk in disks:
            # OVF_STORE 디스크는 제외
            if disk.name == "OVF_STORE":
                continue

            disk_name = disk.name
            disk_size = round(disk.provisioned_size / (1024 ** 3), 2)  # GB 단위 변환
            storage_domain_name = "N/A"
            vm_name = vm_disk_map.get(disk.id, "N/A")

            # 스토리지 도메인 이름 조회
            if disk.storage_domains:
                storage_domain_id = disk.storage_domains[0].id
                try:
                    storage_domain = storage_domains_service.storage_domain_service(storage_domain_id).get()
                    storage_domain_name = storage_domain.name
                except Exception:
                    storage_domain_name = "N/A"

            # 디스크 유형 결정
            content_type = "data"  # 기본값
            if disk.content_type:
                content_type = str(disk.content_type)
            elif disk.bootable:
                content_type = "boot"
            elif disk.shareable:
                content_type = "shared"
            elif disk.format == "raw" and disk.wipe_after_delete:
                content_type = "iso"

            # 디스크 할당 정책
            allocation_policy = "thin" if getattr(disk, 'thin_provisioning', False) else "thick"

            data.append({
                'name': disk_name,
                'size': disk_size,
                'storage_domain': storage_domain_name,
                'vm_name': vm_name,
                'content_type': content_type,
                'id': disk.id,
                'alias': getattr(disk, 'alias', "N/A"),
                'description': getattr(disk, 'description', "N/A"),
                'disk_profile': str(getattr(disk, 'disk_profile', "N/A")),
                'wipe_after_delete': getattr(disk, 'wipe_after_delete', False),
                'virtual_size': round(getattr(disk, 'provisioned_size', 0) / (1024 ** 3), 2),
                'actual_size': round(getattr(disk, 'actual_size', 0) / (1024 ** 3), 2),
                'allocation_policy': allocation_policy
            })

        return data

    # -------------------------------------------------------------------------
    # 메인 로직: 디스크 데이터 조회 및 키 입력 처리
    # -------------------------------------------------------------------------
    disks = fetch_disk_data(connection)
    current_idx = 0
    page = 0
    max_disks_per_page = 27
    sort_key = 'name'      # 초기 정렬 키: 이름순
    reverse_sort = False   # 초기 정렬 방향: 오름차순
    total_pages = (len(disks) + max_disks_per_page - 1) // max_disks_per_page

    while True:
        sorted_disks, current_disks = draw_table(stdscr, disks, current_idx, page, total_pages, sort_key, reverse_sort)
        num_disks = len(current_disks)
        key = stdscr.getch()

        if key in (curses.KEY_UP, 65):
            if num_disks > 0:
                current_idx = (current_idx - 1) % num_disks
        elif key in (curses.KEY_DOWN, 66):
            if num_disks > 0:
                current_idx = (current_idx + 1) % num_disks
        elif key == ord('n'):
            page = (page + 1) % total_pages
            current_idx = 0
        elif key == ord('p'):
            page = (page - 1) % total_pages
            current_idx = 0
        elif key == ord('d'):
            reverse_sort = not reverse_sort if sort_key == 'name' else False
            sort_key = 'name'
        elif key == ord('s'):
            reverse_sort = not reverse_sort if sort_key == 'size' else False
            sort_key = 'size'
        elif key == ord('t'):
            reverse_sort = not reverse_sort if sort_key == 'content_type' else False
            sort_key = 'content_type'
        elif key == ord('o'):
            reverse_sort = not reverse_sort if sort_key == 'allocation_policy' else False
            sort_key = 'allocation_policy'
        elif key == ord('v'):
            reverse_sort = not reverse_sort if sort_key == 'vm_name' else False
            sort_key = 'vm_name'
        elif key == ord('i'):
            reverse_sort = not reverse_sort if sort_key == 'storage_domain' else False
            sort_key = 'storage_domain'
        elif key == 10:  # ENTER 키: 선택한 디스크 상세 정보 표시
            if num_disks > 0:
                selected_disk = current_disks[current_idx]
                draw_disk_details(stdscr, selected_disk)
        elif key == 27 or key == ord('q'):  # ESC 또는 Q 키: 상위 메뉴로 복귀 또는 종료
            break

# =============================================================================
# Section 11: Users Section
# =============================================================================
# ---------------------------------------------------------------------------
# 유틸리티 함수
# ---------------------------------------------------------------------------
def get_display_width(text, width):
    """
    지정된 폭(width)에 맞춰 문자열을 자르거나 패딩함.
    """
    if len(text) > width:
        return text[:width]
    return text.ljust(width)

# SSH 연결 재활용(SSH Multiplexing) 옵션
CONTROL_OPTS = "-o ControlMaster=auto -o ControlPath=/tmp/ssh_mux_%r@%h:%p"

# 사용자 목록 캐싱: 동일 호스트에 대해 5초간 캐시된 결과 재사용
_USERS_CACHE = {}
_CACHE_TIMEOUT = 5  # seconds

def get_users_output(engine_host):
    """
    SSH를 이용해 사용자 목록을 가져오며, 결과를 캐싱함.
    """
    global _USERS_CACHE
    current_time = time.time()
    if engine_host in _USERS_CACHE:
        cached_time, cached_output = _USERS_CACHE[engine_host]
        if current_time - cached_time < _CACHE_TIMEOUT:
            return cached_output

    # 사용자 목록을 조회하는 SSH 명령어 (Multiplexing 옵션 포함)
    query_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} \"ovirt-aaa-jdbc-tool query --what=user\""
    result = subprocess.run(query_cmd, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=15)
    if result.returncode != 0:
        raise Exception(result.stderr.strip())
    output = result.stdout
    _USERS_CACHE[engine_host] = (current_time, output)
    return output

def clear_users_cache(engine_host):
    """
    지정된 호스트의 캐시를 제거함.
    """
    global _USERS_CACHE
    if engine_host in _USERS_CACHE:
        del _USERS_CACHE[engine_host]

def show_error_popup(stdscr, title, message):
    """
    curses 창에 에러 메시지를 팝업으로 표시함.
    """
    height, width = stdscr.getmaxyx()
    popup_height = 7
    popup_width = min(len(message) + 4, width - 4)
    popup_y = (height - popup_height) // 2
    popup_x = (width - popup_width) // 2
    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.border()
    popup.addstr(1, (popup_width - len(title)) // 2, title)
    popup.addstr(3, (popup_width - len(message)) // 2, message)
    prompt = "Press any key to continue"
    popup.addstr(popup_height - 2, (popup_width - len(prompt)) // 2, prompt)
    popup.refresh()
    popup.getch()

def show_custom_popup(stdscr, title, message):
    """
    일반 메시지 팝업을 표시하며, 메시지 텍스트를 중앙 정렬합니다.
    """
    import textwrap
    popup_height = 12
    popup_width = 60
    scr_height, scr_width = stdscr.getmaxyx()
    popup_y = (scr_height - popup_height) // 2
    popup_x = (scr_width - popup_width) // 2
    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.keypad(True)
    curses.curs_set(0)
    popup.border()
    # 제목 중앙 정렬 (굵은 글씨)
    popup.addstr(1, (popup_width - len(title)) // 2, title, curses.A_BOLD)
    # 메시지 라인들을 중앙 정렬하여 표시
    message_lines = textwrap.wrap(message, width=popup_width - 4)
    start_line = 5
    for i, line in enumerate(message_lines):
        if start_line + i >= popup_height - 2:
            break
        popup.addstr(start_line + i, (popup_width - len(line)) // 2, line)
    prompt = "Press any key to continue"
    popup.addstr(popup_height - 2, (popup_width - len(prompt)) // 2, prompt, curses.A_NORMAL)
    popup.refresh()
    popup.getch()


# ---------------------------------------------------------------------------
# 사용자 추가 및 수정 관련 함수
# ---------------------------------------------------------------------------
def add_user_popup_form(stdscr, connection, refresh_users_callback):
    """
    사용자 추가 팝업창을 표시하고, SSH와 API를 통해 새 사용자를 등록함.
    
    단계:
      1. SSH를 통해 사용자 생성 및 firstName 업데이트
      2. 비밀번호 재설정 (Interactive Password Reset)
      3. SSH를 통해 password-valid-to 값 설정
      4. API를 통해 사용자 역할 및 webAdmin 속성 업데이트
    """
    popup_height = 12
    popup_width = 60
    scr_height, scr_width = stdscr.getmaxyx()
    popup_y = (scr_height - popup_height) // 2
    popup_x = (scr_width - popup_width) // 2
    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.keypad(True)
    curses.curs_set(1)

    parsed_url = urlparse(connection.url)
    engine_host = parsed_url.hostname

    # 사용자 입력을 받을 때까지 루프
    while True:
        popup.clear()
        popup.border()
        header = "Add New User"
        popup.addstr(1, (popup_width - len(header)) // 2, header)
        # 입력 필드 표시
        popup.addstr(4, 2, "Username:")
        popup.addstr(5, 2, "Password:")
        popup.addstr(6, 2, "Re-Password:")
        instructions = "TAB or ▲/▼=Navigate | ENTER=Submit | ESC=Cancel"
        popup.addstr(10, 2, instructions)
        popup.refresh()

        # 사용자 입력 필드 (username, password, 재입력 password)
        fields = [
            {"label": "Username:", "value": "", "y": 4, "x": 2 + len("Username:") + 1, "max_len": 30, "hidden": False},
            {"label": "Password:", "value": "", "y": 5, "x": 2 + len("Password:") + 1, "max_len": 30, "hidden": True},
            {"label": "Re-Password:", "value": "", "y": 6, "x": 2 + len("Re-Password:") + 1, "max_len": 30, "hidden": True},
        ]
        current_field = 0
        popup.move(fields[0]["y"], fields[0]["x"])
        popup.refresh()

        # 필드 간 탐색 및 입력 처리
        while True:
            for idx, field in enumerate(fields):
                display_val = field["value"] if not field["hidden"] else "*" * len(field["value"])
                popup.addstr(field["y"], field["x"], " " * field["max_len"])
                popup.addstr(field["y"], field["x"], display_val)
            popup.move(fields[current_field]["y"], fields[current_field]["x"] + len(fields[current_field]["value"]))
            popup.refresh()
            ch = popup.getch()
            if ch in (9, curses.KEY_DOWN):
                current_field = (current_field + 1) % len(fields)
            elif ch == curses.KEY_UP:
                current_field = (current_field - 1) % len(fields)
            elif ch in (27,):  # ESC 키로 취소
                return
            elif ch in (curses.KEY_ENTER, 10, 13):
                # 모든 필드가 채워졌는지, 비밀번호가 일치하는지 확인
                if all(field["value"] for field in fields):
                    if fields[1]["value"] != fields[2]["value"]:
                        curses.curs_set(0)
                        popup.addstr(8, 2, "Passwords do not match!")
                        popup.refresh()
                        curses.napms(1500)
                        popup.addstr(8, 2, " " * (popup_width - 4))
                        popup.refresh()
                        curses.curs_set(1)
                        continue
                    else:
                        break
                else:
                    curses.curs_set(0)
                    popup.addstr(8, 2, "All fields are required!")
                    popup.refresh()
                    curses.napms(1500)
                    popup.addstr(8, 2, " " * (popup_width - 4))
                    popup.refresh()
                    curses.curs_set(1)
                    continue
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if fields[current_field]["value"]:
                    fields[current_field]["value"] = fields[current_field]["value"][:-1]
            elif 0 <= ch < 256:
                if len(fields[current_field]["value"]) < fields[current_field]["max_len"]:
                    fields[current_field]["value"] += chr(ch)
        username = fields[0]["value"].strip()
        new_password = fields[1]["value"]

        # SSH를 통해 해당 사용자가 이미 존재하는지 확인
        try:
            check_user_cmd = f"ovirt-aaa-jdbc-tool query --what=user | grep -w '{username}'"
            ssh_check_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} \"{check_user_cmd}\""
            check_result = subprocess.run(ssh_check_cmd, shell=True,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if check_result.returncode == 0:
                curses.curs_set(0)
                popup.addstr(8, 2, "User already exists!")
                popup.refresh()
                curses.napms(1500)
                popup.addstr(8, 2, " " * (popup_width - 4))
                popup.refresh()
                curses.curs_set(1)
                fields[0]["value"] = ""
                continue
        except Exception:
            curses.curs_set(0)
            popup.addstr(8, 2, "Error checking user!")
            popup.refresh()
            curses.napms(1500)
            popup.addstr(8, 2, " " * (popup_width - 4))
            popup.refresh()
            curses.curs_set(1)
            continue
        break

    # SSH를 통해 새 사용자 생성
    try:
        add_user_cmd = f"ovirt-aaa-jdbc-tool user add {username} >/dev/null 2>&1"
        ssh_add_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} \"{add_user_cmd}\""
        subprocess.run(ssh_add_cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        show_error_popup(stdscr, "Error", f"SSH Error during user add: {str(e)}")
        return

    # firstName 속성 업데이트
    try:
        first_name_cmd = f"ovirt-aaa-jdbc-tool user edit {username} --attribute=firstName={username}"
        ssh_firstname_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} \"{first_name_cmd}\""
        subprocess.run(ssh_firstname_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        show_error_popup(stdscr, "Error", f"Error setting firstName: {str(e)}")
        return

    # 비밀번호 재설정 (interactive 방식)
    if not set_user_password(engine_host, username, new_password, stdscr):
        show_error_popup(stdscr, "Error", "Failed to set password.")
        return

    # password-valid-to 값 설정
    try:
        edit_cmd = f'ovirt-aaa-jdbc-tool user edit {username} --password-valid-to="2125-12-31 12:00:00-0000"'
        ssh_edit_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} {shlex.quote(edit_cmd)}"
        subprocess.run(ssh_edit_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception as e:
        show_error_popup(stdscr, "Error", f"Error setting password valid date: {str(e)}")
        return

    # API를 통한 사용자 역할 및 webAdmin 속성 업데이트 (실패시 예외 무시)
    try:
        users_service = connection.system_service().users_service()
        new_user_obj = next((u for u in users_service.list() if getattr(u, "name", "") == username), None)
        if not new_user_obj:
            new_user_obj = users_service.add(
                User(
                    user_name=f"{username}@internal-authz",
                    domain=Domain(name="internal-authz")
                )
            )
        roles_service = connection.system_service().roles_service()
        super_user_role = next((r for r in roles_service.list() if r.name == "SuperUser"), None)
        if super_user_role:
            permissions_service = connection.system_service().permissions_service()
            permissions_service.add(Permission(role=super_user_role, user=new_user_obj))
    except Exception:
        pass
    try:
        OVIRT_URL = connection.url
        USER_ID = new_user_obj.id
        webadmin_url = f"{OVIRT_URL}/users/{USER_ID}"
        webadmin_data = "<user><webAdmin>true</webAdmin></user>"
        new_user_account = f"{username}@internal"
        requests.put(
            webadmin_url,
            data=webadmin_data,
            auth=HTTPBasicAuth(new_user_account, new_password),
            headers={"Content-Type": "application/xml", "Accept": "application/xml"},
            verify=False
        )
    except Exception:
        pass

    # 사용자 생성 완료 메시지 표시
    popup.clear()
    popup.border()
    complete_msg = f"User {username} created successfully."
    # 5번째 줄(인덱스 5)에 보통 글씨체(curses.A_NORMAL)로 출력
    popup.addstr(5, (popup_width - len(complete_msg)) // 2, complete_msg, curses.A_NORMAL)
    success_prompt = "Press any key to continue"
    popup.addstr(popup_height - 2, (popup_width - len(success_prompt)) // 2, success_prompt)
    popup.refresh()
    popup.getch()


    clear_users_cache(engine_host)
    refresh_users_callback()
    curses.curs_set(0)

def parse_user_query_output(output):
    """
    ovirt-aaa-jdbc-tool의 출력 결과를 파싱하여 사용자 리스트를 반환함.
    """
    users = []
    current_user = None
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("Picked up"):
            continue
        if line.startswith("-- User"):
            if current_user is not None:
                users.append(current_user)
            current_user = {}
            m = re.search(r"-- User\s+(\S+)\s*\(([^)]+)\)", line)
            if m:
                current_user["Name"] = m.group(1)
                current_user["ID"] = m.group(2)
        else:
            if ":" in line and current_user is not None:
                key, val = line.split(":", 1)
                current_user[key.strip()] = val.strip()
    if current_user:
        users.append(current_user)
    return users

# ---------------------------------------------------------------------------
# 사용자 목록 및 상세정보 표시 함수
# ---------------------------------------------------------------------------
def show_users(stdscr, connection):
    """
    curses 인터페이스에 사용자 목록을 122열 크기의 테이블 형식으로 표시합니다.
    
    - 상단 헤더: 왼쪽에는 "- USER LIST (Total User X/Y)"를, 오른쪽에는 "(Page A/B)"를
      122열 기준 고정 위치에 출력합니다.
    - 한 페이지당 최대 25명의 사용자를 표시합니다.
    - 하단 푸터: 왼쪽에는 기본 내비게이션 명령어를, 오른쪽에는 "N=Next | P=Prev"를
      122열 기준 고정 위치에 출력합니다.
    """
    curses.curs_set(0)
    curses.cbreak()
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)
    stdscr.timeout(50)

    fixed_width = 122  # 테이블 및 헤더/푸터 기준 폭

    parsed_url = urlparse(connection.url)
    engine_host = parsed_url.hostname

    try:
        output = get_users_output(engine_host)
    except Exception as e:
        show_error_popup(stdscr, "Error", f"Query command error: {str(e)}")
        return
    users = parse_user_query_output(output)

    selected_users = set()
    current_row = 0
    rows_per_page = 25  # 한 페이지당 최대 25명 표시
    total_users = len(users)
    total_pages = max(1, (total_users + rows_per_page - 1) // rows_per_page)
    current_page = 0
    # 122 = sum(col_widths) + 7, 그러므로 sum(col_widths) = 115
    # 예: [24, 17, 17, 19, 14, 24] 의 합은 115
    col_widths = [24, 17, 17, 19, 14, 24]
    headers = ["Username", "Account Disabled", "Account Locked", "First Name", "Last Name", "Email"]

    while True:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if height < 20 or width < fixed_width:
            stdscr.addstr(0, 0, f"Resize terminal to at least {fixed_width}x20.", curses.color_pair(2))
            stdscr.noutrefresh()
            curses.doupdate()
            continue

        # 상단 헤더 출력 (122열 기준 고정)
        stdscr.addstr(1, 1, "USER", curses.A_BOLD)
        start_idx = current_page * rows_per_page
        current_page_count = min(rows_per_page, total_users - start_idx)
        left_header = f"- USER LIST (Total User {current_page_count}/{total_users})"
        page_info = f"(Page {current_page+1}/{total_pages})"
        stdscr.addstr(3, 1, left_header)
        stdscr.addstr(3, fixed_width - len(page_info), page_info)

        # 테이블 헤더 그리기
        stdscr.addstr(4, 1, "┌" + "┬".join("─" * w for w in col_widths) + "┐")
        header_cells = [get_display_width(h, w) for h, w in zip(headers, col_widths)]
        header_text = "│" + "│".join(header_cells) + "│"
        stdscr.addstr(5, 1, header_text)
        divider_line = "├" + "┼".join("─" * w for w in col_widths) + "┤"
        stdscr.addstr(6, 1, divider_line)
        
        start_idx = current_page * rows_per_page
        end_idx = min(start_idx + rows_per_page, total_users)
        displayed_count = end_idx - start_idx

        # 사용자 목록 각 행 출력
        for idx, user in enumerate(users[start_idx:end_idx]):
            row_y = 7 + idx
            marker = "[x] " if (start_idx + idx) in selected_users else "[ ] "
            row_data = [
                get_display_width(marker + user.get("Name", "-"), col_widths[0]),
                get_display_width(user.get("Account Disabled", "-"), col_widths[1]),
                get_display_width(user.get("Account Locked", "-"), col_widths[2]),
                get_display_width(user.get("First Name", "-"), col_widths[3]),
                get_display_width(user.get("Last Name", "-"), col_widths[4]),
                get_display_width(user.get("Email", "-"), col_widths[5])
            ]
            row_text = "│" + "│".join(row_data) + "│"
            if idx == current_row:
                stdscr.attron(curses.color_pair(1))
                stdscr.addstr(row_y, 1, row_text)
                stdscr.attroff(curses.color_pair(1))
            else:
                stdscr.addstr(row_y, 1, row_text)
        
        footer_line = "└" + "┴".join("─" * w for w in col_widths) + "┘"
        stdscr.addstr(7 + displayed_count, 1, footer_line)

        # 하단 푸터 출력 (122열 기준 고정)
        footer_left = "▲/▼=Navigate | SPACE=Select | ENTER=Details | U=Unlock | A=Add | ESC=Go back | Q=Quit"
        footer_right = "N=Next | P=Prev" if total_pages > 1 else ""
        stdscr.addstr(height - 2, 1, footer_left)
        if footer_right:
            stdscr.addstr(height - 2, fixed_width - len(footer_right), footer_right)
        stdscr.refresh()

        # 사용자 입력 처리
        key = stdscr.getch()
        if key == ord('q'):
            exit(0)
        elif key == 27:
            break
        elif key == curses.KEY_UP:
            if displayed_count > 0:
                current_row = (current_row - 1) % displayed_count
        elif key == curses.KEY_DOWN:
            if displayed_count > 0:
                current_row = (current_row + 1) % displayed_count
        elif key == ord('n') and total_pages > 1 and current_page < total_pages - 1:
            current_page += 1
            current_row = 0
        elif key == ord('p') and total_pages > 1 and current_page > 0:
            current_page -= 1
            current_row = 0
        elif key == ord(' '):
            user_index = start_idx + current_row
            if user_index in selected_users:
                selected_users.remove(user_index)
            else:
                selected_users.add(user_index)
        elif key in (curses.KEY_ENTER, 10, 13):
            user_index = start_idx + current_row
            show_user_details(stdscr, connection, users[user_index])
        elif key == ord('a'):
            # 사용자 추가 후 목록 새로 고침
            add_user_popup_form(stdscr, connection, lambda: None)
            clear_users_cache(engine_host)
            try:
                output = get_users_output(engine_host)
                users = parse_user_query_output(output)
                total_users = len(users)
                total_pages = max(1, (total_users + rows_per_page - 1) // rows_per_page)
                current_page = 0
                current_row = 0
            except Exception as e:
                show_error_popup(stdscr, "Error", f"Failed to refresh users: {str(e)}")
            curses.curs_set(0)
        elif key == ord('u'):
            # 선택된 사용자에 대해 일괄 잠금 해제
            if not selected_users:
                continue
            already_unlocked = []
            other_results = []
            for user_index in sorted(selected_users):
                selected_user = users[user_index]
                username = selected_user.get("Name", None)
                if not username or username == "-":
                    other_results.append("User with invalid name skipped.")
                    continue
                if selected_user.get("Account Locked", "").strip().lower() != "true":
                    already_unlocked.append(username)
                    continue
                unlock_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} \"ovirt-aaa-jdbc-tool user unlock {username}\""
                try:
                    unlock_result = subprocess.run(unlock_cmd, shell=True,
                                                   stdout=subprocess.PIPE,
                                                   stderr=subprocess.PIPE,
                                                   text=True, timeout=15)
                    if unlock_result.returncode == 0:
                        other_results.append(f"User {username} unlocked successfully.")
                    else:
                        other_results.append(f"User {username} unlock failed: {unlock_result.stderr.strip()}")
                except Exception as e:
                    other_results.append(f"User {username} unlock error: {str(e)}")
            selected_users.clear()
            combined_messages = []
            if already_unlocked:
                combined_messages.append("User " + ", ".join(already_unlocked) + " is already unlocked.")
            if other_results:
                combined_messages.extend(other_results)
            combined_message = "\n".join(combined_messages)
            show_custom_popup(stdscr, "Batch Unlock Results", combined_message)

def show_user_details(stdscr, connection, user):
    """
    선택한 사용자의 상세 정보를 표시함.
    """
    parsed_url = urlparse(connection.url)
    engine_host = parsed_url.hostname
    username = user.get("Name", "-")
    
    details_cmd = f"ssh {CONTROL_OPTS} -o StrictHostKeyChecking=no root@{engine_host} \"ovirt-aaa-jdbc-tool user show {username}\""
    try:
        result = subprocess.run(details_cmd, shell=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=15)
    except Exception as e:
        show_error_popup(stdscr, "Error", f"Failed to execute details command: {str(e)}")
        return
    if result.returncode != 0:
        show_error_popup(stdscr, "Error", f"Failed to get user details: {result.stderr.strip()}")
        return

    # 출력 결과 파싱
    details = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("-- User"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            details[key.strip()] = val.strip()

    fields_order = [
        "Name", "ID", "Display Name", "Email", "First Name", "Last Name",
        "Department", "Title", "Description", "Account Disabled",
        "Account Locked", "Account Unlocked At", "Account Valid From",
        "Account Valid To", "Account Without Password", "Last successful Login At",
        "Last unsuccessful Login At", "Password Valid To"
    ]

    stdscr.clear()
    height, width = stdscr.getmaxyx()
    title = f"User Details for {username}"
    stdscr.addstr(1, 1, title, curses.A_BOLD)
    start_y = 3
    for idx, field in enumerate(fields_order):
        value = details.get(field, "-")
        stdscr.addstr(start_y + idx, 2, f"{field}: {value}")
    footer_text = "ESC=Go back | Q=Quit"
    stdscr.addstr(height - 2, 2, footer_text, curses.A_DIM)
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key == 27:
            break
        elif key in (ord('q'), ord('Q')):
            exit(0)

def set_user_password(engine_host, username, new_password, stdscr):
    """
    pexpect를 이용하여 SSH 세션에서 비밀번호 재설정 과정을 자동화함.
    """
    try:
        cmd = f"ssh {CONTROL_OPTS} -tt -o StrictHostKeyChecking=no root@{engine_host} \"/usr/bin/ovirt-aaa-jdbc-tool user password-reset {username}\""
        child = pexpect.spawn(cmd, encoding='utf-8', timeout=15)
        password_prompt_regex = re.compile(r'(?i)(new password|password):')
        child.expect(password_prompt_regex)
        child.sendline(new_password)
        child.expect(password_prompt_regex, timeout=15)
        child.sendline(new_password)
        child.expect(pexpect.EOF, timeout=15)
        child.close()
        return True
    except Exception:
        return False

# =============================================================================
# Section 12: Certificate Section (Placeholder)
# =============================================================================

def show_certificates(stdscr, connection):
    """
    [Placeholder]
    Certificate 관련 기능 미구현.
    이곳에 향후 Certificate 관련 코드를 채워 넣을 예정.
    """
    stdscr.erase()
    stdscr.addstr(1, 1, "Certificate functionality is not yet implemented.", curses.A_BOLD)
    stdscr.addstr(3, 1, "Press any key to go back.")
    stdscr.refresh()
    stdscr.getch()
    
# =============================================================================
# Section 13: Evnets Section
# =============================================================================

import curses
import textwrap
import time
import threading
from datetime import datetime

def show_no_events_popup(stdscr, message="No events found."):
    """
    'No events found.' 등의 메시지를 팝업 창으로 표시함.
    아무 키나 누르면 팝업만 닫고 반환함.
    """
    curses.flushinp()
    height, width = stdscr.getmaxyx()
    popup_height = 7
    popup_width = 50
    popup_y = (height - popup_height) // 2
    popup_x = (width - popup_width) // 2

    popup = curses.newwin(popup_height, popup_width, popup_y, popup_x)
    popup.keypad(True)
    popup.timeout(-1)  # 블로킹 모드
    popup.border()

    # 중앙 정렬 출력
    popup.addstr(2, (popup_width - len(message)) // 2, message, curses.A_BOLD)
    footer = "Press any key to continue."
    popup.addstr(4, (popup_width - len(footer)) // 2, footer, curses.A_DIM)
    popup.refresh()

    # 팝업 창에서 키 입력 대기
    popup.getch()
    curses.flushinp()

    # 팝업 윈도우 지우고 닫기
    popup.clear()
    popup.refresh()
    del popup

def fetch_events(connection, result):
    """
    별도 스레드에서 이벤트 목록을 가져와서 result 딕셔너리에 저장함.
    """
    try:
        events_service = connection.system_service().events_service()
        events = events_service.list()
        # 시간 역순 정렬
        events.sort(key=lambda ev: ev.time if ev.time else datetime.min, reverse=True)
        result['events'] = events
    except Exception as e:
        result['error'] = str(e)

def event_truncate_with_ellipsis(s, max_length):
    """
    문자열 s가 max_length를 넘으면 '...'로 끝을 표시하여 자르고,
    넘지 않으면 그대로 반환함.
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - 3] + '...'

def show_event_detail(stdscr, event):
    """
    선택한 이벤트의 상세 정보를 보여줍니다.
    사용자가 키를 누를 때까지 대기함.
    """
    stdscr.nodelay(False)
    curses.flushinp()
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    detail_lines = []
    detail_lines.append("Event Detail")
    detail_lines.append("")
    event_time = event.time.strftime('%Y-%m-%d %H:%M:%S') if event.time else "-"
    severity = getattr(event.severity, 'name', str(event.severity)) if event.severity else "-"
    description = event.description if event.description else "-"

    detail_lines.append(f"Time: {event_time}")
    detail_lines.append(f"Severity: {severity}")
    detail_lines.append("Description:")

    wrapped_desc = textwrap.wrap(description, width=width - 4)
    detail_lines.extend(wrapped_desc)
    detail_lines.append("")
    detail_lines.append("Press any key to go back.")

    for idx, line in enumerate(detail_lines):
        if idx + 2 < height:
            stdscr.addstr(idx + 2, 1, line)
    stdscr.refresh()
    stdscr.getch()

def show_events(stdscr, connection):
    """
    이벤트 화면:
      - 검색어 입력 후 Enter로 필터 적용
      - w 키: Severity가 WARNING인 이벤트만 표시
      - e 키: Severity가 ERROR인 이벤트만 표시
      - r 키: 이벤트 목록 새로 조회(Refresh)
      - 테이블은 항상 40줄을 그려서 필터 결과가 없어도 테두리가 유지됨
      - 검색 모드일 때는 검색 상자만 부분 갱신(속도 개선).
      - 검색 결과가 없을 경우 팝업 창으로 "No events found." 메시지를 표시한 후
        기존 테이블을 다시 그려주고, 이후 검색창으로 포커스 이동 가능
      - 화면 맨 아래: TAB=Switch focus | W=WARNING | E=ERROR | R=Refresh | ESC=Go back | Q=Quit
    """
    stdscr.erase()
    stdscr.nodelay(True)
    spinner_chars = ['|', '/', '-', '\\']
    spinner_index = 0

    # 1) 별도 스레드로 이벤트를 불러옴
    import threading
    result = {}
    fetch_thread = threading.Thread(target=fetch_events, args=(connection, result))
    fetch_thread.start()
    while fetch_thread.is_alive():
        stdscr.erase()
        stdscr.addstr(1, 1, f"Loading events... {spinner_chars[spinner_index]}", curses.A_BOLD)
        stdscr.refresh()
        spinner_index = (spinner_index + 1) % len(spinner_chars)
        time.sleep(0.1)
    fetch_thread.join()
    stdscr.nodelay(False)

    if 'error' in result:
        stdscr.erase()
        stdscr.addstr(1, 1, f"Failed to fetch Events: {result['error']}")
        stdscr.refresh()
        stdscr.getch()
        return

    events = result.get('events', [])
    search_query = ""         # 현재 적용된 검색어 (검색 전 상태)
    pending_search = ""       # 사용자가 입력 중인 검색어
    severity_filter = ""
    current_focus = "table"   # 초기에는 테이블 모드
    selected_row = 0
    current_page = 0

    curses.curs_set(0)
    curses.start_color()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)
    stdscr.clear()

    # UI 레이아웃 상수
    search_left_width = 7
    search_right_width = 113
    table_col1_width = 19
    table_col2_width = 9
    table_col3_width = 91
    table_total_width = 1 + table_col1_width + 1 + table_col2_width + 1 + table_col3_width + 1
    rows_per_page = 40
    min_height = 4 + rows_per_page + 4  # 검색 상자(3줄) + 테이블(40줄) + 기타

    # 검색 상자 관련
    search_box_top = 4
    search_top_border = "┌" + "─" * search_left_width + "┬" + "─" * search_right_width + "┐"
    search_bottom_border = "└" + "─" * search_left_width + "┴" + "─" * search_right_width + "┘"

    # 필터링 결과 캐싱 (검색어/심각도 조건이 바뀔 때만 새로 계산)
    last_filter_query = None
    last_severity_filter = None
    cached_filtered_events = events

    # 팝업 닫힌 뒤 검색창으로 포커스 이동할지 여부
    force_search_focus = False
    just_redrawn_table = False

    while True:
        height, width = stdscr.getmaxyx()
        if height < min_height or width < table_total_width + 4:
            stdscr.erase()
            stdscr.addstr(0, 0,
                          f"Resize terminal to at least {table_total_width+4}x{min_height}.",
                          curses.color_pair(2))
            stdscr.refresh()
            continue

        # 팝업 닫은 뒤, 곧바로 검색 모드로 이동해야 하는 경우 처리
        if force_search_focus and not just_redrawn_table:
            current_focus = "table"
        elif force_search_focus and just_redrawn_table:
            current_focus = "search"
            force_search_focus = False
            just_redrawn_table = False

        # -----------------------------
        # (1) 검색 모드
        # -----------------------------
        if current_focus == "search":
            just_redrawn_table = False
            stdscr.addstr(search_box_top, 1, search_top_border)
            left_cell = "Search:".ljust(search_left_width)
            displayed_query = pending_search[-search_right_width:]
            right_cell = displayed_query.ljust(search_right_width)
            search_input_line = "│" + left_cell + "│" + right_cell + "│"
            stdscr.addstr(search_box_top + 1, 1, search_input_line)
            stdscr.addstr(search_box_top + 2, 1, search_bottom_border)
            # 커서 위치 지정
            cursor_x = 2 + 1 + search_left_width + 1 + min(len(pending_search), search_right_width) - 1
            curses.curs_set(1)
            stdscr.move(search_box_top + 1, cursor_x)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (9, curses.KEY_BTAB):
                current_focus = "table"
            elif key == 27:
                current_focus = "table"
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                pending_search = pending_search[:-1]
            elif key == 10:  # Enter: 검색 적용
                # 임시로 필터링 테스트
                temp_filtered = events
                if pending_search:
                    sq = pending_search.lower()
                    temp_filtered = [
                        ev for ev in temp_filtered
                        if ((ev.description and sq in ev.description.lower())
                            or (ev.severity and sq in getattr(ev.severity, 'name', str(ev.severity)).lower())
                            or (ev.time and sq in ev.time.strftime('%Y-%m-%d %H:%M:%S')))
                    ]
                if severity_filter:
                    temp_filtered = [
                        ev for ev in temp_filtered
                        if (ev.severity and severity_filter == getattr(ev.severity, 'name', str(ev.severity)).upper())
                    ]
                if not temp_filtered:
                    show_no_events_popup(stdscr, "No events found.")
                    # 테이블은 변경하지 않고, 검색창 포커스 이동
                    current_focus = "table"
                    force_search_focus = True
                else:
                    search_query = pending_search
                    current_page = 0
                    selected_row = 0
                    current_focus = "table"
            elif key != -1 and 32 <= key <= 126:
                pending_search += chr(key)
            continue

        # -----------------------------
        # (2) 테이블 모드
        # -----------------------------
        # 캐싱 로직: 검색어/Severity 필터가 달라졌으면 새로 필터링
        if last_filter_query != search_query or last_severity_filter != severity_filter:
            temp = events
            if search_query:
                sq = search_query.lower()
                temp = [
                    ev for ev in temp
                    if ((ev.description and sq in ev.description.lower())
                        or (ev.severity and sq in getattr(ev.severity, 'name', str(ev.severity)).lower())
                        or (ev.time and sq in ev.time.strftime('%Y-%m-%d %H:%M:%S')))
                ]
            if severity_filter:
                temp = [
                    ev for ev in temp
                    if (ev.severity and severity_filter == getattr(ev.severity, 'name', str(ev.severity)).upper())
                ]
            cached_filtered_events = temp
            last_filter_query = search_query
            last_severity_filter = severity_filter

        filtered_events = cached_filtered_events

        stdscr.erase()
        stdscr.addstr(1, 1, "Events", curses.A_BOLD)

        # 검색 상자 그리기 (테이블 모드에서도 표시)
        stdscr.addstr(search_box_top, 1, search_top_border)
        left_cell = "Search:".ljust(search_left_width)
        displayed_query = pending_search[-search_right_width:]
        right_cell = displayed_query.ljust(search_right_width)
        search_input_line = "│" + left_cell + "│" + right_cell + "│"
        stdscr.addstr(search_box_top + 1, 1, search_input_line)
        stdscr.addstr(search_box_top + 2, 1, search_bottom_border)

        # 테이블 헤더 그리기
        table_top_border = "┌" + "─" * table_col1_width + "┬" + "─" * table_col2_width + "┬" + "─" * table_col3_width + "┐"
        header_row = search_box_top + 3
        table_header_line = ("│" + "Time".ljust(table_col1_width) +
                             "│" + "Severity".ljust(table_col2_width) +
                             "│" + "Description".ljust(table_col3_width) + "│")
        if len(filtered_events) == 0:
            divider_row_used = "├" + "─" * table_col1_width + "┴" + "─" * table_col2_width + "┴" + "─" * table_col3_width + "┤"
        else:
            divider_row_used = "├" + "─" * table_col1_width + "┼" + "─" * table_col2_width + "┼" + "─" * table_col3_width + "┤"
        stdscr.addstr(header_row, 1, table_top_border)
        stdscr.addstr(header_row + 1, 1, table_header_line)
        stdscr.addstr(header_row + 2, 1, divider_row_used)
        table_data_start = header_row + 3

        # 페이지/테이블 데이터
        total_pages = max(1, (len(filtered_events) + rows_per_page - 1) // rows_per_page)
        if current_page >= total_pages:
            current_page = max(0, total_pages - 1)
            selected_row = 0

        page_info = f"- Event List ({current_page+1}/{total_pages})"
        stdscr.addstr(3, 1, page_info)

        if len(filtered_events) == 0:
            full_width = table_total_width - 2
            message = "  No events found."
            row_text = "│" + message.ljust(full_width) + "│"
            stdscr.addstr(table_data_start, 1, row_text)
            for i in range(1, rows_per_page):
                blank_text = "│" + " " * full_width + "│"
                stdscr.addstr(table_data_start + i, 1, blank_text)
        else:
            start_idx = current_page * rows_per_page
            end_idx = start_idx + rows_per_page
            current_page_events = filtered_events[start_idx:end_idx]
            for i in range(rows_per_page):
                row_y = table_data_start + i
                if i < len(current_page_events):
                    event = current_page_events[i]
                    event_time = event.time.strftime('%Y-%m-%d %H:%M:%S') if event.time else "-"
                    sev = getattr(event.severity, 'name', str(event.severity)) if event.severity else "-"
                    description = event.description.replace("\n", " ") if event.description else "-"
                    event_time = event_truncate_with_ellipsis(event_time, table_col1_width)
                    sev = event_truncate_with_ellipsis(sev, table_col2_width)
                    description = event_truncate_with_ellipsis(description, table_col3_width)
                    row_text = (
                        "│" + event_time.ljust(table_col1_width) +
                        "│" + sev.ljust(table_col2_width) +
                        "│" + description.ljust(table_col3_width) +
                        "│"
                    )
                else:
                    row_text = (
                        "│" + " " * table_col1_width +
                        "│" + " " * table_col2_width +
                        "│" + " " * table_col3_width +
                        "│"
                    )
                if current_focus == "table" and i == selected_row:
                    stdscr.attron(curses.color_pair(1))
                    stdscr.addstr(row_y, 1, row_text)
                    stdscr.attroff(curses.color_pair(1))
                else:
                    stdscr.addstr(row_y, 1, row_text)

        table_bottom_row = table_data_start + rows_per_page
        table_bottom_border = (
            "└" + "─" * table_col1_width +
            "┴" + "─" * table_col2_width +
            "┴" + "─" * table_col3_width +
            "┘"
        )
        stdscr.addstr(table_bottom_row, 1, table_bottom_border)

        nav_line1 = "N=Next | P=Prev"
        stdscr.addstr(table_bottom_row + 1, 1, nav_line1, curses.color_pair(2))
        nav_line2 = "TAB=Switch focus | W=WARNING | E=ERROR | R=Refresh | ESC=Go back | Q=Quit"
        stdscr.addstr(height - 2, 1, nav_line2, curses.color_pair(2))

        curses.curs_set(0)
        stdscr.move(height - 1, width - 1)
        stdscr.refresh()
        just_redrawn_table = True

        # 키 입력 처리
        key = stdscr.getch()
        if key == 9:  # Tab
            current_focus = "search"
            pending_search = search_query
        elif key == curses.KEY_UP:
            if selected_row > 0:
                selected_row -= 1
            else:
                if current_page > 0:
                    current_page -= 1
                    selected_row = rows_per_page - 1
        elif key == curses.KEY_DOWN:
            if selected_row < rows_per_page - 1:
                selected_row += 1
            else:
                if current_page < total_pages - 1:
                    current_page += 1
                    selected_row = 0
        elif key in (ord('n'), ord('N')):
            if current_page < total_pages - 1:
                current_page += 1
                selected_row = 0
        elif key in (ord('p'), ord('P')):
            if current_page > 0:
                current_page -= 1
                selected_row = 0

        # -----------------------------
        # (2-1) Severity 필터 (W/E 키)
        # -----------------------------
        elif key in (ord('w'), ord('W')):
            old_severity = severity_filter
            severity_filter = "WARNING"

            # 새 필터로 미리 필터링 테스트
            temp_filtered = events
            if search_query:
                sq = search_query.lower()
                temp_filtered = [
                    ev for ev in temp_filtered
                    if ((ev.description and sq in ev.description.lower())
                        or (ev.severity and sq in getattr(ev.severity, 'name', str(ev.severity)).lower())
                        or (ev.time and sq in ev.time.strftime('%Y-%m-%d %H:%M:%S')))
                ]
            temp_filtered = [
                ev for ev in temp_filtered
                if (ev.severity and severity_filter == getattr(ev.severity, 'name', str(ev.severity)).upper())
            ]
            if not temp_filtered:
                # 결과가 없다면 팝업만 띄우고, 필터 원복
                show_no_events_popup(stdscr, "No WARNING events found.")
                severity_filter = old_severity
            else:
                current_page = 0
                selected_row = 0

        elif key in (ord('e'), ord('E')):
            old_severity = severity_filter
            severity_filter = "ERROR"

            # 새 필터로 미리 필터링 테스트
            temp_filtered = events
            if search_query:
                sq = search_query.lower()
                temp_filtered = [
                    ev for ev in temp_filtered
                    if ((ev.description and sq in ev.description.lower())
                        or (ev.severity and sq in getattr(ev.severity, 'name', str(ev.severity)).lower())
                        or (ev.time and sq in ev.time.strftime('%Y-%m-%d %H:%M:%S')))
                ]
            temp_filtered = [
                ev for ev in temp_filtered
                if (ev.severity and severity_filter == getattr(ev.severity, 'name', str(ev.severity)).upper())
            ]
            if not temp_filtered:
                # 결과가 없다면 팝업만 띄우고, 필터 원복
                show_no_events_popup(stdscr, "No ERROR events found.")
                severity_filter = old_severity
            else:
                current_page = 0
                selected_row = 0

        # -----------------------------
        # (2-2) 새로고침 (R 키)
        # -----------------------------
        elif key in (ord('r'), ord('R')):
            stdscr.nodelay(True)
            spinner_index = 0
            result = {}
            fetch_thread = threading.Thread(target=fetch_events, args=(connection, result))
            fetch_thread.start()
            while fetch_thread.is_alive():
                stdscr.erase()
                stdscr.addstr(1, 1, f"Loading events... {spinner_chars[spinner_index]}", curses.A_BOLD)
                stdscr.refresh()
                spinner_index = (spinner_index + 1) % len(spinner_chars)
                time.sleep(0.1)
            fetch_thread.join()
            stdscr.nodelay(False)
            if 'error' in result:
                stdscr.erase()
                stdscr.addstr(1, 1, f"Failed to fetch Events: {result['error']}")
                stdscr.refresh()
                stdscr.getch()
            else:
                events = result.get('events', [])
                # 필터 캐시 초기화
                last_filter_query = None
                last_severity_filter = None
                cached_filtered_events = events
                current_page = 0
                selected_row = 0

        # -----------------------------
        # (2-3) Enter: 상세보기
        # -----------------------------
        elif key == 10:
            if len(filtered_events) != 0:
                start_idx = current_page * rows_per_page
                current_page_events = filtered_events[start_idx:start_idx + rows_per_page]
                if 0 <= selected_row < len(current_page_events):
                    selected_event = current_page_events[selected_row]
                    show_event_detail(stdscr, selected_event)

        # -----------------------------
        # (2-4) 종료/뒤로가기
        # -----------------------------
        elif key in (ord('q'), ord('Q')):
            import sys
            sys.exit(0)
        elif key == 27:  # ESC
            break

# =============================================================================
# Section 14: Main Execution Block
# =============================================================================

if __name__ == "__main__":
    # 설정 파일에서 FQDN(Fully Qualified Domain Name)을 가져옴
    fqdn = get_fqdn_from_config()
    
    # FQDN을 기반으로 IP 주소를 가져옴
    ip = get_ip_from_hosts(fqdn)
    
    # IP가 네트워크에서 접근 가능한지 확인
    if not check_ip_reachable(ip):
        print("Engine is not running")
        sys.exit(1)  # 실행 종료
    
    # oVirt API 엔드포인트 URL 설정
    url = f"https://{ip}/ovirt-engine/api"
    
    print(f"RutilVM {fqdn}({ip})")
    
    # 기존 세션 정보를 로드 (이미 로그인된 상태인지 확인)
    session_data = load_session()
    
    # 기존 세션이 존재하고, URL이 일치하면 저장된 사용자 정보 사용
    if session_data and session_data["url"] == url:
        username = session_data["username"]
        password = session_data["password"]
    else:
        max_attempts = 2  # 로그인 최대 시도 횟수 설정
        for attempt in range(max_attempts):
            try:
                if attempt == 0:
                    # 사용자에게 계정 정보를 입력받음
                    username = input("Enter username: ")
                    if "@" not in username:
                        username += "@internal"  # 기본 도메인 추가
                    password = getpass.getpass("Enter password: ")
                else:
                    print("Permission denied, please try again.")
                    username = input("Enter username: ")
                    if "@" not in username:
                        username += "@internal"
                    password = getpass.getpass("Enter password: ")
                
                # oVirt API에 연결 시도
                with Connection(
                    url=url,
                    username=username,
                    password=password,
                    insecure=True  # SSL 검증 비활성화 (보안 이슈 주의 필요)
                ) as connection:
                    connection.system_service().get()  # 연결 확인
                break  # 로그인 성공 시 루프 종료
            except Exception:
                if attempt == max_attempts - 1:
                    # 로그인 실패 시 오류 메시지 출력 후 프로그램 종료
                    print(
                        "Failed to connect: Error during SSO authentication access_denied.\n"
                        "Unable to log in. Verify your login information or contact the system administrator."
                    )
                    sys.exit(1)
        
        # 로그인 성공 후 세션 저장
        save_session(username, password, url)
    
    try:
        # oVirt API에 다시 연결 시도
        with Connection(
            url=url,
            username=username,
            password=password,
            insecure=True
        ) as connection:
            connection.system_service().get()  # 연결 확인
            delete_session_on_exit = True  # 종료 시 세션 삭제 여부 설정
            
            # curses 라이브러리를 사용하여 텍스트 기반 UI 실행
            curses.wrapper(main_menu, connection)
    except Exception as e:
        msg = str(e).lower()
        # 네트워크 관련 오류 메시지 처리
        if "no route" in msg or "failed to connect to" in msg:
            print("Engine is not running")
        else:
            print(f"Failed to connect: {e}")
        sys.exit(1)  # 오류 발생 시 프로그램 종료
