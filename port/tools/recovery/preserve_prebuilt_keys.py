#!/usr/bin/env python3
"""为固定 donor 实现保留既有加密数据的策略；不改认证、解密或内核密钥安装结果。"""

import hashlib

SOURCE_SHA256 = "34b1561ba9d653fbd51e964fd83144beb0777bc50d32719f157e50b5c340891b"

# 此 ELF 的四处 VA 与文件偏移相同，已由 PT_LOAD 核对。仅接受整文件 SHA 匹配的原件。
# 地址含义来自对应源码及真实反汇编，见 prebuilt-crypto/analysis/，不按相似字符串猜位置。
PATCHES = (
    (0x342C8C, "68030034", "1b000014",
     "retrieveOrGenerateKey：仅在原 access 判断缺失后，无条件进入原 No key found 失败路径；已有 key 的 retrieveKey 调用不变"),
    (0x32D128, "ce030094", "e0031f2a",
     "fscrypt_init_user0：缺 DE key 时返回 false，不调用 create_de_key"),
    (0x32D14C, "d5040094", "e0031f2a",
     "fscrypt_init_user0：缺 CE key 时返回 false，不调用 create_ce_key"),
    (0x331434, "ff4302d1fd7b03a9", "20008052c0035fd6",
     "fixate_user_ce_key：取消检索成功后的删除、重命名和目录同步；返回仅表示不需要整理候选，不代表认证或解密成功"),
)

FS_MGR_SOURCE_SHA256 = "e7420bb8794311f3836e69c1a6d783379f5be0832badfb946e9da25ef9d3a851"
FS_MGR_PATCHES = (
    (0x3A720, "20100035", "81000014",
     "跳过 /data 的 preventative_fsck 属性比较及标记文件写入；保留后续显式 check 标志处理，本机 fstab 不设置 check"),
    (0x3D094, "e8021832", "f7021832",
     "首次挂载失败后直接更新原 fs_stat 寄存器，保留失败状态"),
    (0x3D098, "e2e30091", "0d000014",
     "进入原失败计数/返回路径，跳过自动 fsck 及再次挂载；首次挂载成功分支不变"),
)


def preserve_existing_keys(original):
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError("密钥保留策略仅适用于已反汇编核对的 infiniti R12.0_2 recovery")
    data = bytearray(original)
    records = []
    for offset, before, after, reason in PATCHES:
        old, new = bytes.fromhex(before), bytes.fromhex(after)
        if len(old) != len(new) or data[offset:offset + len(old)] != old:
            raise ValueError(f"指令不匹配：{offset:#x}")
        data[offset:offset + len(old)] = new
        records.append({"file_offset": hex(offset), "elf_va": hex(offset),
                        "before": before, "after": after, "reason": reason})
    return bytes(data), {"source_sha256": SOURCE_SHA256, "patched_sha256": hashlib.sha256(data).hexdigest(),
                         "patches": records, "initializing_new_encrypted_userdata_supported": False,
                         "authentication_bypassed": False, "phone_tested": False}


def preserve_mount_failures(original):
    if hashlib.sha256(original).hexdigest() != FS_MGR_SOURCE_SHA256:
        raise ValueError("自动修盘修改仅适用于已核对的 donor libfs_mgr")
    data = bytearray(original)
    records = []
    for offset, before, after, reason in FS_MGR_PATCHES:
        old, new = bytes.fromhex(before), bytes.fromhex(after)
        if data[offset:offset + len(old)] != old:
            raise ValueError(f"fs_mgr 指令不匹配：{offset:#x}")
        data[offset:offset + len(old)] = new
        records.append({"file_offset": hex(offset), "before": before, "after": after, "reason": reason})
    return bytes(data), {"source_sha256": FS_MGR_SOURCE_SHA256, "patched_sha256": hashlib.sha256(data).hexdigest(),
                         "patches": records, "phone_tested": False}
