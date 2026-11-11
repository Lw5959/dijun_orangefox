#!/system/bin/sh
# 从已安装系统的 EROFS 镜像读取 KeyMint 参数；不使用 donor 的版本或预置 configured 状态。
# 本入口匹配 OS4.0.0.19 的 system/vendor 布局，不调用任何安全 HAL。
exec >>/tmp/dijun-crypto-params.log 2>&1
setprop twrp.crypto.boot_params.ready false
system_mounted=0
vendor_mounted=0
base=/mnt/dijun-crypto-params

cleanup() {
    [ "$vendor_mounted" = 0 ] || umount "$base/vendor"
    [ "$system_mounted" = 0 ] || umount "$base/system"
}
trap cleanup EXIT

slot=$(getprop ro.boot.slot_suffix)
case "$slot" in _a|_b) ;; *) echo '无法读取实际槽位'; exit 1 ;; esac
system_block=/dev/block/mapper/system$slot
vendor_block=/dev/block/mapper/vendor$slot

# OrangeFox 在 Process_Fstab 开始时建立逻辑分区；与主进程并行等待该真实结果。
count=0
while [ ! -b "$system_block" ] || [ ! -b "$vendor_block" ]; do
    [ "$count" -lt 40 ] || { echo 'system/vendor 逻辑分区未就绪'; exit 1; }
    sleep 0.5
    count=$((count + 1))
done
mkdir -p "$base/system" "$base/vendor" || exit 1
mount -t erofs -o ro "$system_block" "$base/system" || exit 1
system_mounted=1
mount -t erofs -o ro "$vendor_block" "$base/vendor" || exit 1
vendor_mounted=1

release=$(sed -n 's/^ro.build.version.release=//p' "$base/system/system/build.prop")
patch=$(sed -n 's/^ro.build.version.security_patch=//p' "$base/system/system/build.prop")
vendor_patch=$(sed -n 's/^ro.vendor.build.security_patch=//p' "$base/vendor/build.prop")
# 此镜像和原厂模块固定匹配 OS4.0.0.19。若读到旧快照或其他固件，停止而不配置 TEE。
if [ "$release" != 17 ] || [ "$patch" != 2026-09-01 ] || [ "$vendor_patch" != 2026-09-01 ]; then
    echo '原系统参数与本候选匹配的 OS4.0.0.19 不一致'
    exit 1
fi

# 私有只读挂载点不会遮住 ramdisk 的 /vendor 库；先卸载，再允许服务读取新属性。
umount "$base/vendor" || exit 1
vendor_mounted=0
umount "$base/system" || exit 1
system_mounted=0
resetprop ro.build.version.release "$release" || exit 1
resetprop ro.build.version.security_patch "$patch" || exit 1
resetprop ro.vendor.build.security_patch "$vendor_patch" || exit 1
[ "$(getprop ro.build.version.release)" = "$release" ] || exit 1
[ "$(getprop ro.build.version.security_patch)" = "$patch" ] || exit 1
[ "$(getprop ro.vendor.build.security_patch)" = "$vendor_patch" ] || exit 1
# O1 Configure 还携带五个产品字段。它们是本专用机型的现场身份，不能使用 donor 名称；
# system/vendor 镜像分别写着通用 missi/mivendor，也不能把这些通用占位值送给本机 TEE。
for pair in brand=Xiaomi manufacturer=Xiaomi name=dijun model=25042PN24C device=dijun; do
    key=ro.product.${pair%%=*}
    value=${pair#*=}
    resetprop "$key" "$value" || exit 1
    [ "$(getprop "$key")" = "$value" ] || exit 1
done
echo "原系统参数读取完成：Android $release / SPL $patch / vendor SPL $vendor_patch"
setprop twrp.crypto.boot_params.ready true
