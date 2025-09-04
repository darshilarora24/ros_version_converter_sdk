import argparse
import os
import sys
from pathlib import Path

# Local imports (stdlib-only scaffold)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.analyzers.package_parser import parse_package
from sdk.analyzers.rospy_parser import analyze_python_sources
from sdk.analyzers.roslaunch_parser import parse_launch_file
from sdk.ir.model import PackageIR
from sdk.transformers.rospy_to_rclpy import convert_python_package_skeleton


def cmd_analyze(args: argparse.Namespace) -> int:
    pkg_path = Path(args.path).resolve()
    if not pkg_path.exists():
        print(f"[analyze] Path not found: {pkg_path}")
        return 2
    try:
        pkg = parse_package(pkg_path)
    except Exception as e:
        print(f"[analyze] Failed to parse package: {e}")
        return 1
    nodes = analyze_python_sources(pkg_path)
    print("Package:")
    print(f"- name: {pkg.name}")
    print(f"- build_type: {pkg.build_type}")
    print(f"- deps: {', '.join(pkg.deps) if pkg.deps else '(none)'}")
    print("Python nodes:")
    for n in nodes:
        pubs = ', '.join([f"{p.topic}:{p.type}" for p in n.pubs]) or '(none)'
        subs = ', '.join([f"{s.topic}:{s.type}" for s in n.subs]) or '(none)'
        print(f"- {n.name} (file={n.file}) pubs=[{pubs}] subs=[{subs}]")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    src_path = Path(args.path).resolve()
    out_ws = Path(args.out).resolve()
    out_ws.mkdir(parents=True, exist_ok=True)
    try:
        pkg = parse_package(src_path)
    except Exception as e:
        print(f"[convert] Failed to parse package: {e}")
        return 1
    print(f"[convert] Converting package '{pkg.name}' → ROS2 (lang={args.lang})")
    try:
        convert_python_package_skeleton(src_path, out_ws, pkg)
    except Exception as e:
        print(f"[convert] Error during conversion: {e}")
        return 1
    print(f"[convert] Output at: {out_ws}")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    in_launch = Path(args.launch).resolve()
    if not in_launch.exists():
        print(f"[launch] Launch file not found: {in_launch}")
        return 2
    out_pkg = Path(args.out).resolve()
    out_pkg.mkdir(parents=True, exist_ok=True)
    try:
        launch_ir = parse_launch_file(in_launch)
    except Exception as e:
        print(f"[launch] Failed to parse: {e}")
        return 1
    launch_py = out_pkg / (in_launch.stem + ".launch.py")
    # Minimal launch generator (no Jinja dependency)
    with open(launch_py, 'w', encoding='utf-8') as f:
        f.write("""#!/usr/bin/env python3
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    nodes = []
""")
        for n in launch_ir.nodes:
            pkg = n.package or ''
            exe = n.executable or ''
            name = n.name or ''
            f.write(f"    nodes.append(Node(package='{pkg}', executable='{exe}', name='{name}'))\n")
        f.write("""
    return LaunchDescription(nodes)
""")
    print(f"[launch] Wrote {launch_py}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    pkg_path = Path(args.path).resolve()
    missing = []
    for rel in ["package.xml"]:
        if not (pkg_path / rel).exists():
            missing.append(rel)
    if missing:
        print(f"[check] Missing files: {', '.join(missing)}")
        return 1
    print("[check] Basic checks passed.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    report = path / "ros_migrate_report.txt"
    with open(report, 'w', encoding='utf-8') as f:
        f.write("ROS Migrate Report (skeleton)\n")
        f.write(f"Path: {path}\n")
    print(f"[report] Wrote {report}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ros-migrate", description="ROS1 → ROS2 migration SDK (skeleton)")
    sub = p.add_subparsers(dest='cmd', required=True)

    pa = sub.add_parser('analyze', help='Analyze a ROS1 package')
    pa.add_argument('path', help='Path to ROS1 package')
    pa.set_defaults(func=cmd_analyze)

    pc = sub.add_parser('convert', help='Convert a ROS1 package (Python skeleton)')
    pc.add_argument('path', help='Path to ROS1 package')
    pc.add_argument('--lang', choices=['py'], default='py')
    pc.add_argument('--out', required=True, help='Output workspace directory')
    pc.set_defaults(func=cmd_convert)

    pl = sub.add_parser('launch', help='Convert a roslaunch XML to ROS2 launch.py')
    pl.add_argument('launch', help='Path to roslaunch XML file')
    pl.add_argument('--out', required=True, help='Output package directory for launch.py')
    pl.set_defaults(func=cmd_launch)

    pk = sub.add_parser('check', help='Basic checks on a ROS2 package')
    pk.add_argument('path', help='Path to ROS2 package')
    pk.set_defaults(func=cmd_check)

    pr = sub.add_parser('report', help='Generate a simple migration report')
    pr.add_argument('path', help='Path to converted workspace/package')
    pr.set_defaults(func=cmd_report)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())

