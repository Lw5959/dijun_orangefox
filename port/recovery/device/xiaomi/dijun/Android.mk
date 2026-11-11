LOCAL_PATH := $(call my-dir)

ifeq ($(TARGET_DEVICE),dijun)
# 这些为当前原厂内核的可装载模块及其闭包清单。按 ETC 原样安装，绝不 strip、
# 重链接或改写签名，避免破坏 module_layout/符号 CRC 与内核模块签名。
define dijun_recovery_module
include $$(CLEAR_VARS)
LOCAL_MODULE := dijun_recovery_$(subst .,_,$(1))
LOCAL_MODULE_STEM := $(1)
LOCAL_MODULE_TAGS := optional
LOCAL_MODULE_CLASS := ETC
LOCAL_SRC_FILES := proprietary/modules/1.1/$(1)
LOCAL_MODULE_PATH := $$(TARGET_RECOVERY_ROOT_OUT)/vendor/lib/modules/1.1
include $$(BUILD_PREBUILT)
endef

dijun_recovery_module_files := $(notdir $(wildcard $(LOCAL_PATH)/proprietary/modules/1.1/*.ko) $(wildcard $(LOCAL_PATH)/proprietary/modules/1.1/modules.*))
$(foreach file,$(dijun_recovery_module_files),$(eval $(call dijun_recovery_module,$(file))))
# Soong Finder 在首个 Android.mk 停止向下扫描，显式包含两个子目录。
# 子文件会更新 LOCAL_PATH，因此用稳定 DEVICE_PATH，避免后一个 include 路径漂移。
include $(DEVICE_PATH)/proprietary/crypto/Android.mk
include $(DEVICE_PATH)/firmware/Android.mk
endif
