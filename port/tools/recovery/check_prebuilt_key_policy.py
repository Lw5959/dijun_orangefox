#!/usr/bin/env python3
"""执行固定 ELF 的 AArch64 分支，核对密钥保留补丁；外部密码学/文件接口用明确的测试结果代入。"""

import hashlib
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_TPIDR_EL0, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X20

from preserve_prebuilt_keys import preserve_existing_keys, preserve_mount_failures

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "build/recovery/donors/infiniti-r12.0_2/ramdisk-00/root/system/bin/recovery"
END = 0x4000000


def execute(data, start, registers, stubs, stops=(END,), setup=None):
    """只在主机解释指令；TLS/栈和测试字符串均为新建内存，不使用任何手机密钥。"""
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    phoff = struct.unpack_from("<Q", data, 32)[0]
    width, count = struct.unpack_from("<HH", data, 54)
    segments = [struct.unpack_from("<IIQQQQQQ", data, phoff + i * width) for i in range(count)]
    size = max(s[3] + s[6] for s in segments if s[0] == 1)
    cpu.mem_map(0, (size + 4095) & ~4095)
    for kind, _, offset, address, _, filesz, _, _ in segments:
        if kind == 1:
            cpu.mem_write(address, data[offset:offset + filesz])
    for address in (0x1000000, 0x2000000, 0x3000000, END):
        cpu.mem_map(address, 0x10000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x200FF00)
    cpu.reg_write(UC_ARM64_REG_LR, END)
    cpu.reg_write(UC_ARM64_REG_TPIDR_EL0, 0x3000000)
    for register, value in registers.items():
        cpu.reg_write(register, value & ((1 << 64) - 1))
    if setup:
        setup(cpu)
    calls = []

    def step(engine, address, size, _):
        if address in stops:
            engine.emu_stop()
        elif address in stubs:
            name, value = stubs[address]
            calls.append(name)
            engine.reg_write(UC_ARM64_REG_X0, value & ((1 << 64) - 1))
            engine.reg_write(UC_ARM64_REG_PC, engine.reg_read(UC_ARM64_REG_LR))

    cpu.hook_add(UC_HOOK_CODE, step)
    cpu.emu_start(start, END + 4, count=20000)
    pc = cpu.reg_read(UC_ARM64_REG_PC)
    if pc not in stops:
        raise AssertionError(f"没有到达预期返回点：{pc:#x}")
    return cpu.reg_read(UC_ARM64_REG_X0), pc, calls


def main():
    original = ORIGINAL.read_bytes()
    patched, policy = preserve_existing_keys(original)
    results = []
    # 从真实函数入口运行。检索失败必须继续失败，不能因补丁变成“解密成功”。
    for label, data in (("original", original), ("patched", patched)):
        for exists, retrieval, allow_generation in ((True, True, True), (True, False, True),
                                                     (False, False, True), (False, False, False)):
            regs = {UC_ARM64_REG_X0: 0x1000000, UC_ARM64_REG_X1: 0x1000000,
                    UC_ARM64_REG_X2: 0x1000100, UC_ARM64_REG_X3: 0x1000200, UC_ARM64_REG_X4: 0x1000300}
            stubs = {0x379D70: ("access", 0 if exists else -1), 0x37A5A0: ("ShouldLog", 0),
                     0x33E30C: ("retrieveKey", int(retrieval)), 0x341498: ("generateStorageKey", 1),
                     0x33C474: ("storeKeyAtomically", 1)}

            def setup(cpu):
                cpu.mem_write(0x1000000, b"\x02k\0" + bytes(21))  # libc++ 短字符串，仅为测试路径。
                cpu.mem_write(0x1000200, struct.pack("<QBB6x", 64, allow_generation, 0))

            value, _, calls = execute(data, 0x342C30, regs, stubs, setup=setup)
            expected = retrieval if exists else (label == "original" and allow_generation)
            assert value == int(expected), (label, exists, value, calls)
            if label == "patched":
                assert "generateStorageKey" not in calls and "storeKeyAtomically" not in calls
            results.append({"binary": label, "case": "retrieve-existing-or-refuse-missing", "exists": exists,
                            "retrieval": retrieval, "allow_generation": allow_generation, "returned": value, "calls": calls})

    # 使用真实“是否存在”分支结果验证 user0；检查缺 key 时走原 false 返回点。
    for start, reg, present, missing, next_pc, callee in (
            (0x32D11C, UC_ARM64_REG_X20, 0, -1, 0x32D138, 0x32E060),
            (0x32D140, UC_ARM64_REG_X0, 1, 0, 0x32D15C, 0x32E4A0)):
        for exists, value in ((True, present), (False, missing)):
            _, pc, calls = execute(patched, start, {reg: value}, {callee: ("create-user-key", 1)},
                                   stops=(next_pc, 0x32DBEC))
            assert pc == (next_pc if exists else 0x32DBEC) and not calls
            results.append({"binary": "patched", "case": "user0-existing-only", "start": hex(start),
                            "exists": exists, "stop": hex(pc), "calls": calls})

    value, _, calls = execute(patched, 0x331434, {}, {})
    assert value == 1 and not calls
    results.append({"binary": "patched", "case": "skip-candidate-cleanup", "returned": value, "calls": calls})
    original_fs = (ORIGINAL.parent.parent / "lib64/libfs_mgr.so").read_bytes()
    patched_fs, mount_policy = preserve_mount_failures(original_fs)
    for comparison in (0, 1):
        _, pc, calls = execute(patched_fs, 0x3A720, {UC_ARM64_REG_X0: comparison}, {}, stops=(0x3A724, 0x3A924))
        assert pc == 0x3A924 and not calls
        results.append({"binary": "patched-libfs_mgr", "case": "no-preventative-marker-write", "stop": hex(pc)})
    for mount_result in (0, -1):
        stubs = {0x90000: ("errno", 0x1000000), 0x8FF60: ("ShouldLog", 0),
                 0x3D7DC: ("check_fs", 0), 0x3C384: ("mount-retry", 0)}
        _, pc, calls = execute(patched_fs, 0x3D05C, {UC_ARM64_REG_X0: mount_result}, stubs,
                               stops=(0x3D3C4, 0x3D0CC), setup=lambda cpu: cpu.mem_write(0x1000000, struct.pack("<I", 22)))
        assert pc == (0x3D3C4 if mount_result == 0 else 0x3D0CC)
        assert "check_fs" not in calls and "mount-retry" not in calls
        results.append({"binary": "patched-libfs_mgr", "case": "mount-success-or-failure", "result": mount_result,
                        "stop": hex(pc), "calls": calls})
    report = {"passed": True, "cases": results, "source_sha256": hashlib.sha256(original).hexdigest(),
              "patched_sha256": policy["patched_sha256"], "patched_fs_mgr_sha256": mount_policy["patched_sha256"], "phone_operations": False,
              "real_authentication_or_decryption_tested": False,
              "scope": "真实 ELF 控制流；外部文件/密码学调用为测试桩，不能替代 HAL 或真机解密验证"}
    output = ROOT / "build/recovery/prebuilt-crypto/key-policy-checks.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "cases": len(results), "patched_sha256": policy["patched_sha256"]}))


if __name__ == "__main__":
    main()
