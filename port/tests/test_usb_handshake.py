"""USB 模式确认不能早于本机所需的 ConfigFS 清理。"""

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/recovery"))
from build_prebuilt_trial import configure_usb_handshake

BASE = b"""import /init.recovery.usb.rc
on property:sys.usb.config=none && property:sys.usb.configfs=0
    stop adbd
    setprop sys.usb.state ${sys.usb.config}
on property:sys.usb.config=none && property:sys.usb.configfs=1
    rm /config/usb_gadget/g1/configs/b.1/f1
    setprop sys.usb.state ${sys.usb.config}
on property:sys.usb.config=adb && property:sys.usb.ffs.ready=1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}
on property:sys.usb.config=sideload && property:sys.usb.ffs.ready=1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}
on property:sys.usb.config=fastboot && property:sys.usb.ffs.ready=1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}
"""


class UsbHandshakeTest(unittest.TestCase):
    def test_none_has_one_publisher_after_both_function_cleanup(self):
        base = configure_usb_handshake(BASE).decode()
        device = (ROOT / "recovery/device/xiaomi/dijun/recovery/root/init.recovery.usb.rc").read_text()
        blocks = re.split(r"(?=^on )", base + "\n" + device, flags=re.M)
        none = [block for block in blocks if block.startswith("on property:sys.usb.config=none")]
        self.assertEqual(len(none), 1)
        commands = [line.strip() for line in none[0].splitlines()[1:]
                    if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(commands[-1], "setprop sys.usb.state none")
        for required in ("stop adbd", "stop fastbootd",
                         "rm /config/usb_gadget/g1/configs/b.1/f1",
                         "rm /config/usb_gadget/g1/configs/b.1/f2",
                         "setprop sys.usb.ffs.ready 0", "setprop sys.usb.ffs.mtp.ready 0"):
            self.assertIn(required, commands[:-1])

    def test_each_completion_reports_the_mode_it_bound(self):
        data = configure_usb_handshake(BASE).decode()
        self.assertNotIn("setprop sys.usb.state ${sys.usb.config}", data)
        for mode in ("adb", "sideload", "fastboot"):
            self.assertIn("setprop sys.usb.state " + mode, data)

    def test_display_and_crypto_assembly_can_both_apply_the_change(self):
        once = configure_usb_handshake(BASE)
        self.assertEqual(configure_usb_handshake(once), once)


if __name__ == "__main__":
    unittest.main()
