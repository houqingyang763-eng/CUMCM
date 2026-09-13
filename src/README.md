# 第三、第四问方法与实验总入口

2026-09-13按团队要求归为三类。目录归档与模型采纳是两个状态；历史候选移入src不表示被采用。

| 类别 | 阅读入口 | 当前定位 |
| --- | --- | --- |
| 第三问主体方法与实验 | [q3/START_HERE.md](q3/START_HERE.md) | F3为主方案，F3改保留同案比较；包含代码、配置、旧结果与核验入口 |
| 第四问主体方法与实验 | [q4/START_HERE.md](q4/START_HERE.md) | shared25为当前交付方案，B0/joint25为对照；未采用A/B小改 |
| 之前探索的方法与实验 | [exploration/README.md](exploration/README.md) | 早期路线、失败分支、方法比较、诊断与原实验记录 |

GitHub本次仅发布src；外部结果依赖和跨电脑运行条件见[发布说明](GITHUB_DELIVERY.md)。

## 运行与证据

从仓库根目录运行；这些命令不启动官方模拟器，也不新增整局实验：

```powershell
py -3.13 -B -X utf8 src/q3/runtime.py --check
py -3.13 -B -X utf8 src/q3/verify_runtime.py
py -3.13 -B -X utf8 src/q3/verify_evidence.py
py -3.13 -B -X utf8 src/organize_sources.py audit
```

正式图表和运行输出继续保存在outputs。[第三问结果导航](../outputs/q3/README.md)、[第四问结果导航](../outputs/q4/README.md)、[历史结果导航](../outputs/exploration/README.md)。已冻结批次的路径和指纹不改写；迁移映射负责追溯当前位置。

## 迁移约定

- Q1、Q2及官方输入保持原位。Q3/Q4算法逻辑与现有结果不变，本次迁移未追加优化或启动正式测试；Git发布按用户后续指令进行。
- [migration_manifest.json](migration_manifest.json)记录8081个迁移文件的旧新路径、迁移前后SHA256与说明/入口调整。逐文件核验见[迁移结果](../outputs/source_migration/files_verified.json)。
- Q3运行器通过[source_manifest.json](q3/source_manifest.json)解析原源码并恢复临时运行结构，离开上下文后清理；不依赖Windows联接。
- 旧experiments路径在本机保留隐藏目录联接，不占用第二份数据。Git不移植联接；其他Windows电脑需要使用旧路径时运行[restore_compatibility.ps1](restore_compatibility.ps1)。新入口优先使用src中的真实位置。
- 历史脚本的固定目录层数、旧绝对路径不作全量重写；精确复现以冻结source和manifest为准。不能直接将所有历史脚本当作新的独立运行入口。
- 本轮只组织代码与事实证据，未制定论文架构；paper仍是唯一论文正文目录。
