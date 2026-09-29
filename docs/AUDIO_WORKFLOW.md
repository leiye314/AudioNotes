# AudioNotes 内部 workflow/default policy v1.1

适用于公共软件 v0.1.1；这里的 v1.1 不是软件发布号。

这是公共版操作说明。场景配置来自既有本地 v1.1 政策；选型录音、人工复核和实验材料属于私有证据，不包含在公共包中。这里不宣称某模型具有通用准确率优势。

## 登记与识别

用 `Run-ReadingAudioNotes.ps1 -Action scan` 检查 `recordings/inbox`、`courses`、`meetings` 和兼容的 `logic`。扫描保存后台状态但不启动模型。检查大小、修改时间稳定后再计算哈希。事件日期只能使用文件名或用户确认，不能用上传日期。登记到 `outputs/index.json`，inbox 按课程/项目归档，同内容复用、同名不同内容拒绝覆盖。

课堂 profile 是 `course_lecture`，兼容 `logic_lecture`；会议是 `research_meeting`。必要时指定 Collection、Date 和 Scene。原生 mono 保持；立体声明确指定 `-Channels separate`，保留 L/R，不根据能量、文本长度或模型多数票丢声道。

| 场景 | 主模型 | 块长 | 局部备用 |
|---|---|---|---|
| 中文专业课 | Qwen，不强制语言 | 30 秒 | 非 EOS 缩 10 秒；术语等争议可参考 MOSS 30 秒 |
| 中英课堂 | Qwen，不强制语言 | 30 秒 | 非 EOS 缩 10 秒；英语漏句可参考 Whisper 30 秒 |
| 人文课堂 | Qwen，不强制语言 | 30 秒 | 非 EOS 缩 10 秒；人名/播放台词交叠可参考 MOSS 30 秒 |
| 多人会议 | MOSS，原 DEFAULT_PROMPT | 120 秒 | 非 EOS 缩 30 秒；数字/否定等争议可参考 Qwen 30 秒 |

Whisper 每块重新以 `language=None, task='transcribe', beam_size=5, vad_filter=False, condition_on_previous_text=False, word_timestamps=True` 调用，温度回退 `[0,.2,.4,.6,.8,1]`。不继承上一块语言。GPU 串行，保留失败原件、EOS/token 上限及运行指纹。

`-Action asr -Job <job>` 先复用完整来源，无完整结果才调用对应运行器。改稿用 `-RewriteOnly`；即使缺少转写也不因此启动模型。局部备用用 `prepare_local_fallback.py --job <job> --start <秒> --end <秒> --channel L|R|MONO --engine qwen|moss|whisper --reason <原因>`，最多 120 秒；结果仅生成候选，不自动并入正文。然后按返回 plan 用对应环境调用 `run_repair.py --model <engine> --job <job> --plan <plan>`。非 EOS 修复另用 `run_repair.py --job <job> --model qwen|moss` 与 `select_repair.py --job <job> --engine qwen|moss`，保留原候选。

自动 EOS 修复在内部将原生单声道记为 `MONO`，立体声仍按 `L/R` 分开；只修非 EOS 块，保留原失败输出。它是显式调用的修复步骤，`-Action asr` 不会自动启动修复。以 Qwen 为例，在项目根执行（先替换 job；MOSS 改用 `envs/moss` 且两处引擎参数均改为 `moss`）：

```powershell
$taskJob = '<实际 job>'
& .\envs\asr\Scripts\python.exe -B src/run_repair.py --job $taskJob --model qwen
if ($LASTEXITCODE -ne 0) { throw 'Repair inference failed; originals preserved' }
& .\envs\asr\Scripts\python.exe -B src/select_repair.py --job $taskJob --engine qwen
if ($LASTEXITCODE -ne 0) { throw 'Repair selection failed' }
& .\envs\asr\Scripts\python.exe -B src/postprocess_full.py --job $taskJob
if ($LASTEXITCODE -ne 0) { throw 'Source rebuild failed' }
```

重建后检查 `delivery/quality.json` 的 `procedural_pass`，再进入阅读；选择候选只说明 EOS/时间结构通过，不等于听音正确。显式 `--plan` 的局部备用候选仍不自动替换。自动修复要求对应引擎只有一个 full run 和一个 repair run，多个历史 fingerprint 必须先审查选择，不删除原件绕过检查。

## 完整阅读与编辑

用 `src/read_source.py <job> <起段> <止段>` 连续完整读取 `delivery/raw_segments.json`。输出截断则缩小范围补读，读取日志不等于理解或听音核验。整理逐字稿保留原顺序、实质信息、例子、否定、条件、数字、问答、改口；不补造缺录、板书和实名。会议标签仅在当前识别块内有效。播放与现场指令区分，局部人工确认绑定来源及范围。

当前会话将课堂笔记/会议纪要写入 `work/reading_v1/drafts/<unit>.md`，把逐段决定写入 `work/reading_v1/specs/<unit>.json`。下面是合成结构示例；job 和段号必须换成实际来源，内容字段必须来自完整阅读：

```json
{
  "unit": "example", "jobs": ["example_job"], "kind": "lecture",
  "directory": "课程/示例课程/2026-01-01_第一课", "title": "示例第一课",
  "date": "2026-01-01", "project": "示例课程", "topic": "实际主题",
  "notes": "example.md", "intro": "说明实际来源与主讲角色。",
  "uncertainties": "只列实际疑点。", "review": "记录实际完成的内容审查。",
  "headings": [{"at": "example_job:S00001", "title": "实际章节"}],
  "edits": {}, "omit": {}, "replacements": [], "paragraph_starts": [], "join_before": []
}
```

`edits` 以来源键映射到 `{text, basis}`；`omit` 逐项说明省略依据；`replacements` 使用 `{old,new,job,start,end,basis}` 限定范围；只对实际审查后的续句设置 `join_before`。人名/角色使用局部 `speaker_overrides`，不得默认跨块合并；明确要求保留的口吃/台词可在 edit 加 `preserve_verbatim:true`。中英混合可设置 `mixed_language_layout:true`，不自动翻译。笔记关键结论、推导和任务映射到 `<unit>/notes_source_map.json`。

## 发布

执行 `src/reading_publish.py <unit>`，再执行 `--index`。每单元只有 `01_整理逐字稿.md` 和 `02_课堂笔记.md` 或 `02_会议纪要.md`，总入口 `阅读成品/00_总目录.md`。后台保存来源、改动、覆盖与版本；首次发布拒绝未登记覆盖，再次发布检查 hash，手改留原位供会话合并，相同内容不重复写。

内容审查确认重要主题都有去向，检查全部本地链接和两份主文件、正文无技术 ID、原始来源不变。一般疑点标注后继续；不能生成完整材料则保留后台半成品，不能宣称完成。历史任务与期限不转成当前待办。`tests/` 只验证合成机械边界，不代替真实内容复核。
