# scnet-gromacs

[English](README.md) | 中文

当前版本：0.4.0

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
- 调度器终态和 workload 退出码。

CPU 运行是数值 oracle。GPU 运行只证明集成和运行时，不宣称逐位相同或生产性能。
浮点差异必须结合容差和物理合理性报告。

bundled case 只是 smoke test，不能证明多节点扩展、PME 分解、GPU-aware MPI、
PMPI 变体或生产规模精度。

## 工作流

作业调度、状态查询、等待和取消优先使用 `scnet-hpc` OpenAPI。SSH 只用于有限的
脚本上传和日志诊断。

```bash
bash scripts/validate.sh
```

应通过 `scnet-hpc` OpenAPI 在目标计算队列提交这些脚本。可设置：

```text
GROMACS_MODULE     module 名称，默认 gromacs/2026.3
GROMACS_BINARY     可执行文件，默认 gmx_mpi
GROMACS_GPU_MODE   cpu 或 hip，默认 cpu
GROMACS_GPU_PME    设为 1 时增加 -pme gpu，默认 0；仅用于 PME case
GROMACS_EXPECT_GPU_ARCH  可选的期望 gfx 名称，例如 gfx906
GROMACS_EXPECT_VERSION   可选的期望 GROMACS 版本，例如 2026.3
GROMACS_NPME       可选 -npme 值；仅用于真正的多 rank 作业
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
`Potential`、`Kinetic En.`、`Temperature` 都是有限数值。逐数据点应用：

```text
|CPU - HIP| <= atol + rtol * max(|CPU|, |HIP|)
```

默认能量项 `atol=0.05 kJ/mol`、温度 `atol=0.5 K`、`rtol=1e-3`。这些默认值
是 smoke 级契约，不是生产精度规范。通过只说明这个小 case 的数值一致性，不
宣称 CPU/GPU 轨迹逐位相同。

检查器依赖当前 smoke 脚本写出的 `inputs.sha256`；旧版脚本的历史 run 没有该文件。

## 昆山实测范围

已安装的昆山 module 在 gfx906 上实测：GROMACS 2026.3、GCC 16.2、
OpenMPI 5.0.11、DTK 26.04、HIP 6.3.26113、rocFFT 1.0.28。Argon CPU/HIP
smoke 和离子对 PME CPU/HIP smoke 都以 `status=passed` 完成，并通过容差检查。
PME 运行选择 1 个 GPU，并报告 PME 在 GPU 上执行。OpenAPI 优先 runner 也在两个
case 上完成端到端实测，包括远端上传、提交、等待、artifact 下载和比较。这些均为
单节点、单 rank、20 步 smoke 结果，不覆盖性能或更大体系。

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
