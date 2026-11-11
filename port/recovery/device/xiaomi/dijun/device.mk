LOCAL_PATH := device/xiaomi/dijun

# first_api_level / vendor API 由现场读取，恢复用户态版本不伪装成 Android 17。
PRODUCT_SHIPPING_API_LEVEL := 35
PRODUCT_USE_DYNAMIC_PARTITIONS := true
PRODUCT_VIRTUAL_AB_OTA := true
AB_OTA_UPDATER := true
AB_OTA_PARTITIONS := boot init_boot vendor_boot dtbo recovery vbmeta vbmeta_system vbmeta_vendor system system_ext product vendor vendor_dlkm system_dlkm odm odm_dlkm

PRODUCT_PACKAGES += \
    bootctl \
    fastbootd \
    fsck.f2fs \
    sload_f2fs \
    libdrm \
    liblog \
    libmodprobe \
    libvndksupport \
    servicemanager \
    hwservicemanager

# 二进制仅来自这台手机当前固件。ETC prebuilt 保留模块签名/CRC/原始字节，
# 不通过 PRODUCT_COPY_FILES 绕过 AOSP 对 lib 目录 ELF 的检查，也不重新 strip。
DIJUN_MODULE_DIR := $(LOCAL_PATH)/proprietary/modules/1.1
DIJUN_MODULE_FILES := $(notdir $(wildcard $(DIJUN_MODULE_DIR)/*.ko) $(wildcard $(DIJUN_MODULE_DIR)/modules.*))
PRODUCT_PACKAGES += $(addprefix dijun_recovery_,$(subst .,_,$(DIJUN_MODULE_FILES)))

PRODUCT_PROPERTY_OVERRIDES += \
    ro.hardware=O1_asic \
    ro.board.platform=O1_asic \
    ro.crypto.metadata_init_delete_all_keys.enabled=false \
    ro.crypto.recovery_preserve_keys=true

# MiTEE 服务、VINTF 与 linker namespace 由单独的已取证配置接入。
# 不引入 Qualcomm qseecomd/keymaster 脚本，也不启动软件模拟密钥 HAL。
$(call inherit-product, device/xiaomi/dijun/firmware.mk)
$(call inherit-product, device/xiaomi/dijun/boot-hal.mk)
$(call inherit-product, device/xiaomi/dijun/crypto.mk)
