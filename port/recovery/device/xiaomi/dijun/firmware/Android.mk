LOCAL_PATH := $(call my-dir)

ifeq ($(TARGET_DEVICE),dijun)
include $(CLEAR_VARS)
LOCAL_MODULE := dijun_synaptics_spi_firmware
LOCAL_MODULE_STEM := synaptics_spi_dijun.img
LOCAL_MODULE_TAGS := optional
LOCAL_MODULE_CLASS := ETC
LOCAL_SRC_FILES := ../proprietary/firmware/synaptics_spi_dijun.img
# fw_path[] 的标准回退路径，不依赖 /vendor 或 /odm 已经挂载，也不修改内核参数。
LOCAL_MODULE_PATH := $(TARGET_RECOVERY_ROOT_OUT)/lib/firmware
include $(BUILD_PREBUILT)
endif
