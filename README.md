# OrangeFox for Dijun

小米 15S Pro（`dijun / XRING O1`）的 OrangeFox KernelSU 模块。

仅适配 `dijun OS4.0.0.19.XODCNXM`；操作按钮进入 Recovery；卸载恢复原厂。

- 模块 ID：`dijun_orangefox`
- 作者：`OrangeFox Team & Lw59`
- [下载模块](https://github.com/Lw5959/dijun_orangefox/releases/latest)
- [Recovery 适配源码与构建方法](port/README.md)

## 安装和使用

需要已解锁 Bootloader、KernelSU 和上述固件；已在 KernelSU 32707 上验证。

1. 在 KernelSU 管理器的模块页安装发布的 ZIP。
2. 正常重启 Android，使模块生效。
3. 点击模块的“操作”进入 OrangeFox。解锁凭据只在手机上输入。
4. 卸载模块并正常重启 Android，卸载钩子恢复原厂 Recovery，并读回核验。**仅禁用模块不会恢复 Recovery。**

安装器读取当前启动槽，写入对应的 `recovery_a` 或 `recovery_b`，记录为 `installed-slot`。首次安装要求目标分区与包内原厂镜像的完整 SHA256 一致；升级要求旧模块的安装记录、旧镜像与分区一致。写入失败时，首装回退原厂，升级回退此前 OrangeFox。卸载按安装记录恢复，不跟随之后的启动槽变化。

模块不修改 GPT、用户数据或启动槽，不执行 BL 回锁。若 OTA 或其他工具已经修改 Recovery，模块会保留该镜像并报告错误。

## 恢复原厂

如需立即恢复，可在 Android 的 root 终端执行：

```sh
su -c 'sh /data/adb/modules/dijun_orangefox/restore.sh'
```

请保留安装 ZIP。KernelSU 即使卸载脚本失败也可能继续删除模块；必要时可从 ZIP 提取 `stock-recovery.img`，按之前保存的 `installed-slot` 恢复对应分区。例如安装记录为 `_a` 时：

```sh
fastboot -s <手机序列号> flash recovery_a stock-recovery.img
fastboot -s <手机序列号> reboot
```

恢复时根据安装记录选择分区，不按后来变化的启动槽猜测。Bootloader 始终保持解锁。

## 已验证的范围

当前发布镜像已在真实设备 B 槽完成 KSU 升级、重启 Android、模块操作入口进入 Recovery、真实凭据解密及返回 Android。用户确认中文、触控、显示/振动页面、手电筒、振动及亮度调节正常；此前版本还完成了 CE 自建测试文件读写、KSU 安装/卸载和原厂回退。

亮度上限已校准为 16383，CPU 温度节点与 RTC 时间修正已接入。公开的版本状态见 [`config/images.json`](config/images.json)，完整镜像 SHA256 为：

```text
e0af4e1c994da54138e154978a3885a18787368a084e543627c15c052ed22488
```

A 槽逻辑有宿主测试，尚无 A 槽真机验收。完整备份/恢复、刷 ROM/OTA、fastbootd、OTG 和 MTP 文件传输尚未完成验收；本版保留现有 FBE 密钥，不支持初始化新的加密 userdata。上述局部验证不代表全部 OrangeFox 功能已经适配。

## 从源码打包模块

模块打包只需 Python 3.11 或更新版本，使用标准库，不访问手机。将本版 OrangeFox 镜像与匹配的原厂 Recovery 放在本地后运行：

```sh
python3 tools/build_module.py \
  --orangefox /path/to/orangefox.img \
  --stock /path/to/stock-recovery.img \
  --output dist/OrangeFox-for-Dijun.zip
```

脚本核对两份 100 MiB 镜像的完整 SHA256，输出 ZIP 和 `.sha256`。发布 ZIP 中也包含这两份镜像，可直接提取后重新打包。重建 Recovery 的步骤、外部输入哈希及固定上游版本见 [`port/`](port/README.md)。

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s port/tests -v
```

宿主测试覆盖 A/B 选择、安装记录、重复安装、旧版升级、失败回退、错误固件/锁定状态拒绝写入及非本模块镜像保护，不替代真机验收。

## 许可证与来源

模块脚本及原创适配代码按 `GPL-3.0-or-later` 发布，详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。OrangeFox、Team Win、Android 及其他上游文件保留原有许可证和版权声明。

Recovery 采用固定版本的 OrangeFox 通用预编译用户空间，编译 O1 DRM 后端，再接入本机组件与明确记录的补丁。仓库公开模块、设备树、适配脚本、补丁和实际使用的上游源码片段；原厂 HAL、TA、固件和模块作为外部构建输入，保留各自原有权利，不改授本仓库许可证。本仓库由 Lw59 维护。
