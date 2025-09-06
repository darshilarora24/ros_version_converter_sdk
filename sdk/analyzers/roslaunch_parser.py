from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET


@dataclass
class LaunchNode:
    package: Optional[str] = None
    executable: Optional[str] = None
    name: Optional[str] = None
    output: Optional[str] = None
    namespace: Optional[str] = None
    remaps: List[Tuple[str, str]] = field(default_factory=list)
    params: List["LaunchParam"] = field(default_factory=list)
    cond_if: Optional[str] = None
    cond_unless: Optional[str] = None


@dataclass
class LaunchIR:
    nodes: List[LaunchNode] = field(default_factory=list)
    args: List["LaunchArg"] = field(default_factory=list)
    includes: List["LaunchInclude"] = field(default_factory=list)


@dataclass
class LaunchArg:
    name: str
    default: Optional[str] = None
    description: Optional[str] = None


@dataclass
class LaunchParam:
    name: Optional[str] = None
    value: Optional[str] = None
    file: Optional[str] = None


@dataclass
class LaunchInclude:
    file: str
    namespace: Optional[str] = None
    args: List[Tuple[str, str]] = field(default_factory=list)
    cond_if: Optional[str] = None
    cond_unless: Optional[str] = None


def parse_launch_file(path: Path) -> LaunchIR:
    tree = ET.parse(str(path))
    root = tree.getroot()
    ir = LaunchIR()
    # top-level args
    for a in root.findall('arg'):
        ir.args.append(LaunchArg(
            name=a.attrib.get('name', ''),
            default=a.attrib.get('default'),
            description=a.attrib.get('doc')
        ))
    # Helpers for recursion
    def parse_node(elem: ET.Element, inherited_ns: Optional[str] = None) -> None:
        ln = LaunchNode(
            package=elem.attrib.get('pkg'),
            executable=elem.attrib.get('type') or elem.attrib.get('exec'),
            name=elem.attrib.get('name'),
            output=elem.attrib.get('output'),
            namespace=elem.attrib.get('ns') or inherited_ns,
            cond_if=elem.attrib.get('if'),
            cond_unless=elem.attrib.get('unless'),
        )
        for r in elem.findall('remap'):
            frm = r.attrib.get('from')
            to = r.attrib.get('to')
            if frm and to:
                ln.remaps.append((frm, to))
        for p in elem.findall('param'):
            name = p.attrib.get('name')
            if 'value' in p.attrib:
                ln.params.append(LaunchParam(name=name, value=p.attrib.get('value')))
            elif p.text and p.text.strip():
                ln.params.append(LaunchParam(name=name, value=p.text.strip()))
        for rp in elem.findall('rosparam'):
            file = rp.attrib.get('file')
            if file:
                ln.params.append(LaunchParam(file=file))
        ir.nodes.append(ln)

    def parse_group(elem: ET.Element, inherited_ns: Optional[str] = None) -> None:
        ns = elem.attrib.get('ns') or inherited_ns
        # parse child nodes
        for c in elem:
            if c.tag == 'node':
                parse_node(c, ns)
            elif c.tag == 'group':
                parse_group(c, ns)
            elif c.tag == 'include':
                parse_include(c, ns)
            # group-level params/remaps not propagated (TODO)

    def parse_include(elem: ET.Element, inherited_ns: Optional[str] = None) -> None:
        file = elem.attrib.get('file') or ''
        inc = LaunchInclude(
            file=file,
            namespace=inherited_ns or elem.attrib.get('ns'),
            cond_if=elem.attrib.get('if'),
            cond_unless=elem.attrib.get('unless'),
        )
        for a in elem.findall('arg'):
            name = a.attrib.get('name')
            value = a.attrib.get('value')
            if name and value is not None:
                inc.args.append((name, value))
        ir.includes.append(inc)

    # Walk root
    for child in root:
        if child.tag == 'node':
            parse_node(child)
        elif child.tag == 'group':
            parse_group(child)
        elif child.tag == 'include':
            parse_include(child)
    return ir
