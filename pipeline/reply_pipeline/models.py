from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Reply:
    reply_id: str
    author_handle: str
    text: str
    caller: str                      # which account's thread this reply sits under
    url: str = ""
    author_followers: Optional[int] = None
    created_at: Optional[str] = None  # ISO 8601
    source_post_id: str = ""
    like_count: int = 0
    reply_count: int = 0


@dataclass
class Scored:
    reply: Reply
    theme: str
    matched_phrase: str
    ratio: float
    score: int
    intent: str                       # HIGH / MED / LOW
    draft_reply: str = ""
