#!/usr/bin/env python3
"""
HomeLab Network Monitor
A web-based homelab monitoring dashboard.
Monitors OpenWrt router via SSH + local SSH/FTP servers.
Runs on port 6767.
"""

import os
import json
import time
import threading
import subprocess
import re
import signal
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, render_template

# --------------- SSH (optional - graceful fallback) ---------------
try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# --------------- Local Service Monitoring Config ---------------
SERVICE_PORTS = {
    "ssh": 22,
    "ftp": 21,
}

# iptables rules for tracking local service bandwidth
SERVICE_IPTABLES_RULES = []

# --------------- Configuration ---------------
DATA_DIR = Path(__file__).parent / "data"
NICKNAMES_FILE = DATA_DIR / "nicknames.json"
STATS_FILE = DATA_DIR / "stats.json"
HISTORY_FILE = DATA_DIR / "history.json"
BLOCKED_FILE = DATA_DIR / "blocked.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
SPEED_HISTORY_MAX = 300
SPEED_POLL_INTERVAL = 2
STATS_SAVE_INTERVAL = 60

# Router SSH connection — loaded from settings file on startup
ROUTER_HOST = "192.168.1.1"
ROUTER_USER = "root"
ROUTER_PASSWORD = "1234567890"
ROUTER_PORT = 22

# Default settings (used if settings.json is missing)
DEFAULT_SETTINGS = {
    "router_host": "192.168.1.1",
    "router_user": "root",
    "router_password": "1234567890",
    "router_port": 22,
}

# Will hold loaded settings
current_settings = dict(DEFAULT_SETTINGS)

# WAN interface - auto-detected from router if possible
WAN_INTERFACE = "wan"
WIRELESS_INTERFACES = []

app = Flask(__name__)

# --------------- Data Store ---------------
data_lock = threading.Lock()
ssh_lock = threading.Lock()

nicknames = {}
stats = {
    "total_download": 0,
    "total_upload": 0,
    "session_download": 0,
    "session_upload": 0,
    "last_reset": datetime.now().isoformat(),    "last_updated": datetime.now().isoformat(),
}

speed_history = []
blocked_devices = set()
last_rx_bytes = None
last_tx_bytes = None
last_poll_time = None

ssh_client = None
ssh_connected = False


# --------------- Local Service Monitoring ---------------
def setup_service_iptables():
    """Set up iptables rules to track bandwidth per local service.
    These rules count bytes/packets for SSH (22) and FTP (21) traffic.
    """
    global SERVICE_IPTABLES_RULES
    rules = []
    for name, port in SERVICE_PORTS.items():
        rule_in = ["iptables", "-C", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]
        rule_out = ["iptables", "-C", "OUTPUT", "-p", "tcp", "--sport", str(port), "-j", "ACCEPT"]
        # Try adding counting rules (we use -I to insert, and check if they exist first)
        for rule in [rule_in, rule_out]:
            rule_check = rule[:]
            rule_check[1] = "-C"
            try:
                subprocess.run(rule_check, capture_output=True, timeout=5, check=True)
            except subprocess.CalledProcessError:
                # Rule doesn't exist, add it
                rule_insert = rule[:]
                rule_insert[1] = "-I"
                try:
                    subprocess.run(rule_insert, capture_output=True, timeout=5, check=True)
                    rules.append(rule_insert)
                except Exception as e:
                    print(f"  ⚠ Could not add iptables rule for port {port} ({name}): {e}")
    SERVICE_IPTABLES_RULES = rules


def get_service_bandwidth(name):
    """Get byte/packet counts from iptables for a local service."""
    port = SERVICE_PORTS.get(name)
    if not port:
        return {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
    try:
        result = subprocess.run(
            ["iptables", "-L", "INPUT", "-nvx"],
            capture_output=True, text=True, timeout=5
        )
        bytes_in = 0
        packets_in = 0
        for line in result.stdout.split("\n"):
            if f"dpt:{port}" in line and "tcp" in line:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        packets_in += int(parts[0])
                        bytes_in += int(parts[1])
                    except ValueError:
                        pass

        result = subprocess.run(
            ["iptables", "-L", "OUTPUT", "-nvx"],
            capture_output=True, text=True, timeout=5
        )
        bytes_out = 0
        packets_out = 0
        for line in result.stdout.split("\n"):
            if f"spt:{port}" in line and "tcp" in line:
                parts = line.strip().split()
                if len(parts) >= 3:
                    try:
                        packets_out += int(parts[0])
                        bytes_out += int(parts[1])
                    except ValueError:
                        pass

        return {
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "packets_in": packets_in,
            "packets_out": packets_out,
        }
    except Exception as e:
        print(f"Error getting service bandwidth for {name}: {e}")
        return {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}


def find_pids_for_port(port):
    """Find PIDs that have TCP connections on a given port by scanning /proc.
    This works without root, unlike 'ss -tnp' which hides process info for non-root users.
    Returns a dict mapping hex-encoded local addresses to PID lists.
    """
    port_hex = f":{port:04X}"
    pids_by_addr = {}
    try:
        for proc_entry in os.listdir("/proc"):
            if not proc_entry.isdigit():
                continue
            pid = int(proc_entry)
            tcp_path = f"/proc/{pid}/net/tcp"
            try:
                with open(tcp_path) as f:
                    content = f.read()
            except (IOError, OSError):
                continue
            # /proc/[pid]/net/tcp format (hex):
            # sl  local_address  rem_address   st tx_queue rx_queue ...
            #  0: 0100007F:0016 00000000:0000 0A ...
            for line in content.split("\n")[1:]:  # Skip header
                if not line.strip():
                    continue
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                local_addr = parts[1]  # e.g. "0100007F:0016" or "C0A801B8:0016"
                # Only match port (last 4 hex chars after colon)
                if local_addr.endswith(port_hex):
                    if local_addr not in pids_by_addr:
                        pids_by_addr[local_addr] = []
                    pids_by_addr[local_addr].append(pid)
    except Exception as e:
        print(f"Error scanning /proc for port {port}: {e}")
    return pids_by_addr


def parse_ss_output_port(port):
    """Parse ss output for established connections on a given port.
    Uses 'ss -tnp' (without 'state established' so State column IS present)
    to properly parse local/peer IPs, then supplements with PIDs from /proc.
    Returns list of connection dicts."""
    connections = []
    try:
        # NOTE: We DO NOT use "state established" here because ss omits
        # the State column when filtering by state, breaking column alignment.
        # Instead we filter to only ESTAB connections in Python.
        result = subprocess.run(
            ["ss", "-tnp", f"( sport = :{port} or dport = :{port} )"],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("State") or line.startswith("Netid"):
                continue
            parts = line.split()
            # With -tnp (no state filter), columns are:
            # State  Recv-Q  Send-Q  Local  Peer  [Process]
            # Only process ESTABLISHED connections
            if len(parts) < 5:
                continue
            state = parts[0]
            if state not in ("ESTAB", "ESTABLISHED"):
                continue
            recv_q = parts[1]
            send_q = parts[2]
            local = parts[3]
            peer = parts[4]
            
            # Parse local and peer addresses (handles IPv6 with brackets)
            local_ip, local_port = local.rsplit(":", 1) if ":" in local else (local, "")
            peer_ip, peer_port = peer.rsplit(":", 1) if ":" in peer else (peer, "")
            
            # Strip IPv6 brackets
            local_ip = local_ip.strip("[]")
            peer_ip = peer_ip.strip("[]")
            
            # Extract PID and process name from the last part (if present)
            proc_info = ""
            pid = None
            proc_name = ""
            for part in parts[5:]:
                if part.startswith("users:(") or part.startswith("\""):
                    proc_info = part
                    break
            if proc_info:
                m = re.search(r'pid=(\d+)', proc_info)
                if m:
                    pid = int(m.group(1))
                m = re.search(r'"([^"]+)"', proc_info)
                proc_name = m.group(1) if m else ""
            
            connections.append({
                "state": state,
                "local_ip": local_ip,
                "local_port": local_port,
                "peer_ip": peer_ip,
                "peer_port": peer_port,
                "pid": pid,
                "process": proc_name,
                "recv_q": recv_q,
                "send_q": send_q,
            })
    except Exception as e:
        print(f"Error parsing ss output for port {port}: {e}")
    
    # If no PIDs were found by ss (non-root), try /proc scanning
    if connections and all(c.get("pid") is None for c in connections):
        try:
            pids_by_addr = find_pids_for_port(port)
            if pids_by_addr:
                for conn in connections:
                    # Build the local address hex key as /proc would show it
                    ip_hex = addr_to_hex(conn["local_ip"])
                    port_hex = f":{port:04X}"
                    key = f"{ip_hex}{port_hex}"
                    matching_pids = pids_by_addr.get(key, [])
                    if matching_pids:
                        conn["pid"] = matching_pids[0]
                        conn["process"] = "sshd" if port == 22 else "vsftpd"
        except Exception as e:
            print(f"Error matching PIDs for port {port}: {e}")
    
    return connections


def is_process_alive(pid, process_name="sshd"):
    """Check if a process with the given PID exists, is not a zombie,
    and (optionally) matches the expected process name.
    Returns True if the process is alive and valid, False otherwise.
    This prevents stale TCP connections (where the client disconnected
    but the kernel hasn't closed the socket yet) from showing as active.
    """
    if pid is None:
        return False
    try:
        status_path = f"/proc/{pid}/status"
        if not os.path.exists(status_path):
            return False
        with open(status_path) as f:
            content = f.read()
        # Check process state: 'Z' = zombie (dead but not reaped)
        # 'X' = dead, 'T' = stopped — all considered not alive
        state_match = re.search(r'^State:\s+(\S)', content, re.MULTILINE)
        if state_match:
            state = state_match.group(1)
            if state in ('Z', 'X', 'T'):
                return False
        # Verify the process name matches (e.g. contains 'sshd')
        # This prevents stale or reused PIDs from being accepted
        name_match = re.search(r'^Name:\s+(.+)$', content, re.MULTILINE)
        if name_match:
            proc_name_raw = name_match.group(1).strip().lower()
            if process_name.lower() in proc_name_raw:
                return True
        return False
    except (IOError, OSError):
        return False


def addr_to_hex(ip_str):
    """Convert an IPv4 string to the hex format used by /proc/net/tcp.
    Handles both plain IPv4 ('192.168.1.184') and IPv6-mapped IPv4
    ('::ffff:192.168.1.184').
    E.g. '192.168.1.184' -> 'B801A8C0'
    """
    try:
        # Strip IPv6-mapped IPv4 prefix if present (::ffff:x.x.x.x)
        if ip_str.startswith("::ffff:"):
            ip_str = ip_str[7:]
        parts = [int(x) for x in ip_str.split(".")]
        if len(parts) == 4:
            # /proc/net/tcp uses little-endian byte order
            return f"{parts[3]:02X}{parts[2]:02X}{parts[1]:02X}{parts[0]:02X}"
    except (ValueError, TypeError):
        pass
    return "00000000"


def parse_ss_sport_bytes(port, is_server=True):
    """Parse ss -tnpi output to get bytes_acked / bytes_received per connection.
    ss -tnpi without state filter includes the State column.
    Returns dict keyed by peer address string ("IP:PORT").
    """
    bytes_by_peer = {}
    try:
        if is_server:
            # For server connections (like SSH on port 22), the server's
            # source port is :22, so we filter on sport
            result = subprocess.run(
                ["ss", "-tnpi", f"( sport = :{port} )"],
                capture_output=True, text=True, timeout=5
            )
        else:
            result = subprocess.run(
                ["ss", "-tnpi", f"( sport = :{port} or dport = :{port} )"],
                capture_output=True, text=True, timeout=5
            )
        lines = result.stdout.strip().split("\n")
        # With -tnpi (no state filter): State Recv-Q Send-Q Local Peer
        # Followed by indented TCP info on the next line
        current_peer = None
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if "ESTAB" in stripped and not stripped.startswith(" "):
                parts = stripped.split()
                # Column: State Recv-Q Send-Q Local Peer
                if len(parts) >= 5:
                    current_peer = parts[4]  # Peer address (may have brackets for IPv6-mapped)
                    # Strip brackets to match how parse_ss_output_port stores peer_ip
                    if "[" in current_peer:
                        # Extract IP from [::ffff:x.x.x.x]:port format
                        m = re.match(r'\[([^\]]+)\]:?(\d+)', current_peer)
                        if m:
                            cleaned_ip = m.group(1)
                            cleaned_port = m.group(2)
                            current_peer = f"{cleaned_ip}:{cleaned_port}"
                else:
                    current_peer = None
            elif "bytes_acked" in stripped and current_peer:
                ack_m = re.search(r'bytes_acked:(\d+)', stripped)
                recv_m = re.search(r'bytes_received:(\d+)', stripped)
                if ack_m or recv_m:
                    if current_peer not in bytes_by_peer:
                        bytes_by_peer[current_peer] = {"bytes_sent": 0, "bytes_recv": 0}
                    if ack_m:
                        bytes_by_peer[current_peer]["bytes_sent"] = int(ack_m.group(1))
                    if recv_m:
                        bytes_by_peer[current_peer]["bytes_recv"] = int(recv_m.group(1))
    except Exception as e:
        print(f"Error parsing ss -tnpi for port {port}: {e}")
    return bytes_by_peer


def get_ssh_connections():
    """Get active SSH connections with detailed info.
    Returns list of connection dicts with username, IP, PID, bytes.
    Only includes connections where a user is actually logged in
    (verified by matching 'who -u' source IPs with 'ss' peer IPs).
    """
    connections = parse_ss_output_port(22)
    
    # --------------- Get logged-in users via who -u ---------------
    # who -u output: USER TTY DATE TIME IDLE PID COMMENT
    # Each who entry has a source IP like (192.168.1.50) at the end.
    # We map source_ip -> {username, tty, login_time}.
    # This is much more reliable than process-tree matching because
    # the PID chain between sshd/sshd-session and the user's shell
    # varies across systems (traditional sshd vs sshd-session model).
    who_by_ip = {}  # source_ip -> list of who_info
    try:
        who_result = subprocess.run(
            ["who", "-u"],
            capture_output=True, text=True, timeout=5
        )
        for line in who_result.stdout.strip().split("\n"):
            if not line:
                continue
            tokens = line.split()
            if len(tokens) >= 6:
                try:
                    username = tokens[0]
                    tty = tokens[1]
                    login_time = " ".join(tokens[2:-2]) if len(tokens) > 4 else ""
                    # Extract source IP from comment at end: (192.168.1.x)
                    ip_match = re.search(r'\((\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\)', line)
                    source_ip = ip_match.group(1) if ip_match else ""
                    if source_ip:
                        if source_ip not in who_by_ip:
                            who_by_ip[source_ip] = []
                        who_by_ip[source_ip].append({
                            "username": username,
                            "tty": tty,
                            "login_time": login_time,
                        })
                except (ValueError, IndexError):
                    pass
    except Exception:
        who_by_ip = {}
    
    # Get per-connection bytes via ss -tnpi
    bytes_by_peer = parse_ss_sport_bytes(22, is_server=True)
    
    # --------------- Merge & Filter ---------------
    # Match connections to logged-in users by comparing:
    #   who -u source IP == ss peer IP (the remote user's IP)
    # When a user disconnects, who -u stops showing them,
    # so the IP won't match and the connection won't be shown.
    alive_connections = []
    for conn in connections:
        peer_ip = conn.get("peer_ip", "")
        
        # Merge bytes from ss -tnpi
        peer_addr = f"{peer_ip}:{conn['peer_port']}"
        if peer_addr in bytes_by_peer:
            conn["bytes_sent"] = bytes_by_peer[peer_addr]["bytes_sent"]
            conn["bytes_recv"] = bytes_by_peer[peer_addr]["bytes_recv"]
        else:
            conn["bytes_sent"] = 0
            conn["bytes_recv"] = 0
        
        # Match by IP: if who -u shows a user from this IP, it's active.
        if peer_ip in who_by_ip and who_by_ip[peer_ip]:
            who_info = who_by_ip[peer_ip].pop(0)  # Take first entry, then rotate
            who_by_ip[peer_ip].append(who_info)   # Rotate to end for next connection
            conn["username"] = who_info["username"]
            conn["tty"] = who_info["tty"]
            conn["login_time"] = who_info["login_time"]
            alive_connections.append(conn)
        else:
            # No matching who entry -> user logged out, filter out
            conn["username"] = None
            conn["tty"] = None
            conn["login_time"] = None
    
    return alive_connections


def get_ftp_connections():
    """Get active FTP connections with detailed info.
    FTP uses port 21 for control, ports 20/data for data connections.
    Returns list of connection dicts."""
    connections = parse_ss_output_port(21)
    
    # Also check for FTP data connections (port 20)
    data_connections = parse_ss_output_port(20)
    for dc in data_connections:
        dc["is_data"] = True
    for conn in connections:
        conn["is_data"] = False
    
    all_conns = connections + data_connections
    
    # Get bytes via ss -tnpi (FTP can have sport or dport = :21/:20)
    bytes_by_peer = parse_ss_sport_bytes(21, is_server=False)
    
    # Filter out stale connections and merge bytes
    alive_conns = []
    for conn in all_conns:
        peer_addr = f"{conn['peer_ip']}:{conn['peer_port']}"
        if peer_addr in bytes_by_peer:
            conn["bytes_sent"] = bytes_by_peer[peer_addr]["bytes_sent"]
            conn["bytes_recv"] = bytes_by_peer[peer_addr]["bytes_recv"]
        else:
            conn["bytes_sent"] = 0
            conn["bytes_recv"] = 0
        conn["username"] = None
        conn["tty"] = None
        conn["login_time"] = None
        
        # Verify the process is still alive (filter out stale connections)
        pid = conn.get("pid")
        if pid is not None:
            if is_process_alive(pid, "vsftpd") or is_process_alive(pid, "proftpd") or is_process_alive(pid, "pure-ftpd"):
                alive_conns.append(conn)
            # Stale connection — skip
        else:
            # No PID, keep connection but mark it
            alive_conns.append(conn)
            
    return alive_conns


def get_local_services_summary():
    """Get summary of all local services (SSH, FTP)."""
    ssh_conns = get_ssh_connections()
    ftp_conns = get_ftp_connections()
    
    ssh_bw = get_service_bandwidth("ssh")
    ftp_bw = get_service_bandwidth("ftp")
    
    return {
        "ssh": {
            "active_connections": len(ssh_conns),
            "unique_ips": len(set(c["peer_ip"] for c in ssh_conns if c["peer_ip"])),
            "bandwidth": ssh_bw,
        },
        "ftp": {
            "active_connections": len(ftp_conns),
            "unique_ips": len(set(c["peer_ip"] for c in ftp_conns if c["peer_ip"])),
            "bandwidth": ftp_bw,
        },
    }

# --------------- SSH Router Client ---------------
def router_connect():
    """Establish SSH connection to the OpenWrt router."""
    global ssh_client, ssh_connected
    if not HAS_PARAMIKO:
        print("⚠ paramiko not installed. Install it: pip install paramiko")
        return False
    with ssh_lock:
        try:
            if ssh_client:
                try:
                    ssh_client.close()
                except Exception:
                    pass
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_client.connect(
                ROUTER_HOST,
                port=ROUTER_PORT,
                username=ROUTER_USER,
                password=ROUTER_PASSWORD,
                timeout=8,
                allow_agent=False,
                look_for_keys=False,
            )
            ssh_connected = True
            print(f"✓ SSH connected to {ROUTER_USER}@{ROUTER_HOST}")
            return True
        except Exception as e:
            ssh_connected = False
            print(f"✗ SSH connection failed: {e}")
            return False


def router_disconnect():
    """Close the SSH connection."""
    global ssh_client, ssh_connected
    with ssh_lock:
        if ssh_client:
            try:
                ssh_client.close()
            except Exception:
                pass
        ssh_client = None
        ssh_connected = False


def router_cmd(cmd, timeout=10):
    """Run a command on the router via SSH. Returns (stdout, stderr, returncode)."""
    global ssh_client, ssh_connected
    with ssh_lock:
        if not ssh_connected or not ssh_client:
            return "", "SSH not connected", -1
        try:
            transport = ssh_client.get_transport()
            if not transport or not transport.is_active():
                ssh_connected = False
                return "", "SSH transport closed", -1
            chan = ssh_client.get_transport().open_session(timeout=timeout)
            chan.exec_command(cmd)
            
            # Read stdout
            stdout_data = b""
            while not chan.exit_status_ready():
                if chan.recv_ready():
                    stdout_data += chan.recv(65536)
                time.sleep(0.05)
            # Read remaining data
            while chan.recv_ready():
                stdout_data += chan.recv(65536)
            # Read stderr
            stderr_data = b""
            while chan.recv_stderr_ready():
                stderr_data += chan.recv_stderr(65536)
            
            status = chan.recv_exit_status()
            chan.close()
            
            return (
                stdout_data.decode("utf-8", errors="replace").strip(),
                stderr_data.decode("utf-8", errors="replace").strip(),
                status,
            )
        except Exception as e:
            ssh_connected = False
            return "", str(e), -1


def run_router(cmd, timeout=10):
    """Run command on router. Auto-reconnects if needed. Falls back to local."""
    out, err, rc = router_cmd(cmd, timeout)
    if rc == -1 and not ssh_connected:
        # Try reconnecting once
        print("SSH disconnected, trying to reconnect...")
        if router_connect():
            out, err, rc = router_cmd(cmd, timeout)
    return out, err, rc


# --------------- File I/O Helpers ---------------
def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path, default):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return default


def save_json(path, data):
    ensure_data_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_all_data():
    global nicknames, stats, speed_history, blocked_devices, current_settings, ROUTER_HOST, ROUTER_USER, ROUTER_PASSWORD, ROUTER_PORT
    nicknames = load_json(NICKNAMES_FILE, {})
    stats = load_json(STATS_FILE, {
        "total_download": 0,
        "total_upload": 0,
        "session_download": 0,
        "session_upload": 0,
        "last_reset": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
    })
    speed_history = load_json(HISTORY_FILE, [])
    blocked_devices = set(load_json(BLOCKED_FILE, []))

    # Load settings
    saved = load_json(SETTINGS_FILE, {})
    merged = dict(DEFAULT_SETTINGS)
    merged.update(saved)
    current_settings = merged
    ROUTER_HOST = current_settings["router_host"]
    ROUTER_USER = current_settings["router_user"]
    ROUTER_PASSWORD = current_settings["router_password"]
    ROUTER_PORT = current_settings["router_port"]


def save_stats():
    with data_lock:
        stats["last_updated"] = datetime.now().isoformat()
    save_json(STATS_FILE, stats)


def save_nicknames():
    save_json(NICKNAMES_FILE, nicknames)


def save_history():
    with data_lock:
        if len(speed_history) > SPEED_HISTORY_MAX:
            speed_history[:] = speed_history[-SPEED_HISTORY_MAX:]
    save_json(HISTORY_FILE, speed_history)


def save_blocked():
    with data_lock:
        save_json(BLOCKED_FILE, list(blocked_devices))


def save_settings():
    """Save current settings to disk."""
    with data_lock:
        save_json(SETTINGS_FILE, {
            "router_host": current_settings["router_host"],
            "router_user": current_settings["router_user"],
            "router_password": current_settings["router_password"],
            "router_port": current_settings["router_port"],
        })


# --------------- OpenWrt Interface Helpers ---------------
def detect_wireless_interfaces():
    """Auto-detect wireless interfaces on the router via SSH."""
    global WIRELESS_INTERFACES

    # Try ubus via SSH
    out, _, rc = run_router("ubus list 2>/dev/null | grep hostapd || true")
    if rc == 0 and out:
        interfaces = []
        for line in out.split("\n"):
            line = line.strip()
            if line.startswith("hostapd."):
                iface = line.replace("hostapd.", "")
                if iface:
                    interfaces.append(iface)
        WIRELESS_INTERFACES = interfaces
        if interfaces:
            return

    # Fallback: look for wlan-style interfaces on the router
    out, _, _ = run_router("ls /sys/class/net/ 2>/dev/null | grep -E 'wlan|ra[0-9]|ath[0-9]' || true")
    if out:
        WIRELESS_INTERFACES = out.split("\n")

    # If still nothing, try common names
    if not WIRELESS_INTERFACES:
        for iface in ["wlan0", "wlan1", "phy0-ap0", "phy1-ap0", "ra0", "rai0"]:
            out, _, rc = run_router(f"test -d /sys/class/net/{iface} && echo 'exists' || true")
            if out.strip():
                WIRELESS_INTERFACES.append(iface)


def detect_wan_interface():
    """Auto-detect the WAN interface on the router."""
    global WAN_INTERFACE
    for candidate in ["wan", "eth0.2", "pppoe-wan", "vwan", "wwan"]:
        out, _, rc = run_router(f"test -d /sys/class/net/{candidate} && echo 'exists' || true")
        if out.strip():
            WAN_INTERFACE = candidate
            return
    # If nothing found, try to find an interface with a default route
    out, _, _ = run_router("ip route show default 2>/dev/null | awk '{print $5}' | head -1 || true")
    if out.strip():
        WAN_INTERFACE = out.strip()


def get_wan_bytes():
    """Get cumulative RX/TX bytes for the WAN interface via SSH."""
    rx = None
    tx = None
    rx_str, _, rc = run_router(f"cat /sys/class/net/{WAN_INTERFACE}/statistics/rx_bytes 2>/dev/null || echo 'err'")
    tx_str, _, _ = run_router(f"cat /sys/class/net/{WAN_INTERFACE}/statistics/tx_bytes 2>/dev/null || echo 'err'")
    if rc == 0 and rx_str and rx_str != 'err':
        try:
            rx = int(rx_str.strip())
        except ValueError:
            pass
    if tx_str and tx_str != 'err':
        try:
            tx = int(tx_str.strip())
        except ValueError:
            pass
    return rx, tx


def get_dhcp_leases():
    """Parse DHCP leases from the router via SSH."""
    devices = []
    out, _, rc = run_router("cat /tmp/dhcp.leases 2>/dev/null || echo 'err'")
    if rc != 0 or not out or out == 'err':
        return devices
    for line in out.split("\n"):
        parts = line.strip().split()
        if len(parts) >= 4:
            mac = parts[1]
            ip = parts[2]
            hostname = parts[3] if parts[3] != "*" else ""
            devices.append({
                "mac": mac.upper(),
                "ip": ip,
                "hostname": hostname,
                "source": "dhcp",
                "online": False,
            })
    return devices


def get_wireless_clients():
    """Get connected wireless clients via SSH ubus."""
    clients = {}
    for iface in WIRELESS_INTERFACES:
        out, _, rc = run_router(f"ubus call hostapd.{iface} get_clients 2>/dev/null || true")
        if rc != 0 or not out:
            continue
        try:
            data = json.loads(out)
            for mac, info in data.items():
                mac_upper = mac.upper()
                clients[mac_upper] = {
                    "mac": mac_upper,
                    "signal": info.get("signal", 0),
                    "connected_time": info.get("connected_time", 0),
                    "rx_bytes": info.get("bytes", [0, 0])[0] if isinstance(info.get("bytes"), list) else 0,
                    "tx_bytes": info.get("bytes", [0, 0])[1] if isinstance(info.get("bytes"), list) else 0,
                    "source": "wireless",
                }
        except (json.JSONDecodeError, AttributeError):
            pass
    return clients


def get_arp_table():
    """Get ARP table from the router via SSH."""
    arp_devices = {}
    out, _, rc = run_router("arp -an 2>/dev/null || ip neigh show 2>/dev/null || true")
    if rc != 0 or not out:
        return arp_devices
    for line in out.split("\n"):
        m = re.search(r'\(([\d.]+)\)\s+at\s+([0-9a-fA-F:]+)', line)
        if m:
            ip = m.group(1)
            mac = m.group(2).upper()
            if mac and mac != "(INCOMPLETE)" and ":" in mac:
                arp_devices[mac] = {"ip": ip, "mac": mac}
    return arp_devices


def get_interface_list():
    """Get network interfaces from the router via SSH."""
    out, _, _ = run_router("ls /sys/class/net/ 2>/dev/null || true")
    return out.split("\n") if out else []


def get_router_info():
    """Get router system info via SSH."""
    hostname, _, _ = run_router("uci get system.@system[0].hostname 2>/dev/null || hostname")
    model, _, _ = run_router("cat /proc/cpuinfo 2>/dev/null | grep -E '(machine|system type)' | head -1 | cut -d: -f2 || cat /tmp/sysinfo/model 2>/dev/null || echo 'OpenWrt'")
    uptime_str, _, _ = run_router("cat /proc/uptime 2>/dev/null | awk '{print int($1)}' || echo 0")
    loadavg, _, _ = run_router("cat /proc/loadavg 2>/dev/null | awk '{print $1\",\"$2\",\"$3}' || echo '0,0,0'")
    
    mem_info = {}
    mem_raw, _, _ = run_router("cat /proc/meminfo 2>/dev/null || true")
    if mem_raw:
        for line in mem_raw.split("\n"):
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().split()[0]
                try:
                    mem_info[key] = int(val) * 1024
                except (ValueError, IndexError):
                    pass

    uptime_val = 0
    try:
        uptime_val = int(float(uptime_str.strip()))
    except (ValueError, TypeError):
        pass

    return {
        "hostname": hostname.strip() or "OpenWrt",
        "model": model.strip() or "Unknown",
        "uptime": uptime_val,
        "load_average": loadavg.strip() or "0,0,0",
        "memory_total": mem_info.get("MemTotal", 0),
        "memory_free": mem_info.get("MemFree", 0),
        "memory_available": mem_info.get("MemAvailable", 0),
        "ssh_connected": ssh_connected,
    }


def block_device(mac):
    """Block a device by MAC via SSH iptables."""
    mac = mac.upper()
    if not re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', mac):
        return False, "Invalid MAC address format"

    with data_lock:
        blocked_devices.add(mac)
    save_blocked()

    cmds = [
        f"iptables -C FORWARD -m mac --mac-source {mac} -j DROP 2>/dev/null || iptables -I FORWARD -m mac --mac-source {mac} -j DROP",
        f"iptables -C INPUT -m mac --mac-source {mac} -j DROP 2>/dev/null || iptables -I INPUT -m mac --mac-source {mac} -j DROP",
    ]
    for cmd in cmds:
        run_router(cmd)

    return True, "Device blocked"


def unblock_device(mac):
    """Unblock a device by MAC via SSH iptables."""
    mac = mac.upper()
    with data_lock:
        blocked_devices.discard(mac)
    save_blocked()

    cmds = [
        f"iptables -D FORWARD -m mac --mac-source {mac} -j DROP 2>/dev/null || true",
        f"iptables -D INPUT -m mac --mac-source {mac} -j DROP 2>/dev/null || true",
    ]
    for cmd in cmds:
        run_router(cmd)

    return True, "Device unblocked"


def disconnect_device(mac):
    """Disconnect a wireless device via SSH ubus."""
    mac = mac.upper()
    success = False
    for iface in WIRELESS_INTERFACES:
        out, _, rc = run_router(f"ubus call hostapd.{iface} del_client '{{\"addr\":\"{mac}\",\"reason\":5,\"deauth\":true,\"ban\":false}}' 2>/dev/null || true")
        if rc == 0:
            success = True
    if not success and WIRELESS_INTERFACES:
        last_iface = WIRELESS_INTERFACES[-1]
        run_router(f"iw dev {last_iface} station del {mac} 2>/dev/null || true")
    msg = "Device disconnected" if success else "Could not disconnect device"
    return success, msg


def get_current_blocked_rules():
    """Get active iptables block rules from the router via SSH."""
    macs = set()
    out, _, _ = run_router("iptables -L FORWARD -n 2>/dev/null | grep -oE '([0-9A-F]{2}:){5}[0-9A-F]{2}' || true")
    if out:
        for line in out.split("\n"):
            mac = line.strip().upper()
            if re.match(r'^([0-9A-F]{2}:){5}[0-9A-F]{2}$', mac):
                macs.add(mac)
    return macs


# --------------- Speed Monitoring Thread ---------------
def poll_speed():
    """Background thread polling bandwidth from the router via SSH."""
    global last_rx_bytes, last_tx_bytes, last_poll_time, stats, speed_history

    while True:
        try:
            rx, tx = get_wan_bytes()
            now = time.time()
            save_this_cycle = int(now) % STATS_SAVE_INTERVAL < SPEED_POLL_INTERVAL

            if rx is not None and tx is not None:
                with data_lock:
                    if last_rx_bytes is not None and last_tx_bytes is not None and last_poll_time is not None:
                        elapsed = now - last_poll_time
                        if elapsed > 0:
                            dl_speed = max(0, (rx - last_rx_bytes) / elapsed)
                            ul_speed = max(0, (tx - last_tx_bytes) / elapsed)

                            # Protect against router reboots (counters reset)
                            rx_delta = max(0, rx - last_rx_bytes)
                            tx_delta = max(0, tx - last_tx_bytes)
                            stats["total_download"] += rx_delta
                            stats["total_upload"] += tx_delta
                            stats["session_download"] += rx_delta
                            stats["session_upload"] += tx_delta


                            speed_history.append({
                                "timestamp": datetime.now().isoformat(),
                                "download_speed": round(dl_speed, 2),
                                "upload_speed": round(ul_speed, 2),
                            })

                            if len(speed_history) > SPEED_HISTORY_MAX:
                                speed_history = speed_history[-SPEED_HISTORY_MAX:]

                    last_rx_bytes = rx
                    last_tx_bytes = tx
                    last_poll_time = now

            if save_this_cycle:
                save_stats()
                save_history()

        except Exception as e:
            print(f"Error in speed polling: {e}", file=sys.stderr)

        time.sleep(SPEED_POLL_INTERVAL)


# --------------- API Routes ---------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/devices")
def api_devices():
    dhcp_devices = get_dhcp_leases()
    wireless_clients = get_wireless_clients()
    arp_table = get_arp_table()

    device_map = {}

    for d in dhcp_devices:
        mac = d["mac"]
        device_map[mac] = {
            "mac": mac,
            "ip": d["ip"],
            "hostname": d.get("hostname", "") or "",
            "nickname": nicknames.get(d["ip"], ""),
            "source": "dhcp",
            "online": mac in wireless_clients or mac in arp_table,
            "signal": 0,
            "connected_time": 0,
            "rx_bytes": 0,
            "tx_bytes": 0,
            "blocked": mac in blocked_devices,
        }

    for mac, info in wireless_clients.items():
        if mac in device_map:
            device_map[mac].update({
                "online": True,
                "signal": info.get("signal", 0),
                "connected_time": info.get("connected_time", 0),
                "rx_bytes": info.get("rx_bytes", 0),
                "tx_bytes": info.get("tx_bytes", 0),
                "source": "wireless",
            })
        else:
            ip = arp_table.get(mac, {}).get("ip", "")
            device_map[mac] = {
                "mac": mac,
                "ip": ip,
                "hostname": "",
                "nickname": nicknames.get(ip, ""),
                "source": "wireless",
                "online": True,
                "signal": info.get("signal", 0),
                "connected_time": info.get("connected_time", 0),
                "rx_bytes": info.get("rx_bytes", 0),
                "tx_bytes": info.get("tx_bytes", 0),
                "blocked": mac in blocked_devices,
            }

    for mac, info in arp_table.items():
        if mac not in device_map:
            ip = info["ip"]
            device_map[mac] = {
                "mac": mac,
                "ip": ip,
                "hostname": "",
                "nickname": nicknames.get(ip, ""),
                "source": "arp",
                "online": True,
                "signal": 0,
                "connected_time": 0,
                "rx_bytes": 0,
                "tx_bytes": 0,
                "blocked": mac in blocked_devices,
            }

    devices = sorted(device_map.values(), key=lambda d: (
        not d["online"],
        not (d["nickname"] or d["hostname"]),
        d["nickname"] or d["hostname"] or d["ip"] or d["mac"],
    ))

    return jsonify({
        "devices": devices,
        "total": len(devices),
        "online": sum(1 for d in devices if d["online"]),
    })


@app.route("/api/speed")
def api_speed():
    with data_lock:
        if speed_history:
            latest = speed_history[-1]
            dl = latest["download_speed"]
            ul = latest["upload_speed"]
        else:
            dl = 0
            ul = 0

    return jsonify({
        "download_speed": dl,
        "upload_speed": ul,
        "download_bps": dl,
        "upload_bps": ul,
        "download_kbps": round(dl / 1024, 2),
        "upload_kbps": round(ul / 1024, 2),
        "download_mbps": round(dl / (1024 * 1024), 3),
        "upload_mbps": round(ul / (1024 * 1024), 3),
    })


@app.route("/api/history")
def api_history():
    with data_lock:
        hist = list(speed_history)
    max_points = 120
    if len(hist) > max_points:
        step = len(hist) // max_points
        hist = hist[::step][-max_points:]
    return jsonify({"history": hist})


@app.route("/api/stats")
def api_stats():
    with data_lock:
        s = dict(stats)

    s["total_download_human"] = format_bytes(s["total_download"])
    s["total_upload_human"] = format_bytes(s["total_upload"])
    s["session_download_human"] = format_bytes(s["session_download"])
    s["session_upload_human"] = format_bytes(s["session_upload"])

    with data_lock:
        if speed_history:
            avg_dl = sum(h["download_speed"] for h in speed_history) / len(speed_history)
            avg_ul = sum(h["upload_speed"] for h in speed_history) / len(speed_history)
        else:
            avg_dl = 0
            avg_ul = 0

    s["average_download_kbps"] = round(avg_dl / 1024, 2)
    s["average_upload_kbps"] = round(avg_ul / 1024, 2)
    s["router"] = get_router_info()

    dhcp = get_dhcp_leases()
    wireless = get_wireless_clients()
    s["total_devices_known"] = len(dhcp)
    s["total_devices_online"] = len(wireless)
    s["blocked_devices_count"] = len(blocked_devices)

    return jsonify(s)


@app.route("/api/nickname", methods=["POST"])
def api_set_nickname():
    data = request.get_json()
    if not data or "ip" not in data:
        return jsonify({"success": False, "error": "Missing 'ip' field"}), 400
    ip = data["ip"]
    nickname = data.get("nickname", "").strip()
    with data_lock:
        if nickname:
            nicknames[ip] = nickname
        elif ip in nicknames:
            del nicknames[ip]
    save_nicknames()
    return jsonify({"success": True, "ip": ip, "nickname": nickname})


@app.route("/api/nicknames")
def api_get_nicknames():
    with data_lock:
        return jsonify({"nicknames": dict(nicknames)})


@app.route("/api/block/<mac>", methods=["POST"])
def api_block_device(mac):
    success, message = block_device(mac)
    return jsonify({"success": success, "message": message}), 200 if success else 400


@app.route("/api/unblock/<mac>", methods=["POST"])
def api_unblock_device(mac):
    success, message = unblock_device(mac)
    return jsonify({"success": success, "message": message})


@app.route("/api/disconnect/<mac>", methods=["POST"])
def api_disconnect_device(mac):
    success, message = disconnect_device(mac)
    return jsonify({"success": success, "message": message}), 200 if success else 400


@app.route("/api/blocked")
def api_blocked():
    rules_macs = get_current_blocked_rules()
    with data_lock:
        all_blocked = set(blocked_devices) | rules_macs
    blocked_list = [
        {"mac": mac, "nickname": "", "in_config": mac in blocked_devices, "in_iptables": mac in rules_macs}
        for mac in all_blocked
    ]
    return jsonify({"blocked": blocked_list})


@app.route("/api/reset-stats", methods=["POST"])
def api_reset_stats():
    with data_lock:
        stats["session_download"] = 0
        stats["session_upload"] = 0
        stats["total_download"] = 0
        stats["total_upload"] = 0
        stats["last_reset"] = datetime.now().isoformat()
    save_stats()
    return jsonify({"success": True, "message": "Stats reset"})


@app.route("/api/info")
def api_info():
    info = get_router_info()
    info["wireless_interfaces"] = WIRELESS_INTERFACES
    info["wan_interface"] = WAN_INTERFACE
    info["all_interfaces"] = get_interface_list()

    ubus_ok, _, _ = run_router("which ubus 2>/dev/null && echo 'ok' || echo ''")
    iptables_ok, _, _ = run_router("which iptables 2>/dev/null && echo 'ok' || echo ''")

    info["tools"] = {
        "ubus": bool(ubus_ok.strip()),
        "iptables": bool(iptables_ok.strip()),
    }

    info["app_uptime"] = time.time() - app_start_time
    with data_lock:
        info["speed_history_points"] = len(speed_history)
    info["ssh_connected"] = ssh_connected

    return jsonify(info)


@app.route("/api/export/csv")
def api_export_csv():
    """Export all data as a CSV file."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["=== HomeLab Network Monitor - Export ==="])
    writer.writerow(["Exported", datetime.now().isoformat()])
    writer.writerow([])

    # Local Services Summary
    writer.writerow(["=== Local Services ==="])
    services = get_local_services_summary()
    for svc_name, svc_data in services.items():
        writer.writerow([f"Service ({svc_name.upper()})"])
        writer.writerow(["  Active Connections", svc_data.get("active_connections", 0)])
        writer.writerow(["  Unique IPs", svc_data.get("unique_ips", 0)])
        bw = svc_data.get("bandwidth", {})
        writer.writerow(["  Bytes In", bw.get("bytes_in", 0)])
        writer.writerow(["  Bytes Out", bw.get("bytes_out", 0)])
        writer.writerow(["  Packets In", bw.get("packets_in", 0)])
        writer.writerow(["  Packets Out", bw.get("packets_out", 0)])
    writer.writerow([])

    # SSH Connections Detail
    writer.writerow(["=== SSH Connections ==="])
    writer.writerow(["Username", "Source IP", "Local IP", "State", "PID", "Process", "Bytes Sent", "Bytes Recv"])
    try:
        ssh_conns = get_ssh_connections()
        for c in ssh_conns:
            writer.writerow([
                c.get("username", ""),
                c.get("peer_ip", ""),
                c.get("local_ip", ""),
                c.get("state", ""),
                c.get("pid", ""),
                c.get("process", ""),
                c.get("bytes_sent", 0),
                c.get("bytes_recv", 0),
            ])
    except Exception:
        writer.writerow(["Error fetching SSH connections"])
    writer.writerow([])

    # FTP Connections Detail
    writer.writerow(["=== FTP Connections ==="])
    writer.writerow(["Source IP", "Local IP", "Port", "Type", "State", "PID", "Bytes Sent", "Bytes Recv"])
    try:
        ftp_conns = get_ftp_connections()
        for c in ftp_conns:
            port_type = "Data (20)" if c.get("is_data") else "Control (21)"
            writer.writerow([
                c.get("peer_ip", ""),
                c.get("local_ip", ""),
                c.get("local_port", ""),
                port_type,
                c.get("state", ""),
                c.get("pid", ""),
                c.get("bytes_sent", 0),
                c.get("bytes_recv", 0),
            ])
    except Exception:
        writer.writerow(["Error fetching FTP connections"])
    writer.writerow([])
    writer.writerow([])

    # Router Info
    writer.writerow(["=== Router Info ==="])
    info = get_router_info()
    writer.writerow(["Hostname", info.get("hostname", "")])
    writer.writerow(["Model", info.get("model", "")])
    writer.writerow(["Uptime (seconds)", info.get("uptime", 0)])
    writer.writerow(["Load Average", info.get("load_average", "")])
    writer.writerow(["Memory Total", info.get("memory_total", 0)])
    writer.writerow(["Memory Available", info.get("memory_available", 0)])
    writer.writerow(["WAN Interface", WAN_INTERFACE])
    writer.writerow(["Wireless Interfaces", ", ".join(WIRELESS_INTERFACES)])
    writer.writerow(["SSH Connected", info.get("ssh_connected", False)])
    writer.writerow([])

    # Usage Stats
    writer.writerow(["=== Usage Statistics ==="])
    with data_lock:
        writer.writerow(["Total Downloaded (bytes)", stats.get("total_download", 0)])
        writer.writerow(["Total Uploaded (bytes)", stats.get("total_upload", 0)])
        writer.writerow(["Session Downloaded (bytes)", stats.get("session_download", 0)])
        writer.writerow(["Session Uploaded (bytes)", stats.get("session_upload", 0)])
        writer.writerow(["Last Reset", stats.get("last_reset", "")])
        writer.writerow(["Last Updated", stats.get("last_updated", "")])

        if speed_history:
            avg_dl = sum(h["download_speed"] for h in speed_history) / len(speed_history)
            avg_ul = sum(h["upload_speed"] for h in speed_history) / len(speed_history)
            writer.writerow(["Average Download Speed (bps)", round(avg_dl, 2)])
            writer.writerow(["Average Upload Speed (bps)", round(avg_ul, 2)])
    writer.writerow([])

    # Peak Speeds
    writer.writerow(["=== Peak Speeds (from history) ==="])
    with data_lock:
        if speed_history:
            peak_dl = max(h["download_speed"] for h in speed_history)
            peak_ul = max(h["upload_speed"] for h in speed_history)
            writer.writerow(["Peak Download Speed (bps)", round(peak_dl, 2)])
            writer.writerow(["Peak Upload Speed (bps)", round(peak_ul, 2)])
    writer.writerow([])

    # Connected Devices
    writer.writerow(["=== Connected Devices ==="])
    writer.writerow(["MAC", "IP", "Hostname", "Nickname", "Status", "Signal (dBm)", "RX Bytes", "TX Bytes", "Blocked"])
    dhcp_devices = get_dhcp_leases()
    wireless_clients = get_wireless_clients()
    arp_table = get_arp_table()
    seen_macs = set()
    for d in dhcp_devices:
        mac = d["mac"]
        seen_macs.add(mac)
        online = mac in wireless_clients or mac in arp_table
        wc = wireless_clients.get(mac, {})
        writer.writerow([
            mac,
            d["ip"],
            d.get("hostname", ""),
            nicknames.get(d["ip"], ""),
            "Online" if online else "Offline",
            wc.get("signal", ""),
            wc.get("rx_bytes", 0),
            wc.get("tx_bytes", 0),
            "Yes" if mac in blocked_devices else "No",
        ])
    for mac, wc in wireless_clients.items():
        if mac not in seen_macs:
            seen_macs.add(mac)
            ip = arp_table.get(mac, {}).get("ip", "")
            writer.writerow([
                mac,
                ip,
                "",
                nicknames.get(ip, ""),
                "Online",
                wc.get("signal", ""),
                wc.get("rx_bytes", 0),
                wc.get("tx_bytes", 0),
                "Yes" if mac in blocked_devices else "No",
            ])
    writer.writerow([])

    # Blocked Devices
    writer.writerow(["=== Blocked Devices ==="])
    writer.writerow(["MAC", "In Config", "In iptables"])
    rules_macs = get_current_blocked_rules()
    with data_lock:
        all_blocked = set(blocked_devices) | rules_macs
    for mac in sorted(all_blocked):
        writer.writerow([mac, "Yes" if mac in blocked_devices else "No", "Yes" if mac in rules_macs else "No"])
    writer.writerow([])

    # Nicknames
    writer.writerow(["=== IP Nicknames ==="])
    writer.writerow(["IP", "Nickname"])
    with data_lock:
        for ip, nick in sorted(nicknames.items()):
            writer.writerow([ip, nick])
    writer.writerow([])

    # Speed History (sampled)
    writer.writerow(["=== Speed History (last 200 samples) ==="])
    writer.writerow(["Timestamp", "Download Speed (bps)", "Upload Speed (bps)"])
    with data_lock:
        sample = speed_history[-200:] if len(speed_history) > 200 else list(speed_history)
        for h in sample:
            writer.writerow([h["timestamp"], h["download_speed"], h["upload_speed"]])

    csv_content = output.getvalue()
    output.close()

    response = app.response_class(
        response=csv_content,
        status=200,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="homelab-monitor-{datetime.now().strftime("%Y%m%d-%H%M%S")}.csv"'},
    )
    return response


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """Return current router connection settings (password masked)."""
    with data_lock:
        s = dict(current_settings)
    # Mask the password for security
    if s.get("router_password"):
        pwd = s["router_password"]
        if len(pwd) > 4:
            s["router_password"] = pwd[:2] + "••••" + pwd[-1]
        elif len(pwd) > 0:
            s["router_password"] = "••••"
    s["ssh_connected"] = ssh_connected
    return jsonify(s)


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    """Update router connection settings and reconnect."""
    global current_settings, ROUTER_HOST, ROUTER_USER, ROUTER_PASSWORD, ROUTER_PORT
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    host = data.get("router_host", "").strip()
    user = data.get("router_user", "").strip()
    password = data.get("router_password", "").strip()
    try:
        port = int(data.get("router_port", 22))
    except (ValueError, TypeError):
        port = 22

    if not host:
        return jsonify({"success": False, "error": "Router host is required"}), 400
    if not user:
        return jsonify({"success": False, "error": "Router username is required"}), 400
    if port < 1 or port > 65535:
        return jsonify({"success": False, "error": "Port must be between 1 and 65535"}), 400

    with data_lock:
        # If password is masked (unchanged), keep the old one
        if password and "••••" in password:
            password = current_settings.get("router_password", password)

        current_settings["router_host"] = host
        current_settings["router_user"] = user
        current_settings["router_password"] = password
        current_settings["router_port"] = port

        ROUTER_HOST = host
        ROUTER_USER = user
        ROUTER_PASSWORD = password
        ROUTER_PORT = port

    save_settings()

    # Disconnect old session
    router_disconnect()

    # Reconnect with new credentials
    success = router_connect()
    message = "Settings saved"
    if success:
        message += " and reconnected successfully"
        # Re-detect interfaces after reconnect
        detect_wireless_interfaces()
        detect_wan_interface()
    else:
        message += ". SSH connection failed — check credentials and try again"

    return jsonify({"success": True, "message": message, "ssh_connected": ssh_connected})


@app.route("/api/reconnect", methods=["POST"])
def api_reconnect():
    """Force reconnection to the router."""
    success = router_connect()
    if success:
        detect_wireless_interfaces()
        detect_wan_interface()
    return jsonify({
        "success": success,
        "message": "Reconnected to router" if success else "Failed to reconnect",
        "ssh_connected": ssh_connected,
    })


# --------------- API: Local Services ---------------
@app.route("/api/services")
def api_services():
    """Get summary of all local services (SSH, FTP)."""
    return jsonify(get_local_services_summary())


@app.route("/api/service/ssh")
def api_service_ssh():
    """Get detailed SSH connection information."""
    connections = get_ssh_connections()
    total_bw = get_service_bandwidth("ssh")
    return jsonify({
        "connections": connections,
        "total_connections": len(connections),
        "total_bandwidth": total_bw,
    })


@app.route("/api/service/ftp")
def api_service_ftp():
    """Get detailed FTP connection information."""
    connections = get_ftp_connections()
    total_bw = get_service_bandwidth("ftp")
    return jsonify({
        "connections": connections,
        "total_connections": len(connections),
        "total_bandwidth": total_bw,
    })


# --------------- Helpers ---------------
def format_bytes(b):
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    else:
        return f"{b / (1024 * 1024 * 1024):.2f} GB"


# --------------- Startup ---------------
app_start_time = time.time()


def initialize():
    """Initialize the application."""
    ensure_data_dir()
    load_all_data()

    # Connect to router
    if HAS_PARAMIKO:
        print(f"Connecting to {ROUTER_HOST} via SSH...")
        if router_connect():
            detect_wan_interface()
            detect_wireless_interfaces()
        else:
            print("⚠ Could not connect to router. Some features will be unavailable.")
            print("  Make sure the router is reachable and SSH is enabled.")
            print("  You can try reconnecting from the dashboard or via the /api/reconnect endpoint.")
    else:
        print("⚠ paramiko not installed. Install with: pip install paramiko")
        print("  Until then, router stats will not work.")

    # Start speed polling thread
    poll_thread = threading.Thread(target=poll_speed, daemon=True)
    poll_thread.start()

    # Set up iptables rules for local service bandwidth tracking
    print("Setting up iptables rules for SSH/FTP bandwidth tracking...")
    setup_service_iptables()

    print(f"✓ WAN interface: {WAN_INTERFACE}")
    print(f"✓ Wireless interfaces: {WIRELESS_INTERFACES or 'none detected'}")
    print(f"✓ Data directory: {DATA_DIR}")
    print(f"✓ Speed polling: every {SPEED_POLL_INTERVAL}s, history: {SPEED_HISTORY_MAX} points")
    print(f"✓ Local service monitoring: SSH (port 22), FTP (port 21)")


if __name__ == "__main__":
    initialize()
    print(f"\n{'='*50}")
    print(f"  HomeLab Network Monitor")
    print(f"  Router: {ROUTER_USER}@{ROUTER_HOST}")
    print(f"  SSH/FTP monitoring: localhost")
    print(f"  Running on http://0.0.0.0:6767")
    print(f"  Open in browser: http://localhost:6767")
    print(f"{'='*50}\n")

    def shutdown(sig, frame):
        print("\nShutting down... saving data...")
        save_stats()
        save_history()
        router_disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    app.run(host="0.0.0.0", port=6767, debug=False, use_reloader=False)
