#!/usr/bin/env python3
"""离线核验 recovery 的实际 ELF 依赖和 init 服务路径；不加载或执行目标程序。"""

import argparse
import importlib.util
import json
import os
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
AOSP = ROOT / "sources/orangefox/aosp"
# 审计器随保留的轻量 build-make 仓库使用，不依赖已清理的大 AOSP 工作区。
DEFAULT_CHECKER = ROOT / "sources/orangefox/build-make/tools/check_elf_file.py"


class RamdiskFiles:
    """只在 CPIO 的虚拟根内解引用链接，不在主机创建 Android 绝对链接。"""

    def __init__(self, root, entries):
        self.root = Path(root).resolve(strict=True)
        self.entries = {}
        for entry in entries:
            name = PurePosixPath(entry["path"])
            if name.is_absolute() or ".." in name.parts or "\0" in str(name):
                raise ValueError(f"不安全的 CPIO 路径：{entry['path']!r}")
            self.entries["/" if str(name) == "." else "/" + str(name)] = entry

    def resolve(self, name):
        if not name.startswith("/") or "\0" in name:
            raise ValueError(f"需要 Android 绝对路径：{name!r}")
        name = "/" + posixpath.normpath("/" + name.lstrip("/")).lstrip("/")
        for _ in range(41):
            parts = name.strip("/").split("/")
            for index in range(len(parts)):
                prefix = "/" + "/".join(parts[:index + 1])
                entry = self.entries.get(prefix, {})
                if stat.S_ISLNK(entry.get("mode", 0)):
                    target = entry.get("symlink_target", "")
                    if not target or "\0" in target:
                        raise ValueError(f"无效 CPIO 链接：{prefix}")
                    target = posixpath.join(posixpath.dirname(prefix), target)
                    name = "/" + posixpath.normpath(posixpath.join(target, *parts[index + 1:])).lstrip("/")
                    break
            else:
                return name
        raise ValueError(f"CPIO 符号链接循环或超过 40 层：{name}")

    def file(self, name):
        resolved = self.resolve(name)
        entry = self.entries.get(resolved)
        if not entry or not stat.S_ISREG(entry["mode"]):
            return None
        path = self.root / resolved.lstrip("/")
        # 输入来自安全解包器；仍拒绝主机上另行物化的链接，避免绕过虚拟根。
        current = self.root
        for part in PurePosixPath(resolved).parts[1:]:
            current /= part
            if current.is_symlink():
                raise ValueError(f"解包 root 中存在物化链接：{resolved}")
        return path if path.is_file() else None

    def text(self, name):
        path = self.file(name)
        return path.read_text() if path else None


def init_lines(content):
    # init 的双引号字符串可以跨行，不能把其中一行当成独立指令或 rc 语法错误。
    pending = ""
    start = 1
    for number, line in enumerate(content.splitlines(keepends=True), 1):
        if not pending:
            start = number
        pending += line
        if line.rstrip("\n").endswith("\\"):
            pending = pending[:-2] + " " if pending.endswith("\\\n") else pending
            continue
        try:
            words = shlex.split(pending, comments=True)
        except ValueError as error:
            if "No closing quotation" in str(error):
                continue
            raise
        yield start, pending, words
        pending = ""
    if pending:
        raise ValueError(f"init rc 在第 {start} 行存在未闭合字符串或续行")


def init_records(files):
    # 只复现当前 recovery 的入口和目录加载，不推断其他设备或任意启动属性。
    main = "/system/etc/init/hw/init.rc"
    automatic = ("/system/etc/init", "/system_ext/etc/init", "/vendor/etc/init",
                 "/odm/etc/init", "/product/etc/init")
    properties = {"ro.hardware": "O1_asic"}
    records, parse_errors = {}, {}
    for name in sorted(files.entries):
        if not name.endswith(".rc") or not files.file(name):
            continue
        try:
            records[name] = list(init_lines(files.text(name)))
        except ValueError as error:
            parse_errors[name] = str(error)
    loaded, issues, loading, attempted = [], [], set(), set()

    def load(name, source, line=0):
        if "$" in name:
            issues.append({"rc": source, "line": line, "import": name,
                           "error": "无法用已核验的 dijun 属性展开 import"})
            return
        name = files.resolve(name)
        if name in loading:
            issues.append({"rc": source, "line": line, "import": name,
                           "error": "init import 存在循环，不能确定加载集合"})
            return
        if name in loaded:
            return
        attempted.add(name)
        if not files.file(name):
            # AOSP ParseConfig 也允许直接加载一个目录，仅扫描该目录第一层的 .rc。
            children = sorted(path for path in records.keys() | parse_errors.keys()
                              if posixpath.dirname(path) == name)
            if children:
                for child in children:
                    load(child, source, line)
            else:
                issues.append({"rc": source, "line": line, "import": name,
                               "error": "导入文件/目录未在 ramdisk 中找到，不能确认其服务"})
            return
        if name not in records and name not in parse_errors:
            try:
                records[name] = list(init_lines(files.text(name)))
            except ValueError as error:
                parse_errors[name] = str(error)
        if name in parse_errors:
            issues.append({"rc": name, "error": parse_errors[name]})
            return
        loading.add(name)
        # init 在一个文件解析完成后处理其 imports；保留这个顺序和真实行号。
        loaded.append(name)
        for line_number, _, words in records.get(name, []):
            if words and words[0] == "import":
                if len(words) != 2:
                    issues.append({"rc": name, "line": line_number, "error": "无效 import 参数"})
                    continue
                target = words[1]
                for key, value in properties.items():
                    target = target.replace("${" + key + "}", value)
                load(target, name, line_number)
        loading.remove(name)

    load(main, "recovery init 入口")
    for directory in automatic:
        directory = files.resolve(directory)
        for name in sorted(records.keys() | parse_errors.keys()):
            if posixpath.dirname(name) == directory:
                load(name, "init 自动加载目录")
    services, orphans, copies, library_paths = [], [], [], set()
    for name, lines in records.items():
        active = name in loaded
        section = ""
        service = None
        for line_number, line, words in lines:
            if not words:
                continue
            if not line[0].isspace():
                section = " ".join(words)
                service = None
                if words[0] == "service" and len(words) >= 3:
                    service = {"rc": name, "line": line_number, "name": words[1],
                               "program": words[2]}
                    (services if active else orphans).append(service)
            elif not active:
                continue
            elif words[:2] == ["export", "LD_LIBRARY_PATH"] and len(words) == 3:
                library_paths.add(words[2])
            elif words[:2] == ["setenv", "LD_LIBRARY_PATH"] and service and len(words) == 3:
                service["library_path"] = words[2]
            elif words[0] == "copy" and len(words) == 3 and section == "on early-init":
                copies.append((words[1], words[2]))
    if len(library_paths) > 1:
        raise ValueError("ramdisk 中存在不同的全局 LD_LIBRARY_PATH，不能静态确定统一顺序")
    scope = {"main": main, "properties": properties, "loaded_rcs": loaded,
             "automatic_directories": list(automatic), "issues": issues,
             "orphan_rc_parse_errors": {name: error for name, error in parse_errors.items()
                                        if name not in attempted}}
    return services, copies, next(iter(library_paths), ""), scope, orphans


def under(path, directory):
    return path == directory or path.startswith(directory.rstrip("/") + "/")


class LinkerConfig:
    """解析当前 recovery 使用的普通 arm64 profile；保留 namespace 链接白名单。"""

    def __init__(self, files, copies, library_path):
        self.files = files
        self.library_paths = self.paths(library_path)
        self.path = "/system/etc/ld.config.arm64.txt"
        self.copy_source = None
        if not files.file(self.path):
            self.path = "/linkerconfig/ld.config.txt"
            sources = {source for source, target in copies if target == self.path}
            if len(sources) > 1:
                raise ValueError("early-init 对 linkerconfig 的复制来源不唯一")
            if sources:
                self.copy_source = next(iter(sources))
                self.path = self.copy_source
            elif not files.file(self.path):
                self.path = "/system/etc/ld.config.txt"
        content = files.text(self.path)
        if not content or not content.strip():
            raise ValueError(f"没有可静态核验的非空 linker 配置：{self.path}")
        self.directories = []
        self.sections = {}
        section = None
        for number, line in enumerate(content.splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = self.sections.setdefault(line[1:-1], {})
                continue
            match = re.fullmatch(r"([\w.]+)\s*(\+?=)\s*(.*)", line)
            if not match:
                raise ValueError(f"不支持的 linker 配置行：{self.path}:{number}")
            key, operation, value = match.groups()
            if section is None:
                if not key.startswith("dir.") or operation != "=":
                    raise ValueError(f"不支持的 linker profile 声明：{key}")
                self.directories.append((key[4:], self.files.resolve(value)))
            elif operation == "+=" and key in section:
                separator = "," if key == "additional.namespaces" or key.endswith(".links") else ":"
                section[key] += separator + value
            else:
                section[key] = value
        for section_name, values in self.sections.items():
            for namespace in self.namespaces(section_name):
                if f"namespace.{namespace}.search.paths" not in values:
                    raise ValueError(f"namespace 缺少 search.paths：{section_name}/{namespace}")

    @staticmethod
    def paths(value):
        paths = value.replace("${LIB}", "lib64").split(":") if value else []
        if any(not path.startswith("/") or "$" in path for path in paths):
            raise ValueError(f"无法静态展开 linker 路径：{value}")
        return paths

    def namespaces(self, section):
        values = self.sections[section]
        return ["default"] + [item.strip() for item in values.get("additional.namespaces", "").split(",") if item.strip()]

    def contexts(self, name):
        # 库可能从不同进程 profile 装入：每个可搜索到它的 namespace 都要独立核验。
        result = []
        for section in self.sections:
            for namespace in self.namespaces(section):
                paths = self.paths(self.sections[section][f"namespace.{namespace}.search.paths"])
                if namespace == "default":
                    paths = self.library_paths + paths
                if (any(posixpath.dirname(name) == self.files.resolve(path) for path in paths)
                        and self.accessible(section, namespace, name)):
                    result.append((section, namespace))
        if result:
            return result
        for section, directory in self.directories:
            if under(name, directory):
                if section not in self.sections:
                    raise ValueError(f"linker profile 不存在：{section}")
                return [(section, "default")]
        raise ValueError(f"ELF 不属于已核验的 linker profile/search.paths：{name}")

    def accessible(self, section, namespace, name, library_paths=None):
        values = self.sections[section]
        prefix = f"namespace.{namespace}."
        if values.get(prefix + "isolated") != "true":
            return True
        # Bionic is_accessible 也允许 LD_LIBRARY_PATH；隔离标志不会屏蔽已继承的环境目录。
        # 因此厂商服务必须移除全局 /system/lib64 环境路径，不能靠此审计误判其隔离有效。
        environment = self.library_paths if library_paths is None else library_paths
        search = (environment if namespace == "default" else []) + self.paths(values[prefix + "search.paths"])
        permitted = self.paths(values.get(prefix + "permitted.paths", ""))
        return (any(posixpath.dirname(name) == self.files.resolve(p) for p in search) or
                any(under(name, self.files.resolve(p)) for p in permitted))

    def local(self, section, namespace, needed, library_paths):
        values = self.sections[section]
        prefix = f"namespace.{namespace}."
        search = self.paths(values[prefix + "search.paths"])
        paths = (library_paths if namespace == "default" else []) + search
        candidates = [needed] if needed.startswith("/") else [posixpath.join(path, needed) for path in paths]
        if "/" in needed and not needed.startswith("/"):
            raise ValueError(f"依赖含相对路径，无法确定运行目录：{needed}")
        for candidate in candidates:
            path = self.files.file(candidate)
            if not path:
                continue
            resolved = self.files.resolve(candidate)
            if not self.accessible(section, namespace, resolved, library_paths):
                continue
            return resolved, namespace
        return None

    def provider(self, context, needed, library_paths=None):
        section, namespace = context
        if needed == "ld-android.so":
            path = "/system/bin/linker64"
            return (self.files.resolve(path), namespace) if self.files.file(path) else None
        library_paths = self.library_paths if library_paths is None else self.paths(library_paths)
        result = self.local(section, namespace, needed, library_paths)
        if result:
            return result
        values = self.sections[section]
        prefix = f"namespace.{namespace}."
        # Bionic 的链接 namespace 搜索不递归穿透第二条链接；提供者自己的依赖另行核验。
        for linked in (item.strip() for item in values.get(prefix + "links", "").split(",")):
            if not linked:
                continue
            link = prefix + f"link.{linked}."
            allowed = values.get(link + "shared_libs", "").split(":")
            if values.get(link + "allow_all_shared_libs") == "true" or needed in allowed:
                if linked not in self.namespaces(section):
                    raise ValueError(f"链接的 namespace 不存在：{section}/{linked}")
                result = self.local(section, linked, needed, [])
                if result:
                    return result
        return None


def load_backend(checker_path, llvm_readobj):
    spec = importlib.util.spec_from_file_location("aosp_check_elf_file", checker_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if llvm_readobj is None:
        host = "darwin" if os.uname().sysname == "Darwin" else "linux"
        prebuilts = sorted((AOSP / f"prebuilts/clang/host/{host}-x86").glob("clang-*/bin/llvm-readobj"))
        llvm_readobj = shutil.which("llvm-readobj") or (prebuilts[-1] if prebuilts else None)
        if llvm_readobj is None and Path("/opt/homebrew/opt/llvm/bin/llvm-readobj").is_file():
            llvm_readobj = "/opt/homebrew/opt/llvm/bin/llvm-readobj"
    if llvm_readobj is None:
        raise ValueError("找不到主机 llvm-readobj，请用 --llvm-readobj 指定可执行的 LLVM 工具")
    return module, str(llvm_readobj)


def audit_runtime(root, entries, *, checker_path=DEFAULT_CHECKER, llvm_readobj=None):
    """供 audit_image.py 调用；返回 passed/明细，任何依赖或服务路径缺失都会失败。"""
    files = RamdiskFiles(root, entries)
    backend, llvm_readobj = load_backend(Path(checker_path), llvm_readobj)
    services, copies, library_path, init_scope, orphans = init_records(files)
    config = LinkerConfig(files, copies, library_path)
    parsed = {}

    def elf(name):
        if name not in parsed:
            path = files.file(name)
            if not path:
                raise ValueError(f"CPIO 普通文件未安全物化：{name}")
            parsed[name] = backend.ELFParser.open(str(path), llvm_readobj)
        result = parsed[name]
        if result.header.e_machine != 183 or result.header.ei_class != 2 or result.header.ei_data != 1:
            raise ValueError(f"提供者不是 AArch64 little-endian ELF：{name}")
        return result

    class RecordingChecker(backend.Checker):
        # 仍调用 AOSP 原始 DT_NEEDED/强符号校验，只把其诊断收集到 JSON。
        def _error(self, *args):
            self.errors.append(" ".join(str(arg) for arg in args))

        def _note(self, *args):
            pass  # 上游的“关闭检查”建议不是本工具的修复路径。

    checks = []
    object_count = 0
    for name, entry in sorted(files.entries.items()):
        if not stat.S_ISREG(entry["mode"]):
            continue
        path = files.file(name)
        if not path:
            raise ValueError(f"CPIO 普通文件未安全物化：{name}")
        header = backend.ELFParser._read_elf_header(str(path))
        if not header or header.ei_magic != b"\x7fELF" or header.e_machine != 183:
            continue
        obj = elf(name)
        object_count += 1
        if not obj.dt_needed and not obj.imported:
            checks.append({"file": name, "elf_type": header.e_type, "passed": True,
                           "note": "没有动态依赖或动态强导入；ET_REL 内核导入由独立模块审计负责。"})
            continue
        for context in config.contexts(name):
            providers = {}
            shared = []
            for needed in obj.dt_needed:
                provider = config.provider(context, needed)
                if provider:
                    provider_name, namespace = provider
                    shared.append(elf(provider_name))
                    providers[needed] = {"file": provider_name, "namespace": namespace}
                else:
                    providers[needed] = None
            checker = RecordingChecker(llvm_readobj)
            checker._file_path, checker._file_under_test, checker._shared_libs = name, obj, shared
            checker.errors = []
            for method in (lambda: checker.check_dt_needed([]), checker.check_symbols):
                try:
                    method()
                except SystemExit as error:
                    if error.code != 2:
                        raise
            checks.append({"file": name, "section": context[0], "namespace": context[1],
                           "providers": providers, "passed": not checker.errors,
                           "errors": checker.errors})

    for service in services:
        path = files.file(service["program"])
        service["resolved_program"] = files.resolve(service["program"])
        entry = files.entries.get(service["resolved_program"], {})
        service["passed"] = bool(path and entry.get("mode", 0) & 0o111)
        if not service["passed"]:
            service["error"] = "service 程序缺失、不是普通文件或没有执行位"
        if "library_path" in service and service["library_path"] != library_path:
            # 当前设备没有这种覆盖；不能悄悄以全局环境替代服务私有环境。
            service["passed"] = False
            service["error"] = "service 覆盖 LD_LIBRARY_PATH，需按该环境增加独立 ELF 上下文核验"
    return {"schema": "dijun-recovery-runtime-audit-v1",
            "passed": object_count > 0 and bool(services) and not init_scope["issues"] and all(c["passed"] for c in checks + services),
            "aarch64_elf_count": object_count, "elf_context_checks": len(checks),
            "elf_failures": sum(not c["passed"] for c in checks),
            "service_count": len(services), "service_failures": sum(not s["passed"] for s in services),
            "init_load": init_scope, "orphan_services": orphans,
            "linker_config": {"file": config.path, "early_init_copy_source": config.copy_source,
                              "LD_LIBRARY_PATH": library_path},
            "backend": str(checker_path), "llvm_readobj": llvm_readobj,
            "elf_checks": checks, "services": services,
            "phone_operations": False, "hardware_boot_verified": False,
            "note": "仅核验 ramdisk 普通 arm64 ELF 的静态 DT_NEEDED/版本化强符号及 init service 路径；不证明 dlopen、启动顺序、硬件或解密可用。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--checker", type=Path, default=DEFAULT_CHECKER)
    parser.add_argument("--llvm-readobj", type=Path)
    args = parser.parse_args()
    try:
        report = audit_runtime(args.root, json.loads(args.entries.read_text()),
                               checker_path=args.checker, llvm_readobj=args.llvm_readobj)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        summary = {key: report[key] for key in ("passed", "aarch64_elf_count", "elf_failures", "service_count", "service_failures")}
        summary["report"] = str(args.report)
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if report["passed"] else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"recovery 静态运行依赖核验失败：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
