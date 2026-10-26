"""Outlook ingest. The implementation lives with the other mail providers."""

from inbox_brief.mail.outlook import fetch_recent

__all__ = ["fetch_recent"]
