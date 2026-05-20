# Changelog

## v2.3.0 - 2026-05-20
- 新增：支持在配置中指定生成日程使用的 LLM 供应商，留空时继续使用当前 provider。
- 优化：日程读取按每日生成时间切分业务日，避免生成时间前误读新一天未生成的日程。

## v2.2.7 - 2026-02-23
- 修复：LLM 返回空 completion 时增加一次重试，并在失败时给出明确错误 `API返回的completion为空`。
- 增强：统一 completion 抽取字段（`completion_text/completion/text/content`）。

## v2.2.6
- 历史版本（详见 git 历史）。
