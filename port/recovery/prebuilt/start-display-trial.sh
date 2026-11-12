#!/system/bin/sh
# 原厂内核和 vendor_boot 已加载早期依赖；这里只补齐本机显示/触控闭包。
# ADB 由 init 独立启动，模块失败时保留诊断通道，不假报加载成功。
exec >>/tmp/dijun-startup.log 2>&1
echo 'dijun OrangeFox display trial: no data or metadata mount'
while IFS= read -r module; do
    name=${module%.ko}
    name=$(echo "$name" | tr '-' '_')
    [ -d "/sys/module/$name" ] && continue
    /system/bin/toybox insmod "/vendor/lib/modules/1.1/$module" || exit 1
done </vendor/lib/modules/1.1/modules.load
setprop twrp.modules.loaded true
echo 4096 >/sys/class/backlight/panel0-backlight/brightness
# open_drm 和 vibrate 均经 PLT：替换 O1 显示后端，并确保每次震动按时停止。
# 保留原 GUI/输入与用户反馈设置，不通过禁用震动掩盖原厂 HAL 的定时问题。
export LD_PRELOAD=/system/lib64/libdijun_drm.so
exec /system/bin/recovery
