#!/bin/bash
# 4 温度 × 2 独立种子，8 块 GPU 一对一并行
export PATH="/home/gaoxt/miniconda3/bin:$PATH"
source /home/gaoxt/miniconda3/etc/profile.d/conda.sh
conda activate electrolyte-md
python -c "import openmm" || { echo "环境未激活"; exit 1; }

ROOT="/home/gaoxt/projects/AutoMd/auto-MD_electrolyte"
cd "$ROOT"
mkdir -p logs_v2
: > logs_v2/completion.log

runs=(T00C_s1 T00C_s2 T25C_s1 T25C_s2 T45C_s1 T45C_s2 T60C_s1 T60C_s2)

echo "提交 ${#runs[@]} 个任务, 开始: $(date '+%F %T')"
for i in "${!runs[@]}"; do
  r="${runs[$i]}"
  (
    export CUDA_VISIBLE_DEVICES=$i
    cd "$ROOT/runs_v2/$r"
    start=$(date +%s)
    if python run_md.py > "$ROOT/logs_v2/${r}_md.log" 2>&1; then
      echo "MD_OK $r $(( ($(date +%s)-start)/60 ))min" >> "$ROOT/logs_v2/completion.log"
      if python analyze.py > "$ROOT/logs_v2/${r}_analyze.log" 2>&1; then
        echo "ANALYZE_OK $r" >> "$ROOT/logs_v2/completion.log"
      else
        echo "ANALYZE_FAIL $r" >> "$ROOT/logs_v2/completion.log"
      fi
    else
      echo "MD_FAIL $r" >> "$ROOT/logs_v2/completion.log"
    fi
  ) &
  echo "  GPU $i <- $r"
done
wait
echo "全部结束: $(date '+%F %T')"
cat logs_v2/completion.log
