# 阶段 7.3-A：Greenhouse 离线适配器

状态：待用户确认

## 本步骤完成的内容

- 将 Greenhouse Job Board API 登记为经过审核的公开岗位来源；
- 新增 Greenhouse JSON 到统一岗位暂存记录的转换器；
- 清理岗位正文中的 HTML，只保留适合分析的文字；
- 保留岗位 ID、来源更新时间、地点和原始公开链接；
- 暂存格式升级到版本 2，增加来源岗位 ID 与来源更新时间；
- 添加一份完全脱敏、不会联网的 Greenhouse 示例响应；
- 验证转换结果可写入独立 JSONL 暂存区；
- 对缺失正文、非法 board token 和非 HTTPS 链接明确报错。

## 当前仍然没有做什么

- 没有请求 Greenhouse 的真实 API；
- 没有选择或采集任何真实公司；
- 没有连接 Firecrawl；
- 没有将暂存岗位写入正式数据库；
- 没有让采集结果参与岗位画像。

## 数据流

```text
脱敏 Greenhouse JSON 样本
  -> 来源许可检查
  -> 字段校验与 HTML 清洗
  -> 统一岗位记录（schema v2）
  -> 测试临时暂存区
```

## 下一步候选

7.3-B 选择一个使用 Greenhouse 的真实公司公开招聘板，只执行一次只读请求，
限制为少量岗位并保存在 D 盘暂存区。用户检查内容后，再决定是否保留该来源。

官方依据：<https://docs.greenhouse.io/job-board.html>
