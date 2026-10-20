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

HIP 模式记录设备可见性、`GMX_GPU`、HIP runtime 和目标架构。Z100 初次 smoke
显式使用 `-nb gpu -pme gpu -npme 1`。不要用微型 case 宣称生产性能。

## DCU 通用经验

即使验证的是成熟应用，也应遵循通用 DCU 原则：

- 先做目标计算节点探针，再声明能力；
- 明确 CPU oracle 和容差；
- 检查有限值和物理不变量；
- 区分 host/device 数据移动和诊断 trace；
- 测试必须可见，失败要传播为非零状态；
- 同时记录调度器状态和 workload 退出码；
- 记录未覆盖边界：多节点扩展、PME 分解、生产规模体系和精度漂移。
