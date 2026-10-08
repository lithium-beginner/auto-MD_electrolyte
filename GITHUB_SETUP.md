# 从 GitHub 恢复完整项目

网页上传版同时提供可浏览的源码及完整归档。完整目录（包括参数库、模块、模板、测试和示例）位于 `auto-MD_electrolyte_source.zip`。

在新的空目录中解压完整归档即可安装和运行：

```bash
mkdir auto-md-working
cd auto-md-working
unzip /path/to/auto-MD_electrolyte_source.zip
conda env create -f environment.yml
conda activate electrolyte-md
python -m unittest discover -s tests -v
python workflow.py examples/ec_emc_lipf6.json --workdir workdir --library library/profiles/gaff2-am1bcc-fullcharge-v1
```

`electrolyte_parameter_library_v0.2.zip` 为独立参数库归档，保留来源、许可证、参数和验证记录。参数库尚未经实验物性验证，SSIP/CIP/AGG 严格分类尚未实现。当前默认模拟时长适合软件检查，定量性质需要延长、重复模拟并检查收敛。

本地 Python/AmberTools 环境、上游完整仓库、运行轨迹及缓存未上传。
