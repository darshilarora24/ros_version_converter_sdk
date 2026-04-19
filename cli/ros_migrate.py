from __future__ import annotations

import argparse
import sys
from collections import OrderedDict
from pathlib import Path

# Local imports (stdlib-only scaffold)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sdk.analyzers.package_parser import parse_package
from sdk.analyzers.rospy_parser import analyze_python_sources
from sdk.analyzers.roslaunch_parser import parse_launch_file
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
    print(f"  name:       {pkg.name}")
    print(f"  build_type: {pkg.build_type}")
    print(f"  deps:       {', '.join(pkg.deps) if pkg.deps else '(none)'}")
    if pkg.msgs:
        print(f"  msgs:       {', '.join(pkg.msgs)}")
    if pkg.srvs:
        print(f"  srvs:       {', '.join(pkg.srvs)}")
    if pkg.actions:
        print(f"  actions:    {', '.join(pkg.actions)}")
    print(f"Python nodes ({len(nodes)}):")
    for n in nodes:
        pubs = ', '.join([f"{p.topic}[{p.type}]" for p in n.pubs]) or '(none)'
        subs = ', '.join([f"{s.topic}[{s.type}]" for s in n.subs]) or '(none)'
        print(f"  - {n.name} (file={n.file})")
        print(f"      pubs:   {pubs}")
        print(f"      subs:   {subs}")
        if n.srvs:
            servers = [s for s in n.srvs if not s.is_client]
            clients = [s for s in n.srvs if s.is_client]
            if servers:
                print(f"      srv servers: {', '.join(f'{s.name}[{s.type}]' for s in servers)}")
            if clients:
                print(f"      srv clients: {', '.join(f'{s.name}[{s.type}]' for s in clients)}")
        if n.params:
            print(f"      params: {', '.join(p.name for p in n.params)}")
        if n.timers:
            timer_strs = [f"{t.callback}@{t.period}s" if t.period else t.callback for t in n.timers]
            print(f"      timers: {', '.join(timer_strs)}")
        if n.tf_usage:
            print("      tf:     yes (requires tf2_ros migration)")
        if n.clock_usage:
            print("      clock:  yes (use self.get_clock().now())")
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
    print(f"[convert] Converting package '{pkg.name}' -> ROS2 (lang={args.lang})")
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
    launch_py.write_text(_render_launch_file(launch_ir, in_launch.name), encoding='utf-8')
    print(f"[launch] Wrote {launch_py}")
    return 0


def _render_launch_file(launch_ir, source_name: str) -> str:
    imports: OrderedDict[str, list[str]] = OrderedDict()
    _add_import(imports, 'launch', 'LaunchDescription')
    _add_import(imports, 'launch_ros.actions', 'Node')

    lines: list[str] = ['#!/usr/bin/env python3', '', f"# Auto-generated from {source_name}", '']

    body: list[str] = ['def generate_launch_description():', '    actions = []']
    section_started = False

    if getattr(launch_ir, 'args', None):
        _add_import(imports, 'launch.actions', 'DeclareLaunchArgument')
        for arg in launch_ir.args:
            arg_kwargs: list[str] = []
            comments: list[str] = []
            if arg.default is not None:
                default_expr, default_comment = _value_expr(arg.default, imports)
                arg_kwargs.append(f'default_value={default_expr}')
                if default_comment:
                    comments.append(default_comment)
            if arg.description:
                arg_kwargs.append(f'description={repr(arg.description)}')
            for comment in _dedupe_comments(comments):
                body.append(f'    {comment}')
            call = f"DeclareLaunchArgument({repr(arg.name)}"
            if arg_kwargs:
                call += ', ' + ', '.join(arg_kwargs)
            call += ')'
            body.append(f'    actions.append({call})')
        section_started = True

    if getattr(launch_ir, 'includes', None):
        if section_started:
            body.append('')
        _add_import(imports, 'launch.actions', 'IncludeLaunchDescription')
        _add_import(imports, 'launch.launch_description_sources', 'PythonLaunchDescriptionSource')
        for inc in launch_ir.includes:
            comments: list[str] = []
            file_expr, file_comment = _value_expr(inc.file, imports)
            if file_comment:
                comments.append(file_comment)
            include_kwargs: list[str] = []
            if inc.args:
                arg_entries = []
                for key, value in inc.args:
                    val_expr, val_comment = _value_expr(value, imports)
                    arg_entries.append(f"{repr(key)}: {val_expr}")
                    if val_comment:
                        comments.append(val_comment)
                include_kwargs.append(f"launch_arguments={{ {', '.join(arg_entries)} }}.items()")
            cond_expr = None
            if inc.cond_if:
                cond_expr, cond_comment = _value_expr(inc.cond_if, imports)
                if cond_comment:
                    comments.append(cond_comment)
                _add_import(imports, 'launch.conditions', 'IfCondition')
                include_kwargs.append(f'condition=IfCondition({cond_expr})')
            elif inc.cond_unless:
                cond_expr, cond_comment = _value_expr(inc.cond_unless, imports)
                if cond_comment:
                    comments.append(cond_comment)
                _add_import(imports, 'launch.conditions', 'UnlessCondition')
                include_kwargs.append(f'condition=UnlessCondition({cond_expr})')
            include_call = f"IncludeLaunchDescription(PythonLaunchDescriptionSource({file_expr})"
            if include_kwargs:
                include_call += ', ' + ', '.join(include_kwargs)
            include_call += ')'
            for comment in _dedupe_comments(comments):
                body.append(f'    {comment}')
            if inc.namespace:
                _add_import(imports, 'launch.actions', 'GroupAction')
                _add_import(imports, 'launch_ros.actions', 'PushRosNamespace')
                body.append('    actions.append(GroupAction([')
                body.append(f'        PushRosNamespace({repr(inc.namespace)}),')
                body.append(f'        {include_call}')
                body.append('    ]))')
            else:
                body.append(f'    actions.append({include_call})')
        section_started = True

    if getattr(launch_ir, 'nodes', None):
        if section_started:
            body.append('')
        for node in launch_ir.nodes:
            comments: list[str] = []
            pkg = node.package or 'TODO_PACKAGE'
            if node.package is None:
                comments.append('# TODO: set the correct package for this node')
            exe = node.executable or 'TODO_EXECUTABLE'
            if node.executable is None:
                comments.append('# TODO: set the executable for this node')
            node_kwargs: list[str] = [f'package={repr(pkg)}', f'executable={repr(exe)}']
            if node.name:
                node_kwargs.append(f'name={repr(node.name)}')
            if node.output:
                node_kwargs.append(f'output={repr(node.output)}')
            if node.namespace:
                ns_expr, ns_comment = _value_expr(node.namespace, imports)
                node_kwargs.append(f'namespace={ns_expr}')
                if ns_comment:
                    comments.append(ns_comment)
            if node.remaps:
                remap_entries = []
                for frm, to in node.remaps:
                    frm_expr, frm_comment = _value_expr(frm, imports)
                    to_expr, to_comment = _value_expr(to, imports)
                    remap_entries.append(f'({frm_expr}, {to_expr})')
                    if frm_comment:
                        comments.append(frm_comment)
                    if to_comment:
                        comments.append(to_comment)
                node_kwargs.append(f"remappings=[{', '.join(remap_entries)}]")
            if node.params:
                param_entries = []
                for param in node.params:
                    if param.file:
                        file_expr, file_comment = _value_expr(param.file, imports)
                        param_entries.append(file_expr)
                        if file_comment:
                            comments.append(file_comment)
                    elif param.name is not None:
                        val_expr, val_comment = _value_expr(param.value, imports)
                        param_entries.append('{' + repr(param.name) + f': {val_expr}' + '}')
                        if val_comment:
                            comments.append(val_comment)
                if param_entries:
                    node_kwargs.append(f"parameters=[{', '.join(param_entries)}]")
            if getattr(node, 'cond_if', None):
                cond_expr, cond_comment = _value_expr(node.cond_if, imports)
                _add_import(imports, 'launch.conditions', 'IfCondition')
                node_kwargs.append(f'condition=IfCondition({cond_expr})')
                if cond_comment:
                    comments.append(cond_comment)
            elif getattr(node, 'cond_unless', None):
                cond_expr, cond_comment = _value_expr(node.cond_unless, imports)
                _add_import(imports, 'launch.conditions', 'UnlessCondition')
                node_kwargs.append(f'condition=UnlessCondition({cond_expr})')
                if cond_comment:
                    comments.append(cond_comment)
            for comment in _dedupe_comments(comments):
                body.append(f'    {comment}')
            body.append(f"    actions.append(Node({', '.join(node_kwargs)}))")

    body.append('    return LaunchDescription(actions)')

    import_lines: list[str] = []
    for module, names in imports.items():
        if names:
            import_lines.append(f"from {module} import {', '.join(names)}")
        else:
            import_lines.append(f'import {module}')

    lines.extend(import_lines)
    lines.append('')
    lines.extend(body)
    lines.append('')
    return '\n'.join(lines)


def _add_import(imports: OrderedDict[str, list[str]], module: str, name: str) -> None:
    if module not in imports:
        imports[module] = []
    if name not in imports[module]:
        imports[module].append(name)


def _value_expr(raw_value, imports: OrderedDict[str, list[str]]) -> tuple[str, str | None]:
    if raw_value is None:
        return 'None', None
    value = raw_value.strip()
    if not value:
        return "''", None
    if value.startswith('$(arg ') and value.endswith(')'):
        name = value[len('$(arg '):-1].strip()
        _add_import(imports, 'launch.substitutions', 'LaunchConfiguration')
        return f"LaunchConfiguration('{name}')", None
    if value.startswith('$(env ') and value.endswith(')'):
        name = value[len('$(env '):-1].strip()
        _add_import(imports, 'launch.substitutions', 'EnvironmentVariable')
        return f"EnvironmentVariable('{name}')", None
    lowered = value.lower()
    if lowered in {'true', 'false'}:
        return lowered.capitalize(), None
    try:
        if value.startswith('0') and value not in {'0', '0.0'} and not value.startswith('0.'):
            raise ValueError
        return str(int(value)), None
    except ValueError:
        try:
            return str(float(value)), None
        except ValueError:
            pass
    if '$(find ' in value:
        return repr(value), f"# TODO: replace substitution '{value}' with FindPackageShare/PathJoinSubstitution"
    return repr(value), None


def _dedupe_comments(comments: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for comment in comments:
        if comment in seen:
            continue
        seen.add(comment)
        ordered.append(comment)
    return ordered


def cmd_check(args: argparse.Namespace) -> int:
    from sdk.validators.basic import basic_checks
    pkg_path = Path(args.path).resolve()
    issues = basic_checks(pkg_path)
    if issues:
        for issue in issues:
            print(f"[check] ISSUE: {issue}")
        return 1
    print("[check] All checks passed.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    report_path = path / "ros_migrate_report.txt"

    lines = [
        "ROS Migration Report",
        "=" * 50,
        f"Path: {path}",
        "",
    ]

    try:
        pkg = parse_package(path)
        lines.append(f"Package:    {pkg.name}")
        lines.append(f"Build type: {pkg.build_type}")
        lines.append(f"Deps:       {', '.join(pkg.deps) if pkg.deps else '(none)'}")
        if pkg.msgs:
            lines.append(f"Messages:   {', '.join(pkg.msgs)}")
        if pkg.srvs:
            lines.append(f"Services:   {', '.join(pkg.srvs)}")
        if pkg.actions:
            lines.append(f"Actions:    {', '.join(pkg.actions)}")
        lines.append("")

        nodes = analyze_python_sources(path)
        lines.append(f"Python Nodes: {len(nodes)}")
        for n in nodes:
            lines.append(f"  Node: {n.name} ({n.file})")
            if n.pubs:
                lines.append(f"    Publishers ({len(n.pubs)}): " +
                             ', '.join(f"{p.topic}[{p.type}]" for p in n.pubs))
            if n.subs:
                lines.append(f"    Subscribers ({len(n.subs)}): " +
                             ', '.join(f"{s.topic}[{s.type}]" for s in n.subs))
            if n.srvs:
                servers = [s for s in n.srvs if not s.is_client]
                clients = [s for s in n.srvs if s.is_client]
                if servers:
                    lines.append(f"    Srv Servers ({len(servers)}): " +
                                 ', '.join(f"{s.name}[{s.type}]" for s in servers))
                if clients:
                    lines.append(f"    Srv Clients ({len(clients)}): " +
                                 ', '.join(f"{s.name}[{s.type}]" for s in clients))
            if n.params:
                lines.append(f"    Parameters ({len(n.params)}): " +
                             ', '.join(p.name for p in n.params))
            if n.timers:
                timer_strs = [f"{t.callback}@{t.period}s" if t.period else t.callback for t in n.timers]
                lines.append(f"    Timers ({len(n.timers)}): " + ', '.join(timer_strs))
            if n.tf_usage:
                lines.append("    TF usage:    yes (requires tf2_ros migration)")
            if n.clock_usage:
                lines.append("    Clock usage: yes (use self.get_clock().now())")
    except Exception as exc:
        lines.append(f"Note: could not analyze as ROS1 package ({exc})")

    lines.append("")
    lines.append("Manual Follow-Up (TODOs in generated Python files):")
    todo_total = 0
    try:
        for py in sorted(path.rglob("*.py")):
            try:
                text = py.read_text(encoding='utf-8')
                count = text.count('TODO')
                if count:
                    todo_total += count
                    lines.append(f"  {py.relative_to(path)}: {count} TODO(s)")
            except Exception:
                pass
    except Exception:
        pass
    if todo_total == 0:
        lines.append("  (none found)")
    lines.append("")
    lines.append(f"Total TODOs: {todo_total}")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f"[report] Wrote {report_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ros-migrate", description="ROS1 -> ROS2 migration SDK (skeleton)")
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

