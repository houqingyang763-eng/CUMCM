# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 3 | 3 | 4869.36 | 6520.67 | 6779.04 | 1.67 |
| completion_cost | 3 | 3 | 4476.98 | 5705.10 | 5873.99 | 9.67 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| edge_biased_101 | baseline | True | 6779.04 | 178 | 51 | 0 | True | 0.24 |
| edge_biased_101 | completion_cost | True | 5873.99 | 163 | 32 | 0 | False | 0.37 |
| cluster_smooth_102 | baseline | True | 3633.71 | 120 | 26 | 0 | False | 0.70 |
| cluster_smooth_102 | completion_cost | True | 3371.84 | 127 | 17 | 0 | False | 4.03 |
| line_hashed_103 | baseline | True | 4195.33 | 113 | 36 | 0 | False | 0.73 |
| line_hashed_103 | completion_cost | True | 4185.10 | 149 | 29 | 3 | False | 5.27 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
