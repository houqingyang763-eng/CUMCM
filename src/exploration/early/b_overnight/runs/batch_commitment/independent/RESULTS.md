# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| committed_base | 12 | 12 | 3991.50 | 5456.55 | 5480.62 | 6.13 |
| completion | 12 | 12 | 3859.10 | 4742.52 | 4757.48 | 21.45 |
| configured | 12 | 12 | 3911.00 | 4790.29 | 4790.50 | 20.29 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_smooth_94100 | committed_base | True | 3578.20 | 158 | 33 | 0 | False | 0.92 |
| uniform_smooth_94100 | completion | True | 3722.56 | 123 | 23 | 0 | False | 2.39 |
| uniform_smooth_94100 | configured | True | 3738.35 | 122 | 22 | 0 | False | 2.36 |
| uniform_biased_94101 | completion | True | 4730.28 | 174 | 24 | 3 | False | 0.94 |
| uniform_biased_94101 | configured | True | 4651.55 | 164 | 25 | 5 | False | 1.08 |
| uniform_biased_94101 | committed_base | True | 4670.47 | 237 | 53 | 0 | False | 0.71 |
| uniform_hashed_94102 | configured | True | 4790.50 | 164 | 28 | 2 | False | 1.07 |
| uniform_hashed_94102 | committed_base | True | 4747.56 | 177 | 28 | 0 | False | 0.34 |
| uniform_hashed_94102 | completion | True | 4250.72 | 169 | 27 | 4 | False | 1.55 |
| edge_smooth_94103 | committed_base | True | 5436.86 | 201 | 73 | 0 | False | 0.32 |
| edge_smooth_94103 | completion | True | 4613.14 | 136 | 27 | 0 | False | 0.40 |
| edge_smooth_94103 | configured | True | 4640.71 | 141 | 29 | 0 | False | 0.39 |
| edge_biased_94104 | completion | True | 4685.78 | 137 | 25 | 0 | False | 0.42 |
| edge_biased_94104 | configured | True | 4690.98 | 138 | 26 | 0 | False | 0.42 |
| edge_biased_94104 | committed_base | True | 5161.80 | 159 | 35 | 0 | False | 0.17 |
| edge_hashed_94105 | configured | True | 4790.11 | 145 | 28 | 2 | False | 0.41 |
| edge_hashed_94105 | committed_base | True | 5480.62 | 158 | 32 | 0 | False | 0.13 |
| edge_hashed_94105 | completion | True | 4757.48 | 146 | 27 | 2 | False | 0.40 |
| cluster_smooth_94106 | committed_base | True | 3231.76 | 94 | 18 | 0 | False | 0.61 |
| cluster_smooth_94106 | completion | True | 3255.07 | 105 | 15 | 0 | False | 2.44 |
| cluster_smooth_94106 | configured | True | 3299.64 | 103 | 15 | 0 | False | 2.14 |
| cluster_biased_94107 | completion | True | 1317.67 | 73 | 12 | 0 | False | 3.57 |
| cluster_biased_94107 | configured | True | 1331.00 | 74 | 10 | 0 | False | 3.58 |
| cluster_biased_94107 | committed_base | True | 1337.36 | 73 | 13 | 0 | False | 1.63 |
| cluster_hashed_94108 | configured | True | 3412.05 | 143 | 15 | 0 | False | 1.84 |
| cluster_hashed_94108 | committed_base | True | 3254.90 | 126 | 17 | 0 | False | 0.34 |
| cluster_hashed_94108 | completion | True | 3406.05 | 142 | 15 | 0 | False | 1.82 |
| line_smooth_94109 | committed_base | True | 3802.49 | 143 | 25 | 0 | False | 0.39 |
| line_smooth_94109 | completion | True | 4374.27 | 169 | 25 | 2 | False | 3.03 |
| line_smooth_94109 | configured | True | 4332.13 | 152 | 24 | 1 | False | 2.53 |
| line_biased_94110 | completion | True | 3784.88 | 130 | 22 | 0 | False | 1.39 |
| line_biased_94110 | configured | True | 3782.84 | 128 | 20 | 0 | False | 1.40 |
| line_biased_94110 | committed_base | True | 3978.37 | 144 | 22 | 0 | False | 0.28 |
| line_hashed_94111 | configured | True | 3472.15 | 147 | 24 | 6 | False | 3.07 |
| line_hashed_94111 | committed_base | True | 3217.62 | 135 | 29 | 0 | False | 0.27 |
| line_hashed_94111 | completion | True | 3411.36 | 141 | 25 | 4 | False | 3.10 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
