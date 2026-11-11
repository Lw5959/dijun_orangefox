#!/system/bin/sh
# O1 原厂 xr_isp 的 sysfs 协议，见 docs/recovery-hardware-adaptation.md。
# power 是引用计数；只在关闭 -> 开启时取得一次，关闭时归还一次。
base=/sys/devices/platform/soc/soc:xrisp_cdm/xrisp_flash
state=vendor.recovery.torch_on
fail() { echo "手电筒操作失败：$*" >&2; return 1; }
off() {
    echo '1 0 2 0' >"$base/xrisp_flash_torch_en" || return 1
    echo 0 >"$base/xrisp_flash_power" || return 1
    setprop "$state" 0
}
case "$1" in
    toggle)
        [ -w "$base/xrisp_flash_power" ] || { fail '原厂闪光灯驱动未就绪'; exit 1; }
        if [ "$(getprop "$state")" = 1 ]; then
            off || { fail '无法关闭'; exit 1; }
        else
            echo 1 >"$base/xrisp_flash_power" || { fail '无法上电'; exit 1; }
            # 原厂 torch 电流单位为 mA，合法范围 1..500；恢复环境使用每路 50mA。
            if ! echo 50 >"$base/xrisp_flash_torch_curr" ||
               ! echo '1 1 2 1' >"$base/xrisp_flash_torch_en"; then
                off
                fail '无法点亮'; exit 1
            fi
            setprop "$state" 1
        fi;;
    off) [ "$(getprop "$state")" != 1 ] || off;;
    *) fail '参数必须为 toggle 或 off'; exit 1;;
esac
