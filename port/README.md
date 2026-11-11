# Dijun Recovery 适配源码

这里保存发布镜像的设备树、init/USB/FBE 配置、DRM 后端、预编译用户空间修正脚本、硬件接入脚本和构建检查。构建不连接手机，不刷写分区。

当前路线复用 `OrangeFox-R12.0_2-infiniti.zip` 的通用 ARM64 用户空间，只编译 O1 DRM 库；不使用 donor 的内核、厂商模块、fstab 或安全 HAL。完整 AOSP 源码构建未纳入这个精简入口，`recovery/patches/` 中同时保留了此前源码路线的改动。

## 环境和固定依赖

- Python 3.11+、`lz4`、`patch`、LLVM 的 `llvm-readobj`。
- Android NDK `28.2.13676358`，已有真机构建使用 macOS；Linux NDK 路径已接入，尚未执行 Linux 完整镜像构建。
- 分支检查使用 `unicorn==2.1.4`；只验证实际 AArch64 控制流，外部密码学调用为测试桩。
- 所需 DRM 源码、头文件、AVB 工具与 ELF 检查器已按原许可证保留在 `sources/`。精确提交和文件 SHA256 见 `sources.lock.json` 及各组件的 `manifest.json`。

从本目录运行：

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r recovery/requirements-tests.txt
```

原厂输入仅接受 `OS4.0.0.19.XODCNXM`，文件名、大小和哈希见 `config/build-inputs.json`、`config/proprietary-files.json`。通用用户空间来源见 [OrangeFox 发布页](https://orangefox.download/release/69f78ad93ba4241a6c1e09a9)，该 donor 镜像不能直接刷入 dijun。

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
python3 tools/recovery/build_prebuilt_crypto.py
```

第一步生成显示基础包，第二步检查保留既有密钥及挂载失败分支，第三步接入原厂解密和硬件组件，生成 `build/recovery/OrangeFox-dijun-crypto-trial-zh.img`。中间的显示基础包只用于后续组装，不作为本项目的最终发布镜像。

构建报告位于 `build/recovery/prebuilt-crypto/`，ELF/init 检查读取实际 ramdisk。`recovery/prebuilt/sepolicy-firmware-load` 是固定 donor 策略的修正版，其原件/结果哈希和仅有的语义变化记录在 `firmware-policy.json`；它允许 `kernel` 对 `vendor_file` 加载 firmware，保留其他权限及未知权限拒绝行为。

返回模块仓库根目录，将重建镜像和原厂镜像交给 `tools/build_module.py` 打包。只有镜像与已验证发布版本的完整哈希一致，才会生成该版模块；有意修改源码后，需要重新进行版本核验并更新 `config/images.json`。

## 改动与验收边界

- `build_prebuilt_trial.py`：单 primary plane DRM、XBGR8888、中文首次设置及滑块纵向缩放修复。
- `preserve_prebuilt_keys.py`：保留原认证和解密路径，缺失密钥时报错，避免新建/清理密钥及自动 fsck 重试。
- `patch_prebuilt_hardware.py`、`recovery/prebuilt/`：本机亮度/温度参数、原厂振动驱动和 HAL、闪光灯串行控制、RTC 时间修正。
- `stage_prebuilt_crypto.py`：MiTEE/KeyMint、VINTF、linker namespace、原厂 OS/SPL 参数和本机 OTA 身份信息。

镜像构建与宿主检查不会将真机验收字段自动标成通过。本版设备结果在仓库根目录说明及 `config/images.json` 中单独记录；格式化新的加密 userdata、完整备份恢复、OTA 和外置存储仍不属于已通过范围。
