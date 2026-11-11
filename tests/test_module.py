#!/usr/bin/env python3
"""用临时普通文件模拟块设备，验证刷写边界及失败回退；不连接手机。"""

import hashlib
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "common.sh"
STOCK = b"stock-recovery!!"
FOX = b"orangefox-image!"
OTHER = b"thirdparty-img!!"
OLD_FOX = b"orangefox-old!!!"
OLD_STOCK = b"old-recovery!!!!"


class ModuleFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dijun-ksu-tests-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.partition = self.path / "partition_b"
        self.partition.write_bytes(STOCK)
        (self.path / "partition_a").write_bytes(STOCK)
        (self.path / "orangefox.img").write_bytes(FOX)
        (self.path / "stock-recovery.img").write_bytes(STOCK)
        (self.path / "images.env").write_text(
            f"FIRMWARE=OS4.0.4.0.XODCNXM\nIMAGE_BYTES={len(STOCK)}\n"
            f"FOX_SHA256={hashlib.sha256(FOX).hexdigest()}\n"
            f"STOCK_SHA256={hashlib.sha256(STOCK).hexdigest()}\n")

    def run_flow(self, command, **overrides):
        # 替身只存在于宿主测试进程：生产脚本没有可覆盖目标分区的环境开关。
        harness = f"MODDIR={shlex.quote(str(self.path))}\n. {shlex.quote(str(COMMON))}\n"
        harness += r'''
slot_device() { echo "$MODDIR/partition$1"; }
installed_module_dir() { echo "$MODDIR/previous"; }
id() { echo 0; }
getprop() {
    case "$1" in
        ro.product.device) echo "${SIM_PRODUCT:-dijun}";;
        ro.build.version.incremental) echo "${SIM_FIRMWARE:-OS4.0.4.0.XODCNXM}";;
        ro.boot.slot_suffix) echo "${SIM_PROP_SLOT:-${SIM_SLOT:-_b}}";;
    esac
}
boot_value() {
    case "$1" in
        hwproductname) echo dijun;;
        slot_suffix) echo "${SIM_SLOT:-_b}";;
        *) echo "${SIM_LOCK:-unlocked}";;
    esac
}
test() {
    if [ "$1" = -b ]; then [ -f "$2" ]; else command test "$@"; fi
}
blockdev() { wc -c <"$2" | tr -d '[:space:]'; }
sha256sum() { shasum -a 256 "$1"; }
dd() {
    local input output arg
    for arg in "$@"; do
        case "$arg" in if=*) input=${arg#if=};; of=*) output=${arg#of=};; esac
    done
    echo "${input##*/}" >>"$MODDIR/writes"
    if [ "${SIM_FAIL:-}" = all ] || { [ "${SIM_FAIL:-}" = fox ] && [ "$input" = "$MODDIR/orangefox.img" ]; }; then
        printf broken >"$output"
        return 1
    fi
    cat "$input" >"$output"
}
'''
        env = os.environ | overrides
        return subprocess.run(["/bin/sh", "-c", harness + "\n" + command], env=env,
                              capture_output=True, text=True, timeout=10)

    def no_writes(self):
        self.assertFalse((self.path / "writes").exists())

    def test_install_readback_and_restore(self):
        result = self.run_flow("install_recovery && restore_recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.partition.read_bytes(), STOCK)
        self.assertEqual((self.path / "writes").read_text().splitlines(), ["orangefox.img", "stock-recovery.img"])

    def test_repeat_install_does_not_write(self):
        self.partition.write_bytes(FOX)
        (self.path / "installed-slot").write_text("_b\n")
        self.assertEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()

    def test_wrong_device_firmware_slot_or_lock_does_not_write(self):
        for key, value in [("SIM_PRODUCT", "elish"), ("SIM_FIRMWARE", "other"),
                           ("SIM_SLOT", "_invalid"), ("SIM_LOCK", "locked"),
                           ("SIM_PROP_SLOT", "_a")]:
            with self.subTest(key=key):
                self.assertNotEqual(self.run_flow("install_recovery", **{key: value}).returncode, 0)
                self.no_writes()
                self.assertEqual(self.partition.read_bytes(), STOCK)

    def test_corrupt_payload_does_not_write(self):
        (self.path / "orangefox.img").write_bytes(OTHER)
        self.assertNotEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()

    def test_third_party_recovery_is_not_overwritten(self):
        self.partition.write_bytes(OTHER)
        (self.path / "installed-slot").write_text("_b\n")
        for action in ("install_recovery", "restore_recovery"):
            self.assertNotEqual(self.run_flow(action).returncode, 0)
            self.no_writes()
            self.assertEqual(self.partition.read_bytes(), OTHER)

    def test_failed_install_restores_stock_and_reports_failure(self):
        result = self.run_flow("install_recovery", SIM_FAIL="fox")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.partition.read_bytes(), STOCK)
        self.assertIn("原厂 Recovery 已恢复", result.stderr)

    def test_failed_rollback_is_not_reported_as_success(self):
        result = self.run_flow("install_recovery", SIM_FAIL="all")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("写入及回退均失败", result.stderr)

    def test_a_slot_install_and_restore_stay_on_a_after_active_slot_changes(self):
        result = self.run_flow("install_recovery", SIM_SLOT="_a")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.path / "partition_a").read_bytes(), FOX)
        self.assertEqual(self.partition.read_bytes(), STOCK)
        self.assertEqual((self.path / "installed-slot").read_text(), "_a\n")
        result = self.run_flow("restore_recovery", SIM_SLOT="_b")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.path / "partition_a").read_bytes(), STOCK)
        self.assertEqual(self.partition.read_bytes(), STOCK)

    def test_existing_fox_without_install_record_is_not_assigned_a_restore_slot(self):
        self.partition.write_bytes(FOX)
        self.assertNotEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()

    def test_existing_install_on_other_slot_is_not_abandoned(self):
        (self.path / "installed-slot").write_text("_a\n")
        self.assertNotEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()

    def previous_install(self, slot="_b", stock=STOCK):
        previous = self.path / "previous"
        previous.mkdir()
        (previous / "installed-slot").write_text(slot + "\n")
        (previous / "orangefox.img").write_bytes(OLD_FOX)
        (previous / "stock-recovery.img").write_bytes(stock)
        (previous / "images.env").write_text(
            f"FOX_SHA256={hashlib.sha256(OLD_FOX).hexdigest()}\n"
            f"STOCK_SHA256={hashlib.sha256(stock).hexdigest()}\n")
        (self.path / ("partition" + slot)).write_bytes(OLD_FOX)
        return previous

    def test_upgrade_from_verified_previous_image(self):
        self.previous_install()
        result = self.run_flow("install_recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.partition.read_bytes(), FOX)
        self.assertEqual((self.path / "installed-slot").read_text(), "_b\n")

    def test_failed_upgrade_returns_to_previous_image(self):
        self.previous_install()
        result = self.run_flow("install_recovery", SIM_FAIL="fox")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.partition.read_bytes(), OLD_FOX)
        self.assertIn("此前 OrangeFox 已恢复", result.stderr)

    def test_corrupt_previous_package_does_not_authorize_upgrade(self):
        previous = self.previous_install()
        (previous / "orangefox.img").write_bytes(OTHER)
        self.assertNotEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()
        self.assertEqual(self.partition.read_bytes(), OLD_FOX)

    def test_ota_upgrade_preserves_and_restores_each_slots_own_firmware(self):
        self.previous_install("_a", stock=OLD_STOCK)
        result = self.run_flow("install_recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.partition.read_bytes(), FOX)
        self.assertEqual((self.path / "partition_a").read_bytes(), OLD_FOX)
        self.assertEqual((self.path / "previous-slot/stock-recovery.img").read_bytes(), OLD_STOCK)
        self.assertEqual((self.path / "previous-slot/installed-slot").read_text(), "_a\n")
        result = self.run_flow("restore_recovery", SIM_FIRMWARE="a-later-ota")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.partition.read_bytes(), STOCK)
        self.assertEqual((self.path / "partition_a").read_bytes(), OLD_STOCK)

    def test_ota_upgrade_requires_new_stock_on_current_slot(self):
        self.previous_install("_a", stock=OLD_STOCK)
        self.partition.write_bytes(OTHER)
        self.assertNotEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()

    def test_repeat_ota_install_before_module_activation_does_not_write_again(self):
        self.previous_install("_a", stock=OLD_STOCK)
        result = self.run_flow("install_recovery && install_recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.path / "writes").read_text().splitlines(), ["orangefox.img"])
        self.assertEqual((self.path / "previous-slot/stock-recovery.img").read_bytes(), OLD_STOCK)
        self.assertEqual((self.path / "partition_a").read_bytes(), OLD_FOX)

    def test_ota_upgrade_rejects_corrupt_old_stock_before_writing(self):
        previous = self.previous_install("_a", stock=OLD_STOCK)
        (previous / "stock-recovery.img").write_bytes(OTHER)
        self.assertNotEqual(self.run_flow("install_recovery").returncode, 0)
        self.no_writes()
        self.assertEqual((self.path / "partition_a").read_bytes(), OLD_FOX)

    def test_restore_after_ota_preserves_changed_old_slot(self):
        self.previous_install("_a", stock=OLD_STOCK)
        self.assertEqual(self.run_flow("install_recovery").returncode, 0)
        (self.path / "partition_a").write_bytes(OTHER)
        result = self.run_flow("restore_recovery")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.partition.read_bytes(), STOCK)
        self.assertEqual((self.path / "partition_a").read_bytes(), OTHER)

    def test_module_upgrade_keeps_previous_slot_backup(self):
        previous = self.previous_install()
        backup = previous / "previous-slot"
        backup.mkdir()
        (backup / "installed-slot").write_text("_a\n")
        (backup / "stock-recovery.img").write_bytes(OLD_STOCK)
        (backup / "images.env").write_text(
            f"FOX_SHA256={hashlib.sha256(OLD_FOX).hexdigest()}\n"
            f"STOCK_SHA256={hashlib.sha256(OLD_STOCK).hexdigest()}\n")
        (self.path / "partition_a").write_bytes(OLD_FOX)
        result = self.run_flow("install_recovery && restore_recovery")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.path / "partition_a").read_bytes(), OLD_STOCK)

    def test_failed_ota_install_leaves_previous_slot_and_backup_intact(self):
        previous = self.previous_install("_a", stock=OLD_STOCK)
        result = self.run_flow("install_recovery", SIM_FAIL="fox")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.partition.read_bytes(), STOCK)
        self.assertEqual((self.path / "partition_a").read_bytes(), OLD_FOX)
        self.assertEqual((previous / "stock-recovery.img").read_bytes(), OLD_STOCK)

    def test_restore_allows_recorded_image_after_firmware_changes(self):
        self.assertEqual(self.run_flow("install_recovery").returncode, 0)
        result = self.run_flow("restore_recovery", SIM_FIRMWARE="a-later-ota")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.partition.read_bytes(), STOCK)


if __name__ == "__main__":
    unittest.main()
