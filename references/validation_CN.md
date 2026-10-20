# GROMACS 验证模型

## 目标事实

昆山当前 module 包含 GROMACS 2026.3：

- `gromacs/2026.3` 和 `gromacs/2026.3-dtk26.04-z100` 使用自建 GCC 16.2、
  OpenMPI 5.0.11、DTK 26.04、HIP、rocFFT，目标为 gfx906。
- `gromacs/2026.3-pmpi` 及其 DTK/Z100 变体使用平台 OpenMPI 4.1.5。

上游官方文档当前已是 GROMACS 2026.4，因此这是 patch 版本差异；先验证现有
2026.3 二进制，再决定是否值得重编。

## Case 契约

Argon case 固定原子数、盒子、时间步和步数。CPU 运行是 oracle。记录完整
`gmx_mpi --version`、命令行、资源元组、调度器终态、退出码、能量摘要和最终
checksum。

HIP 模式记录设备可见性、`GMX_GPU`、HIP runtime 和目标架构。bundled 无电荷
Argon case 使用 `-nb gpu`；在没有 PME 静电时强制 `-pme gpu` 会被 GROMACS
判为真实输入错误。只有 PME case 才增加 `-pme gpu -npme 1`。不要用微型
case 宣称生产性能。

## 已实测的 harness 陷阱

- GROMACS 2026.3 的成功完成标记是 `Writing final coordinates.`，只搜索
  `Finished mdrun` 会把成功运行误判为失败。
- `gmx energy` 输出时间列加上每个选中能量项的多列数据；检查数据行的数值
  字段，不要假设只有两列。
- `.gro` 与 topology 的原子名大小写不一致，可能让 warning 在 `grompp` 阶段
  变成 fatal。
- MPI 构建不接受 thread-MPI 专用的 `-ntmpi` 参数；本 smoke 使用 MPI 资源
  契约和 `-ntomp`。

昆山实测 module 为 GROMACS 2026.3，编译器 GCC 16.2，OpenMPI 5.0.11，
HIP/DTK 26.04，rocFFT 1.0.28，目标架构 gfx906。上游当前版本是 2026.4，
因此 skill 验证已安装的 2026.3，不把 patch 差异直接当作必须重编的理由。

## DCU 通用经验

即使验证的是成熟应用，也应遵循通用 DCU 原则：

- 先做目标计算节点探针，再声明能力；
- 明确 CPU oracle 和容差；
- 检查有限值和物理不变量；
- 区分 host/device 数据移动和诊断 trace；
- 测试必须可见，失败要传播为非零状态；
- 同时记录调度器状态和 workload 退出码；
- 记录未覆盖边界：多节点扩展、PME 分解、生产规模体系和精度漂移。
