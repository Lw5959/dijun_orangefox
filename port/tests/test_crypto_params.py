#!/usr/bin/env python3
"""在宿主文件树执行参数入口；挂载和属性命令为替身，不调用设备或安全服务。"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "recovery/prebuilt/prepare-crypto-params.sh"


class CryptoParametersTest(unittest.TestCase):
    def run_params(self, **changes):
        values = {
            "release": "17", "system_patch": "2026-10-01", "vendor_patch": "2026-09-01",
            "system_build": "17OS4.0.261106.161950561.XRPECN.S", "vendor_build": "OS4.0.3.1.XODCN",
        } | changes
        with tempfile.TemporaryDirectory(prefix="dijun-crypto-params-") as temporary:
            root = Path(temporary)
            base = root / "mounted"
            (base / "system/system").mkdir(parents=True)
            (base / "vendor").mkdir()
            (base / "system/system/build.prop").write_text(
                f"ro.build.version.release={values['release']}\n"
                f"ro.build.version.security_patch={values['system_patch']}\n"
                f"ro.build.version.incremental={values['system_build']}\n")
            (base / "vendor/build.prop").write_text(
                f"ro.vendor.build.security_patch={values['vendor_patch']}\n"
                f"ro.vendor.build.version.incremental={values['vendor_build']}\n")
            mapper = root / "mapper"
            mapper.mkdir()
            for name in ("system_b", "vendor_b"):
                (mapper / name).touch()
            # 宿主普通文件代替块设备，其余控制流和实际 sed 参数读取保持原样。
            script = SCRIPT.read_text().replace("/mnt/dijun-crypto-params", str(base))
            script = script.replace("/dev/block/mapper", str(mapper)).replace("[ ! -b ", "[ ! -f ")
            script = script.replace("/tmp/dijun-crypto-params.log", str(root / "run.log"))
            harness = r'''
mount() { return 0; }
umount() { return 0; }
setprop() { printf '%s=%s\n' "$1" "$2" >>"$PARAM_TEST_ROOT/states"; }
resetprop() { printf '%s' "$2" >"$PARAM_TEST_ROOT/$1"; }
getprop() {
    if [ "$1" = ro.boot.slot_suffix ]; then echo _b; else cat "$PARAM_TEST_ROOT/$1"; fi
}
'''
            result = subprocess.run(["/bin/sh", "-c", harness + script],
                                    env=os.environ | {"PARAM_TEST_ROOT": str(root)},
                                    capture_output=True, text=True, timeout=10)
            states = (root / "states").read_text()
            props = {p.name: p.read_text() for p in root.glob("ro.*")}
            return result.returncode, states, props, (root / "run.log").read_text()

    def test_actual_system_and_vendor_patches_are_passed_separately(self):
        code, states, props, log = self.run_params()
        self.assertEqual(code, 0, log)
        self.assertTrue(states.endswith("twrp.crypto.boot_params.ready=true\n"))
        self.assertEqual(props["ro.build.version.security_patch"], "2026-10-01")
        self.assertEqual(props["ro.vendor.build.security_patch"], "2026-09-01")
        self.assertEqual(props["ro.product.device"], "dijun")

    def test_other_firmware_or_snapshot_does_not_release_security_services(self):
        for changes in ({"system_patch": "2026-09-01"}, {"vendor_patch": "2026-10-01"},
                        {"system_build": "older-snapshot"}, {"vendor_build": "other-build"},
                        {"release": "16"}):
            with self.subTest(changes=changes):
                code, states, props, log = self.run_params(**changes)
                self.assertNotEqual(code, 0, log)
                self.assertEqual(states, "twrp.crypto.boot_params.ready=false\n")
                self.assertFalse(props)


if __name__ == "__main__":
    unittest.main()
