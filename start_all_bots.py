#!/usr/bin/env python3
"""
START ALL BOTS - Single unified launcher

Starts all 4 processes:
1. Central signal fetcher
2. Bot 1 (Inverter - 13:00-17:00 IST)
3. Bot 2 (Follower)
4. Bot 3 (Follower)

Each runs in its own process with independent logging.

Usage:
    python start_all_bots.py          # Start all bots
    python start_all_bots.py --test   # Test mode (no signal fetcher, bots run for 60s)
    python start_all_bots.py --help   # Show help
"""

import sys
import os
import subprocess
import time
import signal
import argparse
from datetime import datetime

# Color codes for terminal output
GREEN = '\033[92m'
BLUE = '\033[94m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'
BOLD = '\033[1m'

processes = []
test_mode = False
start_time = None


def print_header(msg):
    """Print colored header message."""
    print(f"{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}{msg:^70}{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}\n")


def print_status(bot_name, status, details=""):
    """Print status message with color."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    if status == "STARTING":
        color = YELLOW
    elif status == "RUNNING":
        color = GREEN
    elif status == "ERROR":
        color = RED
    else:
        color = BLUE

    msg = f"[{timestamp}] {bot_name}: {status}"
    if details:
        msg += f" - {details}"
    print(f"{color}{msg}{RESET}")


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    print(f"\n{RED}{BOLD}Stopping all bots...{RESET}\n")
    for proc_info in processes:
        if proc_info['process'] and proc_info['process'].poll() is None:
            print_status(proc_info['name'], "STOPPING")
            try:
                proc_info['process'].terminate()
                proc_info['process'].wait(timeout=5)
            except subprocess.TimeoutExpired:
                print_status(proc_info['name'], "FORCE KILL")
                proc_info['process'].kill()

    print(f"{GREEN}{BOLD}All bots stopped.{RESET}")
    sys.exit(0)


def start_process(cmd, name, env_vars=None):
    """Start a subprocess and track it."""
    try:
        print_status(name, "STARTING", f"Command: {' '.join(cmd)}")

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env
        )

        processes.append({
            'name': name,
            'process': proc,
            'cmd': cmd,
            'start_time': datetime.now()
        })

        print_status(name, "RUNNING", f"PID: {proc.pid}")
        return proc

    except Exception as e:
        print_status(name, "ERROR", str(e))
        return None


def monitor_processes():
    """Monitor running processes and restart if needed."""
    while True:
        try:
            for proc_info in processes:
                proc = proc_info['process']

                # Check if process has exited
                if proc and proc.poll() is not None:
                    uptime = (datetime.now() - proc_info['start_time']).total_seconds()
                    print_status(proc_info['name'], "CRASHED", f"Exit code: {proc.returncode}, Uptime: {uptime:.1f}s")

                    # Restart process (except in test mode)
                    if not test_mode:
                        time.sleep(2)
                        print_status(proc_info['name'], "RESTARTING")
                        new_proc = start_process(proc_info['cmd'], proc_info['name'])
                        proc_info['process'] = new_proc
                    else:
                        # Test mode: exit when first process dies
                        return False

                # In test mode, check timeout
                if test_mode and start_time:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > 60:  # Test for 60 seconds
                        print_status("TEST", "TIMEOUT", "Test mode completed (60s)")
                        return False

            time.sleep(1)

        except KeyboardInterrupt:
            raise


def show_info():
    """Show running bots info."""
    print(f"\n{BOLD}{GREEN}Running Processes:{RESET}\n")
    for proc_info in processes:
        proc = proc_info['process']
        if proc and proc.poll() is None:
            uptime = (datetime.now() - proc_info['start_time']).total_seconds()
            print(f"  {GREEN}✓{RESET} {proc_info['name']:<30} PID: {proc.pid:<8} Uptime: {uptime:.1f}s")
        else:
            print(f"  {RED}✗{RESET} {proc_info['name']:<30} (not running)")
    print()


def main():
    """Main launcher function."""
    global test_mode, start_time

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Start all trading bots with unified launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_all_bots.py              # Start all bots normally
  python start_all_bots.py --test       # Test mode (60 seconds, no signal fetcher)
  python start_all_bots.py --help       # Show this help
        """
    )
    parser.add_argument('--test', action='store_true', help='Test mode (60s, no signal fetcher)')
    parser.add_argument('--no-fetcher', action='store_true', help='Skip signal fetcher')
    args = parser.parse_args()

    test_mode = args.test

    # Setup signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    # Print header
    print_header("MULTI-ALGO TRADING BOT - UNIFIED LAUNCHER")

    print(f"{BOLD}Configuration:{RESET}\n")
    print(f"  Mode:           {'TEST (60s)' if test_mode else 'PRODUCTION'}")
    print(f"  Signal Fetcher: {'DISABLED' if args.no_fetcher or test_mode else 'ENABLED'}")
    print(f"  Bot 1:          Inverter Strategy")
    print(f"  Bot 2:          Follower Strategy")
    print(f"  Bot 3:          Follower Strategy")
    print(f"\n  Log Files:")
    print(f"    Bot 1: bot_1.log")
    print(f"    Bot 2: bot_2.log")
    print(f"    Bot 3: bot_3.log")
    print(f"    Signal: signal_fetcher.log")
    print()

    start_time = datetime.now()

    # Start signal fetcher (unless test mode or --no-fetcher)
    if not test_mode and not args.no_fetcher:
        start_process(
            [sys.executable, "signal_fetcher.py"],
            "SIGNAL FETCHER",
            {"PYTHONUNBUFFERED": "1"}
        )
        time.sleep(2)  # Wait for fetcher to initialize

    # Start bots
    time.sleep(1)
    start_process(
        [sys.executable, "main.py", "--bot-id", "1"],
        "BOT 1 (INVERTER)",
        {"PYTHONUNBUFFERED": "1"}
    )

    time.sleep(1)
    start_process(
        [sys.executable, "main.py", "--bot-id", "2"],
        "BOT 2 (FOLLOWER)",
        {"PYTHONUNBUFFERED": "1"}
    )

    time.sleep(1)
    start_process(
        [sys.executable, "main.py", "--bot-id", "3"],
        "BOT 3 (FOLLOWER)",
        {"PYTHONUNBUFFERED": "1"}
    )

    # Show startup complete
    print(f"\n{GREEN}{BOLD}✓ All bots started successfully!{RESET}\n")

    if test_mode:
        print(f"{YELLOW}Test mode: Running for 60 seconds...{RESET}\n")
    else:
        print(f"{YELLOW}Press Ctrl+C to stop all bots{RESET}\n")

    show_info()

    # Monitor processes
    try:
        monitor_processes()
    except KeyboardInterrupt:
        signal_handler(None, None)


if __name__ == "__main__":
    main()
