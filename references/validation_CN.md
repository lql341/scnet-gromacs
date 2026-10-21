# GROMACS 验证模型

## 目标事实

昆山当前 module 包含 GROMACS 2026.3：

- `gromacs/2026.3` 和 `gromacs/2026.3-dtk26.04-z100` 使用自建 GCC 16.2、
  OpenMPI 5.0.11、DTK 26.04、HIP、rocFFT，目标为 gfx906。
- `gromacs/2026.3-pmpi` 及其 DTK/Z100 变体使用平台 OpenMPI 4.1.5。

上游官方文档当前已是 GROMACS 2026.4，因此这是 patch 版本差异；先验证现有
2026.3 二进制，再决定是否值得重编。

## Case 契约

仓库包含两个 case：

- `cases/argon8` 是无电荷的确定性 CPU/HIP smoke，固定原子数、盒子、时间步和
  步数；HIP 模式使用 `-nb gpu`。
- `cases/ionpair_pme` 是净中性八离子 PME case，设置 `coulombtype = PME`，
  HIP 模式使用 `-nb gpu -pme gpu`，只用于验证 PME GPU 路径，不代表性能或
  生产规模精度。

CPU 运行是 oracle。记录完整 `gmx_mpi --version`、命令行、资源元组、调度器
终态、退出码、输入 checksum、能量摘要和最终 checksum。

HIP 模式记录设备可见性、`GMX_GPU`、HIP runtime 和目标架构。可选的
`GROMACS_EXPECT_GPU_ARCH`（例如 Z100 的 `gfx906`）会在 `rocminfo` 未显示该架构时
让 smoke 失败。PME case 必须
明确出现日志行 `PME tasks will do all aspects on the GPU`；仅有泛泛的 GPU/HIP
字样不算。

## OpenAPI 执行路径

`contrib/run_openapi.py` 是核心计算节点脚本之上的可选编排。它调用已安装的
`scnet-hpc` CLI 的 `--backend openapi`，完成远端 mkdir、upload、submit、限时
wait、详细 job 检查和显式 artifact 下载；不使用 SSH，并拒绝复用已存在的远端
run root 或本地下载目录。也可以不用该包装脚本，直接用 `scnet-hpc` 驱动同一组
脚本。

runner 读取从 `clusters/_template.conf` 复制的私有 profile，或接受显式的队列/
module/资源参数。profile 中的 `GPU_ARCH` 会传给 HIP 作业作为可选架构门禁，但不
替代实际设备探针。对 Hygon Z100，它只给 HIP 作业传 DCU 数量；gfx906 是否可见、
PP/PME 是否真正在设备上执行，仍由目标节点探针和日志决定，profile 只是站点提示，
不是实时证据。

`--mode both` 会提交 CPU 和 HIP，下载两套结果并运行容差检查；调度器状态、平台
退出码和 workload `status=passed` 仍分别检查。

## CPU/HIP 容差契约

使用 `scripts/compare_gromacs_energy.py` 比较两条能量时间序列。两个 run 都必须
有 `status=passed`、相同的 `inputs.sha256` 内容和相同时间网格。逐数据点应用：

```text
|CPU - HIP| <= atol + rtol * max(|CPU|, |HIP|)
```

默认 `Potential` 和 `Kinetic En.` 的 `atol=0.05 kJ/mol`，`Temperature` 的
`atol=0.5 K`，`rtol=1e-3`。这些只是 smoke 级契约；通过不表示逐位相同，
也不能外推到更大体系、更长轨迹、其他精度或其他架构。

## 适配新的 GROMACS 版本

新 module 应视为一个新的目标，而不是无条件替换：

1. 在计算节点探针，记录 `gmx_mpi --version`、编译器、MPI、HIP/DTK、rocFFT、
   GPU 支持和架构。
2. 在私有 profile 中设置 `GROMACS_EXPECT_VERSION`。实际加载的二进制版本不一致
   时，smoke 作业会写出 `status=failed_version` 并以非零状态退出。
3. 重跑 Argon CPU 和 HIP。检查完成标记、GPU 选择、有限能量以及调度器/workload
   状态。日志标记变化时，依据实测证据更新检查器，不要猜测。
4. 重跑 PME case。确认 PME 仍在 GPU 上执行，并确认单 rank 下 `-pme gpu`/
   `-npme` 行为没有变化。若新版本拒绝或改变参数，记录完整 fatal 信息并更新
   case 或已记录的边界。
5. 只有拿到实测值并写明理由后才重新设定 CPU/HIP 容差；新版本通过前保留旧
   profile/证据。
6. 更新 profile 的 module、期望版本、CHANGELOG 和实测范围说明。不要静默放宽
   容差，也不要仅凭版本字符串宣称支持。

bundled `.gro`、topology 和 `md.mdp` 刻意保持最小。若新版本废弃某个 mdp 选项，
以 `grompp` 为准；只有记录 before/after 结果后才修改 case。

## 已实测的 harness 陷阱

- GROMACS 2026.3 的成功完成标记是 `Writing final coordinates.`，只搜索
  `Finished mdrun` 会把成功运行误判为失败。
- `gmx energy` 输出时间列加上每个选中能量项的多列数据；检查数据行的数值
  字段，不要假设只有两列。
- `.gro` 与 topology 的原子名大小写不一致，可能让 warning 在 `grompp` 阶段
  变成 fatal。
- MPI 构建不接受 thread-MPI 专用的 `-ntmpi` 参数；本 smoke 使用 MPI 资源
  契约和 `-ntomp`。
- 单 MPI rank 使用 `-pme gpu -npme 1` 会被判为请求并行模拟并 fatal。单 rank
  只用 `-pme gpu`，不加 `-npme`；只有多 rank 作业才加 `-npme`。PME 日志行
  会区分 PP 和 PME GPU 任务。
- 已安装的 HIP build 可能在 mdrun 前打印非致命的 `dummy_kernel` launch-bounds
  警告。成功判定应依据明确的设备/PME 选择、完成标记、有限能量值和
  `status=passed`，而不是“没有 warning”。
- CPU/HIP 比较只覆盖 21 帧、20 步的 smoke；通过不能外推为生产精度或性能。

昆山实测 module 为 GROMACS 2026.3，编译器 GCC 16.2，OpenMPI 5.0.11，
HIP/DTK 26.04，rocFFT 1.0.28，目标架构 gfx906。上游当前版本是 2026.4，
因此 skill 验证已安装的 2026.3，不把 patch 差异直接当作必须重编的理由。
OpenAPI 优先 runner 已在 Argon 和 PME case 上完成端到端实测，CPU/HIP 比较在
独立调度作业上通过。

## DCU 通用经验

即使验证的是成熟应用，也应遵循通用 DCU 原则：

- 先做目标计算节点探针，再声明能力；
- 明确 CPU oracle 和容差；
- 检查有限值和物理不变量；
- 区分 host/device 数据移动和诊断 trace；
- 测试必须可见，失败要传播为非零状态；
- 同时记录调度器状态和 workload 退出码；
- 记录未覆盖边界：多节点扩展、PME 分解、生产规模体系和精度漂移。
