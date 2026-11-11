#!/usr/bin/env python3
"""固定 donor 的 O1 亮度与温度修正；输入必须已通过原有密钥保留补丁。"""

import hashlib
import struct

KEYS_PATCHED_SHA256 = "7b67b3c54b8229e1ad8d3df5574afd74347cd9ae59026a471d743e5b1fdea8fa"


def patch_hardware(data):
    if hashlib.sha256(data).hexdigest() != KEYS_PATCHED_SHA256:
        raise ValueError("硬件参数修正只接受已核对的密钥保留版本")
    result = bytearray(data)
    records = []
    # SetDefaultValues 内的最大亮度、默认值和百分比计算分子一起修改。
    # 否则界面百分比与实际写入的背光值会不一致；这四处 VA 与文件偏移相同。
    patches = (
        (0x125BB4, 0x5281FFC1, 0x5287FFE1, "亮度上限 4094 -> 原厂 panel0 的 16383"),
        (0x125D40, 0xD2DF8008, 0xD2800008, "默认百分比分子 double 2047 -> 4096：低位"),
        (0x125D4C, 0xF2E813E8, 0xF2E81608, "默认百分比分子 double 2047 -> 4096：高位"),
        (0x125F1C, 0x5280FFE1, 0x52820001, "默认实际亮度 2047 -> 4096"),
    )
    for offset, old, new, reason in patches:
        before, after = struct.pack("<I", old), struct.pack("<I", new)
        if result[offset:offset + 4] != before:
            raise ValueError(f"硬件参数指令不匹配：{offset:#x}")
        result[offset:offset + 4] = after
        records.append({"offset": hex(offset), "before": before.hex(), "after": after.hex(), "reason": reason})
    before = b"/sys/class/thermal/thermal_zone45/temp\0"
    after = b"/sys/class/thermal/thermal_zone6/temp\0\0"
    if result.count(before) != 1:
        raise ValueError("温度路径不是唯一的已核验原件")
    offset = result.index(before)
    result[offset:offset + len(before)] = after
    records.append({"offset": hex(offset), "before": before.hex(), "after": after.hex(),
                    "reason": "使用本机实际 type=cpu-top 的温度节点"})
    return bytes(result), {"source_sha256": KEYS_PATCHED_SHA256,
                           "patched_sha256": hashlib.sha256(result).hexdigest(), "patches": records}
