#!/usr/bin/env python3
"""复用官方 OrangeFox 用户空间，只编译 O1 DRM 后端并打包首轮真机测试镜像。"""

import argparse
import hashlib
import json
import platform
import re
import stat
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

from extract_stock_recovery import avb_info, parse_boot, unpack_ramdisk
from audit_runtime import audit_runtime

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sources/orangefox/recovery"
DEVICE = ROOT / "recovery/device/xiaomi/dijun"
DONOR = ROOT / "build/recovery/donors/infiniti-r12.0_2/ramdisk-00"
BUILD = ROOT / "build/recovery/prebuilt-trial-v2"
DONOR_SHA = "33a31b13b1eebe1cdbb78f4ebdec132d70a5ae0874cbfb927f75f8ee65068bea"


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], check=True, **kwargs)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_drm(ndk):
    """只跨 ABI 传递固定布局的 minui_backend/GRSurface，不混用两套 C++ 对象。"""
    generated = BUILD / "source/minuitwrp"
    generated.mkdir(parents=True, exist_ok=True)
    target = generated / "graphics_drm.cpp"
    target.write_bytes((SOURCE / "minuitwrp/graphics_drm.cpp").read_bytes())
    patch = (ROOT / "recovery/patches/0001-dijun-drm-single-primary.patch").read_text()
    patch = "--- a/minuitwrp/graphics_drm.cpp" + patch.split("--- a/minuitwrp/graphics_drm.cpp", 1)[1]
    run(["patch", "--batch", "-p1"], cwd=generated.parent, input=patch.encode(), stdout=subprocess.PIPE)
    content = target.read_text().replace("#include <android-base/properties.h>\n", "")
    # XRING 没有 Qualcomm SDE SPR 属性。移除这一个 libbase 调用，即可使用已有 NDK。
    content = content.replace('spr_enabled = android::base::GetIntProperty("vendor.display.enable_spr", 0);',
                              'spr_enabled = 0; // O1 不使用 SDE SPR。')
    target.write_text(content)
    exports = BUILD / "drm.exports"
    exports.write_text("{ global: _Z8open_drmv; local: *; };\n")
    headers = ROOT / "sources/orangefox/component-headers/libdrm"
    host = {"Darwin": "darwin-x86_64", "Linux": "linux-x86_64"}[platform.system()]
    toolchain = ndk / "toolchains/llvm/prebuilt" / host
    library = BUILD / "libdijun_drm.so"
    command = [toolchain / "bin/aarch64-linux-android34-clang++", "-shared", "-fPIC", "-O2",
               "-std=c++17", "-fno-exceptions", "-fno-rtti", "-static-libstdc++",
               "-DTW_DRM_SINGLE_PLANE", "-DRECOVERY_RGBX", "-Wl,-z,defs",
               "-Wl,--exclude-libs,ALL", f"-Wl,--version-script={exports}",
               "-Wl,-soname,libdijun_drm.so", "-I", headers, "-I", headers / "include/drm",
               "-I", SOURCE / "minuitwrp/include", "-I", SOURCE / "minuitwrp",
               "-I", SOURCE / "gui/include", "-I", SOURCE / "libpixelflinger/include",
               # donor 已把 libdrm 静态并入 minuitwrp，使用它导出的真实 DRM 接口。
               target, "-L", DONOR / "root/system/lib64", "-lminuitwrp", "-o", library]
    run(command)
    return library, [str(x) for x in command]


def make_cpio(entries, payloads):
    """保留 uid/gid/mode 和链接；已解包的硬链接按实际内容编码，不依赖宿主权限。"""
    result = bytearray()
    for inode, name in enumerate([*sorted(entries), "TRAILER!!!"], 1):
        meta = entries.get(name, {})
        data = payloads.get(name, b"")
        encoded = name.encode() + b"\0"
        fields = [inode, meta.get("mode", 0), meta.get("uid", 0), meta.get("gid", 0),
                  1, meta.get("mtime", 0), len(data), 0, 0,
                  meta.get("rdevmajor", 0), meta.get("rdevminor", 0), len(encoded), 0]
        result.extend(b"070701" + b"".join(f"{x:08x}".encode() for x in fields) + encoded)
        result.extend(b"\0" * (-len(result) % 4))
        result.extend(data)
        result.extend(b"\0" * (-len(result) % 4))
    return bytes(result)


def configure_ui(read, add):
    """旧 .foxs 会覆盖 XML 默认值；在真实入口应用设置并调用原主题重载。"""
    include = b'<xml name="/twres/dijun-ui-defaults.xml"/>'
    ui = read("twres/ui.xml")
    # 清除旧候选无效的预加载覆盖，主题重载时也不重置用户刚选择的语言。
    ui = re.sub(rb'<variable name="(?:tw_language|tw_button_vibrate|tw_keyboard_vibrate|tw_action_vibrate)"[^>]*/>\s*', b"", ui)
    if include not in ui:
        ui = ui.replace(b"<include>", b"<include>\n\t\t" + include, 1)
    add("twres/ui.xml", ui)
    add("twres/dijun-ui-defaults.xml", (ROOT / "recovery/prebuilt/dijun-ui-defaults.xml").read_bytes())
    # 本机 1440x3200、主题1080x1920：方形滑块图标保宽高比后为128x128。
    # 控件按y比例缩放，旧96会要求绘制160行而读出源图边界；77缩放后恰为128。
    variables = "twres/resources/vars.xml"
    add(variables, read(variables).replace(b'<variable name="slidervalue_sliderh" value="96"/>',
                                          b'<variable name="slidervalue_sliderh" value="77"/>'))
    for name, page in (("twres/pages/mount.xml", "decrypt"), ("twres/pages/main.xml", "main")):
        xml = read(name)
        marker = f'<page name="{page}">'.encode()
        # 沿用 setlanguage -> RequestReload -> RunReload；返回原入口，仍走真实解密流程。
        destination = (f'<action><condition var1="dijun_ui_defaults_applied" op="!=" var2="1"/>'
                       f'<action function="set">of_reload_back={page}</action></action>')
        hook = ('\n\t\t\t' + destination +
                '\n\t\t\t<template name="dijun_ui_defaults"/>').encode()
        # 返回页仅在首次初始化设置；后续语言/主题重载应返回用户当前设置页。
        xml = xml.replace(f'<action><action function="set">of_reload_back={page}</action></action>'.encode(),
                          destination.encode())
        if b'<template name="dijun_ui_defaults"/>' not in xml:
            assert xml.count(marker) == 1
            xml = xml.replace(marker, marker + hook, 1)
        add(name, xml)
    chinese = "twres/languages/zh_CN.xml"
    add(chinese, re.sub(rb"<display>.*?</display>", "<display>简体中文</display>".encode(), read(chinese), count=1))


def display_module_closure(directory):
    """显示基础包仅自动加载 DRM/触控闭包；振动和 ISP 由独立硬件服务启动。"""
    dependencies = {}
    for line in (directory / "modules.dep").read_text().splitlines():
        name, _, required = line.partition(":")
        dependencies[name] = required.split()
    pending = ["xring-drm.ko", "synaptics_tcm2.ko", "xiaomi_touch_dijun.ko"]
    selected = set()
    while pending:
        name = pending.pop()
        if name not in selected:
            selected.add(name)
            pending.extend(dependencies[name])
    return selected


def assemble(library):
    entries, payloads = {}, {}
    # 只继承通用用户空间；他机厂商模块、HAL、fstab 和启动脚本全部由本机材料替换。
    for item in json.loads((DONOR / "entries.json").read_text()):
        name = item["path"]
        if (name == "vendor" or name.startswith(("vendor/", "odm/"))
                or name.startswith("init.recovery.qcom")
                or name.startswith("system/etc/vintf/")
                or name.startswith("system/etc/init/android.hardware.boot@")
                or name in ("system/etc/init/keystore2.rc", "system/etc/init/se_omapi.rc",
                            "system/etc/init/android.hardware.health@2.0-service.rc",
                            "system/bin/debuggerd", "FFiles/ps")
                or name.endswith(("/twrp.fstab", "/recovery.fstab", "/additional.fstab"))):
            continue
        entries[name] = item
        if stat.S_ISREG(item["mode"]):
            payloads[name] = (DONOR / "root" / name).read_bytes()
        elif stat.S_ISLNK(item["mode"]):
            payloads[name] = item["symlink_target"].encode()

    def add(name, data, mode=0o644):
        for parent in reversed(Path(name).parents):
            if str(parent) != "." and str(parent) not in entries:
                entries[str(parent)] = {"mode": stat.S_IFDIR | 0o755}
        entries[name] = {"mode": stat.S_IFREG | mode}
        payloads[name] = data

    def file(name, source, mode=0o644):
        add(name, source.read_bytes(), mode)

    file("system/lib64/libdijun_drm.so", library, 0o755)
    # 原厂 AIDL boot HAL 使用 Android 15 libc++ 的 verbose_abort；沿用同一原厂运行库。
    file("system/lib64/libc++.so", ROOT / "build/recovery/stock/recovery_b/ramdisk-00/root/system/lib64/libc++.so", 0o755)
    # donor 的附加 ps 来自旧 Android，使用现有 toybox 的同名命令。
    entries["FFiles/ps"] = {"mode": stat.S_IFLNK | 0o777}
    payloads["FFiles/ps"] = b"/system/bin/toybox"
    file("system/etc/recovery.fstab", ROOT / "recovery/prebuilt/display-trial.fstab")
    # 真机发现 twrp.flags 会新增 fstab 中没有的分区；诊断版必须同时替换这第二个入口。
    add("system/etc/twrp.flags", "# 本轮不新增挂载或刷写条目。\n".encode())
    file("system/bin/start-dijun-recovery", ROOT / "recovery/prebuilt/start-display-trial.sh", 0o755)
    module_directory = DEVICE / "proprietary/modules/1.1"
    display_modules = display_module_closure(module_directory)
    for f in module_directory.iterdir():
        if f.name in ("modules.dep", "modules.load", "modules.load.twrp"):
            lines = [line for line in f.read_text().splitlines()
                     if line.partition(":")[0] in display_modules]
            add("vendor/lib/modules/1.1/" + f.name, ("\n".join(lines) + "\n").encode())
        elif f.suffix == ".ko" and f.name in display_modules:
            file("vendor/lib/modules/1.1/" + f.name, f)
    firmware = json.loads((DEVICE / "proprietary/firmware/manifest.json").read_text())
    file(firmware["runtime_install_path"].lstrip("/"), DEVICE / "proprietary/firmware" / firmware["file"])
    boot = json.loads((DEVICE / "proprietary/boot-hal/manifest.json").read_text())
    for item in boot["files"]:
        name = item["source"].split("/root/", 1)[1]
        file(name, ROOT / item["source"], 0o755 if "/bin/" in name else 0o644)
    file("init.recovery.O1_asic.rc", DEVICE / "recovery/root/init.recovery.O1_asic.rc")
    payloads["init.recovery.O1_asic.rc"] += b"\non boot\n    start vendor.boot-xring\n"
    file("init.recovery.usb.rc", DEVICE / "recovery/root/init.recovery.usb.rc")
    # 此轮只有平台用户空间；/sbin 与 /FFiles 工具也使用同一平台库目录。
    # bionic 会把根目录斜杠去掉而视为空值；使用实际可执行目录，避免每次启动警告。
    profiles = {"recovery": "/system", "tools": "/sbin", "addons": "/FFiles"}
    config = "".join(f"dir.{name} = {path}\n" for name, path in profiles.items())
    config += "".join(f"[{name}]\nnamespace.default.isolated = false\nnamespace.default.search.paths = /system/${{LIB}}\n" for name in profiles)
    add("system/etc/ld.config.txt", config.encode())
    init = "system/etc/init/hw/init.rc"
    payloads[init] = payloads[init].replace(b"import /init.recovery.mksh.rc\n", b"")
    configure_ui(payloads.__getitem__, add)
    add("init.recovery.service.rc", b"service recovery /system/bin/sh /system/bin/start-dijun-recovery\n    socket recovery stream 422 system system\n    seclabel u:r:recovery:s0\n")
    # 固定为此备份对应系统的真实版本；SDK 保留 donor ABI 34，不谎报其用户空间 ABI。
    prop = payloads["prop.default"].decode()
    replacements = {"ro.build.version.release": "17", "ro.build.version.release_or_codename": "17",
                    "ro.build.version.security_patch": "2026-10-01", "ro.vendor.build.security_patch": "2026-09-01",
                    "ro.product.board": "O1", "ro.board.platform": "O1_asic"}
    for key, value in replacements.items():
        prop = re.sub(r"^" + re.escape(key) + r"=.*$", key + "=" + value, prop, flags=re.M)
    prop = re.sub(r"^(ro\.product(?:\.[^.]+)?\.device)=.*$", r"\1=dijun", prop, flags=re.M)
    prop = re.sub(r"^(ro\.product(?:\.[^.]+)?\.model)=.*$", r"\1=25042PN24C", prop, flags=re.M)
    prop = re.sub(r"^(ro\.product(?:\.[^.]+)?\.name)=.*$", r"\1=fox_dijun", prop, flags=re.M)
    prop = re.sub(r"^(ro\.product(?:\.[^.]+)?\.(?:brand|manufacturer))=.*$", r"\1=Xiaomi", prop, flags=re.M)
    prop += "\nro.adb.secure=0\nro.orangefox.port.status=display-trial\nof_skip_fbe_decryption=true\nro.crypto.metadata_init_delete_all_keys.enabled=false\n"
    add("prop.default", prop.encode())
    return make_cpio(entries, payloads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, default=Path.home() / "Library/Android/sdk/ndk/28.2.13676358")
    args = parser.parse_args()
    archive = ROOT / "inputs/recovery/donors/infiniti-r12.0_2/OrangeFox-R12.0_2-infiniti.zip"
    if digest(archive.read_bytes()) != DONOR_SHA:
        raise ValueError("donor ZIP 与已核验官方包不符")
    if not DONOR.exists():
        DONOR.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            parse_boot(package.read("recovery.img"), DONOR.parent)
        unpack_ramdisk((DONOR.parent / "ramdisk.lz4").read_bytes(), DONOR)
    BUILD.mkdir(parents=True, exist_ok=True)
    library, command = build_drm(args.ndk)
    cpio = assemble(library)
    compressed = run(["lz4", "-l", "-12", "-c"], input=cpio, capture_output=True).stdout
    header = bytearray(4096)
    header[:8] = b"ANDROID!"
    struct.pack_into("<4I", header, 8, 0, len(compressed), 0, 1584)
    struct.pack_into("<I", header, 40, 4)
    image = ROOT / "build/recovery/OrangeFox-dijun-display-trial-zh.img"
    image.write_bytes(header + compressed + b"\0" * (-len(compressed) % 4096))
    original = avb_info((ROOT / "inputs/recovery/os4-0-4-0/recovery.img").read_bytes())
    fingerprint = next(x["value"] for x in original["descriptors"] if x.get("key") == "com.android.build.recovery.fingerprint")
    run([sys.executable, ROOT / "sources/orangefox/component-tools/avbtool.py", "add_hash_footer",
         "--image", image, "--partition_name", "recovery", "--partition_size", "104857600",
         "--algorithm", "NONE", "--rollback_index", str(original["rollback_index"]),
         "--rollback_index_location", str(original["rollback_index_location"]),
         "--salt", "c4cbfdb2ca989e645b7404af41d94a001c371a73ec338616b31f1b5c690fb36d",
         "--prop", "com.android.build.recovery.fingerprint:" + fingerprint])
    # 回读实际最终镜像，供已有 ELF/init 审计及真机采集使用。
    import shutil
    unpacked = BUILD / "unpacked"
    if unpacked.exists():
        shutil.rmtree(unpacked)
    unpacked.mkdir()
    data = image.read_bytes()
    layout = parse_boot(data, unpacked)
    ramdisk = unpack_ramdisk((unpacked / "ramdisk.lz4").read_bytes(), unpacked / "ramdisk")
    actual = unpacked / "ramdisk/root"
    # 覆盖真机暴露的问题：不能只检查 recovery.fstab 而漏掉另一个挂载表入口。
    assert not any(line.strip() and not line.lstrip().startswith("#") for line in (actual / "system/etc/twrp.flags").read_text().splitlines())
    assert b'tw_language=zh_CN' in (actual / "twres/dijun-ui-defaults.xml").read_bytes()
    assert (actual / "twres/fonts/DroidSansFallback.ttf").is_file()
    runtime = audit_runtime(unpacked / "ramdisk/root", json.loads((unpacked / "ramdisk/entries.json").read_text()))
    (BUILD / "runtime-audit.json").write_text(json.dumps(runtime, ensure_ascii=False, indent=2) + "\n")
    if not runtime["passed"]:
        raise ValueError("最终镜像存在 ELF/init 依赖问题，详见 runtime-audit.json")
    report = {"image": str(image), "sha256": digest(data), "bytes": len(data),
              "donor_sha256": DONOR_SHA, "drm_sha256": digest(library.read_bytes()),
              "compile_command": command, "layout": layout, "avb": avb_info(data), "ramdisk": ramdisk,
              "runtime_audit_passed": runtime["passed"], "aarch64_elf_count": runtime["aarch64_elf_count"],
              "stage": "display-touch-adb-trial", "data_and_metadata_in_fstab": False,
              "hardware_boot_verified": False, "decryption_verified": False, "phone_operations": False}
    (BUILD / "build.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("image", "sha256", "bytes", "stage", "hardware_boot_verified")}, indent=2))


if __name__ == "__main__":
    main()
