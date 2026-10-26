"""Group messages into threads by ids, then by subject."""

from __future__ import annotations

import re
from collections import defaultdict

from inbox_brief.domain import ParsedMessage

_SUBJECT_PREFIX = re.compile(r"^(?:re|fw|fwd|aw|sv)\s*:\s*", re.IGNORECASE)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        self.add(left)
        self.add(right)
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def normalize_subject(subject: str) -> str:
    text = subject.strip()
    while True:
        updated = _SUBJECT_PREFIX.sub("", text)
        if updated == text:
            break
        text = updated
    return re.sub(r"\s+", " ", text).strip().lower()


def thread_messages(messages: list[ParsedMessage]) -> dict[str, list[ParsedMessage]]:
    """Return thread id -> messages, oldest first.

    The thread id is the id of the earliest message in the thread.
    """
    if not messages:
        return {}
    union = _UnionFind()
    by_header: dict[str, str] = {}
    for message in messages:
        union.add(message.id)
        if message.message_id:
            by_header[message.message_id] = message.id
    for message in messages:
        candidates = []
        if message.in_reply_to:
            candidates.append(message.in_reply_to)
        candidates.extend(message.references)
        for header in candidates:
            parent = by_header.get(header)
            if parent:
                union.union(message.id, parent)

    by_provider: dict[str, str] = {}
    for message in messages:
        token = (message.provider_thread_id or "").strip()
        if not token:
            continue
        previous = by_provider.get(token)
        if previous:
            union.union(message.id, previous)
        else:
            by_provider[token] = message.id

    components: dict[str, list[ParsedMessage]] = defaultdict(list)
    for message in messages:
        components[union.find(message.id)].append(message)

    by_subject: dict[str, str] = {}
    for root, members in list(components.items()):
        subjects = {normalize_subject(member.subject) for member in members}
        subjects.discard("")
        if len(subjects) != 1:
            continue
        subject = next(iter(subjects))
        previous = by_subject.get(subject)
        if previous and previous in components:
            for member in members:
                union.union(member.id, previous)
        else:
            by_subject[subject] = root

    regrouped: dict[str, list[ParsedMessage]] = defaultdict(list)
    for message in messages:
        regrouped[union.find(message.id)].append(message)

    threads: dict[str, list[ParsedMessage]] = {}
    for members in regrouped.values():
        ordered = sorted(members, key=lambda item: (item.date or "9999", item.id))
        threads[ordered[0].id] = ordered
    return threads
