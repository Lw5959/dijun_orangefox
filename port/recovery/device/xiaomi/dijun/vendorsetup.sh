#!/bin/bash
# OrangeFox 要求 FOX_* 从环境导入，不能放进 BoardConfig.mk。
export FOX_BUILD_DEVICE=dijun
export FOX_TARGET_DEVICES=dijun
export FOX_BUILD_TYPE=Unofficial
export FOX_AB_DEVICE=1
export FOX_VIRTUAL_AB_DEVICE=1
export OF_AB_DEVICE_WITH_RECOVERY_PARTITION=1
export FOX_VANILLA_BUILD=1
export OF_NO_REFLASH_CURRENT_ORANGEFOX=1
export OF_DONT_PATCH_ENCRYPTED_DEVICE=1
export OF_DONT_PATCH_ON_FRESH_INSTALLATION=1
export OF_SCREEN_H=3200

# 现有 KernelSU 保持；不随恢复镜像附加其他 root 管理器的安装包。
export FOX_DELETE_MAGISK_ADDON=1
