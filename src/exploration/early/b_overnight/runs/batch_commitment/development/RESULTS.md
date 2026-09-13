# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| base | 4 | 4 | 5101.45 | 6751.99 | 6934.51 | 4.22 |
| committed_base | 4 | 4 | 4350.22 | 5408.34 | 5419.65 | 2.34 |
| committed_completion | 4 | 4 | 4331.65 | 4633.90 | 4639.58 | 7.60 |
| committed_q4_31 | 1 | 1 | 11595.41 | 11595.41 | 11595.41 | 3.85 |
| completion | 4 | 4 | 4331.65 | 4633.90 | 4639.58 | 7.65 |
| q4_31 | 1 | 1 | 11595.41 | 11595.41 | 11595.41 | 4.86 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_smooth_43100 | base | True | 5717.69 | 229 | 50 | 0 | False | 2.64 |
| uniform_smooth_43100 | committed_base | True | 5344.26 | 218 | 39 | 0 | False | 1.20 |
| uniform_smooth_43100 | completion | True | 4639.58 | 175 | 23 | 0 | False | 2.07 |
| uniform_smooth_43100 | committed_completion | True | 4639.58 | 175 | 23 | 0 | False | 2.09 |
| edge_biased_43101 | base | True | 6934.51 | 223 | 91 | 0 | True | 0.41 |
| edge_biased_43101 | committed_base | True | 5419.65 | 221 | 94 | 0 | False | 0.37 |
| edge_biased_43101 | completion | True | 4601.73 | 135 | 24 | 1 | False | 0.37 |
| edge_biased_43101 | committed_completion | True | 4601.73 | 135 | 24 | 1 | False | 0.36 |
| cluster_hashed_43102 | base | True | 3603.69 | 115 | 20 | 0 | False | 0.46 |
| cluster_hashed_43102 | committed_base | True | 3537.81 | 120 | 19 | 0 | False | 0.38 |
| cluster_hashed_43102 | completion | True | 3891.51 | 133 | 21 | 0 | False | 2.42 |
| cluster_hashed_43102 | committed_completion | True | 3891.51 | 133 | 21 | 0 | False | 2.39 |
| line_hashed_43103 | base | True | 4149.90 | 124 | 28 | 0 | False | 0.71 |
| line_hashed_43103 | committed_base | True | 3099.15 | 108 | 19 | 0 | False | 0.39 |
| line_hashed_43103 | completion | True | 4193.78 | 136 | 24 | 2 | False | 2.78 |
| line_hashed_43103 | committed_completion | True | 4193.78 | 136 | 24 | 2 | False | 2.76 |
| q4_uniform_random_smooth_43110 | q4_31 | True | 11595.41 | 321 | 64 | 174 | False | 4.86 |
| q4_uniform_random_smooth_43110 | committed_q4_31 | True | 11595.41 | 321 | 64 | 174 | False | 3.85 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
