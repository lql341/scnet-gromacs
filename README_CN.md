# scnet-gromacs

[English](README.md) | 中文

当前版本：0.8.1

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
- 可选 HIP/DCU `mdrun`；bundled 无电荷 Argon case 显式使用 `-nb gpu`；
- 独立的 PME 离子对 case，使用 `-nb gpu -pme gpu`，检查 PME GPU 日志，
  不给 Argon case 强行添加 PME 参数；
- 有限能量输出、紧凑的最终状态 checksum 和输入 checksum；
- 明确的 CPU/HIP 能量容差比较；
- PME 能量分量（`Coulomb (SR)`、`Coul. recip.`、`LJ (SR)`），不只比较总势能；
- 可选多 rank、PME 分解、多 GPU 和 PMPI 执行路径；
- 调度器终态和 workload 退出码。

CPU 运行是数值 oracle。GPU 运行只证明集成和运行时，不宣称逐位相同或生产性能。
浮点差异必须结合容差和物理合理性报告。

bundled case 只是 smoke test。它们覆盖部分 PME 分解、GPU-aware MPI 和 PMPI
路径，但不能证明多节点扩展或生产规模精度。

## 版本覆盖与空白账户基线

本 skill 不打包 GROMACS。空白 SCNet 账户必须提供站点 module 或自己的构建。
下表的“覆盖”表示在参考环境跑通过，不代表每个账户/集群都自动可用。

| GROMACS | CPU | HIP | PME | 多 rank PME | 多 GPU | 多节点 | PMPI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026.3 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |
| 2026.4 | 是 | 是 | 是 | 是 | 是 | 是 | 是 |

2026.4 参考构建来自官方源码，通过用户级参考 module 验证；2026.4 PMPI 变体
已验证单节点和双节点/4 rank/4 GPU。它们只是用户级 module，不做系统级发布；
仓库不打包它们，空白账户必须自行构建或获取。依据、多节点/UCX 发现和新账户
最低证据要求见
[references/version-coverage.md](references/version-coverage.md)。

用户自有构建可以不使用 module：

```text
GROMACS_MODULE=""
GROMACS_GPU_MODULE=""
GROMACS_BINARY=/absolute/path/to/gmx_mpi
GROMACS_ENV_SCRIPT=/absolute/path/to/env.sh
```

## 工作流

作业调度、状态查询、等待和取消优先使用 `scnet-hpc` OpenAPI。SSH 只用于有限的
脚本上传和日志诊断。

```bash
bash scripts/validate.sh
```

应通过 `scnet-hpc` OpenAPI 在目标计算队列提交这些脚本。可设置：

```text
GROMACS_MODULE     module 名称，默认 gromacs/2026.3
GROMACS_MODULEPATH 可选的私有 modulefile 目录，用于候选构建
GROMACS_BINARY     可执行文件，默认 gmx_mpi
GROMACS_GPU_MODE   cpu 或 hip，默认 cpu
GROMACS_GPU_PME    设为 1 时增加 -pme gpu，默认 0；仅用于 PME case
GROMACS_EXPECT_GPU_ARCH  可选的期望 gfx 名称，例如 gfx906
GROMACS_EXPECT_VERSION   可选的期望 GROMACS 版本，例如 2026.3
GROMACS_ENERGY_TERMS     逗号分隔的 gmx energy 输入项
GROMACS_MPI_RANKS        MPI rank 数，默认 1
GROMACS_OMP_THREADS      每个 rank 的 OpenMP 线程数，默认 2
GROMACS_MPI_LAUNCHER     srun 或 mpirun，默认 srun
GROMACS_NPME             -npme 值；仅当 MPI rank > 1 时有效
GROMACS_EXPECT_GPU_COUNT HIP 模式期望选中的 GPU 数
GROMACS_FORCE_GPU_AWARE_MPI 设置 GMX_FORCE_GPU_AWARE_MPI=1
GROMACS_REQUIRE_GPU_AWARE_MPI 日志显示不支持 GPU-aware MPI 时失败
GROMACS_CASE_ROOT  case 目录，默认 <repo>/cases/argon8
GROMACS_CASE_GRO   输入坐标文件，默认 argon.gro
GROMACS_DEFFNM     输出前缀，默认 argon
GROMACS_RUN_ROOT   唯一可写运行目录
```

不能只根据 module 名称判断 GPU 可用；必须在计算节点确认设备可见，并确认二进制
报告 HIP 支持。PME case 需要把 `GROMACS_CASE_ROOT` 设为
`cases/ionpair_pme`，并设置 `GROMACS_CASE_GRO=ionpair.gro`、
`GROMACS_DEFFNM=ionpair`、`GROMACS_GPU_PME=1`。

单 MPI rank 使用 `-pme gpu` 时不要加 `-npme`。已安装的 GROMACS 在只请求
一个 rank 时会拒绝 `-npme`；只有真正的多 rank 作业才设置 `GROMACS_NPME`。

多 rank 时设置 `GROMACS_MPI_RANKS`、`GROMACS_OMP_THREADS` 和 launcher；
资源必须至少提供 `ranks * threads` 个 CPU。HIP 验证当前要求每个 rank 一个
DCU。PME case 设置 `GROMACS_NPME=1` 可请求独立 PME rank。

昆山参考环境 launcher 行为：

- 自建 OpenMPI 5 module 支持 Slurm PMIx。设置 `SLURM_MPI_TYPE=pmix` 后
  `srun` 可以正确连接多 rank；不设置时 `srun` 会启动 singleton rank；
- 多节点分配必须用 `#SBATCH --ntasks-per-node=...` 平衡；否则调度器可能把
  大部分 rank 放到一个节点，GROMACS 的 GPU 任务分配会失败；
- PMPI module 的平台 OpenMPI 4.1.5 没有 Slurm PMI 支持。多 rank 需要
  `mpirun` 加 MPI transport 覆盖，例如 `MPI_ENV_OMPI_MCA_PML=ob1`；
- 跨节点 UCX 在某个 HCA 路径上失败；把 `UCX_NET_DEVICES` 限制到可用 HCA 后
  UCX 通过并快于 OB1/TCP。OB1 是 fallback，不是通用最佳实践；transport/HCA
  选择应保持站点可配置。

这些是参考站点观察，不是通用 launcher 结论。跨节点运行设置 `NODES`、
`MPI_RANKS`、`MPI_RANKS_PER_NODE`，必要时设置 `SCHEDULER_OPTIONS`；runner 会
平衡分配并向 `srun` 传 `--ntasks-per-node`。

PMPI 参考 module 的多 rank 运行使用 `mpirun` 加 OB1 transport 覆盖，因为平台
UCX 路径可能在 mdrun 前失败：

```text
MPI_LAUNCHER="mpirun"
MPI_LAUNCHER_ARGS="--mca pml ob1 --mca btl self,vader,tcp"
```

`MPI_LAUNCHER_ARGS` 用于启动器命令行参数，`MPI_ENV_*` 用于环境变量。OB1 是
fallback，不是默认。

PMPI 多节点还需要 hostfile 和显式 `ib0` 接口选择，否则平台 MPI 会走管理网：

```text
mpirun --hostfile hostfile --map-by ppr:2:node --bind-to none   --mca pml ob1 --mca btl self,vader,tcp   --mca btl_tcp_if_include ib0 --mca oob_tcp_if_include ib0 -np 4 ...
```

参考 71,844 原子 Lysozyme，PMPI/OB1 多节点 21.4 ns/day，OpenMPI 5 UCX 路径
41.3 ns/day。PMPI 可用，但不是最快的多节点路径。

这些是站点观察，不是通用 launcher 结论。

## 可选的 OpenAPI runner

核心验证路径仍然是三个计算节点脚本。可选编排放在 `contrib/run_openapi.py`；它
通过已安装的 `scnet-hpc` CLI 的 `--backend openapi` 完成远端目录创建、脚本/case
上传、提交、限时等待、作业详情检查和结果下载。也可以不使用该包装脚本，直接用
`scnet-hpc` 驱动同一组脚本。包装脚本不使用 SSH，也不实现第二套凭证或传输层。它优先在同级 `../scnet-hpc`
目录查找 `scnet-hpc`，与共享 `skills/` 目录布局一致；然后回退到
`SCNET_HPC_ROOT` 和各个智能体的 skill 目录。

```bash
python3 contrib/run_openapi.py \
  --cluster <scnet-hpc-profile> \
  --profile clusters/<scnet-hpc-profile>.conf \
  --run-root /absolute/new/remote/run-root \
  --case ionpair_pme \
  --mode both \
  --download-dir ./out/gromacs-pme
```

`--mode both` 提交一个 CPU 作业和一个 HIP 作业，等待两者结束，下载
`result.txt`、版本、checksum、能量和运行日志，并调用
`compare_gromacs_energy.py`。`--mode cpu`（默认）或 `--mode hip` 只运行一个后端。
runner 会拒绝已存在的远端 run root 或本地下载目录。

把 [clusters/_template.conf](clusters/_template.conf) 复制为私有的
`clusters/<profile>.conf`，填写 CPU/DCU 队列、CPU/HIP module、CPU 数、DCU 数和
walltime。模板面向 Z100/DCU，但只是提示，不是实时可用性证据。也可以直接传
`--cpu-queue`、`--hip-queue`、`--cpu-module`、`--hip-module`、`--cpus`、
`--dcus`、`--walltime`。可选的 `GPU_ARCH` profile 字段会传给计算节点设备检查；
Z100 设置为 `GPU_ARCH="gfx906"`。`GROMACS_EXPECT_VERSION` 用于固定 module
版本，站点升级 GROMACS 时同步更新。

可选 runner 会先做只读队列/walltime preflight；失败时 best-effort 下载应用
artifact 和调度器 stdout/stderr 到本地下载目录。这些日志留在仓库外，只用于诊断。

OpenAPI 凭证只通过 `scnet-hpc` 配置；不要在仓库中写入 AK/SK、私钥或站点路径。
如果 OpenAPI 无法提供某个事实，SSH 只用于有限的诊断。

smoke harness 检查 GROMACS 2026.x 的完成标记
`Writing final coordinates.`（同时兼容旧版 `Finished mdrun`），按多列
`energy.xvg` 数据检查有限数值，记录输入和最终 checksum；PME 模式还要求日志
出现 `PME tasks will do all aspects on the GPU`。调度器显示
`COMPLETED` 还不够，workload 也必须写出 `status=passed`。

## CPU/HIP 能量比较

同一 case 分别运行 `cpu` 和 `hip` 模式，然后比较两个 run 目录：

```bash
python3 scripts/compare_gromacs_energy.py CPU_RUN_DIR HIP_RUN_DIR \
  --report comparison.txt
```

检查器要求两个 run 都有 `status=passed`、输入 checksum 相同、时间网格相同，并且
smoke 记录的能量列都是有限数值。PME 运行还比较 `Coulomb (SR)`、
`Coul. recip.`、`LJ (SR)`。逐数据点应用：

```text
|CPU - HIP| <= atol + rtol * max(|CPU|, |HIP|)
```

默认能量项 `atol=0.05 kJ/mol`、温度 `atol=0.5 K`、`rtol=1e-3`。这些默认值
是 smoke 级契约，不是生产精度规范。通过只说明这个小 case 的数值一致性，不
宣称 CPU/GPU 轨迹逐位相同。

## 多 rank、多 GPU 与性能

微 case 只验证多 rank/多 GPU 的执行路径，不代表性能。可选 runner 支持
`--mpi-ranks`、`--omp-threads`、`--mpi-launcher`、`--npme` 和
`--force-gpu-aware`。smoke 脚本会检查 MPI 进程数、请求时的 PME rank 分解、
选中的 GPU 数，以及可选的强制 GPU-aware MPI。

性能表征是独立工作。`benchmarks/catalog.json` 只提供公开 benchmark 类别和
测量字段，不作为 skill 上下文加载，也不提交性能数值；`benchmarks/observations.md`
单独保存参考站点的短小观察。扩展性结论必须使用代表性体系。

参考 2026.4 Lysozyme，71,844 原子，200 步：

| 配置 | 性能 |
| --- | ---: |
| 1 GPU | 29.0 ns/day |
| 2 GPU | 27.3 ns/day |
| 4 GPU，单节点 | 43.1 ns/day |
| 4 GPU，双节点 | 43.5 ns/day |

该小体系 2 GPU 比 1 GPU 慢，4 GPU 为次线性扩展；实测原因是体系规模、
分解/通信和 PME 开销，不是 GPU 不可用。跨节点 4 rank/2 节点传输检查：
可用 UCX HCA 路径 41.3 ns/day，OB1/TCP fallback 32.0 ns/day，默认 UCX HCA
在 mdrun 前失败。OB1 是 fallback，不是默认。强制 GPU-aware MPI 明显变慢；
没有实测不要启用。

更大的 ADH benchmark，134,177 原子，200 步：1 GPU 21.1 ns/day，2 GPU 22.7，
4 GPU 28.7，双节点/4 GPU 27.8。扩展性好于微 case，但仍为次线性；不是生产
benchmark。

还测试了启用 ROCm 的 UCX/OpenMPI 构建。GROMACS 能检测到 GPU-aware MPI
（`MPI library: MPI (GPU-aware: HIP)`、`GPU direct communication will be used`），
但 direct 路径远慢于 host-staged：双节点/4 GPU Lysozyme 约 1.7 ns/day，
单节点/4 GPU 约 0.97 ns/day，而 host-staged 为 43.5/43.1 ns/day。限制
`UCX_TLS=rocm_ipc,sm,self,tcp` 后达到 18.1 ns/day，仍低于 host-staged。
更大的 134k 原子 ADH 也只有 0.57 ns/day（host-staged 28.7），约慢 50 倍，
所以这不只是小体系问题。该 DTK/HIP/mlx5 路径还需要更多 UCX 调优，默认保持关闭。

检查器依赖当前 smoke 脚本写出的 `inputs.sha256`；旧版脚本的历史 run 没有该文件。

## 昆山实测范围

参考环境在 gfx906 上实测了 GROMACS 2026.3 和 GROMACS 2026.4 参考构建，
OpenMPI 5.0.11、DTK 26.04、HIP 6.3.26113、rocFFT 1.0.28。已验证路径包括
单 rank CPU/HIP、PME GPU、双 rank PME 分解、双 rank/双 GPU HIP 和 PME、
微 case 强制 GPU-aware MPI、PMPI 单 rank/多 rank/多 GPU，以及双节点/4 GPU。

2026.4 构建来自官方源码，通过私有 module 路径验证；它不是站点发布 module，
并且需要本地工具链兼容处理。空白账户必须提供自己的 module 或构建，仓库不
打包 GROMACS。详见 [references/version-coverage.md](references/version-coverage.md)。

正常 smoke 作业都以 `status=passed` 完成，比较通过。这些是短时、微 case
结果，不代表生产精度。性能观察是独立的参考站点测量，不是生产 benchmark，
也不是跨站点保证。

## 提炼的 DCU 移植经验

GROMACS 是成熟应用验证，不是从零编写新 kernel 的移植。仍应保留这些通用经验：
以目标计算节点为事实来源，记录 `gfx906` 等架构，保留 CPU 数值 oracle，把设备/
运行时检查和正确性检查分开，检查有限值和物理不变量，并让 workload 与调度器都
传播失败状态。没有目标探针时，不要把 CUDA、ROCm 或新 GPU 的能力外推到 DTK。

## 本地校验与宿主系统

SCNet 计算节点是 Linux；所有提交的作业都运行 Linux bash。本地智能体可以是
Windows、macOS 或 Linux：

- `contrib/run_openapi.py` 和 `scripts/compare_gromacs_energy.py` 使用 Python
  3.8+，跨平台。
- 远端路径始终是 POSIX。`--run-root` 即使从 Windows 本地 shell 传入也会
  规范化为 POSIX；不要把 Windows 盘符路径当作远端路径。
- 跨平台校验命令：
  ```bash
  python3 scripts/validate.py
  ```
- `bash scripts/validate.sh` 是薄包装。Windows 上如需可选的 `bash -n` 语法
  检查，请使用 Git Bash 或 WSL；没有 bash 时，Python 校验器会跳过该检查，
  仍然校验仓库文件。

只检查脚本和 bundled 输入，不在本机编译或运行 GROMACS。

MIT 许可证。
