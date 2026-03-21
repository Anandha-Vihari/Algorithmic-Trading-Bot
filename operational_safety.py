"""
OPERATIONAL SAFETY - Monitoring, retry control, and escalation.

Adds observability and controllability to production trading bot.
Does NOT change core trading logic.
"""

from datetime import datetime, timezone
from collections import defaultdict
from enum import Enum


class LogLevel(Enum):
    """Structured log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def log(level: LogLevel, message: str):
    """Structured logging with timestamp and level."""
    now = datetime.now(timezone.utc).strftime('%H:%M:%S')
    print(f"[{now}] [{level.value}] {message}")


class RetryTracker:
    """Track failed close attempts and escalate after limit."""

    def __init__(self, max_retries: int = 5, max_backoff_seconds: int = 300):
        """
        Args:
            max_retries: Maximum retry attempts before escalation (default 5)
            max_backoff_seconds: Maximum backoff delay in seconds (default 300 = 5 min)
        """
        self.max_retries = max_retries
        self.max_backoff_seconds = max_backoff_seconds

        # Track retries per ticket: {ticket: count}
        self.retry_count = defaultdict(int)

        # Track failed tickets: {ticket: count at escalation}
        self.escalated_tickets = {}

    def increment_retry(self, ticket: int) -> int:
        """Increment retry count for ticket.

        Returns:
            int: New retry count
        """
        self.retry_count[ticket] += 1
        return self.retry_count[ticket]

    def reset_retry(self, ticket: int):
        """Reset retry count (after successful close)."""
        if ticket in self.retry_count:
            del self.retry_count[ticket]
        if ticket in self.escalated_tickets:
            del self.escalated_tickets[ticket]

    def should_escalate(self, ticket: int) -> bool:
        """Check if ticket exceeded max retries."""
        return self.retry_count[ticket] >= self.max_retries

    def mark_escalated(self, ticket: int):
        """Mark ticket as escalated."""
        self.escalated_tickets[ticket] = self.retry_count[ticket]

    def get_retry_count(self, ticket: int) -> int:
        """Get current retry count."""
        return self.retry_count[ticket]

    def get_escalated_tickets(self) -> list:
        """Get list of escalated tickets."""
        return list(self.escalated_tickets.keys())


class StaleTicketDetector:
    """Detect and clean up manually-closed or stale tickets."""

    @staticmethod
    def is_ticket_stale(ticket: int, mt5_positions_list) -> bool:
        """Check if ticket no longer exists in MT5.

        Args:
            ticket: Ticket ID to check
            mt5_positions_list: Current list from mt5.positions_get()

        Returns:
            bool: True if ticket not found in MT5 positions
        """
        if not mt5_positions_list:
            return False

        for pos in mt5_positions_list:
            if pos.ticket == ticket:
                return False  # Found, not stale

        return True  # Not found, stale


class UnmatchedMonitor:
    """Monitor UNMATCHED position growth and alert."""

    def __init__(self, alert_threshold: int = 3):
        """
        Args:
            alert_threshold: Alert if UNMATCHED count exceeds this (default 3)
        """
        self.alert_threshold = alert_threshold
        self.last_count = 0

    def check(self, unmatched_count: int) -> None:
        """Check UNMATCHED growth and log if threshold exceeded.

        Args:
            unmatched_count: Current number of UNMATCHED positions
        """
        if unmatched_count > self.alert_threshold:
            if unmatched_count > self.last_count:
                log(
                    LogLevel.WARN,
                    f"UNMATCHED positions growing: {unmatched_count} (threshold: {self.alert_threshold})"
                )

        self.last_count = unmatched_count


class OperationalSafety:
    """Unified operational safety controller."""

    def __init__(self, max_retries: int = 5, unmatched_threshold: int = 3):
        """Initialize all safety monitors.

        Args:
            max_retries: Max close attempts before escalation
            unmatched_threshold: Alert if UNMATCHED exceeds this
        """
        self.retry_tracker = RetryTracker(max_retries=max_retries)
        self.stale_detector = StaleTicketDetector()
        self.unmatched_monitor = UnmatchedMonitor(alert_threshold=unmatched_threshold)

    def handle_close_failure(self, ticket: int, pair: str, reason: str) -> str:
        """Handle a close failure with retry tracking and escalation.

        Args:
            ticket: Ticket that failed to close
            pair: Trading pair (for logging)
            reason: Why close failed

        Returns:
            str: Action to take: "RETRY" or "ESCALATE"
        """
        retry_count = self.retry_tracker.increment_retry(ticket)

        log(LogLevel.WARN, f"Failed to close {pair} ticket {ticket} (attempt {retry_count}/{self.retry_tracker.max_retries}): {reason}")

        if self.retry_tracker.should_escalate(ticket):
            self.retry_tracker.mark_escalated(ticket)
            log(
                LogLevel.CRITICAL,
                f"Escalated ticket {ticket} after {retry_count} failed attempts. Moving to _FAILED_CLOSE_ bucket."
            )
            return "ESCALATE"

        return "RETRY"

    def handle_close_success(self, ticket: int):
        """Mark ticket as successfully closed."""
        retry_count = self.retry_tracker.get_retry_count(ticket)
        if retry_count > 0:
            log(LogLevel.INFO, f"Successfully closed ticket {ticket} after {retry_count} retries")
        self.retry_tracker.reset_retry(ticket)

    def check_stale_tickets(self, ticket: int, mt5_positions_list) -> bool:
        """Check if ticket is stale (manually closed externally).

        Args:
            ticket: Ticket to check
            mt5_positions_list: Current MT5 positions

        Returns:
            bool: True if stale (should be removed), False if still valid
        """
        if self.stale_detector.is_ticket_stale(ticket, mt5_positions_list):
            log(LogLevel.INFO, f"Ticket {ticket} already closed externally, removing from tracking")
            return True

        return False

    def check_unmatched_growth(self, unmatched_count: int):
        """Monitor UNMATCHED position growth.

        Args:
            unmatched_count: Current number of UNMATCHED positions
        """
        self.unmatched_monitor.check(unmatched_count)

    def get_status_report(self) -> dict:
        """Get operational status report.

        Returns:
            dict: Status with retry counts and escalated tickets
        """
        return {
            "retry_tracking": dict(self.retry_tracker.retry_count),
            "escalated_tickets": self.retry_tracker.get_escalated_tickets(),
            "total_escalated": len(self.retry_tracker.escalated_tickets),
        }
