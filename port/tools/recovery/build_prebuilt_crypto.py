#!/usr/bin/env python3
"""打包已接入原厂解密组件的 dijun 候选；不刷机，不能替代真机解密验收。"""

import hashlib
import json
import stat
import struct
import subprocess
import sys
from pathlib import Path

from build_prebuilt_trial import make_cpio
from extract_stock_recovery import avb_info
import stage_prebuilt_crypto

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "build/recovery/prebuilt-crypto"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    if stage_prebuilt_crypto.main() != 0:
        raise RuntimeError("解密组件的实际 ELF/init 依赖未通过")
    root = STAGE / "root"
    checks = json.loads((STAGE / "key-policy-checks.json").read_text())
    hardware = json.loads((STAGE / "hardware-policy.json").read_text())
    assert checks["passed"]
    assert checks["patched_sha256"] == hardware["source_sha256"]
    final_recovery = (root / "system/bin/recovery").read_bytes()
    assert hardware["patched_sha256"] == sha(final_recovery)
    # 还原硬件修正后必须逐字节回到已完成密钥策略检查的 ELF，不能只沿用旧报告。
    restored = bytearray(final_recovery)
    for patch in hardware["patches"]:
        offset = int(patch["offset"], 16)
        before, after = bytes.fromhex(patch["before"]), bytes.fromhex(patch["after"])
        assert restored[offset:offset + len(after)] == after
        restored[offset:offset + len(after)] = before
    assert sha(restored) == checks["patched_sha256"]
    assert checks["patched_fs_mgr_sha256"] == sha((root / "system/lib64/libfs_mgr.so").read_bytes())
    entries = {entry["path"]: entry for entry in json.loads((STAGE / "entries.json").read_text())}
    payloads = {}
    for name, entry in entries.items():
        if stat.S_ISREG(entry["mode"]):
            payloads[name] = (root / name).read_bytes()
        elif stat.S_ISLNK(entry["mode"]):
            payloads[name] = entry["symlink_target"].encode()
    # 避免再次遗漏额外挂载入口；完整挂载表只有本机正式 device tree 一份。
    assert not any(line.strip() and not line.lstrip().startswith("#") for line in payloads["system/etc/twrp.flags"].decode().splitlines())
    assert payloads["system/etc/recovery.fstab"] == (ROOT / "recovery/device/xiaomi/dijun/recovery.fstab").read_bytes()
    for line in payloads["system/etc/recovery.fstab"].decode().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        assert not {"check", "formattable", "resize"}.intersection(fields[4].split(","))

    compressed = subprocess.run(["lz4", "-l", "-12", "-c"], input=make_cpio(entries, payloads), capture_output=True, check=True).stdout
    header = bytearray(4096)
    header[:8] = b"ANDROID!"
    struct.pack_into("<4I", header, 8, 0, len(compressed), 0, 1584)
    struct.pack_into("<I", header, 40, 4)
    image = ROOT / "build/recovery/OrangeFox-dijun-crypto-trial-zh.img"
    image.write_bytes(header + compressed + bytes(-len(compressed) % 4096))
    stock = ROOT / "inputs/recovery/os4-0-4-0/recovery.img"
    original = avb_info(stock.read_bytes())
    fingerprint = next(x["value"] for x in original["descriptors"] if x.get("key") == "com.android.build.recovery.fingerprint")
    subprocess.run([sys.executable, str(ROOT / "sources/orangefox/component-tools/avbtool.py"), "add_hash_footer",
                    "--image", str(image), "--partition_name", "recovery", "--partition_size", "104857600",
                    "--algorithm", "NONE", "--rollback_index", str(original["rollback_index"]),
                    "--rollback_index_location", str(original["rollback_index_location"]),
                    "--salt", "c4cbfdb2ca989e645b7404af41d94a001c371a73ec338616b31f1b5c690fb36d",
                    "--prop", "com.android.build.recovery.fingerprint:" + fingerprint], check=True)
    data = image.read_bytes()
    report = {"image": str(image), "sha256": sha(data), "bytes": len(data), "avb": avb_info(data),
              "ramdisk_compressed_bytes": len(compressed), "language": "zh_CN", "recovery_userland_sdk": 34,
              "decryption_enabled": True, "original_vendor_files": 31, "key_policy_cases": len(checks["cases"]),
              "hardware_boot_verified": False, "decryption_verified": False, "phone_operations": False,
              "initializing_new_encrypted_userdata_supported": False}
    (STAGE / "build.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("image", "sha256", "bytes", "decryption_enabled", "decryption_verified")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
