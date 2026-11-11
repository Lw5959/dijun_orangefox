#!/system/bin/sh
# 安装选择当前启动槽，卸载使用安装记录；整个流程不切换启动槽，也不操作 GPT/BL。
. "$MODDIR/images.env"

fail() { echo "错误：$*" >&2; return 1; }
digest() {
    local result
    result=$(sha256sum "$1") || return 1
    echo "${result%% *}"
}
boot_value() {
    sed -n "s/^androidboot\.$1 = \"\([^\"]*\)\"$/\1/p" /proc/bootconfig
}
check_device() {
    [ "$(id -u)" = 0 ] || { fail "需要 KernelSU root 权限"; return 1; }
    [ "$(getprop ro.product.device)" = dijun ] || { fail "仅适用于小米 15S Pro（dijun）"; return 1; }
    [ "$(getprop ro.build.version.incremental)" = "$FIRMWARE" ] || { fail "固件不匹配，需要 $FIRMWARE"; return 1; }
    [ "$(boot_value hwproductname)" = dijun ] || { fail "启动信息中的机型不匹配"; return 1; }
    [ "$(boot_value 'vbmeta\.device_state')" = unlocked ] || { fail "Bootloader 必须已解锁"; return 1; }
}
slot_device() { echo "/dev/block/by-name/recovery$1"; }
installed_module_dir() { echo /data/adb/modules/dijun_orangefox; }
select_slot() {
    case "$1" in _a|_b) RECOVERY_SLOT=$1;; *) fail "无法识别恢复镜像的安装位置"; return 1;; esac
    RECOVERY_BLOCK=$(slot_device "$RECOVERY_SLOT")
}
select_current_slot() {
    local slot
    slot=$(boot_value slot_suffix)
    [ "$slot" = "$(getprop ro.boot.slot_suffix)" ] || { fail "启动信息不一致，停止安装"; return 1; }
    select_slot "$slot"
}
select_installed_slot() {
    [ -f "$MODDIR/installed-slot" ] || { fail "缺少安装记录，停止恢复"; return 1; }
    select_slot "$(cat "$MODDIR/installed-slot")"
}
check_partition() {
    test -b "$RECOVERY_BLOCK" || { fail "找不到对应的 Recovery 分区"; return 1; }
    [ "$(blockdev --getsize64 "$RECOVERY_BLOCK")" = "$IMAGE_BYTES" ] || { fail "Recovery 分区大小不匹配"; return 1; }
}
check_image() {
    [ "$(wc -c <"$1" | tr -d '[:space:]')" = "$IMAGE_BYTES" ] &&
        [ "$(digest "$1")" = "$2" ] || { fail "镜像长度或 SHA256 不匹配：${1##*/}"; return 1; }
}
write_image() {
    # 同步写入后读取整个分区核对；dd 成功本身不作为刷写成功证据。
    dd if="$1" of="$RECOVERY_BLOCK" bs=4096 conv=fsync || return 1
    [ "$(digest "$RECOVERY_BLOCK")" = "$2" ]
}
install_recovery() {
    check_device && select_current_slot && check_partition || return 1
    check_image "$MODDIR/orangefox.img" "$FOX_SHA256" &&
        check_image "$MODDIR/stock-recovery.img" "$STOCK_SHA256" || return 1
    local current previous previous_dir rollback_image rollback_sha rollback_name old_sha old_stock
    current=$(digest "$RECOVERY_BLOCK") || return 1
    previous_dir=$(installed_module_dir)
    # 升级时保留原安装位置；换槽后的新安装须先完成旧安装的回退，避免遗留未管理的镜像。
    for previous in "$MODDIR/installed-slot" "$previous_dir/installed-slot"; do
        if [ -f "$previous" ] && [ "$(cat "$previous")" != "$RECOVERY_SLOT" ]; then
            fail "系统启动位置已变化，请先卸载旧模块再安装"; return 1
        fi
    done
    if [ "$current" = "$FOX_SHA256" ]; then
        [ -f "$MODDIR/installed-slot" ] || { [ -f "$previous" ] && cp "$previous" "$MODDIR/installed-slot"; } || {
            fail "缺少原安装记录，无法确认回退位置"; return 1;
        }
        [ "$(cat "$MODDIR/installed-slot")" = "$RECOVERY_SLOT" ] || return 1
        echo "当前已是本包 OrangeFox，无需重复写入。"; return 0
    fi
    rollback_image="$MODDIR/stock-recovery.img"
    rollback_sha=$STOCK_SHA256
    rollback_name="原厂 Recovery"
    if [ "$current" != "$STOCK_SHA256" ]; then
        # 升级只能覆盖有同槽安装记录、且旧包实体镜像与分区一致的已安装版本。
        # 不执行旧 images.env；只读取哈希，避免升级时替换本包的设备检查参数。
        [ -f "$previous_dir/installed-slot" ] &&
            [ "$(cat "$previous_dir/installed-slot")" = "$RECOVERY_SLOT" ] || {
                fail "当前 Recovery 缺少匹配的旧模块安装记录，保留现状"; return 1;
            }
        old_sha=$(sed -n 's/^FOX_SHA256=\([0-9a-f]*\)$/\1/p' "$previous_dir/images.env")
        old_stock=$(sed -n 's/^STOCK_SHA256=\([0-9a-f]*\)$/\1/p' "$previous_dir/images.env")
        [ "$old_stock" = "$STOCK_SHA256" ] && [ "$old_sha" = "$current" ] &&
            check_image "$previous_dir/orangefox.img" "$old_sha" || {
                fail "当前 Recovery 与已安装模块不一致，保留现状"; return 1;
            }
        rollback_image="$previous_dir/orangefox.img"
        rollback_sha=$old_sha
        rollback_name="此前 OrangeFox"
    fi
    printf '%s\n' "$RECOVERY_SLOT" >"$MODDIR/installed-slot" || return 1
    if write_image "$MODDIR/orangefox.img" "$FOX_SHA256"; then
        echo "OrangeFox 已写入并回读核对。"
        return 0
    fi
    # 首装回原厂，升级回旧版；回退对象必须与本次写入前的分区内容完全相同。
    echo "OrangeFox 写入未通过，正在恢复${rollback_name}。" >&2
    if write_image "$rollback_image" "$rollback_sha"; then
        fail "安装失败，${rollback_name} 已恢复"
    else
        fail "写入及回退均失败；请按 installed-slot 记录通过 Fastboot 恢复包内 stock-recovery.img"
    fi
    return 1
}
restore_recovery() {
    check_device && select_installed_slot && check_partition || return 1
    local current
    current=$(digest "$RECOVERY_BLOCK") || return 1
    [ "$current" = "$STOCK_SHA256" ] && { echo "当前已是原厂 Recovery。"; return 0; }
    [ "$current" = "$FOX_SHA256" ] || { fail "当前 Recovery 已变化，保留现有镜像"; return 1; }
    check_image "$MODDIR/stock-recovery.img" "$STOCK_SHA256" || return 1
    write_image "$MODDIR/stock-recovery.img" "$STOCK_SHA256" || { fail "原厂回退未通过，请从 ZIP 取出原厂镜像经 Fastboot 恢复"; return 1; }
    echo "原厂 Recovery 已恢复并回读核对。"
}
