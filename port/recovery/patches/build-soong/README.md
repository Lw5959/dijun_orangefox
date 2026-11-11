# 受限主机上的 Soong 分析内存设置

`0001-dijun-low-memory-analysis.patch` 仅应用到 `build/soong` 提交 `6dc77879464584ef3f178cae622134ed0bf19e1e`，只改变构建主机的 Go 分析进程环境。当前构建树尚未由本任务应用补丁；主线构建入口负责核对 HEAD、应用补丁和传入开关。

第二轮现场记录 `build/recovery/build-attempt-002-build-resources.txt` 为 `memory.peak=4294971392`、`oom_kill=1`，表明触及当前 4GiB cgroup 上限。仅在启动 `soong_ui` 的环境中设置 `DIJUN_SOONG_LOW_MEMORY=1` 时，补丁才为 `primaryBuilderInvocation()` 的 `invocationEnv` 添加固定值：

```text
GOGC=40
GOMEMLIMIT=3GiB
```

其他开关值（包括未设置、`0`、`true`）保留原行为。补丁不改构图参数、默认 `-t` 主机检查、模块/ELF 校验或手机代码。

Blueprint 的 `bootstrap/bootstrap.go:779` 将 `i.Env` 序列化为命令变量，并由第 133 行的 `env -i $env` 启动 builder。因此只在外层 export `GOGC`/`GOMEMLIMIT` 无法保证到达分析器，必须在这里显式加入。两个固定值仅含字母、数字，未引入 shell quoting 输入。

当前树的 `prebuilts/go/linux-x86/VERSION` 是 **go1.23.4**；其 `src/runtime/mgc.go:187` 用 `readGOGC()`、`readGOMEMLIMIT()` 初始化 GC。`src/runtime/debug/garbage.go:223` 明确支持 `GOMEMLIMIT` 及 `GiB` 后缀，`3GiB` 对应 `3221225472` 字节。这个值是 **Go 运行时软限制**，不包含所有非 Go 分配、其他进程或整个 cgroup，不能保证后续构图必然避开 OOM；较低 GOGC 会增加 GC 工作量。

不设置 `GOMAXPROCS`：`build/blueprint/bootstrap/command.go:68` 的 `RunBlueprint()` 会调用 `runtime.GOMAXPROCS(runtime.NumCPU())`，外层同名环境变量会被该调用覆盖。本补丁也不改该逻辑。

可在固定源码根目录中先执行检查，再由构建入口应用：

```sh
git -C build/soong rev-parse HEAD
git -C build/soong apply --check /absolute/project/recovery/patches/build-soong/0001-dijun-low-memory-analysis.patch
git -C build/soong apply /absolute/project/recovery/patches/build-soong/0001-dijun-low-memory-analysis.patch
```

启动构建时将 `DIJUN_SOONG_LOW_MEMORY=1` 显式传到实际运行 `soong_ui` 的容器环境；补丁本身不会扩大容器内存或改变其他容器。重新生成的 `out/soong/bootstrap.ninja` 中，builder 的 `env =` 应包含两个固定值（map 序列化顺序不固定）。是否解决现场 OOM 由主线后续真实构图及 `memory.events` 判定。

已完成的本地主机检查：

- 固定 HEAD 的原文件在临时目录中 `git apply --check`、应用均通过，实际 `build/soong` 源文件未修改。
- 提取补丁后的完整 `primaryBuilderInvocation()` 方法，用最小类型依赖编译执行：四种开关值 × 两种 debug 状态共 8 个组合通过；精确为 `1` 才添加固定值，外层其他 GC 值不被意外转发，原 debug 环境和 `-t` 均保留。
- 在本机 Go 1.26.5 darwin/arm64 下以 `env -i GOGC=40 GOMEMLIMIT=3GiB` 运行临时探针，运行时回读为 `40`、`3221225472`。目标 Go 1.23.4 的支持依据上述树内运行时源码，未把本机探针冒充 Linux 构图验收。

这些检查验证补丁接线和参数语义；未运行新的完整构图，未操作手机。
