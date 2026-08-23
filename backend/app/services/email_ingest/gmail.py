"""Read Santander ES transaction-notification emails over IMAP.

Follows the same graceful-degradation contract as the Ollama client: if
credentials are unset or the server is unreachable, we log a warning and return
an empty list rather than raising — the caller (the /import/email/sync endpoint)
stays usable.

Idempotency is owned by the import dedup hash.  After successful import, call
``archive_santander_emails`` with the UIDs of the parseable messages to move
them out of INBOX into the ``General`` Gmail label.  Unparseable messages are
left in INBOX so the user can inspect them.
"""
from __future__ import annotations

import imaplib
import logging
from collections.abc import Callable
from datetime import date

from ...config import get_settings

logger = logging.getLogger(__name__)

ConnFactory = Callable[[str], "imaplib.IMAP4"]

_ARCHIVE_LABEL = "General"


def _default_factory(host: str) -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(host)


def fetch_santander_emails(
    since: date | None = None,
    limit: int = 200,
    *,
    conn_factory: ConnFactory | None = None,
) -> list[tuple[str, bytes]]:
    """Return ``(uid, raw_rfc822)`` pairs for Santander notification emails.

    Uses IMAP UIDs (stable across sessions) so callers can archive a subset
    after deciding which messages were parseable.  Does NOT archive anything.
    Returns [] on credential/network failure.
    """
    settings = get_settings()
    if not settings.gmail_user or not settings.gmail_app_password:
        logger.warning("Gmail credentials unset; email ingest disabled")
        return []

    factory = conn_factory or _default_factory
    conn: imaplib.IMAP4 | None = None
    try:
        conn = factory(settings.gmail_imap_host)
        conn.login(settings.gmail_user, settings.gmail_app_password)
        conn.select("INBOX", readonly=True)

        criteria: list[str] = ["FROM", settings.santander_email_sender]
        if since is not None:
            criteria += ["SINCE", since.strftime("%d-%b-%Y")]

        typ, data = conn.uid("SEARCH", None, *criteria)  # type: ignore[arg-type]
        if typ != "OK" or not data or not data[0]:
            return []

        uids = data[0].split()[-limit:]
        results: list[tuple[str, bytes]] = []

        for uid in uids:
            typ, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data:
                continue
            for part in msg_data:
                if isinstance(part, tuple) and part[1]:
                    results.append((uid.decode(), part[1]))
                    break

        return results
    except (OSError, imaplib.IMAP4.error) as exc:
        logger.warning("Email ingest fetch failed: %s", exc)
        return []
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass


def archive_santander_emails(
    uids: list[str],
    *,
    conn_factory: ConnFactory | None = None,
) -> None:
    """Move the given IMAP UIDs from INBOX to the General label.

    Call this only for messages that were successfully parsed (and either
    imported or dedup'd).  Failures are logged and swallowed — archival is
    best-effort; idempotency is owned by the dedup hash.
    """
    if not uids:
        return

    settings = get_settings()
    if not settings.gmail_user or not settings.gmail_app_password:
        return

    factory = conn_factory or _default_factory
    conn: imaplib.IMAP4 | None = None
    try:
        conn = factory(settings.gmail_imap_host)
        conn.login(settings.gmail_user, settings.gmail_app_password)
        conn.select("INBOX", readonly=False)

        for uid in uids:
            uid_b = uid.encode()
            try:
                # Mark \Seen before COPY so the copy in General inherits the flag.
                conn.uid("STORE", uid_b, "+FLAGS", "\\Seen")  # type: ignore[arg-type]
                typ, _ = conn.uid("COPY", uid_b, _ARCHIVE_LABEL)  # type: ignore[arg-type]
                if typ == "OK":
                    conn.uid("STORE", uid_b, "+FLAGS", "\\Deleted")  # type: ignore[arg-type]
                else:
                    logger.warning("IMAP COPY to %r failed for uid %s", _ARCHIVE_LABEL, uid)
            except imaplib.IMAP4.error as exc:
                logger.warning("Failed to archive uid %s: %s", uid, exc)

        conn.expunge()
    except (OSError, imaplib.IMAP4.error) as exc:
        logger.warning("Email archive failed: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
