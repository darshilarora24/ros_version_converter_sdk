from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET


@dataclass
class LaunchNode:
    package: Optional[str] = None
    executable: Optional[str] = None
    name: Optional[str] = None
    output: Optional[str] = None


@dataclass
class LaunchIR:
    nodes: List[LaunchNode] = field(default_factory=list)


def parse_launch_file(path: Path) -> LaunchIR:
    tree = ET.parse(str(path))
    root = tree.getroot()
    ir = LaunchIR()
    for n in root.findall('node'):
        ir.nodes.append(LaunchNode(
            package=n.attrib.get('pkg'),
            executable=n.attrib.get('type') or n.attrib.get('exec'),
            name=n.attrib.get('name'),
            output=n.attrib.get('output')
        ))
    return ir

