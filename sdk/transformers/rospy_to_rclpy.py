from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from sdk.ir.model import PackageIR


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

    # Copy python scripts into the module dir, add TODO header
    entries = []
    for py in _ros1_py_scripts(src_pkg):
        rel_name = py.stem
        dst = module_dir / f"{rel_name}.py"
        text = py.read_text(encoding='utf-8')
        header = (
            "# AUTO-GENERATED SKELETON\n"
            "# TODO: convert rospy → rclpy (use SDK transformer)\n\n"
        )
        dst.write_text(header + text, encoding='utf-8')
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

