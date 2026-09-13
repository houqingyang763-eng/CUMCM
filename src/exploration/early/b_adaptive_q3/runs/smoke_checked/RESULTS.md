# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| adaptive | 4 | 4 | 5364.87 | 6840.55 | 6851.41 | 3.58 |
| reference | 4 | 4 | 6681.56 | 7199.62 | 7204.80 | 1.80 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_zero_100 | adaptive | True | 6851.41 | 317 | 95 | 0 | True | 1.90 |
| uniform_zero_100 | reference | True | 7170.30 | 88 | 7 | 324 | True | 0.51 |
| edge_biased_101 | adaptive | True | 6779.04 | 178 | 51 | 0 | True | 0.24 |
| edge_biased_101 | reference | True | 7204.80 | 105 | 7 | 321 | True | 0.37 |
| cluster_smooth_102 | adaptive | True | 3633.71 | 120 | 26 | 0 | False | 0.69 |
| cluster_smooth_102 | reference | True | 6564.07 | 58 | 7 | 341 | True | 0.56 |
| line_hashed_103 | adaptive | True | 4195.33 | 113 | 36 | 0 | False | 0.75 |
| line_hashed_103 | reference | True | 5787.07 | 72 | 7 | 245 | True | 0.36 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
