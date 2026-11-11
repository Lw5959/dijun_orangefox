# dijun 的 OrangeFox 补丁

本目录保留此前完整源码构建路线的补丁和当时的检查状态；当前发布镜像的精简构建及已完成真机结果以仓库根 README 和 `port/README.md` 为准。精简入口仅从 `0001` 提取 DRM 实际源码改动，其余运行时修正由 `tools/recovery/` 及 `recovery/prebuilt/` 实施。

补丁基于 `bootable/recovery` 提交 `0f7831d3240f4c3925a0b5fd7d2c907ddf8704c2`，只应用到实际 AOSP 构建工作树；`sources/orangefox/recovery/` 固定参考副本保持原状。

`0001-dijun-drm-single-primary.patch` 为本设备开启 `TW_DRM_SINGLE_PLANE` 时：

- 经现有 `twrpVarsPlugin` 将开关传入真实 minuitwrp 编译，使用一个覆盖整屏的 primary plane。
- 按 CRTC 可用掩码、plane 的 `type` 和实际 framebuffer fourcc 选择 plane，不把枚举列表前两个对象当成高通的双 mixer。
- 不读取 SDE 专用 topology 来拆分画面；未知的 CRTC/格式组合返回失败并保留日志。
- 清零 AddFB2 未使用的三组槽，避免未初始化的 handle/pitch/offset 被内核视为额外 plane；释放 DRM resources 后清空指针，避免随后的分配失败重复释放。

XRING 原厂模块中存在 `dpu_gem_dumb_create`、mmap 和 atomic commit 实现；`rch_format_map` 包含 `XB24`，设备树使用 `RGBX_8888`，对应本分支的 DRM XBGR8888 / GGL RGBA 内存顺序。静态表记录位于 `build/recovery/drm-format-table.json`，不等同于运行时格式、buffer 分配、commit、颜色或触控验证。

当前已通过固定上游的 `git apply --check`。尚未完成补丁的 OrangeFox 整体编译或真机显示验收，不能标记为已解决黑屏。

`0002-dijun-original-boot-hal.patch` 在 `TARGET_RECOVERY_BOOT_HAL` 显式指定原厂 O1 AIDL 实现时，停止自动拉入默认的三份 HIDL boot service；仍保留 A/B 编译功能和 OTA 工具。该 O1 实现使用 `/dev/slot_bootable`、`/xring-ufs/bootlu_sel` 和 `bcp`，不能用按 AOSP misc 布局初始化的实现替代。原件使用 `cc_prebuilt_binary`、`strip.none=true`、`check_elf_files=true`，构建时必须再检查实际依赖。

`0003-dijun-fbe-installed-os-params.patch` 在 KeyMint/keystore2 启动前，从实际 Android 分区读取现有数据的 OS/patch 参数，并保留 recovery 自身的版本供诊断。取参的所有返回路径统一恢复本函数新建的挂载，避免遮住 ramdisk `/vendor/lib/modules/1.1`；读取、回读或挂载恢复失败时不发布 ready，也不进入解密。本配置的 metadata 解密显式读取 `/etc/recovery.fstab`，保留原厂 wrapped-key 参数。O1 `cmd=0x48` 已证实发送 OS version/OS patch，vendor patch 仅保留真实属性，未证实进入 O1 TEE 配置；不导入会跳过真实配置的 `ro.vendor.keymint.configured`。

`build-make/0001-dijun-recovery-avb-properties.patch` 应用到 `build/make` 提交 `401f131a266b1d6cf0ca9b7e4a385c3b02547725`。原 recovery 的 AVB 只含 recovery fingerprint；原 boot 的 OS/patch 属性仍来自现有 boot 镜像。本补丁为该设备排除 AOSP 默认新加到 recovery 的 boot OS/patch 属性，保留 recovery 自身的真实构建 fingerprint。当前没有 OEM bootloader 证明这些新增字段会被忽略，因此按原厂描述符集合打包，不把恢复用户态版本混入原 boot 的安全参数。
