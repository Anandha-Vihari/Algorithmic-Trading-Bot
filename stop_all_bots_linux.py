#!/usr/bin/env python3
"""
STOP ALL BOTS - Graceful shutdown

Stops all trading bot processes gracefully.

Usage:
    python stop_all_bots.py          # Stop all bots
    python stop_all_bots.py --force  # Force kill all bots
"""

import os
import sys
import signal
import subprocess
import time
import argparse
from datetime import datetime

# Color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


def print_status(msg, status="INFO"):
    """Print status message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    if status == "SUCCESS":
        color = GREEN
    elif status == "ERROR":
        color = RED
    elif status == "WARNING":
        color = YELLOW
    else:
        color = BLUE

    print(f"{color}[{timestamp}] {msg}{RESET}")


def find_processes(pattern):
    """Find running processes by pattern."""
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )
        processes = []
        for line in result.stdout.split('\n'):
            if pattern in line and 'grep' not in line and 'stop_all' not in line:
                parts = line.split()
                if len(parts) > 1:
                    processes.append({
                        'pid': int(parts[1]),
                        'cmdline': ' '.join(parts[10:])
                    })
        return processes
    except Exception as e:
        print_status(f"Failed to find processes: {e}", "ERROR")
        return []


def stop_bots(force=False):
    """Stop all bot processes."""
    print(f"{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}{'STOPPING ALL TRADING BOTS':^70}{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}\n")

    targets = [
        ('signal_fetcher.py', 'Signal Fetcher'),
        ('main.py --bot-id 1', 'Bot 1 (Inverter)'),
        ('main.py --bot-id 2', 'Bot 2 (Follower)'),
        ('main.py --bot-id 3', 'Bot 3 (Follower)'),
    ]

    stopped = 0

    for pattern, name in targets:
        processes = find_processes(pattern)

        if not processes:
            print_status(f"{name}: Not running", "WARNING")
            continue

        for proc_info in processes:
            pid = proc_info['pid']
            print_status(f"{name}: Found PID {pid}")

            try:
                if force:
                    os.kill(pid, signal.SIGKILL)
                    print_status(f"{name}: Force killed (SIGKILL)", "SUCCESS")
                else:
                    os.kill(pid, signal.SIGTERM)
                    print_status(f"{name}: Terminated (SIGTERM)", "SUCCESS")

                # Wait a bit for process to exit
                time.sleep(0.5)
                stopped += 1

            except ProcessLookupError:
                print_status(f"{name}: Already stopped", "WARNING")
            except Exception as e:
                print_status(f"{name}: Error - {e}", "ERROR")

    print()
    print(f"{GREEN}{BOLD}✓ Stopped {stopped} process(es){RESET}\n")

    # Show remaining processes
    print(f"{BOLD}Verifying shutdown...{RESET}\n")
    all_stopped = True
    for pattern, name in targets:
        processes = find_processes(pattern)
        if processes:
            print_status(f"{name}: STILL RUNNING (PID: {processes[0]['pid']})", "WARNING")
            all_stopped = False
        else:
            print_status(f"{name}: Stopped", "SUCCESS")

    print()
    if all_stopped:
        print(f"{GREEN}{BOLD}✓ All bots successfully stopped!{RESET}\n")
        return 0
    else:
        print(f"{YELLOW}{BOLD}⚠ Some processes still running{RESET}\n")
        return 1


def main():
    """Main shutdown function."""
    parser = argparse.ArgumentParser(
        description="Stop all trading bots gracefully"
    )
    parser.add_argument('--force', action='store_true', help='Force kill instead of terminate')
    args = parser.parse_args()

    return stop_bots(force=args.force)


if __name__ == "__main__":
    sys.exit(main())
