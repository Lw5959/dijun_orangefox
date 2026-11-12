#!/usr/bin/env python3
"""离线装配 dijun 原厂解密闭包并检查预编译 OrangeFox ABI；不生成可刷写镜像。"""

import hashlib
import json
import re
import shutil
import stat
from pathlib import Path

from audit_runtime import RamdiskFiles, audit_runtime
from build_prebuilt_trial import configure_ui, configure_usb_handshake
from preserve_prebuilt_keys import preserve_existing_keys, preserve_mount_failures
from patch_prebuilt_hardware import patch_hardware
from patch_prebuilt_session import patch_mtp, patch_session

ROOT = Path(__file__).resolve().parents[2]
DEVICE = ROOT / "recovery/device/xiaomi/dijun"
BASE = ROOT / "build/recovery/prebuilt-trial-v2/unpacked/ramdisk"
STAGE = ROOT / "build/recovery/prebuilt-crypto"


def main():
    STAGE.mkdir(parents=True, exist_ok=True)
    root = STAGE / "root"
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(BASE / "root", root)
    entries = {entry["path"]: entry for entry in json.loads((BASE / "entries.json").read_text())}

    def add(name, data, mode=0o644):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # CPIO 解包必须先有父目录，不能仅在宿主磁盘建目录而漏掉归档条目。
        for parent in reversed(Path(name).parents):
            if str(parent) != "." and str(parent) not in entries:
                entries[str(parent)] = {"path": str(parent), "mode": stat.S_IFDIR | 0o755, "uid": 0, "gid": 0}
        path.write_bytes(data)
        entries[name] = {"path": name, "mode": stat.S_IFREG | mode, "uid": 0, "gid": 0,
                         "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    configure_ui(lambda name: (root / name).read_bytes(), add)
    add("init.recovery.usb.rc", (DEVICE / "recovery/root/init.recovery.usb.rc").read_bytes())
    firmware_policy = json.loads((ROOT / "recovery/prebuilt/firmware-policy.json").read_text())
    policy = (ROOT / "recovery/prebuilt/sepolicy-firmware-load").read_bytes()
    assert hashlib.sha256((root / "sepolicy").read_bytes()).hexdigest() == firmware_policy["source_sha256"]
    assert hashlib.sha256(policy).hexdigest() == firmware_policy["patched_sha256"]
    assert firmware_policy["only_expected_cil_changes"]
    add("sepolicy", policy)
    recovery, key_policy = preserve_existing_keys((root / "system/bin/recovery").read_bytes())
    recovery, hardware_policy = patch_hardware(recovery)
    recovery, session_policy = patch_session(recovery)
    add("system/bin/recovery", recovery, 0o755)
    (STAGE / "key-policy.json").write_text(json.dumps(key_policy, ensure_ascii=False, indent=2) + "\n")
    (STAGE / "hardware-policy.json").write_text(json.dumps(hardware_policy, ensure_ascii=False, indent=2) + "\n")
    (STAGE / "session-policy.json").write_text(json.dumps(session_policy, ensure_ascii=False, indent=2) + "\n")
    mtp, mtp_policy = patch_mtp((root / "system/lib64/libtwrpmtp-ffs.so").read_bytes())
    add("system/lib64/libtwrpmtp-ffs.so", mtp, 0o755)
    (STAGE / "mtp-session-policy.json").write_text(json.dumps(mtp_policy, ensure_ascii=False, indent=2) + "\n")
    fs_mgr, mount_policy = preserve_mount_failures((root / "system/lib64/libfs_mgr.so").read_bytes())
    add("system/lib64/libfs_mgr.so", fs_mgr, 0o755)
    (STAGE / "mount-policy.json").write_text(json.dumps(mount_policy, ensure_ascii=False, indent=2) + "\n")

    vendor = json.loads((DEVICE / "proprietary/crypto/manifest.json").read_text())
    for record in vendor["files"]:
        payload = (ROOT / record["packaged"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"原厂输入不匹配：{record['source']}")
        add(record["source"].lstrip("/"), payload, 0o755 if "/bin/" in record["source"] else 0o644)

    hardware = json.loads((DEVICE / "proprietary/hardware/manifest.json").read_text())
    for record in hardware["files"]:
        if "/etc/vintf/" in record["source"]:
            continue  # 合入 vendor 主清单，避免重复的 override 片段覆盖其他 HAL。
        if record["source"].startswith("/vendor/firmware/cs40l26"):
            continue  # 原厂实际从专用标签的 ODM 副本加载，避免选中另一套 a2h 数据。
        payload = (ROOT / record["packaged"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"原厂硬件输入不匹配：{record['source']}")
        add(record["source"].lstrip("/"), payload, 0o755 if "/bin/" in record["source"] else 0o644)
    # 新驱动在独立服务中加载；保留原来显示/触控启动闭包的成功条件。
    modules = DEVICE / "proprietary/modules/1.1"
    for record in json.loads((modules / "manifest.json").read_text())["records"]:
        payload = (modules / record["file"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"硬件模块原件不匹配：{record['file']}")
        add("vendor/lib/modules/1.1/" + record["file"], payload)
    add("vendor/lib/modules/1.1/modules.load.hardware", (modules / "modules.load").read_bytes())
    for source, destination in (("dijun-torch.sh", "system/bin/dijun-torch"),
                                ("start-dijun-hardware.sh", "system/bin/start-dijun-hardware"),
                                ("dijun-hardware.rc", "system/etc/init/dijun-hardware.rc")):
        add(destination, (ROOT / "recovery/prebuilt" / source).read_bytes(),
            0o755 if "/bin/" in destination else 0o644)
    for name in ("twres/pages/advanced.xml", "twres/pages/anywhere.xml"):
        add(name, (root / name).read_bytes().replace(b'<action function="flashlight"/>',
            b'<action function="cmd">/system/bin/dijun-torch toggle</action>'
            b'<action function="set">of_flash_on=%property.vendor.recovery.torch_on%</action>'))

    for name in ("system/etc/init/dijun-mitee.rc", "system/etc/init/keystore2.rc",
                 "system/etc/vintf/manifest/dijun-mitee.xml"):
        add(name, (DEVICE / "recovery/root" / name).read_bytes())
    # SDK 34 的 servicemanager 读取 vendor 主清单；不能沿用原厂 recovery 的 system device 片段布局。
    for name in ("system/etc/vintf/manifest/dijun-mitee.xml",
                 "system/etc/vintf/manifest/android.hardware.boot-service.xring.xml"):
        entries.pop(name, None)
        (root / name).unlink(missing_ok=True)
    add("vendor/etc/vintf/manifest.xml", (ROOT / "recovery/prebuilt/vendor-manifest.xml").read_bytes())
    add("system/etc/vintf/manifest.xml", (ROOT / "recovery/prebuilt/framework-manifest.xml").read_bytes())
    # 原厂 hal_bootctl_default 域在 donor 策略中不能读取 O1 的 misc；使用已验证的 recovery 域。
    boot_rc = "system/etc/init/android.hardware.boot-service.xring.recovery.rc"
    add(boot_rc, (root / boot_rc).read_bytes().replace(b"u:r:hal_bootctl_default:s0", b"u:r:recovery:s0"))
    # O1 原厂服务使用 system Binder/AIDL；当前恢复内核没有可用的 vndbinder 管理入口。
    # 不让与本机解密闭包无关的旧 vndservicemanager 在后台反复崩溃。
    unused = "system/etc/init/vndservicemanager.rc"
    entries.pop(unused, None)
    (root / unused).unlink(missing_ok=True)
    add("system/etc/recovery.fstab", (DEVICE / "recovery.fstab").read_bytes())
    wrapper = "system/bin/start-dijun-recovery"
    add(wrapper, (root / wrapper).read_bytes().replace(
        b"dijun OrangeFox display trial: no data or metadata mount",
        b"dijun OrangeFox crypto trial: original vendor decryption services"), 0o755)
    add("system/bin/dijun-crypto-params", (ROOT / "recovery/prebuilt/prepare-crypto-params.sh").read_bytes(), 0o755)
    add("system/etc/init/dijun-crypto-params.rc", (ROOT / "recovery/prebuilt/dijun-crypto-params.rc").read_bytes())
    # 完整候选实际启用解密，不沿用显示诊断版的跳过开关。
    prop = (root / "prop.default").read_text()
    prop = prop.replace("of_skip_fbe_decryption=true", "of_skip_fbe_decryption=false")
    prop = prop.replace("ro.orangefox.port.status=display-trial", "ro.orangefox.port.status=crypto-trial")
    prop = re.sub(r"^ro.build.product=.*$", "ro.build.product=dijun", prop, flags=re.M)
    prop = re.sub(r"^ro.product.ab_ota_partitions=.*$", "ro.product.ab_ota_partitions=product,pvmfw", prop, flags=re.M)
    prop += "\n" + (ROOT / "recovery/prebuilt/dijun-hardware.prop").read_text()
    add("prop.default", prop.encode())
    # donor 的 QCOM_RTC_FIX 每次进程重启都强制回到构建日，但补偿只在首轮运行。
    # O1 自带可读 RTC；取消该重置输入，保留原有 RTC 校时流程。
    cfg = "system/etc/fox.cfg"
    add(cfg, re.sub(rb"^ro.build.date.utc_fox=.*\n?", b"", (root / cfg).read_bytes(), flags=re.M))

    # 各进程按其 linker profile 解析库；移除 donor 的全局路径，避免 vendor 先取平台同名库。
    init = "system/etc/init/hw/init.rc"
    lines = (root / init).read_text().splitlines(keepends=True)
    add(init, configure_usb_handshake("".join(line for line in lines if not line.strip().startswith("export LD_LIBRARY_PATH ")).encode()))
    canonical = (DEVICE / "recovery/root/system/etc/ld.config.txt").read_text()
    canonical = canonical.replace("dir.recovery = /system/bin", "dir.recovery = /system\ndir.tools = /sbin\ndir.addons = /FFiles")
    # /sbin 与 /FFiles 的工具使用同一平台 profile；厂商服务始终保留独立 vendor profile。
    platform = canonical.split("[recovery]", 1)[1].split("[vendor]", 1)[0]
    canonical += "\n[tools]" + platform + "\n[addons]" + platform
    add("system/etc/ld.config.txt", canonical.encode())
    (STAGE / "entries.json").write_text(json.dumps(list(entries.values()), ensure_ascii=False, indent=2) + "\n")
    files = RamdiskFiles(root, list(entries.values()))
    for command in ("sh", "getprop", "setprop", "sleep", "mkdir", "mount", "umount", "sed", "grep", "resetprop"):
        if not files.file("/system/bin/" + command):
            raise ValueError(f"参数读取脚本缺少真实命令：{command}")

    audit = audit_runtime(root, list(entries.values()))
    (STAGE / "runtime-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    status = {"vendor_files": len(vendor["files"]), "runtime_audit_passed": audit["passed"],
              "elf_failures": audit["elf_failures"], "service_failures": audit["service_failures"],
              "image_generated": False, "phone_operations": False, "decryption_verified": False,
              "remaining": ["实测真实 Android OS/SPL 参数读取及服务启动时序",
                            "核对预编译 vold 与 Android 17 的 FBE/凭据格式及密钥写入行为",
                            "在明确授权的完整候选上验证 HAL、解密和数据读回"]}
    (STAGE / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    for check in audit["elf_checks"]:
        if not check["passed"]:
            print(json.dumps({k: v for k, v in check.items() if k != "providers"}, ensure_ascii=False))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
