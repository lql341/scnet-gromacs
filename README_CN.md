# scnet-gromacs

[English](README.md) | 中文

当前版本：0.1.0

在 SCNet 计算节点上验证现有 GROMACS module，使用一个很小且确定性的分子动力学
case。流程坚持远端优先：module 加载、`grompp`、`mdrun`、设备检查和数值比较
都在目标计算节点执行，不在 agent 本机运行。

第一版面向昆山 Z100/DTK 环境。昆山当前 module 为 GROMACS 2026.3；官方文档当前
已是 2026.4，因此本 skill 只报告 patch 版本差异，不擅自重新编译软件。
参见[官方 2026.4 发布说明](https://manual.gromacs.org/current/release-notes/2026/2026.4.html)。

## 一句话让 agent 安装

> 使用 `$skill-installer` 从 GitHub 仓库 `lql341/scnet-gromacs` 根目录（path `.`、ref `main`）安装 `scnet-gromacs`，不覆盖已有目录，然后运行 `scripts/validate.sh`；安装阶段不要提交集群作业。

## 验证内容

- module 身份和 `gmx_mpi --version`；
- 编译器、MPI、HIP/DTK、GPU FFT 和目标架构信息；
- bundled 八原子 Argon case 的 CPU `grompp + mdrun`；
- 可选 HIP/DCU `mdrun`，显式使用 `-nb gpu -pme gpu -npme 1`；
- 有限能量输出和紧凑的最终状态 checksum；
- 调度器终态和 workload 退出码。

CPU 运行是数值 oracle。GPU 运行只证明集成和运行时，不宣称逐位相同或生产性能。
浮点差异必须结合容差和物理合理性报告。

## 工作流

作业调度、状态查询、等待和取消优先使用 `scnet-hpc` OpenAPI。SSH 只用于有限的
脚本上传和日志诊断。

```bash
bash scripts/validate.sh
# 计算节点上：
bash scripts/gromacs_module_probe.sh
bash scripts/gromacs_argon_smoke.sbatch
```

可设置：

```text
GROMACS_MODULE     module 名称，默认 gromacs/2026.3
GROMACS_BINARY     可执行文件，默认 gmx_mpi
GROMACS_GPU_MODE   cpu 或 hip，默认 cpu
GROMACS_RUN_ROOT   唯一可写运行目录
```

不能只根据 module 名称判断 GPU 可用；必须在计算节点确认设备可见，并确认二进制
报告 HIP 支持。

## 提炼的 DCU 移植经验

GROMACS 是成熟应用验证，不是从零编写新 kernel 的移植。仍应保留这些通用经验：
以目标计算节点为事实来源，记录 `gfx906` 等架构，保留 CPU 数值 oracle，把设备/
运行时检查和正确性检查分开，检查有限值和物理不变量，并让 workload 与调度器都
传播失败状态。没有目标探针时，不要把 CUDA、ROCm 或新 GPU 的能力外推到 DTK。

## 本地校验

```bash
bash scripts/validate.sh
```

只检查脚本和 bundled 输入，不在本机编译或运行 GROMACS。

MIT 许可证。
