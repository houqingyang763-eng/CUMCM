# 候选资格修复

首次S4使用已有高效用评估必然无信号候选，导致选中不能提供信息的站点，最终空队列。失败证据保留；不把部分46.530分钟作为完成时间。

revision.py原代码：

```python
usable=[x for x in records if x['mean_u']>=.8]
if usable:best=min(usable,key=lambda x:(x['seconds'],-x['mean_u']))
else:best=max(records,key=lambda x:(x['mean_u'],-x['seconds'])) if records else old
```

修复后：

```python
eligible=[x for x in records if not x.get('certain_redundant') and x.get('gain',0)>0]
usable=[x for x in eligible if x['mean_u']>=.8]
if usable:best=min(usable,key=lambda x:(x['seconds'],-x['mean_u']))
else:best=max(eligible,key=lambda x:(x['mean_u'],-x['seconds'])) if eligible else old
```

此外，run.py/run_revision.py在导入前显式置顶本目录，解决Windows子进程把同名policy解析到旧目录的问题。该修复只改变模块加载路径；S1/S2/S3和F3算法代码未变。新增诊断/汇总脚本不计为算法修改。
