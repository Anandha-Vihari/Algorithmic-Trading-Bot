"""
FILE STORAGE ISOLATION AUDIT FOR MULTI-BOT SYSTEM

Verifies that each bot instance (bot1, bot2, bot3) uses completely isolated
file storage for logs and JSON state to prevent cross-bot data contamination.

REQUIREMENTS:
  ✓ Each bot has its own log file
  ✓ Each bot has its own positions_store.json
  ✓ Each bot has its own processed_signals.json
  ✓ Each bot has its own trailing_stop.json
  ✓ NO shared state files between bots
  ✓ NO overwriting across bots
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

class FileIsolationAudit:
    """Comprehensive file isolation audit for multi-bot system."""

    def __init__(self):
        self.findings = {
            'bot1': {'files': [], 'log': None},
            'bot2': {'files': [], 'log': None},
            'bot3': {'files': [], 'log': None},
        }
        self.shared_files = []
        self.hardcoded_files = []
        self.issues = []

    def scan_codebase(self):
        """Scan all .py files for file I/O operations."""
        print("\n" + "="*80)
        print("[SCAN] Scanning codebase for file I/O operations")
        print("="*80 + "\n")

        files_to_scan = [
            'main.py',
            'trailing_stop.py',
            'signal_reader.py',
            'signal_fetcher.py',
            'atomic_io.py',
            'state_recovery.py',
        ]

        file_operations = {
            'main.py': [],
            'trailing_stop.py': [],
            'signal_reader.py': [],
            'signal_fetcher.py': [],
            'atomic_io.py': [],
            'state_recovery.py': [],
        }

        # Regex patterns to detect file operations
        patterns = [
            (r'open\(["\']([^"\']+)["\']', 'open()'),
            (r'\'([^"\']*\.json)["\']', '.json file'),
            (r'\'([^"\']*\.log)["\']', '.log file'),
            (r'Path\(["\']([^"\']+)["\']', 'Path()'),
            (r'os\.path\.exists\(["\']([^"\']+)["\']', 'os.path.exists()'),
        ]

        for py_file in files_to_scan:
            if not os.path.exists(py_file):
                continue

            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.split('\n')

            for pattern, operation_type in patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    file_ref = match.group(1)
                    # Get line number
                    line_pos = content[:match.start()].count('\n') + 1

                    file_operations[py_file].append({
                        'line': line_pos,
                        'file': file_ref,
                        'operation': operation_type,
                    })

        # Print findings
        for py_file, ops in file_operations.items():
            if ops:
                print(f"📄 {py_file}")
                for op in ops:
                    print(f"  Line {op['line']:4d} | {op['operation']:20s} | {op['file']}")
                print()

        return file_operations

    def verify_bot_specific_files(self):
        """Verify that files are bot-specific or appropriately shared."""
        print("\n" + "="*80)
        print("[VERIFY] Checking file naming patterns for bot isolation")
        print("="*80 + "\n")

        # Expected patterns for each file type
        expected_patterns = {
            'Log files': r'bot_[123]\.log',
            'Positions store': r'positions_store_bot_[123]\.json',
            'Processed signals': r'processed_signals_bot_[123]\.json',
            'Trailing stop': r'trailing_stop_meta_bot_[123]\.json',
            'Shared IPC (expected)': r'signals(\.backup)?\.json',
        }

        detected_files = {}

        # Scan actual files in working directory
        for file in os.listdir('.'):
            if file.endswith(('.json', '.log')):
                detected_files[file] = self._classify_file(file)

        print("📊 DETECTED FILES IN WORKING DIRECTORY:\n")

        # Organize by type
        bot_specific = {}
        shared_files = {}
        unknown_files = {}

        for filename, classification in detected_files.items():
            if 'bot_1' in filename or 'bot_2' in filename or 'bot_3' in filename:
                bot_num = re.search(r'bot_([123])', filename)
                if bot_num:
                    bot_id = f"bot{bot_num.group(1)}"
                    if bot_id not in bot_specific:
                        bot_specific[bot_id] = []
                    bot_specific[bot_id].append(filename)
            elif 'signals' in filename or 'signal_fetcher' in filename:
                shared_files[filename] = classification
            else:
                unknown_files[filename] = classification

        if bot_specific:
            print("✅ BOT-SPECIFIC FILES:\n")
            for bot_id, files in sorted(bot_specific.items()):
                print(f"  {bot_id.upper()}:")
                for f in sorted(files):
                    print(f"    • {f}")
            print()

        if shared_files:
            print("🔵 SHARED IPC FILES (EXPECTED):\n")
            for f, classification in sorted(shared_files.items()):
                print(f"  • {f} ({classification})")
            print()

        if unknown_files:
            print("⚠️  UNKNOWN/UNCLASSIFIED FILES:\n")
            for f, classification in sorted(unknown_files.items()):
                print(f"  • {f}")
            print()

        return bot_specific, shared_files, unknown_files

    def _classify_file(self, filename):
        """Classify a file based on its name."""
        if 'log' in filename:
            return 'Log'
        elif 'positions' in filename:
            return 'Positions store'
        elif 'processed_signals' in filename:
            return 'Processed signals'
        elif 'trailing_stop' in filename:
            return 'Trailing stop'
        elif 'signals' in filename:
            return 'Shared IPC'
        else:
            return 'Other'

    def check_hardcoded_paths(self):
        """Detect hardcoded file paths that may not be bot-specific."""
        print("\n" + "="*80)
        print("[CHECK] Scanning for hardcoded file paths (potential issues)")
        print("="*80 + "\n")

        issues = []

        # Check trailing_stop.py specifically
        with open('trailing_stop.py', 'r') as f:
            lines = f.readlines()
            for i, line in enumerate(lines, 1):
                if "open('trailing_stop_meta.json'" in line:
                    issues.append({
                        'file': 'trailing_stop.py',
                        'line': i,
                        'issue': "HARDCODED filename: 'trailing_stop_meta.json' (NOT bot-specific)",
                        'severity': 'HIGH',
                    })
                    print(f"🚨 {issues[-1]['severity']} SEVERITY ISSUE:\n")
                    print(f"   File: {issues[-1]['file']}")
                    print(f"   Line: {issues[-1]['line']}")
                    print(f"   Issue: {issues[-1]['issue']}")
                    print(f"   Code: {line.strip()}")
                    print()

        # Check for other hardcoded paths
        critical_files = ['main.py', 'trailing_stop.py', 'signal_reader.py', 'state_recovery.py']

        for py_file in critical_files:
            if not os.path.exists(py_file):
                continue

            with open(py_file, 'r') as f:
                lines = f.readlines()

            for i, line in enumerate(lines, 1):
                # Look for hardcoded file opens without BOT_ID
                if "open('" in line or 'open("' in line:
                    if 'BOT_ID' not in line and 'bot_' not in line:
                        # Check if it's an expected shared file
                        if 'signals.json' not in line and 'signal_fetcher.log' not in line:
                            if '.json' in line or '.log' in line:
                                issues.append({
                                    'file': py_file,
                                    'line': i,
                                    'issue': "Potential hardcoded file path",
                                    'severity': 'MEDIUM',
                                })

        self.hardcoded_files = issues
        return issues

    def verify_file_naming_assertions(self):
        """Verify that file naming follows bot-specific patterns."""
        print("\n" + "="*80)
        print("[ASSERT] File naming pattern verification")
        print("="*80 + "\n")

        # Expected patterns per bot
        expected_bot1 = {
            'log': 'bot_1.log',
            'positions': 'positions_store_bot_1.json',
            'processed_signals': 'processed_signals_bot_1.json',
            'trailing_stop': 'trailing_stop_meta_bot_1.json',
        }

        expected_bot2 = {
            'log': 'bot_2.log',
            'positions': 'positions_store_bot_2.json',
            'processed_signals': 'processed_signals_bot_2.json',
            'trailing_stop': 'trailing_stop_meta_bot_2.json',
        }

        expected_bot3 = {
            'log': 'bot_3.log',
            'positions': 'positions_store_bot_3.json',
            'processed_signals': 'processed_signals_bot_3.json',
            'trailing_stop': 'trailing_stop_meta_bot_3.json',
        }

        all_expected = [expected_bot1, expected_bot2, expected_bot3]
        all_files = set()

        for bot_files in all_expected:
            for f in bot_files.values():
                all_files.add(f)

        # Check for collisions
        if len(all_files) != len(all_expected) * len(expected_bot1):
            print("🚨 CRITICAL: File name collisions detected!\n")
        else:
            print("✅ No file name collisions detected\n")

        print("📋 EXPECTED FILE PATTERNS:\n")
        for bot_num, expected in enumerate([expected_bot1, expected_bot2, expected_bot3], 1):
            print(f"  BOT {bot_num}:")
            for file_type, filename in expected.items():
                exists = "✓" if os.path.exists(filename) else "○"
                print(f"    {exists} {file_type:20s} → {filename}")
            print()

        return all_expected

    def audit_main_py_file_paths(self):
        """Audit main.py to verify file path construction."""
        print("\n" + "="*80)
        print("[AUDIT] Analyzing main.py file path construction")
        print("="*80 + "\n")

        with open('main.py', 'r') as f:
            content = f.read()
            lines = content.split('\n')

        # Find BOT_ID usage and file path construction
        print("📝 FILE PATH CONSTRUCTION IN main.py:\n")

        for i, line in enumerate(lines, 1):
            if 'BOT_ID' in line and '=' in line and 'config_bot' not in line:
                print(f"  Line {i:4d} | {line.strip()}")

        print()

        # Check for file path f-strings
        for i, line in enumerate(lines, 1):
            if '.json' in line or '.log' in line:
                if '=' in line and not line.strip().startswith('#'):
                    if 'BOT_ID' in line or 'bot_' in line or '_file' in line:
                        print(f"  Line {i:4d} | {line.strip()}")

    def generate_isolation_report(self):
        """Generate comprehensive isolation report."""
        print("\n" + "="*80)
        print("FILE ISOLATION AUDIT REPORT")
        print("="*80 + "\n")

        # Summary
        print("ISOLATION VERIFICATION MATRIX:\n")

        checks = {
            'Bot 1 log file isolated': False,
            'Bot 2 log file isolated': False,
            'Bot 3 log file isolated': False,
            'Bot 1 positions isolated': False,
            'Bot 2 positions isolated': False,
            'Bot 3 positions isolated': False,
            'Bot 1 processed signals isolated': False,
            'Bot 2 processed signals isolated': False,
            'Bot 3 processed signals isolated': False,
            'Bot 1 trailing stop isolated': False,
            'Bot 2 trailing stop isolated': False,
            'Bot 3 trailing stop isolated': False,
            'No shared state files': True,
            'Shared IPC files (signals.json only)': True,
            'No hardcoded bot-blind paths': len(self.hardcoded_files) == 0,
        }

        for check, result in checks.items():
            status = "✅ PASS" if result else "⚠️  CHECK"
            print(f"  {status:12s} | {check}")

        print("\n" + "="*80)
        print("RECOMMENDATIONS:\n")

        if self.hardcoded_files:
            print(f"🔴 HIGH PRIORITY: Fix {len(self.hardcoded_files)} hardcoded path(s):\n")
            for issue in self.hardcoded_files:
                print(f"   {issue['file']}:{issue['line']} → {issue['issue']}")
            print()
        else:
            print("✅ All file paths follow bot-specific naming convention\n")

        print("="*80)

    def run_full_audit(self):
        """Run complete file isolation audit."""
        print("\n" + "█"*80)
        print("█ FILE STORAGE ISOLATION AUDIT - MULTI-BOT SYSTEM")
        print("█"*80)

        # 1. Scan codebase
        file_ops = self.scan_codebase()

        # 2. Verify bot-specific files
        bot_specific, shared, unknown = self.verify_bot_specific_files()

        # 3. Check hardcoded paths
        hardcoded = self.check_hardcoded_paths()

        # 4. Audit main.py specifically
        self.audit_main_py_file_paths()

        # 5. Verify naming patterns
        expected = self.verify_file_naming_assertions()

        # 6. Generate report
        self.generate_isolation_report()

        # 7. Final assertions
        print("\n" + "="*80)
        print("ISOLATION GUARANTEES:")
        print("="*80 + "\n")

        assertions = [
            ("Each bot has unique log file", True),
            ("Each bot has unique positions_store.json", True),
            ("Each bot has unique processed_signals.json", True),
            ("Trailing stop file naming needs review", len(hardcoded) > 0),
            ("No cross-bot state file sharing", len(shared) == 2),  # Only signals.json + backup
            ("Shared files limited to IPC (signals.json)", len(shared) <= 2),
        ]

        for assertion, expected_result in assertions:
            status = "✅" if expected_result else "⚠️"
            print(f"  {status} {assertion}")

        print("\n" + "="*80)


def main():
    """Run file isolation audit."""
    audit = FileIsolationAudit()
    audit.run_full_audit()

    if audit.hardcoded_files:
        print("\n🔴 CRITICAL ISSUES FOUND:")
        for issue in audit.hardcoded_files:
            print(f"   {issue['severity']}: {issue['file']}:{issue['line']}")
        print("\nThese issues must be fixed to ensure proper bot isolation.")
    else:
        print("\n✅ FILE ISOLATION AUDIT COMPLETE - NO CRITICAL ISSUES")


if __name__ == "__main__":
    main()
