#!/usr/bin/env python3
import sys
import os
import socket
import subprocess
import time

try:
    import psutil
except ImportError:
    print("Error: 'psutil' is not installed in the active environment.")
    print("Please activate your virtual environment (.venv) first, or run 'pip install psutil'.")
    sys.exit(1)

def run_cmd(cmd, sudo=False):
    """Run a shell command and return stdout. Raises subprocess.CalledProcessError on failure."""
    if sudo and os.getuid() != 0:
        cmd = ["sudo"] + cmd
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()

def get_macos_service_name(device_name):
    """Map a BSD device name (like en1 or bridge0) to its macOS Network Service Name."""
    try:
        output = run_cmd(["networksetup", "-listallhardwareports"])
        lines = output.split("\n")
        current_port = None
        for i, line in enumerate(lines):
            if line.startswith("Hardware Port:"):
                current_port = line.replace("Hardware Port:", "").strip()
            elif line.startswith("Device:") and current_port:
                dev = line.replace("Device:", "").strip()
                if dev == device_name:
                    return current_port
    except Exception:
        pass
    
    # Fallback to listing all services and matching
    try:
        services_output = run_cmd(["networksetup", "-listallnetworkservices"])
        services = [s.strip() for s in services_output.split("\n")[1:] if s.strip()]
        for service in services:
            if device_name.lower() in service.lower() or "thunderbolt" in service.lower():
                return service
    except Exception:
        pass
    return None

def detect_link_interface():
    """Scan all interfaces for an active link-local address (169.254.x.x) or connected states."""
    print("Scanning network interfaces for active link cable connection...")
    
    # 1. Look for automatic link-local (169.254.x.x) IP address (most reliable indicator of direct connection)
    for iface, addrs in psutil.net_if_addrs().items():
        # Skip loopback
        if iface.startswith("lo"):
            continue
        for addr in addrs:
            if addr.family == socket.AF_INET:
                if addr.address.startswith("169.254."):
                    print(f" -> Found active link-local interface: '{iface}' (IP: {addr.address})")
                    return iface
                    
    # 2. Fallback: Ask user if they want to pick from active interfaces
    print("\nNo link-local (169.254.x.x) IP detected yet.")
    print("Checking for connected interfaces without global IPs...")
    
    active_interfaces = []
    stats = psutil.net_if_stats()
    for iface, addrs in psutil.net_if_addrs().items():
        if iface.startswith("lo"):
            continue
        stat = stats.get(iface)
        if stat and stat.isup:
            # Check if it has a global IPv4 already
            has_global_ip = False
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127.") and not addr.address.startswith("169.254."):
                    has_global_ip = True
            
            # Interfaces that are UP but don't have a main internet IP are likely our link cable
            if not has_global_ip:
                active_interfaces.append(iface)
                
    if active_interfaces:
        if len(active_interfaces) == 1:
            print(f" -> Auto-detected candidate interface: '{active_interfaces[0]}'")
            return active_interfaces[0]
            
        print("\nMultiple candidate interfaces found. Please select your link cable interface:")
        for idx, iface in enumerate(active_interfaces, 1):
            print(f" [{idx}] {iface}")
        try:
            choice = int(input("Select interface number: ")) - 1
            if 0 <= choice < len(active_interfaces):
                return active_interfaces[choice]
        except Exception:
            pass
            
    return None

def main():
    print("=" * 80)
    print("GEOCENTRIC 2.1 LINK CABLE AUTO-CONFIGURATOR")
    print("=" * 80)
    
    # Check if run as root
    is_root = os.getuid() == 0
    if not is_root:
        print("Note: This script configures network hardware and will prompt for sudo permissions.")
        
    is_mac = sys.platform == "darwin"
    is_linux = sys.platform.startswith("linux")
    
    if not is_mac and not is_linux:
        print(f"Error: Unsupported operating system: {sys.platform}")
        sys.exit(1)
        
    # Attempt to detect link cable interface (retry up to 5 times)
    iface = None
    for attempt in range(5):
        iface = detect_link_interface()
        if iface:
            break
        print(f"No link interface detected yet (Attempt {attempt+1}/5). Retrying in 2 seconds...")
        time.sleep(2)
        
    if not iface:
        print("\n[!] Setup failed: Could not automatically detect the link cable network interface.")
        print("Make sure your USB/Thunderbolt cable is plugged into BOTH computers and active.")
        sys.exit(1)
        
    print(f"\nConfiguring interface '{iface}' for high-speed collaborative training...")
    
    if is_mac:
        # macOS Configuration
        service_name = get_macos_service_name(iface)
        if not service_name:
            # Fallback to Thunderbolt Bridge
            service_name = "Thunderbolt Bridge"
            
        print(f"macOS Network Service detected: '{service_name}'")
        target_ip = "192.168.99.1"
        try:
            print(f"Setting static IP {target_ip} on '{service_name}'...")
            run_cmd(["networksetup", "-setmanual", service_name, target_ip, "255.255.255.0"], sudo=True)
            print("\n" + "=" * 80)
            print(" SUCCESS: macOS Link Cable Network Configured Successfully!")
            print(f" Your Mac's Link IP is: {target_ip}")
            print("=" * 80 + "\n")
        except Exception as e:
            print(f"networksetup failed: {e}. Trying low-level BSD ifconfig fallback...")
            try:
                run_cmd(["ifconfig", iface, target_ip, "netmask", "255.255.255.0", "up"], sudo=True)
                print("\n" + "=" * 80)
                print(" SUCCESS: macOS Link Cable Network Configured via ifconfig!")
                print(f" Your Mac's Link IP is: {target_ip}")
                print("=" * 80 + "\n")
            except Exception as e2:
                print(f"\nError configuring macOS interface: {e2}")
                print("Please configure manual IP 192.168.99.1 on your link interface in Network Settings.")
                sys.exit(1)
            
    elif is_linux:
        # Linux (Ubuntu) Configuration
        target_ip = "192.168.99.2"
        try:
            print(f"Flushing existing addresses on '{iface}'...")
            try:
                run_cmd(["ip", "addr", "flush", "dev", iface], sudo=True)
            except Exception:
                pass
                
            print(f"Assigning static IP {target_ip}/24 to '{iface}'...")
            run_cmd(["ip", "addr", "add", f"{target_ip}/24", "dev", iface], sudo=True)
            run_cmd(["ip", "link", "set", "dev", iface, "up"], sudo=True)
            
            # Configure NetworkManager if available so it doesn't fight us
            try:
                run_cmd(["nmcli", "device", "set", iface, "managed", "no"], sudo=True)
            except Exception:
                pass
                
            print("\n" + "=" * 80)
            print(" SUCCESS: Linux Link Cable Network Configured Successfully!")
            print(f" Your Linux PC's Link IP is: {target_ip}")
            print("=" * 80 + "\n")
        except Exception as e:
            print(f"\nError configuring Linux interface: {e}")
            print(f"Please run this manual command on Linux: sudo ip addr add {target_ip}/24 dev {iface}")
            sys.exit(1)

if __name__ == "__main__":
    main()
