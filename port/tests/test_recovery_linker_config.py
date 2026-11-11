"""覆盖原厂 HAL 装配时实际遇到的 LD_LIBRARY_PATH 隔离误判。"""

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/recovery"))
from audit_runtime import LinkerConfig, RamdiskFiles


class LinkerEnvironmentTest(unittest.TestCase):
    def test_inherited_system_path_precedes_vendor_library(self):
        # 两份同名库模拟真实的 platform/vendor libc++，这里只检查解析路径，不假装 ELF 可用。
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = {
                "system/etc/ld.config.txt": """dir.vendor = /vendor/bin
[vendor]
namespace.default.isolated = true
namespace.default.search.paths = /vendor/lib64
namespace.default.permitted.paths = /vendor
""",
                "system/lib64/libc++.so": "platform",
                "vendor/lib64/libc++.so": "vendor",
            }
            entries = []
            for name, value in payloads.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value)
                entries.append({"path": name, "mode": stat.S_IFREG | 0o644})
            files = RamdiskFiles(root, entries)
            inherited = LinkerConfig(files, [], "/system/lib64")
            self.assertEqual(inherited.provider(("vendor", "default"), "libc++.so"),
                             ("/system/lib64/libc++.so", "default"))
            clean = LinkerConfig(files, [], "")
            self.assertEqual(clean.provider(("vendor", "default"), "libc++.so"),
                             ("/vendor/lib64/libc++.so", "default"))


if __name__ == "__main__":
    unittest.main()
