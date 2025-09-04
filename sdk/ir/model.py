from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class TopicIR:
    topic: str
    type: str = ""
    callback: Optional[str] = None
    qos_hint: Optional[str] = None


@dataclass
class NodeIR:
    name: str
    lang: str = "py"
    file: str = ""
    pubs: List[TopicIR] = field(default_factory=list)
    subs: List[TopicIR] = field(default_factory=list)
    srvs: List[str] = field(default_factory=list)
    params: List[str] = field(default_factory=list)
    timers: List[str] = field(default_factory=list)
    tf_usage: bool = False
    clock_usage: bool = False


@dataclass
class PackageIR:
    name: str
    path: Path
    build_type: str = "catkin"
    deps: List[str] = field(default_factory=list)
    msgs: List[str] = field(default_factory=list)
    srvs: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
