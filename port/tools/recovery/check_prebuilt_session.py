#!/usr/bin/env python3
"""执行真实 ARM64 会话补丁分支；外部用户枚举与 DE 接口采用测试桩。"""

import json
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X8, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X24, UC_ARM64_REG_X27, UC_ARM64_REG_SP

from check_prebuilt_key_policy import execute
from patch_prebuilt_session import ROOT, SYMBOLS, patch_mtp, patch_session
from patch_prebuilt_hardware import patch_hardware
from preserve_prebuilt_keys import preserve_existing_keys


def main():
    donor = ROOT / "build/recovery/donors/infiniti-r12.0_2/ramdisk-00/root/system/bin/recovery"
    data, _ = preserve_existing_keys(donor.read_bytes())
    data, _ = patch_hardware(data)
    patched, policy = patch_session(data)
    cases = []
    assert patched[0x171CC8:0x171CCC] == bytes.fromhex("1f2003d5")
    cases.append({"case": "no-fastboot-usb-before-boot-message-cleanup", "early_publication_removed": True})
    for fastboot_mode in (False, True):
        values = []
        def setup_fastboot_ready(cpu):
            cpu.mem_write(0x1000200, (0x1000300).to_bytes(8, "little"))
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_set_property_cpp"]:
                    key = bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X0), 24))
                    value = bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X1), 24))
                    assert key.startswith(b"\x1csys.usb.config\0")
                    assert value.startswith(b"\x10fastboot\0")
                    values.append("fastboot")
                if address == 0x110FE4:
                    assert engine.reg_read(UC_ARM64_REG_X3) == 0x1000300
            cpu.hook_add(UC_HOOK_CODE, observe)
        _, pc, calls = execute(patched, 0x110FC0, {UC_ARM64_REG_X27: 0x1000200},
                                {SYMBOLS["recovery_clear_boot_message"]: ("clear-existing-boot-request", 0),
                                 SYMBOLS["recovery_get_fastboot_mode"]: ("read-startup-mode", fastboot_mode),
                                 SYMBOLS["recovery_set_property_cpp"]: ("publish-fastboot-usb", 1)},
                                stops=(0x111130, 0x110FE4), setup=setup_fastboot_ready)
        assert calls == ["clear-existing-boot-request", "read-startup-mode"] + (["publish-fastboot-usb"] if fastboot_mode else [])
        assert pc == (0x110FE4 if fastboot_mode else 0x111130)
        assert values == (["fastboot"] if fastboot_mode else [])
        cases.append({"case": "fastboot-visible-after-original-boot-request-cleanup", "fastboot_mode": fastboot_mode, "calls": calls})
    # FIFO 读取和 xset 分支保持原样；门控仅位于普通命令的提交分支。
    assert patched[0x2CB2D8:0x2CB2DC] == data[0x2CB2D8:0x2CB2DC]
    for running in (False, True):
        _, pc, calls = execute(patched, 0x2CB51C, {}, {},
                               stops=(SYMBOLS["cli_submit"], SYMBOLS["cli_busy_reply"]),
                               setup=lambda cpu: cpu.mem_write(SYMBOLS["action_running"], bytes([running])))
        assert pc == (SYMBOLS["cli_busy_reply"] if running else SYMBOLS["cli_submit"])
        assert not calls
        cases.append({"case": "cli-dispatch", "action_running": running,
                      "accepted": pc == SYMBOLS["cli_submit"]})

    pending_address = SYMBOLS["pending_cli_done"]
    observed = []

    def observe_mark(cpu):
        from check_prebuilt_key_policy import END
        cpu.hook_add(UC_HOOK_CODE, lambda c, address, size, _: observed.append(bytes(c.mem_read(pending_address, 1))) if address == END else None)

    execute(patched, policy["symbols"]["dijun_defer_cli_done"], {}, {}, setup=observe_mark)
    assert observed == [b"\1"]
    cases.append({"case": "defer-reply-until-thread-exit", "pending": True})

    for normal_thread, pending in ((True, False), (True, True), (False, True)):
        def setup_finish(cpu):
            cpu.mem_write(pending_address, bytes([pending]))
        _, _, calls = execute(patched, policy["symbols"]["dijun_finish_action"],
                               {UC_ARM64_REG_X0: 0x1000000,
                                UC_ARM64_REG_X24: 0x39AF80 if normal_thread else 0x39AFB8},
                               {SYMBOLS["recovery_delete"]: ("delete-thread-data", 0),
                                SYMBOLS["recovery_ors_done"]: ("close-cli-and-reset-fifo", 0)}, setup=setup_finish)
        assert calls == ["delete-thread-data"] + (["close-cli-and-reset-fifo"] if normal_thread and pending else [])
        cases.append({"case": "finish-cli-reply", "normal_thread": normal_thread, "pending": pending, "calls": calls})

    for page_done in (0, 1):
        closed_outputs = []

        def setup_close(cpu):
            cpu.mem_write(SYMBOLS["ors_output"], (0x1000000).to_bytes(8, "little"))
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_fclose"]:
                    assert int.from_bytes(engine.mem_read(SYMBOLS["ors_output"], 8), "little") == 0
                    closed_outputs.append(engine.reg_read(UC_ARM64_REG_X0))
            cpu.hook_add(UC_HOOK_CODE, observe)

        _, _, calls = execute(patched, SYMBOLS["recovery_ors_done"], {},
                               {0x128F94: ("read-page-done", page_done),
                                0x379620: ("close-old-input", 0),
                                0x2CC27C: ("reset-command-listener", 0),
                                SYMBOLS["recovery_fclose"]: ("close-cli-output", 0)}, setup=setup_close)
        assert closed_outputs == [0x1000000]
        assert calls == ["read-page-done"] + ([] if page_done else ["close-old-input", "reset-command-listener"]) + ["close-cli-output"]
        cases.append({"case": "listener-ready-before-eof", "page_done": page_done, "calls": calls})

    for mtp_enabled in (False, True):
        for install_result in (0, 1, -2):
            toggles = []

            def setup_sideload(cpu):
                def observe(engine, address, size, _):
                    if address == SYMBOLS["recovery_toggle_mtp"]:
                        toggles.append(engine.reg_read(UC_ARM64_REG_X0))
                    elif address == SYMBOLS["recovery_sideload"]:
                        assert engine.reg_read(UC_ARM64_REG_X0) == 0x1000000
                        assert engine.reg_read(UC_ARM64_REG_X1) == 0x1000100
                cpu.hook_add(UC_HOOK_CODE, observe)

            value, _, calls = execute(patched, policy["symbols"]["dijun_ors_sideload"],
                                      {UC_ARM64_REG_X0: 0x1000000, UC_ARM64_REG_X1: 0x1000100},
                                      {SYMBOLS["recovery_toggle_mtp"]: ("toggle-mtp", mtp_enabled),
                                       SYMBOLS["recovery_sideload"]: ("sideload-once", install_result)}, setup=setup_sideload)
            assert toggles == [0, int(mtp_enabled)]
            assert value == install_result & 0xFFFFFFFF
            assert calls == ["toggle-mtp", "sideload-once", "toggle-mtp"]
            cases.append({"case": "sideload-usb-lifecycle", "mtp_enabled": mtp_enabled,
                          "install_result": install_result, "toggles": toggles})
    for install_result in (0, 1, -2):
        _, pc, calls = execute(patched, 0x1A9EAC, {UC_ARM64_REG_X0: install_result}, {},
                               stops=(SYMBOLS["ors_sideload_error"], SYMBOLS["ors_sideload_finished"]))
        assert pc == (SYMBOLS["ors_sideload_finished"] if install_result == 0 else SYMBOLS["ors_sideload_error"])
        assert not calls
        cases.append({"case": "sideload-no-second-install", "install_result": install_result, "stop": hex(pc)})

    for entry, state, populated, de_result in (
            ("dijun_restore_users", "1", False, False), ("dijun_restore_users", "1", True, False),
            ("dijun_restore_users", "0", False, True), ("dijun_restore_users", "-1", False, False),
            ("dijun_sync_encrypted", "1", False, False), ("dijun_sync_encrypted", "0", False, True),
            ("dijun_sync_encrypted", "-1", False, False)):
        encrypted_values = []

        def setup(cpu):
            cpu.mem_write(SYMBOLS["partition_manager_got"], (0x1000000).to_bytes(8, "little"))
            cpu.mem_write(0x1000100, (0x1000200).to_bytes(8, "little") +
                          (0x1000240 if populated else 0x1000200).to_bytes(8, "little"))

            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_property_get"]:
                    engine.mem_write(engine.reg_read(UC_ARM64_REG_X1), state.encode() + b"\0")
                elif address == SYMBOLS["recovery_set_integer"]:
                    assert engine.reg_read(UC_ARM64_REG_X0) == 0x1000300
                    encrypted_values.append(engine.reg_read(UC_ARM64_REG_X1))

            cpu.hook_add(UC_HOOK_CODE, observe)

        stubs = {SYMBOLS[name]: (name, result) for name, result in (
            ("recovery_property_get", len(state)), ("recovery_get_users", 0x1000100),
            ("recovery_parse_users", 0), ("recovery_decrypt_fbe_de", de_result),
            ("recovery_set_integer", 0))}
        _, _, calls = execute(patched, policy["symbols"][entry],
                               {UC_ARM64_REG_X0: 0x1000300, UC_ARM64_REG_X19: 0x1000400,
                                UC_ARM64_REG_X20: 0x1000500}, stubs, setup=setup)
        assert encrypted_values == [0 if state == "1" else 1], (state, encrypted_values)
        assert ("recovery_parse_users" in calls) == (entry == "dijun_restore_users" and state == "1" and not populated)
        assert ("recovery_decrypt_fbe_de" in calls) == (entry == "dijun_restore_users" and state != "1")
        cases.append({"case": entry, "cached_ce_state": state, "users_already_loaded": populated,
                      "de_initialization_result": de_result, "requires_credentials": bool(encrypted_values[0]),
                      "calls": calls})

    for entry, expected in ((0x1A6510, 1), (0x1A7EB8, 0)):
        values = []

        def setup_digest(cpu):
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_set_integer"]:
                    values.append(engine.reg_read(UC_ARM64_REG_X1))
            cpu.hook_add(UC_HOOK_CODE, observe)

        execute(patched, entry, {UC_ARM64_REG_SP: 0x2001000, UC_ARM64_REG_X8: 0x1000000}, {},
                stops=(SYMBOLS["recovery_set_integer"],), setup=setup_digest)
        assert values == [expected]
        cases.append({"case": "restore-digest", "explicit_skip_requested": expected == 0, "verification_enabled": bool(expected)})

    for mtp_pid in (1234, 2345):
        waited = []
        def setup_mtp_wait(cpu):
            cpu.mem_write(0x1000000 + 0x38, mtp_pid.to_bytes(4, "little"))
            def observe(engine, address, size, _):
                if address == 0x37A020:
                    waited.append(engine.reg_read(UC_ARM64_REG_X0))
                    assert int.from_bytes(engine.mem_read(0x1000000 + 0x38, 4), "little") == 0
            cpu.hook_add(UC_HOOK_CODE, observe)
        execute(patched, 0x164BC4, {UC_ARM64_REG_X19: 0x1000000},
                {0x37A020: ("wait-mtp-child", mtp_pid)}, stops=(0x164BD8,), setup=setup_mtp_wait)
        assert waited == [mtp_pid]
        cases.append({"case": "wait-only-mtp-child", "expected_pid": mtp_pid, "waited_pid": waited[0]})

    for ready in (False, True):
        def check_usb_wait(cpu):
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_wait_property"]:
                    key = bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X0), 24))
                    value = bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X1), 24))
                    assert key.startswith(b"\x1asys.usb.state\0")
                    assert value.startswith(b"\x06adb\0")
                    assert engine.reg_read(UC_ARM64_REG_X2) == 5000
            cpu.hook_add(UC_HOOK_CODE, observe)
        cpu_results = []
        def setup_usb_wait(cpu):
            check_usb_wait(cpu)
            from check_prebuilt_key_policy import END
            cpu.hook_add(UC_HOOK_CODE, lambda c, a, s, _: cpu_results.append(c.reg_read(UC_ARM64_REG_X20)) if a == END else None)
        _, _, calls = execute(patched, policy["symbols"]["dijun_disable_mtp_done"], {},
                               {SYMBOLS["recovery_property_set"]: ("request-adb", 0),
                                SYMBOLS["recovery_wait_property"]: ("wait-adb-ack", ready)}, setup=setup_usb_wait)
        assert calls == ["request-adb", "wait-adb-ack"] and cpu_results == [int(ready)]
        value, _, _ = execute(patched, 0x164C54, {UC_ARM64_REG_X20: ready}, {}, stops=(0x164C58,))
        assert value == int(ready)
        cases.append({"case": "mtp-disable-waits-adb", "ready": ready, "returned": value})

    phase_address = SYMBOLS["sideload_phase"]
    for name, expected, button, stop in (("dijun_sideload_begin", 0, 0, "sideload_begin_continue"),
                                          ("dijun_sideload_ready", 1, 1, "sideload_ready_continue"),
                                          ("dijun_sideload_finished", 0, 0, "sideload_finish_continue")):
        observed_phase, buttons = [], []
        def setup_phase(cpu):
            cpu.mem_write(phase_address, (3).to_bytes(4, "little"))
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_set_integer"]:
                    assert bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X0), 24)).startswith(b"\x1atw_has_cancel\0")
                    buttons.append(engine.reg_read(UC_ARM64_REG_X1))
                    observed_phase.append(int.from_bytes(engine.mem_read(phase_address, 4), "little"))
                if address == SYMBOLS["sideload_begin_continue"]:
                    assert engine.reg_read(UC_ARM64_REG_X0) == 0x1000000
                    assert engine.reg_read(UC_ARM64_REG_X1) == 0x1000100
                    assert engine.reg_read(UC_ARM64_REG_SP) == 0x200FF00 - 96
            cpu.hook_add(UC_HOOK_CODE, observe)
        execute(patched, policy["symbols"][name], {UC_ARM64_REG_X0: 0x1000000, UC_ARM64_REG_X1: 0x1000100},
                {SYMBOLS["recovery_set_integer"]: ("set-cancel-button", 0)}, stops=(SYMBOLS[stop],), setup=setup_phase)
        assert buttons == [button] and observed_phase == [expected]
        cases.append({"case": name, "phase": expected, "cancel_button": button})

    for phase, pid in ((0, 1464), (1, 1464), (2, 1464), (3, 1464), (1, 0)):
        signs, phases = [], []
        def setup_cancel(cpu):
            from check_prebuilt_key_policy import END
            cpu.mem_write(phase_address, phase.to_bytes(4, "little"))
            cpu.mem_write(SYMBOLS["minadbd_child"], pid.to_bytes(4, "little"))
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_kill"]:
                    signs.append((engine.reg_read(UC_ARM64_REG_X0), engine.reg_read(UC_ARM64_REG_X1)))
                elif address == SYMBOLS["recovery_property_set"]:
                    assert bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X0), 15)).startswith(b"sys.usb.config\0")
                    assert bytes(engine.mem_read(engine.reg_read(UC_ARM64_REG_X1), 5)) == b"none\0"
                elif address == END:
                    phases.append(int.from_bytes(engine.mem_read(phase_address, 4), "little"))
            cpu.hook_add(UC_HOOK_CODE, observe)
        _, _, calls = execute(patched, policy["symbols"]["dijun_sideload_cancel"], {},
                               {SYMBOLS["recovery_property_set"]: ("disconnect-ffs", 0),
                                SYMBOLS["recovery_kill"]: ("signal-minadbd", 0)}, setup=setup_cancel)
        assert calls == (["disconnect-ffs", "signal-minadbd"] if phase == 1 and pid else [])
        assert signs == ([(pid, 15)] if phase == 1 and pid else [])
        assert phases == [3 if phase == 1 else phase]
        cases.append({"case": "sideload-cancel-without-ui-wait", "phase": phase, "pid": pid, "calls": calls})

    for phase, install_result in ((0, 0), (1, 0), (1, 1), (2, 0), (3, 0)):
        phases, buttons = [], []
        def setup_install(cpu):
            cpu.mem_write(phase_address, phase.to_bytes(4, "little"))
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_set_integer"]:
                    buttons.append(engine.reg_read(UC_ARM64_REG_X1))
                elif address == SYMBOLS["recovery_install_zip"]:
                    assert engine.reg_read(UC_ARM64_REG_X0) == 0x1000000
                    assert engine.reg_read(UC_ARM64_REG_X1) == 0x1000100
                    assert engine.reg_read(UC_ARM64_REG_X2) == 0
                    phases.append(int.from_bytes(engine.mem_read(phase_address, 4), "little"))
            cpu.hook_add(UC_HOOK_CODE, observe)
        value, _, calls = execute(patched, policy["symbols"]["dijun_sideload_install"],
                                  {UC_ARM64_REG_X0: 0x1000000, UC_ARM64_REG_X1: 0x1000100, UC_ARM64_REG_X2: 0},
                                  {SYMBOLS["recovery_set_integer"]: ("hide-cancel-before-install", 0),
                                   SYMBOLS["recovery_install_zip"]: ("install-zip", install_result)}, setup=setup_install)
        assert calls == (["hide-cancel-before-install", "install-zip"] if phase == 1 else [])
        assert buttons == ([0] if phase == 1 else []) and phases == ([2] if phase == 1 else [])
        assert value == (install_result if phase == 1 else 1)
        cases.append({"case": "sideload-install-excludes-cancel", "phase": phase, "install_result": install_result, "calls": calls})

    # 固定 donor 只有这个调用点使用 forkserver，主程序和库必须一起应用补丁。
    import struct
    callers = [offset for offset in range(0x110000, 0x37C150, 4)
               if struct.unpack_from("<I", data, offset)[0] ==
               0x94000000 | (((SYMBOLS["recovery_mtp_forkserver"] - offset) >> 2) & 0x3FFFFFF)]
    assert callers == [0x164818]
    for cli_active in (False, True):
        received = []

        def setup_mtp_forkserver(cpu):
            cpu.mem_write(SYMBOLS["ors_output"], (0x1000200 if cli_active else 0).to_bytes(8, "little"))
            def observe(engine, address, size, _):
                if address == SYMBOLS["recovery_fileno"]:
                    assert engine.reg_read(UC_ARM64_REG_X0) == 0x1000200
                if address == SYMBOLS["recovery_mtp_forkserver"]:
                    assert engine.reg_read(UC_ARM64_REG_X0) == 0x1000000
                    assert engine.reg_read(UC_ARM64_REG_X1) == 0x1000100
                    received.append(engine.reg_read(UC_ARM64_REG_X2) & 0xFFFFFFFF)
            cpu.hook_add(UC_HOOK_CODE, observe)

        value, _, calls = execute(patched, policy["symbols"]["dijun_mtp_forkserver"],
                                  {UC_ARM64_REG_X0: 0x1000000, UC_ARM64_REG_X1: 0x1000100},
                                  {SYMBOLS["recovery_fileno"]: ("get-cli-output-fd", 68),
                                   SYMBOLS["recovery_mtp_forkserver"]: ("fork-mtp", 896)}, setup=setup_mtp_forkserver)
        assert value == 896 and received == [68 if cli_active else 0xFFFFFFFF]
        assert calls == (["get-cli-output-fd"] if cli_active else []) + ["fork-mtp"]
        cases.append({"case": "mtp-pass-cli-fd", "cli_active": cli_active, "fd": received[0]})

    original_mtp = (donor.parent.parent / "lib64/libtwrpmtp-ffs.so").read_bytes()
    patched_mtp, mtp_policy = patch_mtp(original_mtp)
    for fork_result, fd in ((896, 68), (-1, 68), (0, 68), (0, -1)):
        closed = []
        def setup_mtp_child(cpu):
            def observe(engine, address, size, _):
                if address == 0x3E200:
                    closed.append(engine.reg_read(UC_ARM64_REG_X0))
            cpu.hook_add(UC_HOOK_CODE, observe)
        value, _, calls = execute(patched_mtp, mtp_policy["symbols"]["dijun_mtp_fork"],
                                  {UC_ARM64_REG_X2: fd},
                                  {0x3F1C0: ("fork", fork_result), 0x3E200: ("close-cli-output-copy", 0)},
                                  setup=setup_mtp_child)
        assert value == fork_result & ((1 << 64) - 1)
        assert closed == ([fd] if fork_result == 0 and fd >= 0 else [])
        cases.append({"case": "mtp-child-releases-cli-output", "fork_result": fork_result,
                      "inherited_fd": fd, "closed": closed})

    for original, changed, changes in ((data, patched, policy), (original_mtp, patched_mtp, mtp_policy)):
        restored = bytearray(changed)
        for patch in reversed(changes["patches"]):
            offset = int(patch["offset"], 16)
            after, before = bytes.fromhex(patch["after"]), bytes.fromhex(patch["before"])
            assert restored[offset:offset + len(after)] == after
            restored[offset:offset + len(after)] = before
        assert restored == original
    report = {"passed": True, "cases": cases, "patched_sha256": policy["patched_sha256"],
              "patched_mtp_sha256": mtp_policy["patched_sha256"],
              "phone_operations": False, "scope": "真实 ARM64 控制流；不代替实际用户枚举、凭据解密或真机验收"}
    (ROOT / "build/recovery/prebuilt-crypto/session-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "cases": len(cases), "patched_sha256": policy["patched_sha256"]}))


if __name__ == "__main__":
    main()
