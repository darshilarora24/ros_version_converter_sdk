from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, List

from sdk.ir.model import PackageIR, NodeIR
from sdk.rules.loader import load_api_rules, load_qos_rules
from sdk.analyzers.rospy_parser import analyze_python_file


PKG_XML_TEMPLATE = """<?xml version="1.0"?>
<package format="3">
  <name>{name}</name>
  <version>0.1.0</version>
  <description>Auto-converted ROS1 → ROS2 package (skeleton)</description>
  <maintainer email="todo@example.com">TODO</maintainer>
  <license>TODO</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <buildtool_depend>ament_python</buildtool_depend>
  <exec_depend>rclpy</exec_depend>
  <exec_depend>rosidl_default_runtime</exec_depend>
  {msg_deps}
  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
"""


SETUP_CFG_TEMPLATE = """[metadata]
name = {name}
version = 0.1.0

[options]
packages = find:
install_requires =
    rclpy
zip_safe = false

[options.entry_points]
console_scripts =
{entry_points}
"""


def _ros1_py_scripts(src: Path):
    yield from src.glob('*.py')
    scripts = src / 'scripts'
    if scripts.exists():
        yield from scripts.glob('*.py')


def convert_python_package_skeleton(src_pkg: Path, out_ws: Path, pkg: PackageIR) -> None:
    """
    Minimal skeleton converter for Python packages.
    - Creates ROS2-style package folder
    - Copies Python scripts as-is into a module folder named after the package
    - Generates package.xml (format 3) and setup.cfg with console_scripts entries

    NOTE: This is a scaffold. Actual AST-based conversion (rospy→rclpy) is not yet applied here.
    """
    ros2_pkg_dir = out_ws / f"{pkg.name}_ros2"
    module_dir = ros2_pkg_dir / pkg.name
    launch_dir = ros2_pkg_dir / 'launch'
    config_dir = ros2_pkg_dir / 'config'

    for d in [module_dir, launch_dir, config_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy msgs/srvs/actions if exist
    for iface in ['msg', 'srv', 'action']:
        src_dir = src_pkg / iface
        if src_dir.exists():
            shutil.copytree(src_dir, ros2_pkg_dir / iface, dirs_exist_ok=True)

    # Copy or transform python scripts into the module dir
    entries = []
    for py in _ros1_py_scripts(src_pkg):
        rel_name = py.stem
        dst = module_dir / f"{rel_name}.py"
        transformed = transform_rospy_file(py)
        content: str
        if transformed is None:
            # Fallback: copy with TODO header
            text = py.read_text(encoding='utf-8')
            header = (
                "# AUTO-GENERATED SKELETON\n"
                "# TODO: convert rospy → rclpy (use SDK transformer)\n\n"
            )
            content = header + text
        else:
            content = transformed
        dst.write_text(content, encoding='utf-8')
        # Add console_script only if a main() exists
        if 'def main(' in content:
            entries.append(f"    {rel_name} = {pkg.name}.{rel_name}:main")

    # package.xml
    msg_deps = "".join([f"  <exec_depend>{d}</exec_depend>\n" for d in pkg.deps if d.endswith('_msgs')])
    (ros2_pkg_dir / 'package.xml').write_text(
        PKG_XML_TEMPLATE.format(name=pkg.name, msg_deps=msg_deps), encoding='utf-8'
    )

    # setup.cfg with console_scripts (best-effort)
    entry_points = "\n".join(entries) if entries else ""
    (ros2_pkg_dir / 'setup.cfg').write_text(
        SETUP_CFG_TEMPLATE.format(name=pkg.name, entry_points=entry_points), encoding='utf-8'
    )

    # Minimal pyproject for editable installs if desired
    (ros2_pkg_dir / 'pyproject.toml').write_text(
        """[build-system]\nrequires = [\"setuptools\"]\nbuild-backend = \"setuptools.build_meta\"\n""",
        encoding='utf-8'
    )


def _collect_non_rospy_imports(src: str) -> List[str]:
    import ast
    lines: List[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return lines
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            # Skip rospy imports
            if isinstance(n, ast.Import) and any(a.name == 'rospy' for a in n.names):
                continue
            if isinstance(n, ast.ImportFrom) and (n.module == 'rospy' or (n.module and n.module.startswith('rospy.'))):
                continue
            seg = ast.get_source_segment(src, n)
            if seg:
                lines.append(seg.strip())
    return lines


def _collect_defs(src: str) -> List[str]:
    import ast
    out: List[str] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            seg = ast.get_source_segment(src, n)
            if seg:
                out.append(seg.rstrip())
    return out


def _rewrite_logging_in_text(src: str) -> str:
    # Prefer rule-driven mappings if available; fall back to rclpy logger
    try:
        rules_dir = Path(__file__).resolve().parents[1] / 'rules'
        api = load_api_rules(rules_dir)
        logging_map = (api.get('logging') or {}) if isinstance(api, dict) else {}
    except Exception:
        logging_map = {}
    # Replace known logging calls
    repl = {
        'rospy.logdebug': logging_map.get('rospy.logdebug', 'rclpy.logging.get_logger("migrated").debug'),
        'rospy.loginfo': logging_map.get('rospy.loginfo', 'rclpy.logging.get_logger("migrated").info'),
        'rospy.logwarn': logging_map.get('rospy.logwarn', 'rclpy.logging.get_logger("migrated").warn'),
        'rospy.logerr': logging_map.get('rospy.logerr', 'rclpy.logging.get_logger("migrated").error'),
    }
    for k, v in repl.items():
        # If rule suggests node.get_logger(), prefer global rclpy logger in free functions
        if v.startswith('node.get_logger()'):
            v = 'rclpy.logging.get_logger("migrated")' + v[len('node.get_logger()'):]
        src = src.replace(k, v)
    return src


def transform_rospy_file(path: Path) -> Optional[str]:
    """Attempt a first-pass rospy→rclpy transformation for simple pub/sub nodes.

    - Keeps non-rospy imports and all defs (functions/classes) from original file
    - Generates a Node subclass that creates publishers/subscriptions discovered
    - Adds a main() that inits and spins the node
    - Applies naive logging rewrite in kept defs

    Returns new source text, or None if the file does not look like a rospy node.
    """
    src = path.read_text(encoding='utf-8')
    node_ir: Optional[NodeIR] = analyze_python_file(path)
    if node_ir is None:
        return None

    # Gather imports and defs
    imports = _collect_non_rospy_imports(src)
    defs_src = _collect_defs(_rewrite_logging_in_text(src))

    lines: List[str] = []
    # Load rules
    rules_dir = Path(__file__).resolve().parents[1] / 'rules'
    try:
        api_rules = load_api_rules(rules_dir)
    except Exception:
        api_rules = {}
    try:
        qos_rules = load_qos_rules(rules_dir)
    except Exception:
        qos_rules = {}

    publisher_method = ((api_rules.get('pubsub') or {}).get('publisher_method')) or 'create_publisher'
    subscription_method = ((api_rules.get('pubsub') or {}).get('subscription_method')) or 'create_subscription'
    default_depth = ((qos_rules.get('queue_to_qos') or {}).get('default_depth')) or 10

    # Imports
    lines.extend(imports)
    lines.append('import rclpy')
    lines.append('from rclpy.node import Node')
    # Optional QoS imports if latched is detected
    if node_ir and any(getattr(p, 'latched', None) for p in node_ir.pubs):
        lines.append('from rclpy.qos import QoSProfile, QoSDurabilityPolicy')
    lines.append('')
    # Keep defs
    if defs_src:
        lines.extend(defs_src)
        lines.append('')

    # Node class
    lines.append('class MigratedNode(Node):')
    lines.append("    def __init__(self):")
    lines.append("        super().__init__('migrated_node')")
    # Timer hint from rospy.Rate usage
    # Try to extract a numeric rate to hint at timer period
    import re as _re
    m = _re.search(r"rospy\.Rate\((\d+(?:\.\d+)?)\)", src)
    if m:
        try:
            hz = float(m.group(1))
            if hz > 0:
                period = round(1.0 / hz, 6)
                lines.append(f"        # TODO: replace rospy.Rate loop with timer")
                lines.append(f"        self.timer = self.create_timer({period}, getattr(self, '_tick', lambda: None))")
        except Exception:
            pass
    if node_ir.pubs:
        lines.append("        # Publishers")
        for i, p in enumerate(node_ir.pubs):
            typ = p.type or 'TODO_MSG_TYPE'
            topic = p.topic or 'TODO_TOPIC'
            depth = p.queue_size if (hasattr(p, 'queue_size') and p.queue_size) else default_depth
            if getattr(p, 'latched', None):
                lines.append(f"        _qos_{i} = QoSProfile(depth={depth})")
                lines.append(f"        _qos_{i}.durability = QoSDurabilityPolicy.TRANSIENT_LOCAL")
                lines.append(f"        self.publisher_{i} = self.{publisher_method}({typ}, '{topic}', _qos_{i})")
            else:
                lines.append(f"        self.publisher_{i} = self.{publisher_method}({typ}, '{topic}', {depth})")
    if node_ir.subs:
        lines.append("        # Subscriptions")
        for i, s in enumerate(node_ir.subs):
            typ = s.type or 'TODO_MSG_TYPE'
            topic = s.topic or 'TODO_TOPIC'
            cb = s.callback or 'lambda msg: None  # TODO: set callback'
            depth = s.queue_size if (hasattr(s, 'queue_size') and s.queue_size) else default_depth
            lines.append(f"        self.subscription_{i} = self.{subscription_method}({typ}, '{topic}', {cb}, {depth})")
    lines.append('')

    # main()
    lines.append('def main():')
    lines.append('    rclpy.init()')
    lines.append('    node = MigratedNode()')
    lines.append('    rclpy.spin(node)')
    lines.append('    rclpy.shutdown()')
    lines.append('')
    lines.append("if __name__ == '__main__':")
    lines.append('    main()')

    return "\n".join(lines)
