# dijun 独立 recovery 的源码图裁剪；由产品 makefile 显式 include。
# 依据：固定 Blueprint build/blueprint/context.go 的 SourceRootDirAllowed。
# 本版未命中任何前缀的路径默认允许，负前缀才拒绝；最长匹配优先。
# 不用单独的 "-" 关闭默认根，也不用通配符或把 "." 当作白名单。
# 负前缀排除无关实现；必要的更具体正前缀保留其下被引用的 proto。
# 目录项保留末尾 /，避免误伤同名前缀的兄弟目录。
# 此列表用于收窄无关源码扫描和分析内存，不保证成品的依赖完整性。
# official minimal 的配套缺项策略可能略过 required/defaults，最终必须核对
# 镜像实际程序、ELF 依赖、服务入口和本机功能，不能把构图通过当作适配完成。

# 独立 native recovery 不选择 CTS、应用 APK 或 Android framework UI 图。
# 这里只跳过其 BP 声明；源码仍可被保留的原生模块作为 include/源文件读取。
# ART（含 libdexfile）、frameworks/native、hardware/interfaces、packages/modules
# 及 vold/keystore2/fs_mgr/KeyMint/Gatekeeper 保持扫描，不按 Java 字样整树误删。
PRODUCT_SOURCE_ROOT_DIRS += \
    -cts/ \
    -packages/apps/ \
    -frameworks/base/packages/

# 首轮报错的车载 CTS 主模块与其同目录 app/lib 均不进入恢复镜像。
PRODUCT_SOURCE_ROOT_DIRS += \
    -cts/tests/tests/car/ \
    -cts/tests/tests/car_permission_tests/

# 虚拟机能力 VTS 使用 minimal manifest 未提供的 rdroidtest.defaults；
# 保留 capabilities_service 的 AIDL、default 和 noop 实现目录。
PRODUCT_SOURCE_ROOT_DIRS += \
    -hardware/interfaces/virtualization/capabilities_service/vts/

# remote-access-hal-defaults 和其单测都需要缺失的 vhalclient_defaults。
# 只去掉这两个节点；保留 proto/bind_to_device_socket_mutator，因为
# wakeup_client_protos 还被其他车载节点引用，不能整棵删除 remoteaccess。
PRODUCT_SOURCE_ROOT_DIRS += \
    -hardware/interfaces/automotive/remoteaccess/hal/default/Android.bp \
    -hardware/interfaces/automotive/remoteaccess/hal/default/test/

# CHRE 根 Android.bp 的 rpc_world_* 需要缺失的 Pigweed 生成器；
# 子树中的 nanoapp、host HAL、Java 测试引用同一族生成物，一起裁掉。
PRODUCT_SOURCE_ROOT_DIRS += \
    -system/chre/

# framework 的 aconfig Java 节点仍引用 chre_flags；只恢复真实声明所在根 BP。
# 其余 CHRE 实现/测试继续不扫描，.aconfig 源文件本身无需单独 Blueprint 节点。
PRODUCT_SOURCE_ROOT_DIRS += system/chre/Android.bp

# 缺失 neuralnetworks_utils_defaults 会影响 common、adapter、service、
# 各版 utils 及引用它们的 VTS。保留 AIDL/HIDL 接口声明，避免无关的
# VNDK/source_module_name 引用因整棵 neuralnetworks 被删除而失效。
PRODUCT_SOURCE_ROOT_DIRS += \
    -hardware/interfaces/neuralnetworks/utils/ \
    -hardware/interfaces/neuralnetworks/1.0/utils/ \
    -hardware/interfaces/neuralnetworks/1.1/utils/ \
    -hardware/interfaces/neuralnetworks/1.2/utils/ \
    -hardware/interfaces/neuralnetworks/1.3/utils/ \
    -hardware/interfaces/neuralnetworks/aidl/utils/ \
    -hardware/interfaces/neuralnetworks/1.0/vts/ \
    -hardware/interfaces/neuralnetworks/1.1/vts/ \
    -hardware/interfaces/neuralnetworks/1.2/vts/ \
    -hardware/interfaces/neuralnetworks/1.3/vts/ \
    -hardware/interfaces/neuralnetworks/aidl/vts/

# tradefed-contrib 缺少 tradefed_errorprone_defaults，其 tests 又依赖它。
# 不裁掉整个 tools/tradefederation/core：它还向大量保留的测试 BP 提供
# tradefed 等真实模块。已知 core/Android.bp 的 tradefed_zip/tradefed-core
# 仍引用 contrib，须由后续严格构图报告并单独审阅，不能为隐藏这两条
# 打包边而连带删除数百个节点，也不能提供假 contrib/defaults。
PRODUCT_SOURCE_ROOT_DIRS += \
    -tools/tradefederation/contrib/

# securitybulletin 的 checkinput 引用属于未选择的全平台测试图；当前整棵
# CTS 已由上方排除。以下更具体规则继续生效，不为测试 PoC 提供假 defaults。
PRODUCT_SOURCE_ROOT_DIRS += \
    -cts/hostsidetests/securitybulletin/securityPatch/CVE-2023-4863/ \
    -cts/hostsidetests/securitybulletin/securityPatch/CVE-2023-21085/ \
    -cts/hostsidetests/securitybulletin/securityPatch/CVE-2023-40114/

# AEMU snapshot/host-common/base tests 使用缺失的 gfxstream_defaults；
# 此主机模拟器实现族不参与实体 dijun 的 recovery 图。
PRODUCT_SOURCE_ROOT_DIRS += \
    -hardware/google/aemu/

# 此测试主 BP 依赖 MotionTestDefaults；SystemUI/SettingsLib 的同族 Java
# 测试引用不属于本 native recovery，当前整个 framework packages 图由上方排除。
PRODUCT_SOURCE_ROOT_DIRS += \
    -frameworks/base/packages/SystemUI/compose/scene/tests/Android.bp

# 车载 VehicleHalDefaults[-V3] 依赖缺失 large-parcelable 默认配置；
# 实现、假硬件和同族测试一起裁掉，AIDL 接口声明保持默认允许。
# 更长的正前缀保留两个 proto 子树，不能因排除 impl 而丢掉协议输入。
# aidl_test 与 radio 单测分别引用 VehicleHalUtils/IVehicleHardware，
# 同步排除这两个测试节点，避免留下必然无法解析的实现族边。
PRODUCT_SOURCE_ROOT_DIRS += \
    -hardware/interfaces/automotive/vehicle/aidl/impl/3/ \
    -hardware/interfaces/automotive/vehicle/aidl/impl/current/ \
    hardware/interfaces/automotive/vehicle/aidl/impl/3/proto/ \
    hardware/interfaces/automotive/vehicle/aidl/impl/current/proto/ \
    -hardware/interfaces/automotive/vehicle/aidl/aidl_test/ \
    -hardware/interfaces/broadcastradio/aidl/default/test/ \
    -hardware/interfaces/automotive/audiocontrol/aidl/default/Android.bp

# 已核对本 fork 的 recovery、vold、keystore2、fs_mgr 和设备配置，均无
# Secretkeeper、dice_policy、explicitkeydice 或 authmgr 引用。此处去掉
# 需要 avf_build_flags_rust 的 Secretkeeper 实现族及其明确调用方：
# nonsecure/Trusty 参考服务、SEE authmgr/DICE policy 实现和对应 VTS。
# 这些引用未进入当前 FBE 构建链；保留 Secretkeeper/AuthGraph/HwCrypto
# AIDL 声明、system/authgraph 以及现役 MiTEE KeyMint/Gatekeeper 输入。
PRODUCT_SOURCE_ROOT_DIRS += \
    -system/secretkeeper/ \
    -hardware/interfaces/security/secretkeeper/default/ \
    -system/core/trusty/secretkeeper/ \
    -system/see/authmgr/ \
    -hardware/interfaces/security/secretkeeper/aidl/vts/ \
    -hardware/interfaces/security/see/hwcrypto/aidl/vts/

# BPF 保留：system/bpf 由构建侧补齐真实源码，不在这里排除 Connectivity。
# recovery、vold/fs_mgr、KeyMint、Gatekeeper、显示/触控和设备私有输入均保留。
#
# 构建入口采用上游 minimal 配套策略；不提供空模块或关闭原生 ELF/链接检查。
# 原生 enforce-product-packages-exist 也受全局 ALLOW_MISSING 条件约束，
# 不把一次无效的宏调用描述为产品包完整性保证。
