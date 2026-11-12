# OrangeFox for Dijun

小米 15S Pro（`dijun / XRING O1`）的 OrangeFox KernelSU 模块。

当前版本适配 `OS4.0.4.0.XODCNXM`，已在真机 A 槽完成 KSU 安装、Android 重启、Recovery 冷启动、真实凭据解密及文件读写往返验证。用户确认常用界面与硬件功能正常。

支持中文界面、既有 userdata 解密、文件管理、备份恢复、USB MTP、ADB sideload 与 fastbootd。保留用户保存的触摸、键盘和操作完成震动设置。命令行恢复默认校验备份摘要，显式 `M` 参数才跳过。

- 模块 ID：`dijun_orangefox`
- 作者：`OrangeFox Team & Lw59`
- [下载最新模块](https://github.com/Lw5959/dijun_orangefox/releases/latest)
- [旧固件 OS4.0.0.19 已验证版本](https://github.com/Lw5959/dijun_orangefox/releases/tag/R12.0_2-dijun-20261111.2)
- [Recovery 适配源码与构建方法](port/README.md)
- [OS4.0.4.0 适配变化与验证范围](docs/firmware-os4-0-4-0.md)

## 安装和使用

需要已解锁 Bootloader、适配当前内核的 KernelSU，以及 `OS4.0.4.0.XODCNXM`。已在当前固件的真机 A 槽验证安装和激活。

1. 保留新旧版本的安装 ZIP，在 KernelSU 管理器的模块页安装与当前固件匹配的发布 ZIP。
2. 正常重启 Android，使模块生效。
3. 点击模块的“操作”进入 OrangeFox。解锁凭据只在手机上输入。
4. 卸载模块并正常重启 Android，卸载钩子恢复原厂 Recovery，并读回核验。**仅禁用模块不会恢复 Recovery。**

安装器读取当前启动槽，写入对应的 `recovery_a` 或 `recovery_b`，记录为 `installed-slot`。首次安装要求目标分区与本版原厂镜像的完整 SHA256 一致；同槽升级要求旧模块的安装记录、旧镜像及同版原厂回退镜像一致。写入失败时，首装回退原厂，升级回退此前 OrangeFox。

OTA 换槽后，若当前槽为新版原厂 Recovery，安装器核对旧模块材料，将旧槽的安装记录和旧版原厂镜像保存在模块的 `previous-slot/`，再安装当前槽。安装过程只写当前槽。卸载分别核对各槽镜像，使用各自对应版本的原厂镜像恢复。再次更新模块时继续保留旧槽回退材料。

模块不修改 GPT、用户数据或启动槽，不执行 BL 回锁。若 OTA 或其他工具已经修改 Recovery，卸载会保留该镜像并报告错误。回退不要求当前 Android 仍为安装时的固件，但要求分区完整哈希与安装记录匹配。

## 恢复原厂

可在 Android 的 root 终端执行以下命令，恢复成功后不会自动重启：

```sh
su -c 'sh /data/adb/modules/dijun_orangefox/restore.sh'
```

OTA 跨槽升级后，建议在卸载前先执行上述手动恢复，并保留 `installed-slot`、`previous-slot/` 与新旧安装 ZIP。KernelSU 即使卸载脚本失败也可能继续删除模块；必要时从**对应版本**的 ZIP 提取 `stock-recovery.img`，按保存的该版本安装记录恢复。例如新版安装记录为 `_a` 时：

```sh
fastboot -s <手机序列号> flash recovery_a stock-recovery.img
fastboot -s <手机序列号> reboot
```

旧槽使用旧版 ZIP 的原厂镜像及旧安装记录。Bootloader 始终保持解锁。

## 已验证的范围

本版通过 21 项模块宿主测试、6 项参数、linker 与 USB 时序测试、17 项 AArch64 密钥策略分支检查及 52 项会话、恢复、sideload 与 fastbootd 生命周期分支检查。新版 51 个模块的 4514 项符号导入与 OTA 中真实内核及配套模块的 CRC 和加载顺序一致，ELF/init 依赖检查通过。

本轮真机已完成 OTA 换槽后的 KSU 安装及 B 槽回退材料保留、Android 重启、模块操作入口冷启动、真实凭据解密、自建 CE 文件在 Android → Recovery → Android 的读写与删除。中文、显示/触控、显示与振动页面、手电筒、振动和亮度获得用户确认；亮度界面值与实际节点读数一致。

返回 Android 后，4 个磁盘的 28 份 GPT 原始元数据文件逐字节一致，38 个启动相关分区仅 `recovery_a` 发生预期变化；`recovery_b`、原 A 槽及 BL 解锁状态保持。公开验收状态见 [`config/images.json`](config/images.json)。完整镜像 SHA256 为：

```text
1802648d266119999979b91ae18b71d2a0566597eaf2cb190233a2f9d8e0cb9c
```

旧固件 `OS4.0.0.19` 的历史版本曾在 B 槽完成冷启动、解密、文件读写、中文、触控、手电筒、振动、亮度及安装/卸载回退。这些历史结果不作为新版通过记录。

本轮已实测卸载及双槽原厂 Recovery 回退，A 槽恢复 OS4.0.4.0、B 槽恢复其原有 OS4.0.0.19。卸载 Recovery 模块不会升级或回退 Android 系统，也不会同步两个槽的固件。另已实测 Boot/Recovery 的备份和恢复、MTP 文件发送/读回/删除，以及连续 100 条命令和已解密会话的界面重启。

`.4` 已通过真实菜单的 sideload 开始、取消、返回，以及受控 Recovery ZIP 的一次写入、完整读回和正常退出；MTP/ADB 均恢复，KSU 模块页可再次进入。最终镜像将 fastbootd 的 USB 开放移到原有启动请求清理之后，电脑在设备首次出现 0.077 秒后立即发送返回命令，也能正常回到 Recovery、解密并访问 CE 文件。各项测试对应的镜像与组件范围在固件文档中分别记录。

完整 userdata 备份恢复、刷 ROM/OTA 和 OTG 尚未完成验收。完整 OTA 会更新非当前槽及 UEFI 等固件，与本轮保留原槽和 UEFI 的约束不兼容，不能以模块安装或升级材料保留代替刷 ROM/OTA 实测。本版保留现有 FBE 密钥，不支持初始化新的加密 userdata。

## 从源码打包模块

模块打包只需 Python 3.11 或更新版本，使用标准库，不访问手机。将本版 OrangeFox 镜像与匹配的原厂 Recovery 放在本地后运行：

```sh
python3 tools/build_module.py \
  --orangefox /path/to/orangefox.img \
  --stock /path/to/stock-recovery.img \
  --output dist/OrangeFox-for-Dijun-OS4.0.4.0.zip
```

脚本核对两份 100 MiB 镜像的完整 SHA256，输出 ZIP 和 `.sha256`。发布 ZIP 中也包含这两份镜像，可直接提取后重新打包。重建 Recovery 的步骤、外部输入哈希及固定上游版本见 [`port/`](port/README.md)。

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s port/tests -v
```

宿主测试覆盖 A/B 选择、安装记录、重复安装、旧版升级、OTA 跨槽材料保留与分别回退、失败回退、错误固件/锁定状态拒绝写入及非本模块镜像保护，不替代真机验收。

## 许可证与来源

模块脚本及原创适配代码按 `GPL-3.0-or-later` 发布，详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。OrangeFox、Team Win、Android 及其他上游文件保留原有许可证和版权声明。

Recovery 采用固定版本的 OrangeFox 通用预编译用户空间，编译 O1 DRM 后端，再接入本机组件与明确记录的补丁。仓库公开模块、设备树、适配脚本、补丁和实际使用的上游源码片段；原厂 HAL、TA、固件和模块作为外部构建输入，保留各自原有权利，不改授本仓库许可证。本仓库由 Lw59 维护。
