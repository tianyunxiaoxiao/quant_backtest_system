# 因子与回测平台每日数据更新

## 目标

因子平台和回测平台共同读取 `/data/research/current` 指向的不可变数据版本。因子平台读取
`panel_shards`，回测平台读取同一版本中的 `warehouse_rqdata`。一次 symlink 替换同时发布
两边数据，避免股票、全 A 等权和三个指数基准出现日期错位。

## 每日流程

1. 工作日 18:30（Asia/Shanghai）由 `qbt-data-update.timer` 触发。
2. 取最近交易日的前一交易日为统一目标，并检查 RQData `stock_daybar` 与
   `exchange_index_daybar` 均已就绪。因估值、换手率等因子字段晚于收盘行情更新，统一保留
   一个交易日滞后，避免发布“有价格、无因子”的半成品。
3. 获取文件锁，确认 QBT 与 QPF 都没有待运行或运行中的任务。
4. 以当前不可变版本为硬链接基础创建 `.partial` 候选目录。
5. 用 7 个交易日重叠窗口更新全部 31 个股票字段。
6. 从同一 panel 重建回测仓库，并从 RQData 更新沪深 300、中证 500、中证 1000。
7. 校验全部 panel 字段、回测交易日历和三个指数都完整覆盖目标交易日，并校验内容哈希。
8. 候选目录重命名为不可变 release，最后一次 `os.replace` 切换 `current`。

任何步骤失败都不会修改 `current`。systemd 每 15 分钟重试，最多四次；日志使用
`journalctl -u qbt-data-update.service` 查看。`/data/research/previous` 保存发布前版本，回滚时先
运行校验器，再原子切换 `current`。

## 部署约束

- `/etc/qpf/rqdata.env` 权限必须为 `0600`，仅包含 `RQDATAC_CONF`。
- QBT 容器应挂载 `/data/research:/data/research:ro`，并设置
  `QBT_WAREHOUSE=/data/research/current/warehouse_rqdata`。
- 定时器使用的 `QBT_DATA_IMAGE` 必须与当前 QBT 服务镜像一致。
- 发布前脚本会查询 QBT SQLite 与 QPF PostgreSQL，任一平台存在非终态任务时拒绝发布。

## 手动检查

```bash
systemctl status qbt-data-update.timer
journalctl -u qbt-data-update.service -n 200 --no-pager
/opt/qpf/venv/bin/python /opt/qbt/app/scripts/validate_data_release.py \
  --release /data/research/current
```

手动运行 `systemctl start qbt-data-update.service` 与定时流程完全相同。首次部署或变更挂载时，
应在无运行任务的窗口重启 `qbt-web.service`，并检查两个平台报告的 `date_max` 一致。
