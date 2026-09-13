# 第三问本地原型结果

本文件由 run_local.py 生成。自建案例和自建误差场，不是官方成绩；没有稀有失败概率保证。

| 策略 | 局数 | 完成且审计通过 | 虚拟均值/秒 | P95/秒 | 最慢/秒 | 现实总耗时/秒 |
|---|---:|---:|---:|---:|---:|---:|
| completion | 4 | 4 | 3537.79 | 4772.54 | 4829.67 | 14.51 |
| route | 4 | 4 | 3676.16 | 4650.41 | 4698.17 | 20.52 |

P95 使用样本分位数线性插值。失败局的时间也保留，失败不能靠缩短时间获益。

| 案例 | 策略 | 完成 | 虚拟/秒 | 检测次数 | 检测位置数 | 清除失败次数 | 启用参考完成 | 现实/秒 |
|---|---|---|---:|---:|---:|---:|---|---:|
| uniform_smooth_41100 | completion | True | 4448.77 | 167 | 31 | 2 | False | 1.18 |
| uniform_smooth_41100 | route | True | 4379.82 | 149 | 28 | 1 | False | 1.64 |
| edge_biased_41101 | completion | True | 4829.67 | 152 | 30 | 2 | False | 0.45 |
| edge_biased_41101 | route | True | 4698.17 | 148 | 33 | 0 | False | 0.62 |
| cluster_hashed_41102 | completion | True | 3045.48 | 108 | 18 | 0 | False | 5.83 |
| cluster_hashed_41102 | route | True | 3709.83 | 111 | 21 | 0 | False | 8.23 |
| line_hashed_41103 | completion | True | 1827.23 | 121 | 21 | 4 | False | 7.04 |
| line_hashed_41103 | route | True | 1916.84 | 123 | 28 | 0 | False | 10.03 |

详情见 results.json、results.csv、cases.json、manifest.json 和每局 actions/*.jsonl。
每一步检查真实源仍在保守区域和保留清除格中；检查程序使用真值，策略不接触它。
