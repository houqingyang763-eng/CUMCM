# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| adaptive | 12 | 12 | 4726.04 | 6804.75 | 7251.90 | 8.89 |
| reference | 12 | 12 | 6849.37 | 9258.59 | 9345.73 | 6.16 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_smooth_110 | adaptive | True | 5215.12 | 162 | 44 | 0 | False | 1.14 |
| uniform_smooth_110 | reference | True | 9187.30 | 82 | 7 | 526 | True | 0.94 |
| uniform_biased_111 | adaptive | True | 4665.40 | 220 | 84 | 0 | False | 2.03 |
| uniform_biased_111 | reference | True | 9345.73 | 64 | 7 | 554 | True | 0.89 |
| uniform_hashed_112 | adaptive | True | 4999.17 | 169 | 27 | 0 | False | 0.42 |
| uniform_hashed_112 | reference | True | 6163.56 | 93 | 7 | 253 | True | 0.41 |
| edge_smooth_113 | adaptive | True | 6438.91 | 150 | 26 | 0 | True | 0.23 |
| edge_smooth_113 | reference | True | 6577.87 | 115 | 7 | 259 | True | 0.27 |
| edge_biased_114 | adaptive | True | 6152.48 | 204 | 40 | 0 | True | 0.47 |
| edge_biased_114 | reference | True | 6747.12 | 105 | 7 | 309 | True | 0.36 |
| edge_hashed_115 | adaptive | True | 7251.90 | 181 | 38 | 0 | True | 0.21 |
| edge_hashed_115 | reference | True | 7159.82 | 105 | 7 | 315 | True | 0.35 |
| cluster_smooth_116 | adaptive | True | 3901.92 | 120 | 24 | 0 | False | 1.12 |
| cluster_smooth_116 | reference | True | 7374.79 | 60 | 7 | 385 | True | 0.67 |
| cluster_biased_117 | adaptive | True | 3496.25 | 107 | 21 | 0 | False | 1.28 |
| cluster_biased_117 | reference | True | 8638.06 | 54 | 7 | 530 | True | 0.92 |
| cluster_hashed_118 | adaptive | True | 1531.66 | 69 | 19 | 0 | False | 0.69 |
| cluster_hashed_118 | reference | True | 6300.68 | 43 | 5 | 330 | True | 0.54 |
| line_smooth_119 | adaptive | True | 4019.76 | 159 | 36 | 0 | False | 0.54 |
| line_smooth_119 | reference | True | 3725.77 | 88 | 7 | 76 | True | 0.11 |
| line_biased_120 | adaptive | True | 5010.52 | 147 | 26 | 0 | False | 0.39 |
| line_biased_120 | reference | True | 5875.12 | 86 | 7 | 278 | True | 0.41 |
| line_hashed_121 | adaptive | True | 4029.38 | 136 | 26 | 0 | False | 0.36 |
| line_hashed_121 | reference | True | 5096.60 | 78 | 7 | 202 | True | 0.28 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
