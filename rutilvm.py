#!/usr/bin/python3
"""
date: 20250210
RutilVM Assistor

메뉴 항목 순서:
  1. Virtual Machines
  2. Data Centers
  3. Clusters
  4. Hosts
  5. Networks
  6. Storage Domains     ← (추후 구현: placeholder)
  7. Storage Disks       ← (추후 구현: placeholder)
  8. Users               ← (추후 구현: placeholder)
  9. Certificate         ← (추후 구현: placeholder)

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
from datetime import datetime, timezone  # 날짜/시간 처리
from ovirtsdk4.types import Host, VmStatus, Ip, IpVersion  # oVirt SDK 타입
from ovirtsdk4 import Connection, Error  # oVirt SDK 연결 및 오류 처리
from requests.auth import HTTPBasicAuth  # HTTP 기본 인증
import socket           # 네트워크 연결 확인
import math
import ovirtsdk4.types as types  # oVirt SDK 타입 사용


# HTTPS 경고 메시지 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----- 유틸리티 함수들 -----

def truncate_with_ellipsis(value, max_width):
    """문자열의 길이가 max_width보다 길면 생략 부호(...)를 추가하여 잘라 반환"""
    value = str(value) if value else "-"
    if len(value) > max_width:
        return value[:max_width - 2] + ".."
    return value
def truncate_value(value, max_width):
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

# 전역 세션 관련 변수 (SSH_CONNECTION 기반)
TERMINAL_SESSION_ID = os.environ.get("SSH_CONNECTION", "local_session").replace(" ", "_")
SESSION_FILE = f"/tmp/ovirt_session_{TERMINAL_SESSION_ID}.pkl"
session_data = None
delete_session_on_exit = False

def load_session():
    """
    SESSION_FILE에 저장된 세션 데이터를 불러와 전역 변수에 저장.
    """
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
    """
    사용자명, 비밀번호, URL을 세션 데이터로 저장하여 SESSION_FILE에 기록.
    """
    global session_data
    session_data = {"username": username, "password": password, "url": url}
    with open(SESSION_FILE, "wb") as file:
        pickle.dump(session_data, file)

def clear_session():
    """
    delete_session_on_exit가 참이면 세션 데이터를 지우고 파일을 삭제.
    """
    global session_data
    if delete_session_on_exit:
        session_data = None
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)

def signal_handler(sig, frame):
    """
    SIGINT, SIGHUP, SIGTERM 시그널을 처리하여 세션 삭제 없이 종료.
    """
    global delete_session_on_exit
    delete_session_on_exit = False
    sys.exit(0)

# 시그널 핸들러 등록
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
    """
    curses.curs_set(0)  # 커서 숨김
    curses.cbreak()     # 키 입력 즉시 처리
    curses.start_color()  # 색상 초기화
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # 선택 메뉴 색상
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)  # 기본 색상
    stdscr.timeout(50)  # 입력 대기 시간 50ms

    menu = [
        "Virtual Machines",
        "Data Centers",
        "Clusters",
        "Hosts",
        "Networks",
        "Storage Domains",
        "Storage Disks",
        "Users",
        "Certificate"
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
                # ← 필요한 함수 추가: Networks
                show_networks(stdscr, connection)
            elif menu[current_row] == "Storage Domains":
                # ← 필요한 함수 추가: Storage Domains
                show_storage_domains(stdscr, connection)
            elif menu[current_row] == "Storage Disks":
                # ← 필요한 함수 추가: Storage Disks
                show_storage_disks(stdscr, connection)
            elif menu[current_row] == "Users":
                # ← 필요한 함수 추가: Users
                show_users(stdscr, connection)
            elif menu[current_row] == "Certificate":
                # ← 필요한 함수 추가: Certificate
                show_certificates(stdscr, connection)

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
        # 모든 호스트 정보를 리스트로 가져옵니다.
        hosts = hosts_service.list()
        # 호스트 id를 키로, 호스트 이름을 값으로 하는 딕셔너리 생성
        hosts_map = {host.id: host.name for host in hosts}
        # 모든 VM 정보를 리스트로 가져옵니다.
        vms = vms_service.list()
    except Exception as e:
        # 데이터 로딩에 실패하면 에러 메시지를 화면에 출력하고, 사용자의 입력을 기다린 후 함수를 종료.
        stdscr.addstr(7, 1, f"Failed to fetch VM data: {e}", curses.color_pair(4))
        stdscr.refresh()
        stdscr.getch()
        return

    # 한 페이지에 표시할 VM 행의 개수를 설정.
    rows_per_page = 20
    # 전체 VM 개수를 기준으로 총 페이지 수를 계산합니다.
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
            # VM의 호스트 이름을 매핑에서 가져옵니다. (호스트 정보가 없으면 "N/A")
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

def show_events(stdscr, connection, data_center):
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
            show_events(stdscr, connection, dcs[current_row])
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
#def truncate_value(value, max_width):
#    """문자열의 길이가 max_width보다 길면 생략 부호(...)를 추가하여 잘라 반환"""
#    value = str(value) if value else "-"
#    if len(value) > max_width:
#        return value[:max_width - 2] + ".."
#    return value
#
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
    height, width = stdscr.getmaxyx()
    event_win = curses.newwin(height, width, 0, 0)
    event_win.clear()

    # 이벤트 서비스에서 이벤트 가져오기
    events_service = connection.system_service().events_service()
    all_events = events_service.list(max=100)  # 최신 100개 이벤트 가져오기

    # 선택된 네트워크의 정보
    network_name = network.get("name", "-")
    network_id = network.get("id", "-")
    network_data_center = network.get("data_center", "-")

    # 네트워크 및 Data Center와 관련된 이벤트 필터링
    network_events = [
        ev for ev in all_events
        if ev.description and ("network" in ev.description.lower())
        and (network_name in ev.description or network_id in ev.description)
        and (network_data_center in ev.description)
    ]

    # 페이지네이션 설정
    MAX_ROWS = 40  # 한 페이지에 표시할 최대 이벤트 개수
    total_events = len(network_events)
    max_page = max(1, (total_events + MAX_ROWS - 1) // MAX_ROWS)
    current_page = 1

    indent = " "  # 앞 공백 한 칸 유지

    def draw_event_page():
        event_win.erase()
        title = indent + f"- Event Page for {network_name} (Data Center: {network_data_center}) ({current_page}/{max_page})"
        event_win.addstr(1, 0, title)  # 공백 한 칸 유지하여 출력

        # 테이블 헤더
        event_headers = ["Time", "Severity", "Description"]
        event_widths = [19, 9, 91]  # 요청하신 대로 열 너비 설정

        if total_events == 0:
            # 이벤트가 없을 경우, `Severity`와 `Description` 열을 하나의 셀로 합침
            header_line = indent + "┌" + "─" * event_widths[0] + "┬" + "─" * event_widths[1] + "┬" + "─" * event_widths[2] + "┐"
            divider_line = indent + "├" + "─" * event_widths[0] + "┴" + "─" * (event_widths[1] + event_widths[2] + 1) + "┤"
            footer_line = indent + "└" + "─" * (sum(event_widths) + 4) + "┘"  # 오른쪽 정렬 수정

            event_win.addstr(3, 0, header_line)
            event_win.addstr(4, 0, indent + "│" + f"{event_headers[0]:<{event_widths[0]}}" + "│" + f"{event_headers[1]:<{event_widths[1]}}" + "│" + f"{event_headers[2]:<{event_widths[2]}}" + "│")
            event_win.addstr(5, 0, divider_line)
            event_win.addstr(6, 0, indent + "│" + " No events found for this network.".ljust(sum(event_widths) + 2) + "│")  # 정렬 수정
            event_win.addstr(7, 0, footer_line)
        else:
            header_line = indent + "┌" + "┬".join("─" * w for w in event_widths) + "┐"
            event_win.addstr(3, 0, header_line)
            event_win.addstr(4, 0, indent + "│" + "│".join(f"{truncate_value(h, w):<{w}}" for h, w in zip(event_headers, event_widths)) + "│")
            event_win.addstr(5, 0, indent + "├" + "┼".join("─" * w for w in event_widths) + "┤")

            start_idx = (current_page - 1) * MAX_ROWS
            end_idx = min(start_idx + MAX_ROWS, total_events)

            for i, event in enumerate(network_events[start_idx:end_idx]):
                time_str = event.time.strftime("%Y-%m-%d %H:%M:%S") if event.time else "-"
                severity = str(event.severity).split(".")[-1]  # ENUM 값에서 문자열 추출
                message = event.description if event.description else "-"

                row = [
                    truncate_value(time_str, event_widths[0]),
                    truncate_value(severity, event_widths[1]),
                    truncate_value(message, event_widths[2])
                ]

                event_win.addstr(6 + i, 0, indent + "│" + "│".join(f"{col:<{w}}" for col, w in zip(row, event_widths)) + "│")

            event_win.addstr(6 + (end_idx - start_idx), 0, indent + "└" + "┴".join("─" * w for w in event_widths) + "┘")

        # `N=Next | P=Prev` 문구 위치 조정
        event_win.addstr(8 if total_events == 0 else 7 + (end_idx - start_idx), 0, indent + "N=Next | P=Prev")  

        # `ESC=Go back | Q=Quit` 문구 위치 조정 (화면 하단)
        event_win.addstr(height - 2, 0, indent + "ESC=Go back | Q=Quit")

        event_win.refresh()

    draw_event_page()

    while True:
        key = event_win.getch()
        if key == 27:  # ESC 키 (뒤로가기)
            break
        elif key in (ord('q'), ord('Q')):  # 프로그램 종료
            exit(0)
        elif key in (ord('n'), ord('N')) and current_page < max_page:  # 다음 페이지
            current_page += 1
            draw_event_page()
        elif key in (ord('p'), ord('P')) and current_page > 1:  # 이전 페이지
            current_page -= 1
            draw_event_page()

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
            divider_line = indent + "├" + "─" * event_widths[0] + "┴" + "─" * (event_widths[1] + event_widths[2] + 1) + "┤"
            footer_line = indent + "└" + "─" * (sum(event_widths) + 4) + "┘"

            event_win.addstr(3, 0, header_line)
            event_win.addstr(4, 0, indent + "│" + f"{event_headers[0]:<{event_widths[0]}}" + "│" + f"{event_headers[1]:<{event_widths[1]}}" + "│" + f"{event_headers[2]:<{event_widths[2]}}" + "│")
            event_win.addstr(5, 0, divider_line)
            event_win.addstr(6, 0, indent + "│" + " No events found for this network.".ljust(sum(event_widths) + 2) + "│")
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
        stdscr.addstr(net_table_start + 1, 0, indent + "│" + "│".join(f"{truncate_value(h, w):<{w}}" for h, w in zip(net_headers, net_widths)) + "│")
        stdscr.addstr(net_table_start + 2, 0, indent + "├" + "┼".join("─" * w for w in net_widths) + "┤")
    except curses.error:
        pass
    for idx, net in enumerate(network_info):
        mtu_raw = net.get("mtu", 1500)
        mtu_value = "Default(1500)" if mtu_raw == 1500 else truncate_value(str(mtu_raw), net_widths[5])
        row = [
            truncate_value(net.get("name", "-"), net_widths[0]),
            truncate_value(net.get("data_center", "-"), net_widths[1]),
            truncate_value(net.get("description", "-"), net_widths[2]),
            truncate_value(str(net.get("role", "-")).lower(), net_widths[3]),
            truncate_value(str(net.get("vlan_tag", "-")), net_widths[4]),
            truncate_value(mtu_value, net_widths[5]),
            truncate_value(str(net.get("port_isolation", "-")), net_widths[6]),
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
        stdscr.addstr(vnic_table_start + 1, 0, indent + "│" + "│".join(f"{truncate_value(h, w):<{w}}" for h, w in zip(vnic_headers, vnic_widths)) + "│")
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
            stdscr.addstr(vnic_row_start + idx, 0, indent + "│" + "│".join(f"{truncate_value(col, w):<{w}}" for col, w in zip(row, vnic_widths)) + "│")
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
        stdscr.addstr(vm_table_start + 1, 0, indent + "│" + "│".join(f"{truncate_value(h, w):<{w}}" for h, w in zip(vm_headers, vm_widths)) + "│")
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
            truncate_value(vm.get("vm_name", "-"), vm_widths[0]),
            truncate_value(vm.get("cluster", "-"), vm_widths[1]),
            truncate_value(vm.get("ip", "-"), vm_widths[2]),
            truncate_value(vm.get("host_name", "-"), vm_widths[3]),
            truncate_value(vm.get("vnic_status", "-"), vm_widths[4]),
            truncate_value(vm.get("vnic", "-"), vm_widths[5])
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
    # 색상 초기화: Network List 테이블의 선택된 행 커서 색상 설정
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

    clusters = {cluster.id: cluster.name for cluster in clusters_service.list()}
    data_centers = {dc.id: dc.name for dc in data_centers_service.list()}
    hosts = {host.id: host.name for host in hosts_service.list()}
    vnic_profiles_service = system_service.vnic_profiles_service()
    vnic_profiles = {profile.id: profile for profile in vnic_profiles_service.list()}

    networks = networks_service.list()

    network_info = []
    for net in networks:
        data_center_name = data_centers.get(net.data_center.id, "-") if net.data_center else "-"
        associated_vms_dict = {}
        for vm in vms_service.list():
            vm_service = vms_service.vm_service(vm.id)
            try:
                nics = vm_service.nics_service().list()
                for nic in nics:
                    vnic_profile_id = nic.vnic_profile.id if nic.vnic_profile else None
                    if vnic_profile_id and vnic_profile_id in vnic_profiles:
                        vnic_profile = vnic_profiles[vnic_profile_id]
                        if vnic_profile.network and getattr(vnic_profile.network, "id", None) == net.id:
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
                            if vm.id not in associated_vms_dict:
                                associated_vms_dict[vm.id] = {
                                    "vm_name": vm.name or "-",
                                    "cluster": cluster_name,
                                    "ip": ip_address,
                                    "host_name": host_name,
                                    "vnic_status": vnic_status,
                                    "vnic": vnic_name,
                                    "id": vm.id
                                }
                            else:
                                existing = associated_vms_dict[vm.id]["vnic"]
                                if vnic_name not in existing.split(","):
                                    associated_vms_dict[vm.id]["vnic"] = existing + "," + vnic_name
            except Exception:
                pass
        aggregated_vms = list(associated_vms_dict.values())
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
        elif key in (10, 13):  # ENTER 키를 눌렀을 때
            show_event_page(stdscr, connection, network_info[selected_network_idx])  # 네트워크 정보 전달

        else:
            time.sleep(0.05)


# =============================================================================
# Section 9: Storage Domains Section (Placeholder)
# =============================================================================

def show_storage_domains(stdscr, connection):
    """
    [Placeholder]
    Storage Domains 관련 기능 미구현.
    이곳에 향후 Storage Domains 관련 코드를 채워 넣을 예정.
    """
    stdscr.erase()
    stdscr.addstr(1, 1, "Storage Domains functionality is not yet implemented.", curses.A_BOLD)
    stdscr.addstr(3, 1, "Press any key to go back.")
    stdscr.refresh()
    stdscr.getch()

# =============================================================================
# Section 10: Storage Disks Section (Placeholder)
# =============================================================================

def show_storage_disks(stdscr, connection):
    """
    [Placeholder]
    Storage Disks 관련 기능 미구현.
    이곳에 향후 Storage Disks 관련 코드를 채워 넣을 예정.
    """
    stdscr.erase()
    stdscr.addstr(1, 1, "Storage Disks functionality is not yet implemented.", curses.A_BOLD)
    stdscr.addstr(3, 1, "Press any key to go back.")
    stdscr.refresh()
    stdscr.getch()

# =============================================================================
# Section 11: Users Section (Placeholder)
# =============================================================================

def show_users(stdscr, connection):
    """
    [Placeholder]
    Users 관련 기능 미구현.
    이곳에 향후 Users 관련 코드를 채워 넣을 예정.
    """
    stdscr.erase()
    stdscr.addstr(1, 1, "Users functionality is not yet implemented.", curses.A_BOLD)
    stdscr.addstr(3, 1, "Press any key to go back.")
    stdscr.refresh()
    stdscr.getch()

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
# Section 13: Main Execution Block
# =============================================================================

if __name__ == "__main__":
    # FQDN 및 IP 주소 획득
    fqdn = get_fqdn_from_config()
    ip = get_ip_from_hosts(fqdn)
    # 포트 443에 대해 IP 연결 체크 (엔진 기동 여부)
    if not check_ip_reachable(ip):
        print("엔진이 기동중이 않음. (Engine is not running)")
        sys.exit(1)
    url = f"https://{ip}/ovirt-engine/api"
    print(f"RutilVM {fqdn}({ip})")
    session_data = load_session()
    if session_data and session_data["url"] == url:
        username = session_data["username"]
        password = session_data["password"]
    else:
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                if attempt == 0:
                    username = input("Enter username: ")
                    if "@" not in username:
                        username += "@internal"
                    password = getpass.getpass("Enter password: ")
                else:
                    print("Permission denied, please try again.")
                    username = input("Enter username: ")
                    if "@" not in username:
                        username += "@internal"
                    password = getpass.getpass("Enter password: ")
                with Connection(
                    url=url,
                    username=username,
                    password=password,
                    insecure=True
                ) as connection:
                    connection.system_service().get()
                break
            except Exception:
                if attempt == max_attempts - 1:
                    print(
                        "Failed to connect: Error during SSO authentication access_denied.\n"
                        "Unable to log in. Verify your login information or contact the system administrator."
                    )
                    sys.exit(1)
        save_session(username, password, url)
    try:
        with Connection(
            url=url,
            username=username,
            password=password,
            insecure=True
        ) as connection:
            connection.system_service().get()
            delete_session_on_exit = True
            curses.wrapper(main_menu, connection)
    except Exception as e:
        msg = str(e).lower()
        if "no route" in msg or "failed to connect to" in msg:
            print("Engine is not running")
        else:
            print(f"Failed to connect: {e}")
        sys.exit(1)
