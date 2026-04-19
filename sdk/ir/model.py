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
    queue_size: Optional[int] = None
    latched: Optional[bool] = None


@dataclass
class ServiceIR:
    name: str
    type: str = ""
    handler: Optional[str] = None
    is_client: bool = False


@dataclass
class ParamIR:
    name: str
    default: Optional[str] = None


@dataclass
class TimerIR:
    callback: str
    period: Optional[float] = None


@dataclass
class NodeIR:
    name: str
    lang: str = "py"
    file: str = ""
    pubs: List[TopicIR] = field(default_factory=list)
    subs: List[TopicIR] = field(default_factory=list)
    srvs: List[ServiceIR] = field(default_factory=list)
    params: List[ParamIR] = field(default_factory=list)
    timers: List[TimerIR] = field(default_factory=list)
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
