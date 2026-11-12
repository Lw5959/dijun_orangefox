# Dijun Recovery 适配源码

这里保存发布镜像的设备树、init/USB/FBE 配置、DRM 后端、预编译用户空间修正脚本、硬件接入脚本和构建检查。构建不连接手机，不刷写分区。

当前路线复用 `OrangeFox-R12.0_2-infiniti.zip` 的通用 ARM64 用户空间，只编译 O1 DRM 库；不使用 donor 的内核、厂商模块、fstab 或安全 HAL。完整 AOSP 源码构建未纳入这个精简入口，`recovery/patches/` 中同时保留了此前源码路线的改动。

## 环境和固定依赖

- Python 3.11+、`lz4`、`patch`、LLVM 的 `llvm-readobj`。
- Android NDK `28.2.13676358`，已有真机构建使用 macOS；Linux NDK 路径已接入，尚未执行 Linux 完整镜像构建。
- NDK 不在 macOS 默认目录时，先设置 `ANDROID_NDK_HOME=/path/to/android-ndk/28.2.13676358`，会话检查及最终装配使用同一路径。
- 分支检查使用 `unicorn==2.1.4`；只验证实际 AArch64 控制流，外部密码学调用为测试桩。
- 所需 DRM 源码、头文件、AVB 工具与 ELF 检查器已按原许可证保留在 `sources/`。精确提交和文件 SHA256 见 `sources.lock.json` 及各组件的 `manifest.json`。

从本目录运行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r recovery/requirements-tests.txt
```

原厂输入仅接受 `OS4.0.4.0.XODCNXM`，文件名、大小和哈希见 `config/build-inputs.json`、`config/proprietary-files.json`。通用用户空间来源见 [OrangeFox 发布页](https://orangefox.download/release/69f78ad93ba4241a6c1e09a9)，该 donor 镜像不能直接刷入 dijun。

## 准备原厂输入

自行准备与清单一致的原厂 Recovery、vendor_boot，以及只读提取的 `vendor/`、`odm/`、`vendor_dlkm/` 文件树。脚本只复制清单内的构建依赖，不读取用户数据或凭据：

```sh
python3 tools/prepare_inputs.py \
  --orangefox-zip /path/to/OrangeFox-R12.0_2-infiniti.zip \
  --stock-recovery /path/to/recovery.img \
  --vendor-boot /path/to/vendor_boot.img \
  --firmware-root /path/to/firmware-tree
```

若已经按 `recovery/device/xiaomi/dijun/proprietary/` 布局保存了原厂组件，可以用 `--prepared-blobs /path/to/proprietary` 替代 `--firmware-root`，此时不必提供 vendor_boot。每项原件仍须通过完整 SHA256 检查。HAL、TA、触控/振动固件及内核模块不作为本仓库的开源代码提交。

## 构建与核验

```sh
python3 tools/recovery/build_prebuilt_trial.py --ndk /path/to/android-ndk/28.2.13676358
python3 tools/recovery/check_prebuilt_key_policy.py
python3 tools/recovery/check_prebuilt_session.py
python3 tools/recovery/build_prebuilt_crypto.py
```

第一步生成显示基础包，随后检查保留既有密钥、挂载失败、会话恢复和摘要校验分支，最后接入原厂解密和硬件组件，生成 `build/recovery/OrangeFox-dijun-crypto-trial-zh.img`。中间的显示基础包只用于后续组装，不作为本项目的最终发布镜像。

构建报告位于 `build/recovery/prebuilt-crypto/`，ELF/init 检查读取实际 ramdisk。`recovery/prebuilt/sepolicy-firmware-load` 是固定 donor 策略的修正版，其原件/结果哈希和仅有的语义变化记录在 `firmware-policy.json`；它允许 `kernel` 对 `vendor_file` 加载 firmware，保留其他权限及未知权限拒绝行为。

策略修改源码为 `tools/recovery/patch_firmware_policy.c`，使用 libsepol 3.5；仓库保留已核对的策略产物，因此精简构建无需重新安装该库。显示基础包根据 DRM/触控入口与真实 `modules.dep` 计算加载闭包，新增振动/ISP 模块保留在最终硬件服务中加载，避免改变已经验收的启动顺序。

已在 macOS 完成 OS4.0.4.0 原厂输入准备、DRM 编译、17 项密钥策略及 52 项会话 AArch64 分支检查与最终镜像构建。100 MiB 镜像 SHA256 为 `1802648d266119999979b91ae18b71d2a0566597eaf2cb190233a2f9d8e0cb9c`，ELF/init 检查无依赖或服务入口失败。具体真机范围见仓库根 README。

返回模块仓库根目录，将重建镜像和原厂镜像交给 `tools/build_module.py` 打包。只有镜像与本版固定的完整哈希一致，才会生成该版模块；有意修改源码后，需要重新进行版本核验并更新 `config/images.json`。

## 改动与验收边界

- `build_prebuilt_trial.py`：单 primary plane DRM、XBGR8888、中文首次设置及滑块纵向缩放修复。
- `preserve_prebuilt_keys.py`：保留原认证和解密路径，缺失密钥时报错，避免新建/清理密钥及自动 fsck 重试。
- `patch_prebuilt_hardware.py`、`recovery/prebuilt/`：本机亮度/温度参数、原厂振动驱动和 HAL、闪光灯串行控制、RTC 时间修正。
- `stage_prebuilt_crypto.py`：MiTEE/KeyMint、VINTF、linker namespace、原厂 OS/SPL 参数和本机 OTA 身份信息。
- `patch_prebuilt_session.py`、`recovery/patches/prebuilt-session.S`、`prebuilt-mtp.S`：固定 donor 的 CLI 完成回复时序、MTP 子进程输出 fd 清理、已有 FBE 解锁会话的用户状态重建、ORS 恢复摘要、sideload 的 USB/取消生命周期，以及原有 BCB 清理后的 fastbootd 开放时点。主程序与 MTP 库配套修改，使用已核对的段间零填充及主程序 8 字节新增 BSS，沿用原 RX/RW 段权限；不修改认证接口、密钥保留补丁或新增运行库。

本版原厂 system 为 Android 17 / SPL `2026-10-01`，vendor 为 SPL `2026-09-01`；原始内部构建号分别为 `17OS4.0.261106.161950561.XRPECN.S` 与 `OS4.0.3.1.XODCN`。参数入口分别核对两侧版本，不能将 vendor SPL 也改成十月。原厂 Recovery 的 AVB rollback index 仍为 `1788220800`，构建从新原件读取此值与 fingerprint。

镜像构建与宿主检查不会将真机验收字段自动标成通过。本版的真机结果在仓库根目录说明及 `config/images.json` 中单独记录；已实测双槽卸载回退、Boot/Recovery 备份恢复、MTP 及会话重启。格式化新的加密 userdata、完整 userdata 恢复、ROM/OTA 和 OTG 不属于已通过范围。
