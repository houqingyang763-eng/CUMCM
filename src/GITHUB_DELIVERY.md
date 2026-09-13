# GitHub 发布范围与运行条件

本次仅发布 `src/`，以最新上游main为基底，不删除上游既有 `experiments/`，不夹带本机其他未提交改动。

## 包含与缺项

包含历史探索、Q3 F3/F3改、Q4 shared25的代码、配置、说明，以及已归档在src内的实验证据。缓存、私有会话、本机保护状态和Windows目录联接被排除。

`outputs/q4/`、`outputs/experiments/b_q3_p1/`、`outputs/source_migration/` 等本机结果不在本次src发布范围。因此指向这些结果的链接在只有本次PR的克隆中可能缺失；不能把代码发布解释为全部论文证据已经上传。

`migration_manifest.json` 是本机完整迁移的历史收据，包含未发布的缓存条目；它不是Git发布清单。`organize_sources.py audit` 针对原完整迁移目录。Git克隆缺少被排除文件时，不应将这项审计视为可独立通过的发布检查。

## 可直接核验的入口

在仓库根目录运行：

```powershell
py -3.13 -B -X utf8 src/q3/runtime.py --check
py -3.13 -B -X utf8 src/q4/test_selected.py
```

两条命令只验证导入、策略构造和入口契约，不启动官方模拟器。

Q3的 `verify_runtime.py` 和 `verify_evidence.py` 还需要source_manifest列出的 `outputs/experiments/b_q3_p1/` 对应冻结批次。Q4的 `audit_delivery.py` 需要 `outputs/q4/` 原批次与演练证据。取得这些原结果后才能复核相应报告；不要为填补缺项而伪造文件或改写原指纹。

## 跨电脑旧路径

Q3主运行器独立解析src映射，不依赖联接。`restore_compatibility.ps1` 只适合目标旧目录尚不存在的Windows工作区；上游已有同名实体目录时会拒绝操作，这是保护现有内容。优先使用src入口，不删除实体目录来迁就历史脚本。

`src/.gitattributes` 禁止自动转换本目录换行，以保留冻结源码与证据的原始SHA256。此次发布没有新增模型实验或官方正式测试。
