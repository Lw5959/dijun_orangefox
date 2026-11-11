# 原厂 MiTEE 的最小 ARM64 依赖；主 device.mk 只需 include 此文件。
# 由 0003 补丁消费；原系统参数读取失败时不启动 HAL，也不进入现有 key 的解密/升级路径。
TW_REQUIRE_CRYPTO_BOOT_PARAMS := true
DIJUN_CRYPTO_PATH := device/xiaomi/dijun/proprietary/crypto
PRODUCT_PACKAGES += \
    dijun_mitee_gatekeeper \
    dijun_mitee_keymint \
    dijun_mitee_supplicant \
    dijun_mitee_android_hardware_gatekeeper_V1_ndk \
    dijun_mitee_android_hardware_security_keymint_V3_ndk \
    dijun_mitee_android_hardware_security_rkp_V3_ndk \
    dijun_mitee_android_hardware_security_secureclock_V1_ndk \
    dijun_mitee_android_hardware_security_sharedsecret_V1_ndk \
    dijun_mitee_android_system_suspend_V1_ndk \
    dijun_mitee_lib_android_keymaster_keymint_utils \
    dijun_mitee_libbase \
    dijun_mitee_libc__ \
    dijun_mitee_libcppbor \
    dijun_mitee_libcppbor_external \
    dijun_mitee_libcppcose_rkp \
    dijun_mitee_libcrypto \
    dijun_mitee_libcutils \
    dijun_mitee_libgatekeeper \
    dijun_mitee_libhardware \
    dijun_mitee_libhidlbase \
    dijun_mitee_libkeymaster_messages \
    dijun_mitee_libkeymaster_portable \
    dijun_mitee_libkeymint \
    dijun_mitee_libpuresoftkeymasterdevice \
    dijun_mitee_libsoft_attestation_cert \
    dijun_mitee_libteecli \
    dijun_mitee_libtrusty \
    dijun_mitee_libutils \
    dijun_mitee_libz

# 只把不可变 TA 作为普通固件复制；不复制任何 Android 用户密钥/secure-storage。
PRODUCT_COPY_FILES += \
    $(DIJUN_CRYPTO_PATH)/vendor/mitee/ta/dba51a17-0563-11e7-93b16fa7b0071a51.ta:$(TARGET_COPY_OUT_RECOVERY)/root/vendor/mitee/ta/dba51a17-0563-11e7-93b16fa7b0071a51.ta \
    $(DIJUN_CRYPTO_PATH)/vendor/mitee/ta/4d573443-6a56-4272-ac6f2425af9ef9bb.ta:$(TARGET_COPY_OUT_RECOVERY)/root/vendor/mitee/ta/4d573443-6a56-4272-ac6f2425af9ef9bb.ta

# 此库由 OrangeFox 平台源码构建，不能用原 Android 的 Binder/Bionic 替换。
RECOVERY_LIBRARY_SOURCE_FILES += $(TARGET_OUT_SHARED_LIBRARIES)/libvndksupport.so
