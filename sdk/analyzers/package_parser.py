from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import List

from sdk.ir.model import PackageIR


def _read_text(p: Path) -> str:
    return p.read_text(encoding='utf-8')


def parse_package(pkg_path: Path) -> PackageIR:
    pkg_xml = pkg_path / 'package.xml'
    if not pkg_xml.exists():
        raise FileNotFoundError(f"package.xml not found at {pkg_xml}")

    tree = ET.parse(str(pkg_xml))
    root = tree.getroot()

    name_el = root.find('name')
    name = name_el.text.strip() if name_el is not None else pkg_path.name

    # deps (format 1/2 best-effort)
    dep_tags = [
        'depend', 'build_depend', 'exec_depend', 'run_depend',
        'buildtool_depend', 'test_depend'
    ]
    deps: List[str] = []
    for tag in dep_tags:
        for d in root.findall(tag):
            if d.text:
                deps.append(d.text.strip())
    deps = sorted(set(deps))

    # build_type: detect catkin in CMakeLists
    cmake = pkg_path / 'CMakeLists.txt'
    build_type = 'catkin'
    if cmake.exists():
        txt = _read_text(cmake)
        if re.search(r'ament_', txt):
            build_type = 'ament'

    # messages
    msgs_dir = pkg_path / 'msg'
    srvs_dir = pkg_path / 'srv'
    acts_dir = pkg_path / 'action'
    msgs = [p.name for p in msgs_dir.glob('*.msg')] if msgs_dir.exists() else []
    srvs = [p.name for p in srvs_dir.glob('*.srv')] if srvs_dir.exists() else []
    actions = [p.name for p in acts_dir.glob('*.action')] if acts_dir.exists() else []

    return PackageIR(
        name=name,
        path=pkg_path,
        build_type=build_type,
        deps=deps,
        msgs=msgs,
        srvs=srvs,
        actions=actions,
    )

