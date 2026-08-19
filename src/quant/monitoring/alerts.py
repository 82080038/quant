"""Alert system — Telegram + email notifications for trading events.

Sends alerts for:
  - Risk gate violations (order rejections)
  - Drawdown breaches
  - Portfolio halt triggers
  - Daily P&L summary
  - Signal generation results
  - Model retirement verdicts
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Optional

import requests

from quant.core.rate_limiter import get_limiter

_telegram_limiter = get_limiter("telegram", base_rate=1.0, burst=5, timeout=10)

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """Alert message."""
    title: str
    message: str
    level: str  # info, warning, critical
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


class AlertManager:
    """Multi-channel alert manager (Telegram + email).

    Usage:
        am = AlertManager()
        am.send(Alert(
            title="Order Rejected",
            message="BBCA.JK buy blocked: position exceeds 15%",
            level="warning",
        ))
    """

    def __init__(
        self,
        telegram_bot_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        email_smtp_host: Optional[str] = None,
        email_from: Optional[str] = None,
        email_to: Optional[str] = None,
    ):
        self.telegram_bot_token = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.email_smtp_host = email_smtp_host
        self.email_from = email_from
        self.email_to = email_to

        self._buffer: list[Alert] = []
        self._buffer_size = 100

    def send(self, alert: Alert) -> bool:
        """Send an alert through all configured channels.

        Args:
            alert: Alert to send

        Returns:
            True if at least one channel succeeded
        """
        self._buffer.append(alert)
        if len(self._buffer) > self._buffer_size:
            self._buffer = self._buffer[-self._buffer_size:]

        success = False

        if self.telegram_bot_token and self.telegram_chat_id:
            if self._send_telegram(alert):
                success = True

        if self.email_smtp_host and self.email_from and self.email_to:
            if self._send_email(alert):
                success = True

        if not success:
            logger.info("Alert [%s]: %s — %s", alert.level, alert.title, alert.message)

        return success

    def _send_telegram(self, alert: Alert) -> bool:
        """Send alert via Telegram bot."""
        emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(alert.level, "📢")
        text = f"{emoji} *{alert.title}*\n\n{alert.message}\n\n_{alert.timestamp}_"

        try:
            _telegram_limiter.acquire_sync()
            _telegram_limiter.sleep_backoff_sync()
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }
            resp = requests.post(url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.warning("Telegram alert failed: %s", e)
            return False

    def _send_email(self, alert: Alert) -> bool:
        """Send alert via email."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            subject = f"[{alert.level.upper()}] {alert.title}"
            body = f"{alert.message}\n\nTimestamp: {alert.timestamp}"

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = self.email_from
            msg["To"] = self.email_to

            with smtplib.SMTP(self.email_smtp_host, 587) as server:
                server.starttls()
                server.sendmail(self.email_from, [self.email_to], msg.as_string())
            return True
        except Exception as e:
            logger.warning("Email alert failed: %s", e)
            return False

    def send_daily_summary(self, result) -> None:
        """Send daily trading summary.

        Args:
            result: PaperTradingResult from PaperTradingOMS.reconcile()
        """
        message = (
            f"Daily P&L Summary\n\n"
            f"NAV: {result.nav:,.0f} IDR\n"
            f"Cash: {result.cash:,.0f} IDR\n"
            f"Total P&L: {result.total_pnl:,.0f} IDR ({result.total_return_pct:+.2f}%)\n"
            f"Max Drawdown: {result.max_drawdown:.2%}\n"
            f"Trades: {result.n_trades}\n"
            f"Rejected: {result.n_rejected}\n"
            f"Reconciliation: {'OK' if result.reconciliation_ok else 'MISMATCH'}"
        )

        self.send(Alert(
            title="Daily Trading Summary",
            message=message,
            level="info" if result.total_pnl >= 0 else "warning",
        ))

    def send_risk_alert(self, violations: list[str], context: str = "") -> None:
        """Send risk violation alert.

        Args:
            violations: List of risk violations
            context: Additional context
        """
        message = "Risk violations detected:\n\n"
        for v in violations:
            message += f"• {v}\n"
        if context:
            message += f"\nContext: {context}"

        self.send(Alert(
            title="Risk Gate Violation",
            message=message,
            level="critical",
        ))

    def send_halt_alert(self, reason: str) -> None:
        """Send portfolio halt alert.

        Args:
            reason: Halt reason
        """
        self.send(Alert(
            title="PORTFOLIO HALTED",
            message=f"Trading has been halted.\n\nReason: {reason}",
            level="critical",
        ))
