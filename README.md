# ROS Migrate SDK (ROS1 → ROS2)

A pragmatic, extensible SDK + CLI to assist with migrating ROS1 (rospy/roscpp, catkin, roslaunch) codebases to ROS2 (rclpy/rclcpp, ament, Python launch).

Status: initial scaffold (IR models, analyzers stubs, rules, templates, CLI skeleton).

Quick start (skeleton)
- Analyze a ROS1 package: `python -m cli.ros_migrate analyze <path-to-ros1-pkg>`
- Convert (prototype, Python-focused): `python -m cli.ros_migrate convert <path-to-ros1-pkg> --lang py --out ./out_ws`
- Convert a launch file: `python -m cli.ros_migrate launch <path-to-launch.xml> --out ./out_pkg`

What’s included
- IR dataclasses (`sdk/ir/model.py`)
- Analyzers (ROS1 Python, launch XML, package.xml)
- Transformers stubs (rospy → rclpy)
- Rules (YAML) and templates (Jinja-ready)
- CLI (`cli/ros_migrate.py`) with basic subcommands

Roadmap (next)
- Flesh out AST-based Python transformer
- Generate ROS2 package structure fully (package.xml v3, setup.cfg)
- Add validators and HTML report
- Add C++ transformer (libclang)

Notes
- Current scaffold avoids non-stdlib deps at runtime. Templates and rules are provided for future use.
