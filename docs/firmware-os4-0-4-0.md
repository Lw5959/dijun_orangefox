# OS4.0.4.0.XODCNXM 适配

本版使用本地 dijun 完整 OTA 的原厂输入，已完成电脑端构建、静态核验，以及 OS4.0.4.0 真机 A 槽的安装、冷启动、解密和 Android 往返验收。

## 固件差异

- Android 17，system SPL `2026-10-01`；vendor SPL `2026-09-01`。
- system 内部构建号：`17OS4.0.261106.161950561.XRPECN.S`；vendor：`OS4.0.3.1.XODCN`。
- 现有启动链的内核更新为 `6.18.21-android17-5-g284297031c53-abogki553682993-4k`。Recovery 仍是 v4 ramdisk-only 镜像，安装模块不写 boot、init_boot 或 vendor_boot。
- 114 项构建依赖中 10 项变化：`tee-supplicant`、`os_cpu_vip_sched.ko`、`xr_ddr.ko`、`drm_display_helper.ko`、`xring_smmu.ko`、`mitee.ko`、`xr_mem_s1.ko`、`xr_pmic.ko`、`xring-drm.ko`、`synaptics_tcm2.ko`。

## 固定原件与产物

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| 新版原厂 Recovery | 104857600 | `6b09247cea7869b66b383009a28b77160c42afb0be90d6c143eca2d7c253b629` |
| 新版原厂 vendor_boot | 100663296 | `ef9bd5838e3a672a02e280ee7279b0ef31b2f5031838e23ce036cc0ccb5e7eaf` |
| OTA 内核 Image | 42940928 | `1a971c836ff10b7f237adb01e2a0e30bfe72e43fb4fe7f460e7a9ad8067c267d` |
| OrangeFox 发布镜像 | 104857600 | `4f3caf55bc27d7311c58fa1361c54e8056335bb55db4bac281a8ca8940915fd5` |

Recovery 与 vendor_boot 已按 OTA payload 的完整分区 SHA256 核对。vendor、odm、vendor_dlkm 与 system 只解码所需 extent；每个读取的 payload 操作均核对摘要，没有将局部提取描述为整分区重新计算通过。114 项原厂文件的大小与 SHA256 固定在 `port/config/proprietary-files.json`。

## OTA 后的模块迁移

旧模块在 OTA 换槽后可能仍记录原槽；旧卸载脚本也会因 Android 固件版本变化拒绝回退。本版在当前槽为新版原厂 Recovery 时接受跨槽升级，核对并保存旧模块的原厂镜像与安装记录，然后只写当前 Recovery。卸载按两个槽各自记录恢复。当前槽与原件不匹配、旧材料损坏或记录无效时拒绝安装；恢复时保留已被 OTA 或其他工具替换的分区。

回退不再要求当前 Android 版本等于安装固件。机型、解锁状态、分区大小、安装位置和完整镜像哈希仍须匹配。安装和模块操作入口继续严格要求 `OS4.0.4.0.XODCNXM`。

## 静态核验与设备边界

- 21 项模块流程宿主测试通过，包括跨槽 OTA 升级、各自版本回退、旧材料损坏、已变化的 Recovery 保护及写入失败回退。
- 3 项参数与 linker 测试通过；参数测试实际执行 shell 入口，在宿主使用挂载与属性命令替身。
- 17 项 AArch64 密钥策略分支检查通过；外部文件与密码学调用仍是测试桩。
- 从 OTA 内核恢复的 ELF 中 `.kernel` 与原始 Image 完全一致；9177 个内核导出与 51 个配套模块完成 4514 项符号 CRC 及模块加载顺序核对，无失败。
- 最终镜像的 ELF/init 依赖核验通过；构建使用新版原厂 AVB fingerprint 与 rollback 参数。

## 真机验收

2026-11-11 在 `OS4.0.4.0.XODCNXM` 真机 A 槽完成：

- 通过 KernelSU 安装发布镜像，完整回读 SHA256 一致；B 槽原有 OrangeFox 未改变，旧版原厂回退镜像与 `_b` 安装记录保留成功。
- 正常重启 Android，模块激活，再通过模块“操作”入口冷启动 Recovery。
- 真实凭据解密成功，`tw_is_decrypted=1`；Android 自建 CE 测试文件在 Recovery 读回一致，追加内容并同步，返回 Android 后再次读回一致，测试文件已删除。
- 用户确认“所有功能正常”，本轮记录范围为常用界面与显示/触控、振动、手电筒和亮度。现场为中文，亮度百分比 42、界面值与节点值同为 6880，最大值 16383；CPU 温度读数 37°C。
- 返回 Android 后，4 个磁盘的 28 份 GPT 主备及保留区文件逐字节相同，38 个启动相关分区仅 `recovery_a` 发生预期变化。当前仍为 A 槽、BL 解锁，Android 启动完成且用户存储已解锁，新模块保留。

`config/images.json` 已按上述实测回填。卸载时的双槽完整回退尚未重新实测；完整备份恢复、刷 ROM/OTA、fastbootd、OTG 和 MTP 文件传输仍未验收。用户的功能确认不扩展到这些未执行项目。原 `OS4.0.0.19` 发布版的结果归属于历史版本。
