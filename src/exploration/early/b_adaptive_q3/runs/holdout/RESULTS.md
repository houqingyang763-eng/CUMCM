# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| adaptive | 24 | 24 | 4719.27 | 6966.78 | 7102.66 | 19.36 |
| reference | 24 | 24 | 7060.73 | 9010.95 | 9266.20 | 13.81 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_smooth_10010 | adaptive | True | 5215.18 | 184 | 34 | 0 | False | 0.70 |
| uniform_smooth_10010 | reference | True | 7913.65 | 93 | 7 | 405 | True | 0.66 |
| uniform_smooth_10011 | adaptive | True | 6073.26 | 267 | 76 | 0 | False | 1.10 |
| uniform_smooth_10011 | reference | True | 8885.23 | 101 | 7 | 522 | True | 0.90 |
| uniform_biased_10012 | adaptive | True | 4934.10 | 164 | 38 | 0 | False | 0.68 |
| uniform_biased_10012 | reference | True | 9033.13 | 83 | 7 | 513 | True | 0.86 |
| uniform_biased_10013 | adaptive | True | 6288.21 | 232 | 66 | 0 | True | 1.23 |
| uniform_biased_10013 | reference | True | 9266.20 | 93 | 7 | 543 | True | 0.99 |
| uniform_hashed_10014 | adaptive | True | 5911.75 | 175 | 32 | 0 | False | 0.70 |
| uniform_hashed_10014 | reference | True | 8102.09 | 80 | 7 | 446 | True | 0.70 |
| uniform_hashed_10015 | adaptive | True | 5557.02 | 186 | 49 | 0 | False | 1.94 |
| uniform_hashed_10015 | reference | True | 7889.17 | 64 | 7 | 386 | True | 0.65 |
| edge_smooth_10016 | adaptive | True | 4441.96 | 155 | 51 | 0 | False | 0.31 |
| edge_smooth_10016 | reference | True | 8056.38 | 98 | 7 | 389 | True | 0.47 |
| edge_smooth_10017 | adaptive | True | 6524.27 | 213 | 63 | 0 | True | 0.29 |
| edge_smooth_10017 | reference | True | 6164.07 | 113 | 7 | 247 | True | 0.26 |
| edge_biased_10018 | adaptive | True | 7044.87 | 205 | 61 | 0 | True | 0.37 |
| edge_biased_10018 | reference | True | 6526.97 | 112 | 7 | 265 | True | 0.35 |
| edge_biased_10019 | adaptive | True | 6521.86 | 173 | 46 | 0 | True | 0.39 |
| edge_biased_10019 | reference | True | 6829.40 | 110 | 7 | 283 | True | 0.30 |
| edge_hashed_10020 | adaptive | True | 5779.41 | 171 | 33 | 0 | False | 0.22 |
| edge_hashed_10020 | reference | True | 7212.15 | 108 | 7 | 306 | True | 0.34 |
| edge_hashed_10021 | adaptive | True | 7102.66 | 173 | 41 | 0 | True | 0.27 |
| edge_hashed_10021 | reference | True | 7807.74 | 105 | 7 | 348 | True | 0.39 |
| cluster_smooth_10022 | adaptive | True | 3802.18 | 109 | 25 | 0 | False | 0.91 |
| cluster_smooth_10022 | reference | True | 7901.65 | 54 | 7 | 445 | True | 0.80 |
| cluster_smooth_10023 | adaptive | True | 1707.54 | 79 | 19 | 0 | False | 2.08 |
| cluster_smooth_10023 | reference | True | 7192.66 | 20 | 1 | 535 | True | 0.99 |
| cluster_biased_10024 | adaptive | True | 3739.22 | 134 | 23 | 0 | False | 0.39 |
| cluster_biased_10024 | reference | True | 5703.31 | 85 | 7 | 280 | True | 0.47 |
| cluster_biased_10025 | adaptive | True | 3533.58 | 130 | 23 | 0 | False | 0.74 |
| cluster_biased_10025 | reference | True | 6034.29 | 78 | 7 | 300 | True | 0.53 |
| cluster_hashed_10026 | adaptive | True | 3761.02 | 127 | 21 | 0 | False | 0.55 |
| cluster_hashed_10026 | reference | True | 6415.33 | 73 | 7 | 340 | True | 0.60 |
| cluster_hashed_10027 | adaptive | True | 3736.06 | 115 | 22 | 0 | False | 0.57 |
| cluster_hashed_10027 | reference | True | 6612.02 | 67 | 7 | 340 | True | 0.59 |
| line_smooth_10028 | adaptive | True | 4307.13 | 141 | 35 | 0 | False | 0.90 |
| line_smooth_10028 | reference | True | 5380.02 | 68 | 7 | 228 | True | 0.38 |
| line_smooth_10029 | adaptive | True | 3535.32 | 129 | 32 | 0 | False | 2.20 |
| line_smooth_10029 | reference | True | 8069.96 | 56 | 7 | 490 | True | 0.86 |
| line_biased_10030 | adaptive | True | 1979.01 | 99 | 28 | 0 | False | 1.23 |
| line_biased_10030 | reference | True | 8154.73 | 50 | 5 | 574 | True | 0.91 |
| line_biased_10031 | adaptive | True | 3446.41 | 146 | 25 | 0 | False | 0.51 |
| line_biased_10031 | reference | True | 5659.30 | 89 | 7 | 275 | True | 0.43 |
| line_hashed_10032 | adaptive | True | 4305.89 | 144 | 29 | 0 | False | 0.46 |
| line_hashed_10032 | reference | True | 4432.55 | 88 | 7 | 152 | True | 0.22 |
| line_hashed_10033 | adaptive | True | 4014.47 | 133 | 22 | 0 | False | 0.62 |
| line_hashed_10033 | reference | True | 4215.40 | 85 | 7 | 112 | True | 0.18 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
