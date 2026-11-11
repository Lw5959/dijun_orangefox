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
    [ "$(boot_value hwproductname)" = dijun ] || { fail "启动信息中的机型不匹配"; return 1; }
    [ "$(boot_value 'vbmeta\.device_state')" = unlocked ] || { fail "Bootloader 必须已解锁"; return 1; }
}
check_firmware() {
    [ "$(getprop ro.build.version.incremental)" = "$FIRMWARE" ] || { fail "固件不匹配，需要 $FIRMWARE"; return 1; }
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
preserve_previous_slot() {
    local source previous_slot old_sha old_stock destination
    source=$1
    previous_slot=$(cat "$source/installed-slot") || return 1
    case "$previous_slot" in _a|_b) ;; *) fail "旧安装位置无效，停止升级"; return 1;; esac
    [ "$previous_slot" != "$RECOVERY_SLOT" ] || { fail "旧回退记录与当前安装位置冲突"; return 1; }
    # OTA 后原槽可能仍保留旧 OrangeFox；只保存其回退材料，不在安装时写另一个槽。
    # 不执行旧脚本或 images.env，以免旧固件条件覆盖本包的检查参数。
    old_sha=$(sed -n 's/^FOX_SHA256=\([0-9a-f]*\)$/\1/p' "$source/images.env")
    old_stock=$(sed -n 's/^STOCK_SHA256=\([0-9a-f]*\)$/\1/p' "$source/images.env")
    [ "${#old_sha}" = 64 ] && check_image "$source/stock-recovery.img" "$old_stock" || {
        fail "旧槽回退材料不完整，保留旧模块后再处理"; return 1;
    }
    if [ -f "$source/orangefox.img" ]; then
        check_image "$source/orangefox.img" "$old_sha" || return 1
    fi
    destination="$MODDIR/previous-slot"
    [ "$source" != "$destination" ] || return 0
    mkdir -p "$destination" && cp "$source/stock-recovery.img" "$destination/stock-recovery.img" &&
        check_image "$destination/stock-recovery.img" "$old_stock" || return 1
    printf '%s\n' "$previous_slot" >"$destination/installed-slot" || return 1
    printf 'FOX_SHA256=%s\nSTOCK_SHA256=%s\n' "$old_sha" "$old_stock" >"$destination/images.env" || return 1
    echo "已保留 $previous_slot 槽的原版本回退材料，卸载时按各槽记录恢复。"
}
install_recovery() {
    check_device && check_firmware && select_current_slot && check_partition || return 1
    check_image "$MODDIR/orangefox.img" "$FOX_SHA256" &&
        check_image "$MODDIR/stock-recovery.img" "$STOCK_SHA256" || return 1
    local current previous previous_dir rollback_image rollback_sha rollback_name old_sha old_stock
    current=$(digest "$RECOVERY_BLOCK") || return 1
    previous_dir=$(installed_module_dir)
    previous="$previous_dir/installed-slot"
    if [ -f "$MODDIR/installed-slot" ] && [ "$(cat "$MODDIR/installed-slot")" != "$RECOVERY_SLOT" ]; then
        fail "本包安装记录与当前启动位置不一致"; return 1
    fi
    if [ -f "$previous" ] && [ "$(cat "$previous")" != "$RECOVERY_SLOT" ]; then
        # OTA 后首次安装要求新版原厂 Recovery；重复安装须已有本包同槽记录。
        [ "$current" = "$STOCK_SHA256" ] || {
            [ "$current" = "$FOX_SHA256" ] && [ -f "$MODDIR/installed-slot" ];
        } || { fail "OTA 后当前 Recovery 缺少匹配的原厂镜像或本包安装记录"; return 1; }
        preserve_previous_slot "$previous_dir" || return 1
    elif [ -d "$previous_dir/previous-slot" ]; then
        preserve_previous_slot "$previous_dir/previous-slot" || return 1
    fi
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
restore_record() {
    local source current fox_sha stock_sha
    source=$1
    [ -f "$source/installed-slot" ] || { fail "缺少安装记录，停止恢复"; return 1; }
    select_slot "$(cat "$source/installed-slot")" && check_partition || return 1
    fox_sha=$(sed -n 's/^FOX_SHA256=\([0-9a-f]*\)$/\1/p' "$source/images.env")
    stock_sha=$(sed -n 's/^STOCK_SHA256=\([0-9a-f]*\)$/\1/p' "$source/images.env")
    current=$(digest "$RECOVERY_BLOCK") || return 1
    [ "$current" = "$stock_sha" ] && { echo "$RECOVERY_SLOT 槽已是原厂 Recovery。"; return 0; }
    [ "$current" = "$fox_sha" ] || { fail "$RECOVERY_SLOT 槽 Recovery 已变化，保留现有镜像及回退记录"; return 1; }
    check_image "$source/stock-recovery.img" "$stock_sha" || return 1
    write_image "$source/stock-recovery.img" "$stock_sha" || { fail "$RECOVERY_SLOT 槽原厂回退未通过，请保留对应回退镜像经 Fastboot 恢复"; return 1; }
    echo "$RECOVERY_SLOT 槽原厂 Recovery 已恢复并回读核对。"
}
restore_recovery() {
    # OTA 会改变当前固件，但不会改变记录所指的分区；回退依靠完整镜像哈希确认归属。
    check_device || return 1
    local status
    status=0
    restore_record "$MODDIR" || status=1
    if [ -d "$MODDIR/previous-slot" ]; then
        restore_record "$MODDIR/previous-slot" || status=1
    fi
    return "$status"
}
