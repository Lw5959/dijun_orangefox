#!/usr/bin/env python3
"""修复固定 donor 的 CLI 收尾竞态及已有解密映射后的用户状态恢复。"""

import hashlib
import json
import os
import platform
import struct
import subprocess
from pathlib import Path

SOURCE_SHA256 = "647e76dfa663015d843257c00d6c04ad69e5ee0c0b20a30ec0424e3071a58f8f"
MTP_SOURCE_SHA256 = "d0a92a285b661952b246074a1d6b9644bae80d5b5939f8c1237a25537c65eb85"
ROOT = Path(__file__).resolve().parents[2]
STUB_START = 0x37C150
MTP_STUB_START = 0x3F6B0
SYMBOLS = {
    "action_running": 0x39AF88,
    "cli_submit": 0x2CB520,
    "cli_busy_reply": 0x2CB398,
    "ors_output": 0x39A920,
    "pending_cli_done": 0x39B9A8,
    "sideload_phase": 0x39B9AC,
    "minadbd_child": 0x39A480,
    "recovery_ors_done": 0x2CC488,
    "recovery_delete": 0x3792F0,
    "recovery_fclose": 0x3799F0,
    "recovery_fileno": 0x37A220,
    "recovery_mtp_forkserver": 0x37A010,
    "cli_done_canary": 0x2CC518,
    "recovery_toggle_mtp": 0x17DB04,
    "recovery_sideload": 0x25616C,
    "ors_sideload_error": 0x1A9EB0,
    "ors_sideload_finished": 0x1A9F6C,
    "partition_manager_got": 0x385F98,
    "recovery_property_get": 0x1B83CC,
    "recovery_property_set": 0x1B8620,
    "recovery_set_property_cpp": 0x3793D0,
    "recovery_clear_boot_message": 0x179CD4,
    "recovery_get_fastboot_mode": 0x1723BC,
    "fastboot_ready_continue": 0x110FD4,
    "recovery_wait_property": 0x37AA70,
    "recovery_kill": 0x379F70,
    "recovery_install_zip": 0x257FE0,
    "sideload_begin_continue": 0x256170,
    "sideload_ready_continue": 0x256890,
    "sideload_finish_continue": 0x256B04,
    "sideload_cancel_epilogue": 0x2E7CD4,
    "recovery_get_users": 0x1633CC,
    "recovery_parse_users": 0x162834,
    "recovery_decrypt_fbe_de": 0x13CF94,
    "recovery_set_integer": 0x12901C,
}


def build_stubs(ndk=None, *, mtp=False):
    """只编译固定 ARM64 会话逻辑；不链接 HAL，也不连接设备。"""
    ndk = ndk or Path(os.environ.get("ANDROID_NDK_HOME", str(Path.home() / "Library/Android/sdk/ndk/28.2.13676358")))
    host = {"Darwin": "darwin-x86_64", "Linux": "linux-x86_64"}[platform.system()]
    tools = ndk / "toolchains/llvm/prebuilt" / host / "bin"
    output = ROOT / "build/recovery/prebuilt-crypto/session-patch"
    output.mkdir(parents=True, exist_ok=True)
    name = "mtp" if mtp else "session"
    source = ROOT / f"recovery/patches/prebuilt-{name}.S"
    obj, elf, raw = (output / f"{name}.{suffix}" for suffix in ("o", "elf", "bin"))
    start = MTP_STUB_START if mtp else STUB_START
    symbols = {"mtp_fork": 0x3F1C0, "mtp_close": 0x3E200} if mtp else SYMBOLS
    entry = "dijun_mtp_fork" if mtp else "dijun_cli_gate"
    subprocess.run([str(tools / "aarch64-linux-android34-clang"), "-c", str(source), "-o", str(obj)], check=True)
    subprocess.run([str(tools / "ld.lld"), f"-Ttext={start:#x}", f"--entry={entry}",
                    *[f"--defsym={name}={address:#x}" for name, address in symbols.items()],
                    str(obj), "-o", str(elf)], check=True)
    subprocess.run([str(tools / "llvm-objcopy"), "--only-section=.text", "-O", "binary", str(elf), str(raw)], check=True)
    names = subprocess.run([str(tools / "llvm-nm"), "--defined-only", str(elf)],
                           check=True, capture_output=True, text=True).stdout
    addresses = {parts[2]: int(parts[0], 16) for line in names.splitlines() if len(parts := line.split()) == 3}
    return raw.read_bytes(), addresses


def patch_session(original, ndk=None):
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("会话修复只接受完成既有密钥与硬件修正的固定 donor")
    blob, addresses = build_stubs(ndk)
    data, records = bytearray(original), []

    def replace(offset, before, after, reason):
        if len(before) != len(after) or data[offset:offset + len(before)] != before:
            raise ValueError(f"会话修复原始字节不匹配：{offset:#x}")
        data[offset:offset + len(before)] = after
        records.append({"offset": hex(offset), "before": before.hex(), "after": after.hex(), "reason": reason})

    # 仅使用 RX 与下一 LOAD 段之间的真实零填充，不覆盖已有指令或增长文件。
    if STUB_START + len(blob) > 0x380000:
        raise ValueError("会话代码超过已核对的段间空隙")
    replace(STUB_START, bytes(len(blob)), blob, "ARM64 CLI 门控与 FBE 会话恢复")
    for offset, old, symbol, link, reason in (
        (0x110FD0, "630340f9", "dijun_fastboot_ready", False, "GUI 初始化及原有 BCB 清理完成后才开放 USB fastbootd"),
        (0x2CB51C, "680600f0", "dijun_cli_gate", False, "只对普通命令检查动作忙状态，保留 GUI 内部 xset 等同步命令"),
        (0x2CB3D8, "86b90294", "recovery_ors_done", True, "忙时回复后清空输出并重建 FIFO，不留下悬空 orsout"),
        (0x1AD970, "00013fd6", "dijun_defer_cli_done", True, "普通 CLI 命令的完成回复延迟至整个动作列表退出"),
        (0x2DF0EC, "81680294", "dijun_finish_action", True, "原动作忙状态清零并解锁后完成 CLI 回复，cancel 线程不抢回复"),
        (0x2CC514, "881640f9", "dijun_close_cli_output", False, "先完成输入监听恢复，最后关闭 CLI 输出发出 EOF"),
        (0x164818, "fe550894", "dijun_mtp_forkserver", True, "向配套 MTP forkserver 传入 ORS 输出 fd，由子进程关闭继承副本"),
        (0x164BF8, "8a4e0194", "dijun_disable_mtp_done", True, "MTP 停止后等 adb 模式完成，避免普通 adbd 与 minadbd 交错启动"),
        (0x25616C, "fd7bbaa9", "dijun_sideload_begin", False, "初始化 sideload 会话，USB 就绪前收起取消入口"),
        (0x25688C, "00018052", "dijun_sideload_ready", False, "USB sideload 就绪后开放等待阶段的取消入口"),
        (0x256B00, "a0018052", "dijun_sideload_finished", False, "后台线程完成后清理取消状态"),
        (0x2E7BB0, "f40400d0", "dijun_sideload_cancel", True, "取消只解绑 USB 并通知子进程，不阻塞界面或抢先结束页面"),
        (0x2E7BB4, "40ebfff0", "sideload_cancel_epilogue", False, "跳过原取消函数的同步 stat、sleep、waitpid 与提前 page_done"),
        (0x2570E0, "c0030094", "dijun_sideload_install", True, "开始安装与取消互斥；安装开始后隐藏取消，不在取消请求后写入包"),
        (0x1A9EA8, "b1b00294", "dijun_ors_sideload", True, "ORS sideload 与 GUI 共用 MTP 暂停和恢复流程，避免 USB ready 互等"),
        (0x1A9EAC, "20050034", "dijun_ors_sideload_result", False, "保留 sideload 返回状态，成功时不再次读取已关闭的 FUSE 安装包"),
        (0x13BB34, "3ab5ff97", "dijun_restore_users", True, "已有 metadata 映射时重建用户列表，按本轮实际 CE 解锁记录恢复状态"),
        (0x152B50, "3359ff97", "dijun_sync_encrypted", True, "fstab 收尾按 CE 状态设置 encrypted，避免无条件覆盖已恢复的解锁状态"),
    ):
        displacement = (addresses | SYMBOLS)[symbol] - offset
        instruction = (0x94000000 if link else 0x14000000) | ((displacement >> 2) & 0x3FFFFFF)
        replace(offset, bytes.fromhex(old), struct.pack("<I", instruction), reason)
    # OrangeFox 的恢复界面把这个遗留 skip 变量用作“启用校验”，ORS 却沿用反向语义。
    # 正常命令必须校验摘要；只有显式 M 参数才跳过，与界面及现有提示保持一致。
    replace(0x1A6510, bytes.fromhex("e1031f2a"), bytes.fromhex("21008052"), "ORS restore 默认启用恢复摘要校验")
    replace(0x1A7EB8, bytes.fromhex("21008052"), bytes.fromhex("e1031f2a"), "ORS restore 的显式 M 参数才关闭摘要校验")
    replace(0x2CC4B4, bytes.fromhex("4fb50294"), bytes.fromhex("1f2003d5"), "输出关闭移到完成回调末尾")
    replace(0x2CC4D8, bytes.fromhex("7f9204f9"), bytes.fromhex("1f2003d5"), "监听重建前继续保留非空输出状态，避免 GUI 抢读")
    # 原代码把 mtppid 清零后 waitpid(0)，可能回收或等待无关子进程。
    # 在清零前读取真正的 MTP PID，只等待已经终止的那个服务。
    replace(0x164BC8, bytes.fromhex("e0031f2a"), bytes.fromhex("603a40b9"), "Disable_MTP 只回收自身 MTP 子进程")
    replace(0x164C54, bytes.fromhex("20008052"), bytes.fromhex("e003142a"), "Disable_MTP 返回实际 USB 模式切换结果")
    replace(0x171CC8, bytes.fromhex("c21d0894"), bytes.fromhex("1f2003d5"),
            "移除 startupArgs 中过早开放 fastbootd 的调用，避免启动请求尚未清理时接受返回命令")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    rx_found = False
    for index in range(phcount):
        offset = phoff + phsize * index
        kind, flags, file_offset, va, _, filesz, memsz, _ = struct.unpack_from("<IIQQQQQQ", data, offset)
        if kind == 1 and flags == 5:
            assert file_offset == va == 0x110000 and va + filesz == STUB_START and filesz == memsz
            new_size = STUB_START + len(blob) - va
            replace(offset + 32, struct.pack("<QQ", filesz, memsz), struct.pack("<QQ", new_size, new_size),
                    "扩展原 RX 映射以覆盖段间的会话代码，不新增 LOAD 段或权限")
            rx_found = True
    if not rx_found:
        raise ValueError("未找到已核对的 RX LOAD 段")
    # 单独声明 8 字节 BSS，保存尚未发送的 CLI 完成通知。沿用原 RW 段和权限。
    for index in range(phcount):
        offset = phoff + phsize * index
        kind, flags, _, va, _, filesz, memsz, _ = struct.unpack_from("<IIQQQQQQ", data, offset)
        if kind == 1 and flags == 6 and va == 0x397E30:
            assert va + memsz == SYMBOLS["pending_cli_done"] and filesz == 0x1C0
            replace(offset + 40, struct.pack("<Q", memsz), struct.pack("<Q", memsz + 8),
                    "原 RW 段末尾增加独立完成通知，不复用上游状态内存")
            break
    else:
        raise ValueError("未找到已核对的 BSS LOAD 段")
    return bytes(data), {"source_sha256": SOURCE_SHA256, "patched_sha256": hashlib.sha256(data).hexdigest(),
                         "patches": records, "symbols": addresses,
                         "authentication_changed": False, "phone_tested": False}


def patch_mtp(original, ndk=None):
    """与 recovery 的唯一 forkserver 调用点配套，关闭子进程继承的 ORS fd。"""
    if hashlib.sha256(original).hexdigest() != MTP_SOURCE_SHA256:
        raise ValueError("MTP 会话修复只接受固定 donor 的原始库")
    blob, addresses = build_stubs(ndk, mtp=True)
    data, records = bytearray(original), []

    def replace(offset, before, after, reason):
        if len(before) != len(after) or data[offset:offset + len(before)] != before:
            raise ValueError(f"MTP 会话修复原始字节不匹配：{offset:#x}")
        data[offset:offset + len(before)] = after
        records.append({"offset": hex(offset), "before": before.hex(), "after": after.hex(), "reason": reason})

    if MTP_STUB_START + len(blob) > 0x40000:
        raise ValueError("MTP 会话代码超过原 RX 段后的零填充")
    replace(MTP_STUB_START, bytes(len(blob)), blob, "MTP 子进程关闭额外传入的 ORS 输出 fd")
    branch = 0x94000000 | (((addresses["dijun_mtp_fork"] - 0x35468) >> 2) & 0x3FFFFFF)
    replace(0x35468, bytes.fromhex("56270094"), struct.pack("<I", branch), "保留 fork 返回值，仅在子进程关闭输出副本")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", data, 54)
    for index in range(phcount):
        offset = phoff + phsize * index
        kind, flags, file_offset, va, _, filesz, memsz, _ = struct.unpack_from("<IIQQQQQQ", data, offset)
        if kind == 1 and flags == 5:
            assert file_offset == va == 0x20000 and va + filesz == MTP_STUB_START and filesz == memsz
            new_size = MTP_STUB_START + len(blob) - va
            replace(offset + 32, struct.pack("<QQ", filesz, memsz), struct.pack("<QQ", new_size, new_size),
                    "沿用原 RX 段及权限，映射 MTP 子进程清理逻辑")
            break
    else:
        raise ValueError("未找到 MTP 原 RX LOAD 段")
    return bytes(data), {"source_sha256": MTP_SOURCE_SHA256, "patched_sha256": hashlib.sha256(data).hexdigest(),
                         "patches": records, "symbols": addresses, "phone_tested": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ndk", type=Path)
    args = parser.parse_args()
    patched, report = patch_session(args.source.read_bytes(), args.ndk)
    args.output.write_bytes(patched)
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"patched_sha256": report["patched_sha256"], "symbols": {k: hex(v) for k, v in report["symbols"].items() if k.startswith("dijun_")}}))
