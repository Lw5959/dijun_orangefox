DEVICE_PATH := device/xiaomi/dijun

# 现场只有 arm64-v8a；恢复环境使用通用 ARMv8 用户态，不套用高通平台配置。
TARGET_ARCH := arm64
TARGET_ARCH_VARIANT := armv8-a
TARGET_CPU_VARIANT := generic
TARGET_CPU_ABI := arm64-v8a
TARGET_CPU_ABI2 :=
TARGET_BOARD_PLATFORM := O1_asic
TARGET_BOOTLOADER_BOARD_NAME := O1
TARGET_NO_BOOTLOADER := true
TARGET_2ND_ARCH :=

# 原厂 recovery_b 仅有 v4 ramdisk，内核和 DT/早期模块来自现有启动链。
# PRODUCT_BUILD_RECOVERY_IMAGE 显式开启独立镜像，避免 TARGET_NO_KERNEL 关闭目标。
TARGET_NO_KERNEL := true
TARGET_KERNEL_VERSION := 6.18
TARGET_KERNEL_NO_GCC := true
BOARD_EXCLUDE_KERNEL_FROM_RECOVERY_IMAGE := true
BOARD_BOOT_HEADER_VERSION := 4
BOARD_KERNEL_PAGESIZE := 4096
BOARD_RECOVERY_MKBOOTIMG_ARGS := --header_version 4
BOARD_RECOVERYIMAGE_PARTITION_SIZE := 104857600
BOARD_FLASH_BLOCK_SIZE := 4096
BOARD_RAMDISK_USE_LZ4 := true

# 只生成修改后 payload 的无签名 AVB hash footer，不复制失效的 OEM 签名。
# 无 RECOVERY_KEY_PATH 时 AOSP recovery footer 为 algorithm NONE；仅供解锁 BL 验证。
# 与原厂保持 rollback 数值，但本工程不构建或刷写外部 vbmeta。
BOARD_AVB_ENABLE := true
# 原 recovery 只有 recovery fingerprint，不向现有 boot 启动链追加 AOSP16 OS/patch 值。
# 由 build-make 的设备限定补丁消费；原 boot_b 的 AVB 属性保持原状。
BOARD_RECOVERY_EXCLUDE_BOOT_PROPERTIES := true
BOARD_AVB_RECOVERY_ADD_HASH_FOOTER_ARGS := \
    --rollback_index 1788220800 \
    --rollback_index_location 11 \
    --salt c4cbfdb2ca989e645b7404af41d94a001c371a73ec338616b31f1b5c690fb36d

BOARD_SUPER_PARTITION_METADATA_DEVICE := super
BOARD_USES_METADATA_PARTITION := true
BOARD_HAS_LARGE_FILESYSTEM := true
BOARD_HAS_NO_REAL_SDCARD := true
BOARD_USERDATAIMAGE_FILE_SYSTEM_TYPE := f2fs
TARGET_USERIMAGES_USE_F2FS := true
TARGET_USERIMAGES_USE_EXT4 := true
TARGET_USERIMAGES_USE_EROFS := true
# 统一使用平台 shared libblkid；只关闭上游同名 legacy 模块定义。
TW_USE_SYSTEM_LIBBLKID := true
TARGET_RECOVERY_FSTAB := $(DEVICE_PATH)/recovery.fstab
TARGET_RECOVERY_DEVICE_DIRS += $(DEVICE_PATH)
# 使用已核对的恢复 fstab，不让原 Android 的 first-stage 条目覆盖本配置。
TW_SKIP_ADDITIONAL_FSTAB := true

# 使用 O1 设备 rc 补齐 ConfigFS MTP，不让默认 legacy android_usb rc 并行改 gadget。
# MTP 保持启用，ADB/fastboot/sideload 的基础 ConfigFS 状态机仍由上游 init.rc 提供。
TW_EXCLUDE_DEFAULT_USB_INIT := true

# 现场为 xring_drm / DSI-1；minuitwrp 自带 DRM 后端，无 fbdev 或 QCOM overlay。
# 原模块 rch_format_map 含 XB24。选 XBGR8888 + GGL RGBA 的一致内存布局，
# 避免上游无配置时 RGB565 与 GGL BGRA8888 的 16/32 位不一致。
# 实际色序和触控方向仍必须由真机图案及四角点击验收。
TARGET_RECOVERY_PIXEL_FORMAT := RGBX_8888
TW_DRM_SINGLE_PLANE := true
TW_THEME := portrait_hdpi
TARGET_SCREEN_WIDTH := 1440
TARGET_SCREEN_HEIGHT := 3200
TW_BRIGHTNESS_PATH := /sys/class/backlight/panel0-backlight/brightness
TW_MAX_BRIGHTNESS := 16383
# 初始值取量程四分之一，是本工程选择，不是对原厂默认亮度的测量。
TW_DEFAULT_BRIGHTNESS := 4096
TW_DEFAULT_LANGUAGE := zh_CN
TW_EXTRA_LANGUAGES := true
TW_INPUT_BLACKLIST :=

# 不修改磁盘加密策略；实际可解密性还取决于原厂 MiTEE/KeyMint HAL 接线和实测。
TW_INCLUDE_CRYPTO := true
TW_INCLUDE_CRYPTO_FBE := true
TW_INCLUDE_FBE_METADATA_DECRYPT := true
TW_USE_DMCTL := true
# 上游为动态分区装入 lpdumpd.rc；同时装入对应程序和库，避免孤立服务。
TW_INCLUDE_LPDUMP := true
TARGET_RECOVERY_BOOT_HAL := android.hardware.boot-service.xring.recovery
TW_INCLUDE_RESETPROP := true
TWRP_INCLUDE_LOGCAT := true
TARGET_USES_LOGD := true

# 正常 Android 的触控不在 vendor_boot，加入匹配原厂最小依赖闭包。
# 使用 loader 实际支持的 /vendor/lib/modules/1.1，避免改变 first-stage UFS 加载路径。
TW_LOAD_VENDOR_MODULES := xring-drm.ko synaptics_tcm2.ko xiaomi_touch_dijun.ko
TW_LOAD_VENDOR_BOOT_MODULES := true
TW_LOAD_PREBUILT_MODULES_AT_FIRST := true
