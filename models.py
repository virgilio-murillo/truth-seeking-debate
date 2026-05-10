from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


class Status(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PAUSED = "paused"
    AGREED = "agreed"
    RESOLVED = "resolved"


@dataclass
class Exchange:
    round: int
    team: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ContentionNode:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_id: Optional[str] = None
    claim: str = ""
    team_a_position: str = ""
    team_b_position: str = ""
    exchanges: list[Exchange] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    status: Status = Status.PENDING
    current_round: int = 0
    depth: int = 0
    winner: Optional[str] = None
    truth: Optional[str] = None
    was_paused: bool = False

    @property
    def priority(self) -> int:
        p = -self.depth * 1000
        if self.was_paused:
            p -= 500
        return p


@dataclass
class Truth:
    statement: str
    contention_id: str
    confidence: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class DebateState:
    topic: str = ""
    opening_a: str = ""
    opening_b: str = ""
    tree: dict[str, ContentionNode] = field(default_factory=dict)
    found_truths: list[Truth] = field(default_factory=list)
    agreement_counts: dict[str, dict] = field(default_factory=dict)
