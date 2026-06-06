"""Deploy-time readiness checks for the price tracker services."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import app.config as config
from app.database.db import get_session, init_db
from app.database.repository import UserRepository
from app.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

SERVICE_MAIN = "main"
SERVICE_DASHBOARD = "dashboard"
SERVICE_BOT = "telegram-bot"
SERVICE_ALL = "all"
ALLOWED_SERVICES = {SERVICE_MAIN, SERVICE_DASHBOARD, SERVICE_BOT, SERVICE_ALL}


@dataclass
class ReadinessCheck:
    """A single readiness check result."""

    name: str
    ok: bool
    message: str


@dataclass
class ReadinessReport:
    """Aggregate readiness results."""

    checks: list[ReadinessCheck]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def render(self) -> str:
        """Render a concise human-readable report."""
        lines = []
        for check in self.checks:
            status = "OK" if check.ok else "FAIL"
            lines.append(f"[{status}] {check.name}: {check.message}")
        lines.append("READY" if self.ok else "NOT READY")
        return "\n".join(lines)


def _check_database() -> ReadinessCheck:
    try:
        init_db()
        return ReadinessCheck(
            name="database",
            ok=True,
            message="Database initialized successfully",
        )
    except Exception as exc:
        logger.error("readiness_database_failed", error=str(exc))
        return ReadinessCheck(
            name="database",
            ok=False,
            message=f"Database initialization failed: {exc}",
        )


def _check_dashboard() -> ReadinessCheck:
    session = get_session()
    try:
        admins = UserRepository.list_admins(session)
        if admins:
            return ReadinessCheck(
                name="dashboard",
                ok=True,
                message=f"{len(admins)} admin account(s) available",
            )

        if not config.settings.auth_bootstrap_token:
            return ReadinessCheck(
                name="dashboard",
                ok=False,
                message="No admin users exist and AUTH_BOOTSTRAP_TOKEN is missing",
            )

        return ReadinessCheck(
            name="dashboard",
            ok=True,
            message="Bootstrap token configured for first-admin setup",
        )
    except Exception as exc:
        logger.error("readiness_dashboard_failed", error=str(exc))
        return ReadinessCheck(
            name="dashboard",
            ok=False,
            message=f"Dashboard readiness failed: {exc}",
        )
    finally:
        session.close()


def _check_main() -> ReadinessCheck:
    if not config.settings.telegram_bot_token or not config.settings.telegram_chat_id:
        return ReadinessCheck(
            name="main",
            ok=False,
            message="TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set",
        )

    return ReadinessCheck(
        name="main",
        ok=True,
        message="Notification credentials configured",
    )


def _check_bot() -> ReadinessCheck:
    if not config.settings.telegram_bot_token:
        return ReadinessCheck(
            name="telegram-bot",
            ok=False,
            message="TELEGRAM_BOT_TOKEN is required",
        )

    return ReadinessCheck(
        name="telegram-bot",
        ok=True,
        message="Bot token configured",
    )


def build_readiness_report(service: str = SERVICE_ALL) -> ReadinessReport:
    """Build a deploy-time readiness report for the requested service."""
    normalized_service = service.strip().lower()
    if normalized_service not in ALLOWED_SERVICES:
        raise ValueError(f"Unsupported service: {service}")

    checks: list[ReadinessCheck] = [_check_database()]

    if normalized_service in {SERVICE_ALL, SERVICE_DASHBOARD}:
        checks.append(_check_dashboard())

    if normalized_service in {SERVICE_ALL, SERVICE_MAIN}:
        checks.append(_check_main())

    if normalized_service in {SERVICE_ALL, SERVICE_BOT}:
        checks.append(_check_bot())

    return ReadinessReport(checks=checks)


def run_readiness_check(service: str = SERVICE_ALL) -> int:
    """Run readiness checks and return a process exit code."""
    report = build_readiness_report(service)
    print(report.render())
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for readiness checks."""
    setup_logging()

    parser = argparse.ArgumentParser(description="Run deploy-time readiness checks")
    parser.add_argument(
        "--service",
        default=SERVICE_ALL,
        choices=sorted(ALLOWED_SERVICES),
        help="Service to validate",
    )
    args = parser.parse_args(argv)

    raise SystemExit(run_readiness_check(args.service))


if __name__ == "__main__":
    main()
