#!/usr/bin/env python3
"""离线解包 dijun 原厂恢复输入，输出 OrangeFox 移植所需布局与依赖；不操作手机。"""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import stat
import struct
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
BOOT_HEADER_REFERENCE = "https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/heads/android17-release/include/bootimg/bootimg.h"
AVB_REFERENCE = "https://android.googlesource.com/platform/external/avb/+/refs/heads/main/avbtool.py"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def align(size, page=4096):
    return (size + page - 1) // page * page


def cstring(data):
    return data.split(b"\0", 1)[0].decode(errors="replace")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def section(data, offset, size, path):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"镜像段越界：{path.name}")
    payload = data[offset:offset + size]
    path.write_bytes(payload)
    return {"offset": offset, "bytes": size, "sha256": sha256(payload), "file": path.name}


def avb_info(data):
    if data[-64:-60] != b"AVBf":
        return {"footer_present": False, "signature_verified": False}
    _, major, minor, original, offset, size, reserved = struct.unpack(
        ">4sIIQQQ28s", data[-64:])
    if major != 1 or minor != 0 or any(reserved) or original > offset or offset + size > len(data) - 64:
        raise ValueError("AVB footer 不合法")
    vbmeta = data[offset:offset + size]
    if vbmeta[:4] != b"AVB0" or len(vbmeta) < 256:
        raise ValueError("AVB vbmeta 头缺失")
    auth_size, aux_size, algorithm = struct.unpack_from(">QQI", vbmeta, 12)
    if 256 + auth_size + aux_size != size:
        raise ValueError("AVB 数据块长度不一致")
    descriptor_offset, descriptor_size, rollback = struct.unpack_from(">QQQ", vbmeta, 96)
    if descriptor_offset + descriptor_size > aux_size:
        raise ValueError("AVB descriptors 越界")
    cursor = 256 + auth_size + descriptor_offset
    end = cursor + descriptor_size
    descriptors = []
    while cursor < end:
        tag, following = struct.unpack_from(">QQ", vbmeta, cursor)
        next_cursor = cursor + 16 + following
        if next_cursor > end or following % 8:
            raise ValueError("AVB descriptor 长度不合法")
        value = {"tag": tag, "bytes": 16 + following}
        if tag == 0:
            if following < 16:
                raise ValueError("AVB property descriptor 不完整")
            key_size, value_size = struct.unpack_from(">QQ", vbmeta, cursor + 16)
            start = cursor + 32
            if start + key_size + 1 + value_size + 1 > next_cursor:
                raise ValueError("AVB property descriptor 字符串越界")
            if vbmeta[start + key_size] != 0 or vbmeta[start + key_size + 1 + value_size] != 0:
                raise ValueError("AVB property descriptor 缺少字符串终止符")
            value.update({"key": vbmeta[start:start + key_size].decode(),
                          "value": vbmeta[start + key_size + 1:start + key_size + 1 + value_size].decode()})
        elif tag == 2:
            if following < 116:
                raise ValueError("AVB hash descriptor 不完整")
            image_size = struct.unpack_from(">Q", vbmeta, cursor + 16)[0]
            algorithm_name = cstring(vbmeta[cursor + 24:cursor + 56])
            name_size, salt_size, digest_size, flags = struct.unpack_from(">4I", vbmeta, cursor + 56)
            start = cursor + 132
            if start + name_size + salt_size + digest_size > next_cursor or image_size > original:
                raise ValueError("AVB hash descriptor payload 越界")
            name = vbmeta[start:start + name_size].decode()
            salt = vbmeta[start + name_size:start + name_size + salt_size]
            digest = vbmeta[start + name_size + salt_size:start + name_size + salt_size + digest_size]
            calculated = hashlib.new(algorithm_name, salt + data[:image_size]).digest()
            if calculated != digest:
                raise ValueError(f"原厂 AVB payload 哈希不符：{name}")
            value.update({"partition_name": name, "image_size": image_size, "hash_algorithm": algorithm_name,
                          "salt_hex": salt.hex(), "digest_hex": digest.hex(), "flags": flags, "payload_digest_matches": True})
        descriptors.append(value)
        cursor = next_cursor
    return {"footer_present": True, "footer_version": [major, minor], "original_image_size": original,
            "vbmeta_offset": offset, "vbmeta_size": size, "algorithm_type": algorithm,
            "rollback_index": rollback, "flags": struct.unpack_from(">I", vbmeta, 120)[0],
            "rollback_index_location": struct.unpack_from(">I", vbmeta, 124)[0],
            "release_string": cstring(vbmeta[128:176]), "descriptors": descriptors,
            "signature_verified": False,
            "signature_note": "已核对镜像内 AVB hash descriptor；未使用 OEM 信任根独立验签，改动后旧签名不能沿用。"}


def parse_boot(data, out):
    version = struct.unpack_from("<I", data, 40)[0]
    if version != 4:
        raise ValueError(f"本次原厂输入应为 Android boot v4，实际 {version}")
    kernel, ramdisk, os_version, header_size = struct.unpack_from("<4I", data, 8)
    signature = struct.unpack_from("<I", data, 1580)[0]
    if header_size != 1584:
        raise ValueError("boot v4 header_size 不匹配")
    ramdisk_offset = 4096 + align(kernel)
    signature_offset = ramdisk_offset + align(ramdisk)
    image_end = signature_offset + align(signature)
    if image_end > len(data):
        raise ValueError("boot v4 声明的分段越界")
    values = {"format": "Android boot image", "header_version": version, "header_size": header_size,
              "page_size": 4096, "os_version_encoded": os_version,
              "os_version": f"{os_version >> 25}.{(os_version >> 18) & 127}.{(os_version >> 11) & 127}" if os_version else None,
              "os_patch_level": f"{2000 + ((os_version >> 4) & 127):04}-{os_version & 15:02}" if os_version else None,
              "cmdline": cstring(data[44:1580]), "image_end": image_end,
              "reserved": list(struct.unpack_from("<4I", data, 24)),
              "kernel": section(data, 4096, kernel, out / "kernel"),
              "ramdisk": section(data, ramdisk_offset, ramdisk, out / "ramdisk.lz4"),
              "signature": section(data, signature_offset, signature, out / "boot_signature")}
    (out / "header.bin").write_bytes(data[:4096])
    values["ramdisks"] = [{"name": "generic", "type": "generic", "file": "ramdisk.lz4"}] if ramdisk else []
    return values


def parse_vendor(data, out):
    version, page, kernel_addr, ramdisk_addr, ramdisk_size = struct.unpack_from("<5I", data, 8)
    if version != 4 or page != 4096:
        raise ValueError("本次 vendor_boot 应为 v4 / 4096 字节页")
    header_size, dtb_size, dtb_addr = struct.unpack_from("<IIQ", data, 2096)
    table_size, table_count, entry_size, bootconfig_size = struct.unpack_from("<4I", data, 2112)
    if header_size != 2128 or entry_size < 108 or table_size != table_count * entry_size:
        raise ValueError("vendor_boot 头或 ramdisk table 不合法")
    ramdisk_offset = align(header_size, page)
    dtb_offset = ramdisk_offset + align(ramdisk_size, page)
    table_offset = dtb_offset + align(dtb_size, page)
    bootconfig_offset = table_offset + align(table_size, page)
    image_end = bootconfig_offset + align(bootconfig_size, page)
    if image_end > len(data):
        raise ValueError("vendor_boot 分段越界")
    result = {"format": "Android vendor boot image", "header_version": version, "header_size": header_size,
              "page_size": page, "kernel_addr": kernel_addr, "ramdisk_addr": ramdisk_addr,
              "tags_addr": struct.unpack_from("<I", data, 2076)[0], "name": cstring(data[2080:2096]),
              "cmdline": cstring(data[28:2076]), "dtb_addr": dtb_addr, "image_end": image_end,
              "vendor_ramdisk": section(data, ramdisk_offset, ramdisk_size, out / "vendor_ramdisk.lz4"),
              "dtb": section(data, dtb_offset, dtb_size, out / "dtb"),
              "ramdisk_table": section(data, table_offset, table_size, out / "vendor_ramdisk_table.bin"),
              "bootconfig": section(data, bootconfig_offset, bootconfig_size, out / "bootconfig"),
              "ramdisk_table_count": table_count, "ramdisk_table_entry_size": entry_size, "ramdisks": []}
    (out / "header.bin").write_bytes(data[:align(header_size, page)])
    for index in range(table_count):
        start = table_offset + entry_size * index
        size, offset, kind = struct.unpack_from("<3I", data, start)
        name = cstring(data[start + 12:start + 44])
        if offset + size > ramdisk_size:
            raise ValueError("vendor ramdisk fragment 越界")
        filename = f"fragment-{index:02}.lz4"
        section(data, ramdisk_offset + offset, size, out / filename)
        result["ramdisks"].append({"name": name, "type": kind, "offset": offset, "bytes": size,
                                  "board_id": list(struct.unpack_from("<16I", data, start + 44)), "file": filename})
    return result


def unpack_cpio(data, out):
    """只物化目录和普通文件；符号链接、硬链接和设备元数据保留在清单及原始 cpio。"""
    out.mkdir()
    cursor, entries, contents = 0, [], {}
    while cursor < len(data):
        while cursor < len(data) and data[cursor] == 0:
            cursor += 1
        if cursor == len(data):
            break
        if data[cursor:cursor + 6] not in (b"070701", b"070702") or cursor + 110 > len(data):
            raise ValueError(f"ramdisk 不是完整 newc/crc CPIO：偏移 {cursor}")
        fields = [int(data[cursor + 6 + i * 8:cursor + 14 + i * 8], 16) for i in range(13)]
        inode, mode, uid, gid, nlink, mtime, size, devmajor, devminor, rdevmajor, rdevminor, namesize, checksum = fields
        crc_format = data[cursor:cursor + 6] == b"070702"
        name_start = cursor + 110
        payload_start = align(name_start + namesize, 4)
        payload_end = payload_start + size
        if namesize < 1 or namesize > 65536 or payload_end > len(data) or data[name_start + namesize - 1] != 0:
            raise ValueError("CPIO 条目名称或内容越界")
        name = data[name_start:name_start + namesize - 1].decode()
        cursor = align(payload_end, 4)
        if name == "TRAILER!!!":
            continue
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or "\0" in name:
            raise ValueError(f"拒绝 CPIO 目录穿越路径：{name!r}")
        normalized = str(pure)
        payload = data[payload_start:payload_end]
        if crc_format and sum(payload) & 0xffffffff != checksum:
            raise ValueError("CPIO crc 条目校验失败")
        entry = {"path": normalized, "mode": mode, "uid": uid, "gid": gid, "nlink": nlink,
                 "inode": inode, "mtime": mtime, "bytes": size, "devmajor": devmajor, "devminor": devminor,
                 "rdevmajor": rdevmajor, "rdevminor": rdevminor, "sha256": sha256(payload)}
        target = out / normalized
        if stat.S_ISDIR(mode):
            target.mkdir(parents=True, exist_ok=True)
        elif stat.S_ISREG(mode):
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_dir():
                raise ValueError(f"CPIO 文件与目录冲突：{normalized}")
            target.write_bytes(payload)
            contents[normalized] = payload
        elif stat.S_ISLNK(mode):
            entry["symlink_target"] = payload.decode(errors="replace")
        else:
            entry["materialized"] = False
        entries.append(entry)
    # newc 硬链接组可能只在最后一个条目携带内容；按 inode/device 组还原普通文件内容。
    links = {}
    for entry in entries:
        if stat.S_ISREG(entry["mode"]) and entry["nlink"] > 1 and entry["bytes"]:
            links[(entry["devmajor"], entry["devminor"], entry["inode"])] = contents[entry["path"]]
    for entry in entries:
        key = (entry["devmajor"], entry["devminor"], entry["inode"])
        if stat.S_ISREG(entry["mode"]) and entry["nlink"] > 1 and not entry["bytes"] and key in links:
            (out / entry["path"]).write_bytes(links[key])
            entry["resolved_hardlink_bytes"] = len(links[key])
    return entries


def unpack_ramdisk(compressed, out):
    if compressed[:4] in (b"\x02\x21\x4c\x18", b"\x04\x22\x4d\x18"):
        kind = "lz4-legacy" if compressed[:4] == b"\x02\x21\x4c\x18" else "lz4-frame"
        decompressed = subprocess.run(["lz4", "-d", "-c"], input=compressed, capture_output=True, check=True).stdout
    elif compressed[:2] == b"\x1f\x8b":
        kind, decompressed = "gzip", gzip.decompress(compressed)
    elif compressed[:6] in (b"070701", b"070702"):
        kind, decompressed = "cpio", compressed
    else:
        raise ValueError("未支持的原厂 ramdisk 压缩格式")
    out.mkdir()
    (out / "ramdisk.cpio").write_bytes(decompressed)
    entries = unpack_cpio(decompressed, out / "root")
    write_json(out / "entries.json", entries)
    return {"compression": kind, "uncompressed_bytes": len(decompressed), "cpio_sha256": sha256(decompressed),
            "entry_count": len(entries), "symlinks_materialized": False, "special_nodes_materialized": False}


def dependencies(directory):
    text_files, modules, elf = {}, [], []
    reader = shutil.which("llvm-readelf") or "/opt/homebrew/opt/llvm/bin/llvm-readelf"
    patterns = re.compile(r"touch|goodix|focal|novatek|display|drm|dpu|panel|ufs|f2fs|crypt|keymint|keymaster|gatekeeper|weaver|tee|trusty", re.I)
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or "/root/" not in str(path):
            continue
        relative = str(path.relative_to(directory))
        module_text = path.name in ("modules.load", "modules.load.recovery", "modules.dep", "modules.softdep", "modules.options", "modules.blocklist", "modules.builtin", "modules.order", "modules.order.recovery")
        if path.suffix in (".rc", ".prop") or "fstab" in path.name or module_text:
            if path.stat().st_size < 1024 * 1024:
                text_files[relative] = path.read_text(errors="replace")
        if path.suffix == ".ko":
            data = path.read_bytes()
            fields = {key: match.group(1).decode(errors="replace") for key in ("vermagic", "depends", "name")
                      if (match := re.search(rb"(?:^|\0)" + key.encode() + rb"=([^\0]+)", data))}
            modules.append({"file": relative, "bytes": len(data), "sha256": sha256(data), **fields,
                            "driver_interest": bool(patterns.search(path.name))})
        if patterns.search(path.name) or path.name in ("init", "recovery", "linker64", "vold"):
            with path.open("rb") as stream:
                magic = stream.read(4)
            if magic == b"\x7fELF":
                result = subprocess.run([reader, "-d", str(path)], capture_output=True, text=True, check=True)
                elf.append({"file": relative, "needed": re.findall(r"\(NEEDED\).*?\[([^]]+)\]", result.stdout)})
    service_stanzas = []
    for file, text in text_files.items():
        if file.endswith(".rc"):
            current = None
            for line in text.splitlines():
                if line.startswith("service "):
                    current = {"file": file, "header": line, "options": []}
                    service_stanzas.append(current)
                elif line and not line[0].isspace() and not line.startswith("#"):
                    current = None
                elif current is not None and line.strip() and not line.lstrip().startswith("#"):
                    current["options"].append(line.strip())
    return {"text_files": text_files, "modules": modules, "elf_dependencies": elf, "services": service_stanzas}


def extract(args):
    manifest = json.loads((args.inputs / "manifest.json").read_text())
    if manifest.get("product") != "dijun" or manifest.get("firmware") != "OS4.0.0.19.XODCNXM" or manifest.get("original_slot") != "_b":
        raise ValueError("输入归属不匹配 dijun OS4.0.0.19 原 _b")
    images = [(item["partition"], args.inputs / item["file"], item["sha256"], item["bytes"]) for item in manifest["partitions"]]
    boot_manifest_path = ROOT / "artifacts/device-trial/restore/manifest.json"
    boot_manifest = json.loads(boot_manifest_path.read_text())
    images.append(("boot_b", boot_manifest_path.parent / "boot_b.img", boot_manifest["sha256"], boot_manifest["partition_bytes"]))
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "dijun-stock-recovery-layout-v1", "input_manifest": str((args.inputs / "manifest.json").relative_to(ROOT)),
              "boot_header_reference": BOOT_HEADER_REFERENCE, "avb_reference": AVB_REFERENCE,
              "reference_source_blobs": {"bootimg.h": "06ac30ad1044452be73946f15f092bf9bea358a3", "avbtool.py": "595936c88d24b6e571b303a23a0e7cfe2e185bc7"},
              "phone_operations": False, "images": {}, "hardware_tested": False}
    for name, path, expected_hash, expected_bytes in images:
        data = path.read_bytes()
        if len(data) != expected_bytes or sha256(data) != expected_hash:
            raise ValueError(f"原厂输入长度/哈希不一致：{name}")
        out = args.output / name
        out.mkdir()
        if data[:8] == b"ANDROID!":
            values = parse_boot(data, out)
        elif data[:8] == b"VNDRBOOT":
            values = parse_vendor(data, out)
        else:
            raise ValueError(f"未知原厂镜像格式：{name}")
        values.update({"input": str(path.relative_to(ROOT)), "partition_bytes": len(data), "sha256": expected_hash, "avb": avb_info(data)})
        for index, ramdisk in enumerate(values["ramdisks"]):
            ramdisk["extraction"] = unpack_ramdisk((out / ramdisk["file"]).read_bytes(), out / f"ramdisk-{index:02}")
        report["images"][name] = values
    write_json(args.output / "layout.json", report)
    dependency_report = dependencies(args.output)
    write_json(args.output / "dependencies.json", dependency_report)
    print(json.dumps({"layout": str(args.output / "layout.json"), "dependencies": str(args.output / "dependencies.json"),
                      "images": {name: {key: value.get(key) for key in ("header_version", "page_size", "kernel", "ramdisk", "ramdisk_table_count")} for name, value in report["images"].items()},
                      "module_count": len(dependency_report["modules"]), "service_count": len(dependency_report["services"])}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=ROOT / "inputs/recovery/os4-0-0-19")
    parser.add_argument("--output", type=Path, default=ROOT / "build/recovery/stock")
    args = parser.parse_args()
    try:
        extract(args)
    except (OSError, ValueError, KeyError, struct.error, subprocess.SubprocessError) as error:
        parser.exit(1, f"原厂恢复输入解包失败：{error}\n")


if __name__ == "__main__":
    main()
