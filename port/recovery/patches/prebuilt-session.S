// 固定 infiniti R12.0_2 ELF 的会话修复，代码放入原 RX 段后的零填充。
// 所有目标由链接器 --defsym 提供，均是镜像内相对调用，兼容运行时 ASLR。
.text
.global dijun_fastboot_ready
dijun_fastboot_ready:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    // startupArgs 原本先开放 USB fastbootd，主流程稍后才清理 --fastboot
    // 启动请求；电脑立即 reboot recovery 会再次读到该请求并重进 fastbootd。
    // 沿用主流程现有 BCB 清理，在它完成且 GUI 初始化后才开放服务。
    adr x0, usb_config_cpp
    adr x1, usb_fastboot_cpp
    bl recovery_set_property_cpp
    ldp x29, x30, [sp], #16
    ldr x3, [x27]
    b fastboot_ready_continue

.balign 16
.global dijun_cli_gate
dijun_cli_gate:
    // 只在普通命令分支拒绝已有动作；xset/changepage 等同步分支继续可用。
    // GUI 的 cmd 动作会等待子进程 twrp xset，不能在 FIFO 读取前阻挡它。
    adrp x8, action_running
    add x8, x8, :lo12:action_running
    ldarb w8, [x8]
    cbnz w8, cli_busy_reply
    adrp x8, ors_output
    b cli_submit

.balign 16
.global dijun_defer_cli_done
dijun_defer_cli_done:
    // 此时命令已执行，但 operation_end 和返回原页面尚未结束。
    // 先标记，等动作列表结束后再关闭输出；下一条命令才不会抢先到达。
    adrp x8, pending_cli_done
    add x8, x8, :lo12:pending_cli_done
    mov w9, #1
    strb w9, [x8]
    ret

.balign 16
.global dijun_finish_action
dijun_finish_action:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl recovery_delete
    // cancel_thread 退出时不能替仍在运行的正常动作关闭 FIFO。
    adrp x8, action_running
    add x8, x8, :lo12:action_running
    sub x8, x8, #8
    cmp x24, x8
    b.ne finish_return
    adrp x8, pending_cli_done
    add x8, x8, :lo12:pending_cli_done
    ldrb w9, [x8]
    cbz w9, finish_return
    strb wzr, [x8]
    bl recovery_ors_done
finish_return:
    ldp x29, x30, [sp], #16
    ret

.balign 16
.global dijun_close_cli_output
dijun_close_cli_output:
    // 原完成回调先恢复监听，最后才发出 EOF；客户端收到完成时服务端已就绪。
    // x20 保留原 ors_command_done 的 TLS；x19 已被原函数复用为 page_done。
    adrp x9, ors_output
    add x9, x9, :lo12:ors_output
    ldr x0, [x9]
    str xzr, [x9]
    bl recovery_fclose
    ldr x8, [x20, #0x28]
    b cli_done_canary

.balign 16
.global dijun_mtp_forkserver
dijun_mtp_forkserver:
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    stp x19, x20, [sp, #16]
    mov x19, x0
    mov x20, x1
    // forkserver 不执行 exec，CLOEXEC 无法阻止 MTP 继承 ORS 输出。
    // 将本次输出 fd 交给配套 MTP 补丁，只在 fork 的子进程中关闭。
    adrp x8, ors_output
    add x8, x8, :lo12:ors_output
    ldr x0, [x8]
    cbz x0, mtp_no_cli_output
    bl recovery_fileno
    mov w2, w0
    b mtp_fork
mtp_no_cli_output:
    mov w2, #-1
mtp_fork:
    mov x0, x19
    mov x1, x20
    bl recovery_mtp_forkserver
    ldp x19, x20, [sp, #16]
    ldp x29, x30, [sp], #32
    ret

.balign 16
.global dijun_disable_mtp_done
dijun_disable_mtp_done:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl recovery_property_set
    // Disable_MTP 只发布 adb 请求就返回，紧接的 sideload 会读到旧状态，
    // 还可能让迟到的 start adbd 与 minadbd 同时占用 FFS。先等本轮切换完成。
    adr x0, usb_state_cpp
    adr x1, usb_adb_cpp
    mov x2, #5000
    bl recovery_wait_property
    // 此处原函数已不再使用 x20，最终返回前仍从原栈恢复调用者的 x20。
    mov w20, w0
    ldp x29, x30, [sp], #16
    ret

.balign 16
.global dijun_sideload_begin
dijun_sideload_begin:
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    stp x0, x1, [sp, #16]
    adrp x8, sideload_phase
    add x8, x8, :lo12:sideload_phase
    stlr wzr, [x8]
    mov w1, wzr
    bl sideload_cancel_button
    ldp x0, x1, [sp, #16]
    ldp x29, x30, [sp], #32
    // 执行被替换的原函数序言，保留完整栈布局及原调用者返回地址。
    stp x29, x30, [sp, #-96]!
    b sideload_begin_continue

.balign 16
.global dijun_sideload_ready
dijun_sideload_ready:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    adrp x8, sideload_phase
    add x8, x8, :lo12:sideload_phase
    mov w9, #1
    stlr w9, [x8]
    mov w1, #1
    bl sideload_cancel_button
    ldp x29, x30, [sp], #16
    mov w0, #8
    b sideload_ready_continue

.balign 16
.global dijun_sideload_finished
dijun_sideload_finished:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    adrp x8, sideload_phase
    add x8, x8, :lo12:sideload_phase
    stlr wzr, [x8]
    mov w1, wzr
    bl sideload_cancel_button
    ldp x29, x30, [sp], #16
    mov w0, #13
    b sideload_finish_continue

.balign 16
.global dijun_sideload_cancel
dijun_sideload_cancel:
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    str x19, [sp, #16]
    adrp x8, sideload_phase
    add x8, x8, :lo12:sideload_phase
cancel_claim:
    // 与开始安装互斥：仅等待传输阶段可以取消，不能中断正在写入的包。
    ldaxr w9, [x8]
    cmp w9, #1
    b.ne cancel_not_waiting
    mov w10, #3
    stlxr w11, w10, [x8]
    cbnz w11, cancel_claim
    adrp x9, minadbd_child
    add x9, x9, :lo12:minadbd_child
    ldr w19, [x9]
    cmp w19, #0
    b.le cancel_return
    // 先解绑 FFS，使子进程的 USB 请求可以退出；界面只发信号，不做
    // stat(FUSE exit)、sleep 或 waitpid，不提前结束页面。回收由原后台线程完成。
    adr x0, usb_config_name
    adr x1, usb_none
    bl recovery_property_set
    mov w0, w19
    mov w1, #15
    bl recovery_kill
    b cancel_return
cancel_not_waiting:
    clrex
cancel_return:
    ldr x19, [sp, #16]
    ldp x29, x30, [sp], #32
    ret

.balign 16
.global dijun_sideload_install
dijun_sideload_install:
    stp x29, x30, [sp, #-48]!
    mov x29, sp
    stp x0, x1, [sp, #16]
    str x2, [sp, #32]
    adrp x8, sideload_phase
    add x8, x8, :lo12:sideload_phase
install_claim:
    ldaxr w9, [x8]
    cmp w9, #1
    b.ne install_cancelled
    mov w10, #2
    stlxr w11, w10, [x8]
    cbnz w11, install_claim
    mov w1, wzr
    bl sideload_cancel_button
    ldp x0, x1, [sp, #16]
    ldr x2, [sp, #32]
    bl recovery_install_zip
    b install_return
install_cancelled:
    clrex
    mov w0, #1
install_return:
    ldp x29, x30, [sp], #48
    ret

sideload_cancel_button:
    adr x0, cancel_button_cpp
    mov w2, wzr
    b recovery_set_integer

.balign 8
usb_state_cpp:
    .byte 26
    .asciz "sys.usb.state"
    .zero 9
usb_adb_cpp:
    .byte 6
    .asciz "adb"
    .zero 19
cancel_button_cpp:
    .byte 26
    .asciz "tw_has_cancel"
    .zero 9
usb_config_cpp:
    .byte 28
    .asciz "sys.usb.config"
    .zero 8
usb_fastboot_cpp:
    .byte 16
    .asciz "fastboot"
    .zero 14
usb_config_name:
    .asciz "sys.usb.config"
usb_none:
    .asciz "none"

.balign 16
.global dijun_ors_sideload
dijun_ors_sideload:
    stp x29, x30, [sp, #-48]!
    mov x29, sp
    stp x19, x20, [sp, #16]
    stp x21, x22, [sp, #32]
    mov x19, x0
    mov x20, x1
    // 沿用 GUI sideload 的 MTP 生命周期。否则 ConfigFS 清空 ready 后，
    // 旧 MTP 进程不会重新发布描述符，USB 模式恢复会一直等待。
    mov w0, wzr
    bl recovery_toggle_mtp
    mov w21, w0
    mov x0, x19
    mov x1, x20
    bl recovery_sideload
    mov w22, w0
    mov w0, w21
    bl recovery_toggle_mtp
    mov w0, w22
    ldp x21, x22, [sp, #32]
    ldp x19, x20, [sp, #16]
    ldp x29, x30, [sp], #48
    ret

.balign 16
.global dijun_ors_sideload_result
dijun_ors_sideload_result:
    cbz w0, sideload_success
    b ors_sideload_error
sideload_success:
    // twrp_sideload 的安装回调已经刷入过 ZIP，不能在 FUSE 关闭后再次安装。
    mov w26, wzr
    b ors_sideload_finished

.balign 16
.global dijun_restore_users
dijun_restore_users:
    stp x29, x30, [sp, #-144]!
    mov x29, sp
    stp x19, x20, [sp, #16]
    // x19 是原 Setup_Data_Partition 的 this，x0 是待写的 tw_is_encrypted。
    mov x20, x0
    adr x0, user_decrypt_property
    add x1, sp, #48
    adr x2, unknown_property
    bl recovery_property_get
    ldrh w8, [sp, #48]
    cmp w8, #0x31
    b.ne initialize_de
    // 同一次内核启动中 CE 已解锁：只重建用户列表，不重新装载或整理密钥。
    adrp x0, partition_manager_got
    ldr x0, [x0, :lo12:partition_manager_got]
    bl recovery_get_users
    ldp x8, x9, [x0]
    cmp x8, x9
    b.ne update_encrypted
    adrp x0, partition_manager_got
    ldr x0, [x0, :lo12:partition_manager_got]
    bl recovery_parse_users
    b update_encrypted
initialize_de:
    // 只有 metadata 映射不足以证明 CE 解锁；仍执行原有 DE 初始化与凭据流程。
    mov x0, x19
    bl recovery_decrypt_fbe_de
    b update_encrypted

.balign 16
.global dijun_sync_encrypted
dijun_sync_encrypted:
    stp x29, x30, [sp, #-144]!
    mov x29, sp
    stp x19, x20, [sp, #16]
    mov x20, x0
    // Process_Fstab 末尾原来无条件写回 encrypted=1，会覆盖前面恢复的结果。
update_encrypted:
    adr x0, user_decrypt_property
    add x1, sp, #48
    adr x2, unknown_property
    bl recovery_property_get
    ldrh w8, [sp, #48]
    cmp w8, #0x31
    cset w1, ne
    mov x0, x20
    mov w2, wzr
    bl recovery_set_integer
    ldp x19, x20, [sp, #16]
    ldp x29, x30, [sp], #144
    ret
user_decrypt_property:
    .asciz "twrp.user.0.decrypt"
unknown_property:
    .asciz "-1"
