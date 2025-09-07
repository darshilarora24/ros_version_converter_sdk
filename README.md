# ROS Migrate SDK (ROS1 → ROS2)

A pragmatic, extensible SDK + CLI to help migrate ROS1 (rospy/roscpp, catkin, roslaunch) codebases to ROS2 (rclpy/rclcpp, ament, Python launch).

Status: early scaffold focused on Python (rclpy) with IR models, analyzers, minimal transformers, rules, templates, and a CLI skeleton.

## Features (current)
- Analyze ROS1 Python nodes to detect publishers/subscribers and basic package metadata.
- Convert ROS1 Python packages into ROS2-style package skeletons (best-effort):
  - Creates `package.xml` (format 3), `setup.cfg`, and `pyproject.toml`.
  - Copies `msg/`, `srv/`, `action/` directories when present.
  - Attempts a simple `rospy` → `rclpy` rewrite for pub/sub and logging; otherwise copies with a TODO header.
- Convert roslaunch XML to a minimal ROS2 `launch.py` file.
- Basic checks and a placeholder report generator.

## Requirements
- Python 3.9+ (per `pyproject.toml`).
- No non-stdlib runtime dependencies for the scaffold.

## Install (editable)
```bash
python -m pip install -e .
```
This installs the `ros-migrate` entrypoint (see `[project.scripts]` in `pyproject.toml`). You can also run via module for local iteration.

## CLI Usage
- Analyze a ROS1 package:
  - `ros-migrate analyze <path-to-ros1-pkg>`
  - or `python -m cli.ros_migrate analyze <path>`
- Convert a ROS1 package (Python skeleton):
  - `ros-migrate convert <path-to-ros1-pkg> --lang py --out ./out_ws`
- Convert a roslaunch XML to ROS2 `launch.py`:
  - `ros-migrate launch <path-to-launch.xml> --out ./out_pkg`
- Basic ROS2 package check:
  - `ros-migrate check <path-to-ros2-pkg>`
- Generate a simple migration report:
  - `ros-migrate report <path>`

Run `ros-migrate -h` or subcommand `-h` for details.

## Testing
- Quick smoke test without installing: `python -m cli.ros_migrate -h`
- Run the unit tests (stdlib `unittest`): `python -m unittest -v`

## Examples
Analyze a ROS1 package:
```bash
ros-migrate analyze ~/ws/src/my_pkg
```

Convert a ROS1 Python package to a ROS2 skeleton in `./out_ws`:
```bash
ros-migrate convert ~/ws/src/my_pkg --lang py --out ./out_ws
```
Output layout (example):
```
out_ws/
  my_pkg_ros2/
    package.xml
    setup.cfg
    pyproject.toml
    launch/
    config/
    msg/ (if existed)
    srv/ (if existed)
    action/ (if existed)
    my_pkg/
      <scripts>.py  # transformed or copied with TODO header
```

Convert a roslaunch XML:
```bash
ros-migrate launch my_pkg/launch/legacy.launch --out ./my_pkg_ros2
```
Produces `my_pkg_ros2/legacy.launch.py` with a `LaunchDescription` that instantiates detected nodes.

## Before/After (Python)
A small example to illustrate what the scaffold does and what you’ll likely adjust manually.

ROS1 (rospy):
```python
#!/usr/bin/env python
import rospy
from std_msgs.msg import String

def cb(msg):
    rospy.loginfo(f"heard: {msg.data}")

def main():
    rospy.init_node('talker')
    pub = rospy.Publisher('/chatter', String, queue_size=10)
    sub = rospy.Subscriber('/chatter', String, cb)
    rate = rospy.Rate(10)
    while not rospy.is_shutdown():
        pub.publish(String(data='hello'))
        rate.sleep()

if __name__ == '__main__':
    main()
```

Tool-generated ROS2 (rclpy) skeleton (first pass):
```python
from std_msgs.msg import String
import rclpy
from rclpy.node import Node

def cb(msg):
    rclpy.logging.get_logger("migrated").info(f"heard: {msg.data}")

class MigratedNode(Node):
    def __init__(self):
        super().__init__('migrated_node')
        # Publishers
        self.publisher_0 = self.create_publisher(String, '/chatter', 10)
        # Subscriptions
        self.subscription_0 = self.create_subscription(String, '/chatter', cb, 10)

def main():
    rclpy.init()
    node = MigratedNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

Polished manually (adds a timer to replace the rospy loop):
```python
from std_msgs.msg import String
import rclpy
from rclpy.node import Node

def cb(msg):
    rclpy.logging.get_logger("migrated").info(f"heard: {msg.data}")

class MigratedNode(Node):
    def __init__(self):
        super().__init__('talker')
        self.pub = self.create_publisher(String, '/chatter', 10)
        self.sub = self.create_subscription(String, '/chatter', cb, 10)
        self.timer = self.create_timer(0.1, self._tick)

    def _tick(self):
        self.pub.publish(String(data='hello'))

def main():
    rclpy.init()
    node = MigratedNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

## What Gets Transformed (Python)
Refer to `sdk/transformers/rospy_to_rclpy.py`:
- Keeps non-rospy imports and top-level defs/classes from the original.
- Creates a `MigratedNode(Node)` and sets up publishers/subscriptions found by the analyzer.
- Adds a `main()` with `rclpy.init()`, `rclpy.spin()`, and `rclpy.shutdown()`.
- Rewrites simple `rospy.log*` calls to `rclpy` logging.

Limitations of the current pass:
- Message types and topics may become placeholders (`TODO_MSG_TYPE`, `TODO_TOPIC`) when not statically inferable.
- Parameters, services, timers, TF, and QoS mapping are not yet comprehensive.
- C++ (`roscpp` → `rclcpp`) is not implemented.
- Templates and YAML rules exist but are not yet fully integrated into the conversion flow.

## Known Gaps
- ROS1 rates/loops: not auto-translated to `create_timer`; add manually.
- Services/actions: analyzers and transformers don’t generate stubs yet.
- Parameters: declare/get/set are not consistently mapped; review manually.
- TF/TF2: only placeholders in rules; no generation of TF code.
- QoS: queue sizes → QoS profiles not inferred beyond defaults.
- Launch: only basic `<node>` → `Node(...)`; args/remaps/env and conditionals are not handled.
- Build: Python focus (`ament_python`); `ament_cmake` and C++ not supported yet.

## Project Structure
- `cli/ros_migrate.py`: CLI with subcommands (`analyze`, `convert`, `launch`, `check`, `report`).
- `sdk/ir/model.py`: IR dataclasses: `PackageIR`, `NodeIR`, `TopicIR`.
- `sdk/analyzers/`: parsers for `package.xml`, Python AST (`rospy`), and `roslaunch` XML.
- `sdk/transformers/rospy_to_rclpy.py`: minimal Python transformer and package skeleton generator.
- `sdk/templates/`: Jinja-ready templates (e.g., `rclpy_node.py.j2`).
- `sdk/rules/`: YAML mappings for APIs and QoS hints.
- `sdk/validators/`: basic validators (scaffold).

## Extending the SDK
- Improve the Python transformer to use the YAML rules in `sdk/rules/api_python.yaml` and QoS hints in `sdk/rules/qos.yaml`.
- Expand analyzers to extract parameters, services, timers, and TF usage.
- Add C++ support (likely via `libclang` or `clangd` JSON AST) and `ament_cmake` package generation.
- Integrate Jinja templates for node/file generation with richer context from the IR.
- Add a report generator that summarizes deltas, manual TODOs, and confidence.

## Troubleshooting
- If `convert` fails on `package.xml`, ensure the input path is a ROS1 package with a valid `package.xml` and (optionally) `CMakeLists.txt`.
- If generated files contain TODO placeholders, the analyzer could not infer types/topics; update manually or improve rules.
- On Windows paths, prefer using forward slashes in examples or quote paths with spaces.

## Roadmap
- Flesh out AST-based Python transformer with parameter/service/timer handling.
- Generate ROS2 package structure fully (setup.py or setuptools config as needed) and richer launch generation.
- Add validators and a human-readable HTML report.
- Add C++ transformer (`roscpp` → `rclcpp`).

## Notes
- Current scaffold avoids non-stdlib deps at runtime. Templates and rules are provided for future use.
## License
This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
