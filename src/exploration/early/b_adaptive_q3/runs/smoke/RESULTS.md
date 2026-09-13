# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| adaptive | 4 | 4 | 5420.76 | 6948.14 | 6982.06 | 4.19 |
| reference | 4 | 4 | 6445.31 | 7702.52 | 7898.40 | 2.79 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_zero_100 | adaptive | True | 6755.92 | 347 | 116 | 0 | True | 2.67 |
| uniform_zero_100 | reference | True | 7898.40 | 88 | 7 | 534 | True | 0.85 |
| edge_biased_101 | adaptive | True | 6982.06 | 215 | 79 | 0 | True | 0.35 |
| edge_biased_101 | reference | True | 6592.53 | 105 | 7 | 302 | True | 0.35 |
| cluster_smooth_102 | adaptive | True | 3633.71 | 120 | 26 | 0 | False | 0.73 |
| cluster_smooth_102 | reference | True | 6454.82 | 58 | 7 | 604 | True | 1.06 |
| line_hashed_103 | adaptive | True | 4311.35 | 134 | 40 | 0 | False | 0.44 |
| line_hashed_103 | reference | True | 4835.47 | 72 | 7 | 366 | True | 0.52 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
