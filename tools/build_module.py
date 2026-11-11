#!/usr/bin/env python3
"""用已核验的两份镜像构建 KernelSU ZIP；仅使用 Python 标准库，不连接设备。"""

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_FILES = ("module.prop", "common.sh", "customize.sh", "action.sh", "restore.sh",
                "uninstall.sh", "skip_mount", "README.md", "LICENSE", "NOTICE")


def entry(name):
    # 固定归档时间和文件权限，使不同检出时间生成的同版安装包保持一致。
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 11, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def add_file(archive, name, source):
    with Path(source).open("rb") as stream, archive.open(entry(name), "w") as target:
        shutil.copyfileobj(stream, target)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(orangefox, stock, destination):
    """固定固件及完整镜像哈希，防止把错误回退镜像打入可刷写模块。"""
    manifest = json.loads((ROOT / "config/images.json").read_text())
    images = (("orangefox.img", Path(orangefox), manifest["orangefox_sha256"]),
              ("stock-recovery.img", Path(stock), manifest["stock_sha256"]))
    for name, path, expected in images:
        if path.stat().st_size != manifest["image_bytes"] or digest(path) != expected:
            raise ValueError(f"{name} 的大小或 SHA256 与 config/images.json 不一致")
    env = (f"FIRMWARE={manifest['firmware']}\nIMAGE_BYTES={manifest['image_bytes']}\n"
           f"FOX_SHA256={manifest['orangefox_sha256']}\nSTOCK_SHA256={manifest['stock_sha256']}\n")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 显式清单确保 Git、测试、构建脚本和本地材料不会混进安装包。
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in MODULE_FILES:
            add_file(archive, name, ROOT / name)
        archive.writestr(entry("images.env"), env)
        archive.writestr(entry("build-status.json"), json.dumps({
            "image_sha256": manifest["orangefox_sha256"],
            "stock_sha256": manifest["stock_sha256"],
            "image_readback_passed": True,
            "validation": manifest["validation"],
        }, ensure_ascii=False, indent=2) + "\n")
        for name, path, _ in images:
            add_file(archive, name, path)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC 检查失败")
        for name, _, expected in images:
            with archive.open(name) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError(f"ZIP 中 {name} 回读不一致")
    sha = digest(destination)
    destination.with_suffix(destination.suffix + ".sha256").write_text(f"{sha}  {destination.name}\n")
    return {"zip": str(destination), "bytes": destination.stat().st_size, "sha256": sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orangefox", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/OrangeFox-for-Dijun.zip")
    args = parser.parse_args()
    print(json.dumps(build(args.orangefox, args.stock, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
