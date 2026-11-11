#!/usr/bin/env python3
"""从本地原厂材料准备固定版本的 Recovery 构建输入，不连接手机。"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/recovery"))
from extract_stock_recovery import parse_boot, parse_vendor, unpack_ramdisk


def copy_checked(source, destination, record):
    """先验证原件再复制；外部固件与发布时核验的完整哈希必须一致。"""
    source, destination = Path(source), Path(destination)
    with source.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != record["sha256"] or (
            "bytes" in record and source.stat().st_size != record["bytes"]):
        raise ValueError(f"原厂输入不匹配：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def unpack_stock(source, directory, vendor=False):
    directory.mkdir(parents=True, exist_ok=True)
    ramdisk = directory / "ramdisk-00"
    # 只替换本脚本生成的解包目录，不删除用户传入的原件。
    if ramdisk.exists():
        shutil.rmtree(ramdisk)
    if vendor:
        layout = parse_vendor(source.read_bytes(), directory)
        if len(layout["ramdisks"]) != 1:
            raise ValueError("vendor_boot 与固定构建布局不一致")
        compressed = directory / layout["ramdisks"][0]["file"]
    else:
        parse_boot(source.read_bytes(), directory)
        compressed = directory / "ramdisk.lz4"
    unpack_ramdisk(compressed.read_bytes(), ramdisk)
    return ramdisk / "root"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orangefox-zip", type=Path, required=True)
    parser.add_argument("--stock-recovery", type=Path, required=True)
    parser.add_argument("--vendor-boot", type=Path)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--prepared-blobs", type=Path,
                        help="已按设备树 proprietary/ 布局保存的原厂输入")
    inputs.add_argument("--firmware-root", type=Path,
                        help="包含 vendor/、odm/、vendor_dlkm/ 的只读原厂文件树")
    args = parser.parse_args()
    if args.firmware_root and not args.vendor_boot:
        parser.error("--firmware-root 需要同时提供 --vendor-boot")
    manifest = json.loads((ROOT / "config/build-inputs.json").read_text())
    records = json.loads((ROOT / "config/proprietary-files.json").read_text())
    donor = manifest["donor"]
    copy_checked(args.orangefox_zip, ROOT / donor["file"], donor)
    recovery = manifest["stock"]["recovery_b.img"]
    copy_checked(args.stock_recovery, ROOT / recovery["file"], recovery)
    stock_root = unpack_stock(ROOT / recovery["file"], ROOT / "build/recovery/stock/recovery_b")
    vendor_root = None
    if args.vendor_boot:
        vendor = manifest["stock"]["vendor_boot_b.img"]
        copy_checked(args.vendor_boot, ROOT / vendor["file"], vendor)
        vendor_root = unpack_stock(ROOT / vendor["file"],
                                   ROOT / "build/recovery/stock/vendor_boot_b", vendor=True)
    for record in records:
        kind = record["kind"]
        if kind == "stock":
            source = stock_root / record["source"].split("/root/", 1)[1]
        elif args.prepared_blobs:
            source = args.prepared_blobs / record["prepared"]
        elif kind == "vendor_boot":
            source = vendor_root / record["source"].split("/root/", 1)[1]
        elif kind == "vendor_dlkm":
            source = args.firmware_root / "vendor_dlkm/lib/modules" / Path(record["source"]).name
        else:
            source = args.firmware_root / record["source"].lstrip("/")
        copy_checked(source, ROOT / record["destination"], record)
    print(json.dumps({"firmware": manifest["firmware"], "verified_files": len(records),
                      "phone_operations": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
