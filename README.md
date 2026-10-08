# 电解液经典 MD 自动化工作流

第一版实现：标准化 JSON → 配方单元计数 → RDKit 盐拆分 → GAFF2/参数库 → Packmol → GROMACS `.top/.itp` → OpenMM → RDF/溶剂化/输运分析。

已新增实际电解液参数库：44 个组分身份、38 个有数值参数的组分、52 个参数包和 6 种完整锂盐，见 `library/README.md`。它是有来源、经过结构/软件检查的候选库，尚未完成实验性质验证。GAFF2 与 ComBat OPLS 使用各自 profile；Li⁺的模型与迁移限制记录在库中。当前引擎是 **OpenMM**；没有实现 LAMMPS 转换器。

## 安装

推荐在 Linux GPU 工作站使用 conda/mamba：

```bash
conda env create -f environment.yml
conda activate electrolyte-md
python -m unittest discover -s tests -v
```

AmberTools/ACPYPE 的平台支持由上游包决定；macOS 可用于配方与分析，生产计算优先 Linux。`pip install .` 安装 Python 库依赖；Packmol、AmberTools 与 ACPYPE 仍需另行安装。首次验证后自行导出环境锁文件；本项目不声称宽版本依赖已构成锁定环境。

## 从配方到结果

```bash
python recipe_generate.py 'examples/*.json' --workdir workdir
cd workdir/EC_EMC_LiPF6
python prepare_system.py --library /absolute/path/to/verified_library --auto-parameterize
python run_md.py
python analyze.py
```

批量连续执行（逐配方运行，失败日志保留，其余配方继续）：

```bash
python workflow.py 'examples/*.json' --workdir workdir --library /absolute/path/to/verified_library --auto-parameterize
```

支持多个 JSON 参数、glob、单个配方对象或配方对象列表。先验证所有配方再生成；已有目录不覆盖。各工作目录带脚本和模块副本，可以单独搬到计算节点。默认只生成目录，不启动昂贵计算。

### JSON 合约

完整例子见 `examples/ec_emc_lipf6.json`。

- 顶层：`recipe_name`、`time`、`solvents`、`additives`、`salts`、`simulation`。三个成分数组都必须存在，可以为空。
- 成分：`name`、`full_name`、`smiles`、`mass_fraction` ∈ [0,1]、`molar_mass` > 0（g/mol）、`purity` ∈ [0,1]。
- 质量分数总和必须为 1（容差 1e-6）。`name` 是安全目录/缩写标识；中文名称放在 `full_name`。
- `simulation.units` 必须显式声明 K、bar、mol/L、nm；`box_nm` 是三维正交盒边长，非体积。
- 温度、压力、步长、截断半径、阶段步数、报告间隔与种子均校验。`platform` 可用 CPU、CUDA 等当前 OpenMM 已安装平台。
- `total_molecules` 明确定义为**拆盐之前的配方单元总数**，盐展开后粒子分子数增加；实际数量写入 manifest。

计算：在 1 g 名义原料基准上 `n_i = w_i × purity_i / M_i`，归一化并使用最大余数法分配整数配方单元。每种盐的所有离子片段继承同一个配方单元数，因此多价盐也保持化学计量与电中性。极少量成分若被取整为零会报错，要求扩大体系。

纯度默认 `reject`：必须显式加入杂质成分。选择 `active_renormalize` 才会忽略未知杂质、按有效成分重新归一化；这不是实际杂质模型。输入摩尔质量作为配方计数依据，用户需确认与 SMILES 对应。

盒尺寸与组成确定初始密度及实际盐浓度。程序不会为了凑成宣称的 1 mol/L 同时悄悄改动质量分数。浓度写入 manifest；NPT 后最终浓度重新计算。此版本不接受独立目标浓度约束，避免超定输入。

盐先按分子图的不连通片段拆分，按 RDKit **原子形式电荷之和**分类，而非简单搜索字符串中的 +/-。能正确处理多价盐、重复阴离子和中性两性离子；盐中存在中性溶剂合物片段时要求单独建模。不支持反应、解离动力学、电子转移或电极界面。

### 参数库

每个分子以 canonical SMILES 的 SHA256 前 16 位定位：

```bash
python -c 'from electrolyte.parameters import key; print(key("[Li+]"))'
```

可用导入工具将已经审核的单分子参数放入正确位置（盐的阳/阴离子分别导入）：

```bash
python register_parameters.py --smiles '[Li+]' --source '实际论文 DOI / 参数版本 / 电荷方案' --itp li.itp --pdb li.pdb --atomtypes atomtypes.atp --library verified_library
```

目录约定：

```text
verified_library/<hash>/
  metadata.json
  molecule.pdb
  molecule.itp
  atomtypes.atp
```

`metadata.json` 示例（此处不提供任何物理数值）：

```json
{"smiles":"[Li+]", "forcefield":"GAFF2", "source":"论文 DOI / 参数库版本 / 电荷方案"}
```

要求：单个 moleculetype；显式原子质量、电荷；PDB 原子顺序/名称严格匹配 `[ atoms ]`；原子数、元素与 SMILES 对应；电荷和与形式电荷一致；有来源。ITP 应展开条件宏与嵌套 include；不要带 `[ defaults ]`。`atomtypes.atp` 在本项目是带 `[ atomtypes ]` 的 GROMACS include，**不同于原生 `.atp` 的原子名/质量表**。这是为满足 .atp 引用需求设置的明确文件约定。库条目还需显式 PDB CONECT 连接，并与 ITP 键图匹配。

默认 GAFF2 profile 的参数必须兼容模板的 AMBER 组合规则与 1–4 缩放：comb-rule=2，fudgeLJ=0.5，fudgeQQ=1/1.2。metadata 的 GAFF2 标签不是兼容性的科学证明。不同力场、离子模型、缩放电荷不应直接混用；电荷缩放尚未实现。ComBat OPLS profile 通过独立模板使用 comb-rule=3 和 Coulomb 1–4=0.5，不能使用默认 GAFF2 模板。

未知多原子分子可显式开启 `--auto-parameterize`：RDKit 生成 3D，ACPYPE/AmberTools 生成 GAFF2/AM1-BCC，保存命令和日志；覆盖失败则停止。单原子离子永远要求参数库；新内置库的 Li⁺候选有单独来源说明。复杂无机阴离子不保证 GAFF2 覆盖，优先提供论文参数。坐标来自参数化后的 GRO，避免 RDKit 和拓扑原子排序错配。参数结构校验不能替代键连接与构象、化学参数的人工审核。

### MD 阶段

最小化 → NVT → NPT → 固定最终 NPT 体积的 NVT production。PME、氢键约束、LangevinMiddle 恒温器。模板默认 1 fs；生产长度只是起步示例，不是收敛承诺。初始盒必须满足截断半径要求，平衡后体积也应审查。已准备文件有 SHA256 校验，输入改动会阻止运行。输出包括轨迹、热力学 CSV、状态 XML、checkpoint 和版本/种子/平台元数据。

当前版本防止覆盖已有模拟输出；保存 checkpoint 便于人工恢复，但尚无自动续跑/断点拼接功能。失败后保留日志，需检查后使用新的工作目录。NPT 自动选用最后体积而不是经统计确认的平均体积，正式研究应增加平衡诊断和体积采样。Langevin 摩擦影响输运，正式结果需检查摩擦依赖或增加合适的输运恒温方案。

### 分析输出

`results/summary.json` + CSV：

- 阳离子–配位原子、阳离子–阴离子标记原子 RDF（Å）。
- 配位原子数分布、唯一分子计数的溶剂化壳层组成/比例。
- 邻近阴离子分子数量 0/1/≥2 的比例；不冒充严格 SSIP/CIP/AGG 聚类识别。
- 各组分质心 MSD 与扩散系数（m²/s）；去除整体质心漂移；多时间起点平均。
- Nernst–Einstein 电导率和包含离子相关运动的集体 Einstein 电导率（S/m）、两者比值与拟合 R²。
- NPT 后实际盐浓度（mol/L）。
- 密度、温度、体积、势能的均值/标准差和前后半段对比（用于诊断，不自动判定平衡）。
- 可选压力张量 CSV 的 Green–Kubo 黏度积分曲线（Pa·s）。OpenMM 默认 reporter **不输出完整压力张量**，因此默认不计算黏度。

分析配置位于工作目录 `templates/analysis.json`；针对配方修改选择语句、配位半径、RDF 范围和拟合区间。默认供体选择为 O/F，阳离子为 Li，阴离子标记为 P/S，只是 EC/EMC/常见锂盐的起点。接触类别使用供体选择里的阴离子原子定义；选择范围必须按实际体系修改，例如避免把不参与配位的 O/F 原子混入。

输运分析限固定正交盒生产轨迹；采样间隔必须足够短，避免分子在帧间移动超过半个盒。拟合区间按最大滞后时间的比例指定，不自动判断扩散区间；负斜率保留以暴露不可靠估计。目前不提供置信区间，必须对独立重复模拟做分块与长度收敛分析。纯溶剂也可分析扩散与热力学统计；没有阳离子时跳过阳离子 RDF 和壳层统计。黏度需可靠的 NVT 压力张量数据及积分平台，禁止从 MSD 或单个标量压力伪造黏度。

```bash
python analyze.py --stress-csv stress.csv
# CSV 表头：time_ps,Pxy_bar,Pxz_bar,Pyz_bar
```

## 开源调研与路线

独立实现本项目，使用上游工具接口，没有复制第三方源码：

- [mdgo](https://github.com/htz1992213/mdgo)：电解液体系搭建与分析，适合参考分析模块；查询时仓库页面未成功读取，概述来自 [PyPI](https://pypi.org/project/mdgo/)。
- [PEMD](https://github.com/HouGroup/PEMD)：聚合物电解质建模、力场、模拟和分析。
- [fftool](https://github.com/paduagroup/fftool)：参数库、Packmol 和多引擎输入生成，可作为后续 LAMMPS 路线。
- [ACPYPE](https://github.com/alanwilter/acpype)：Antechamber/GAFF 拓扑生成与格式转换；GPL-3.0，作为外部程序调用，分发前仍需检查依赖许可证。
- [OpenMM GromacsTopFile](https://docs.openmm.org/latest/api-python/generated/openmm.app.gromacstopfile.GromacsTopFile.html)：读取 GROMACS 拓扑并创建 OpenMM System。

后续优先级：真实参数库和单分子/小盒参考验证 → 密度与溶剂化验证 → 独立副本/误差条 → 压力张量 reporter 与黏度 → 自动续跑和调度器 → LAMMPS 后端 → 严格离子簇/停留时间/迁移数分析。真实电解液的预测精度主要由参数、电荷模型、平衡与采样决定，流程自动化本身不能保证。
