#!/system/bin/sh
# 显示和触控由原启动入口加载；新增驱动独立初始化，错误保留在启动日志。
exec >>/tmp/dijun-hardware.log 2>&1
# 本机内核新增 firmware_load 权限；ramdisk 策略已补齐 kernel 对 vendor_file 的这一项。
# CPIO 新文件的初始标签与 ADB 推送不同，加载前固定为实测可用的标签。
chcon u:object_r:vendor_file:s0 /odm/firmware/cs40l26* || exit 1
failed=0
while IFS= read -r module; do
    name=${module%.ko}
    name=$(echo "$name" | tr '-' '_')
    [ -d "/sys/module/$name" ] && continue
    /system/bin/toybox insmod "/vendor/lib/modules/1.1/$module" || failed=1
done </vendor/lib/modules/1.1/modules.load.hardware
[ "$failed" = 0 ] || exit 1
setprop vendor.recovery.hardware_ready 1
setprop ctl.start vibratorfeature-hal-service
