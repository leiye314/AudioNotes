# AudioNotes v0.1.1

**公共软件版本：v0.1.1。内部 workflow/default policy：v1.1；阅读状态标识继续使用 `reading-v1`。这些版本号分别描述发布包与处理政策。**

面向 Windows/CUDA 的本地录音处理与阅读发布工具。课堂使用 Qwen，会议使用 MOSS；机械工具负责发现、登记、识别衔接、保全和发布。内容整理需要能读取项目文件的 AI agent（当前推荐 Codex），或由人工完整阅读转写后完成。机械脚本本身不会自动生成高质量课堂笔记或会议纪要，也不会自行调用订阅模型。

导出包不含录音、用户笔记、姓名表、历史实验、模型权重和环境。这是通用代码基线，不是个人数据迁移包。

## 开始

仓库：[leiye314/AudioNotes](https://github.com/leiye314/AudioNotes)。下面取得最新 main；按 release tag 精确复现见 [SETUP](docs/SETUP.md)。

```powershell
git clone https://github.com/leiye314/AudioNotes.git
Set-Location AudioNotes
```

从 clone 后开始，请逐步执行 [安装与 smoke 检查](docs/SETUP.md)。固定版本说明见 [依赖说明](docs/DEPENDENCIES.md)。纯合成测试只需要 Python 标准库，不需要模型或 GPU：

```powershell
python -B -m unittest discover -s tests -v
python -B release/export_public.py --check
```

先执行 `New-Item -ItemType Directory -Force recordings/inbox | Out-Null`，再把文件放进去，给文件名加真实事件日期。以下文件名和 job 是占位示例，需替换成实际值：

```powershell
.\Run-ReadingAudioNotes.ps1 -Action scan
.\Run-ReadingAudioNotes.ps1 -Action register -Source (Join-Path $PWD 'recordings/inbox/2026-01-01_课程.wav') -Profile course_lecture -Collection '示例课程' -Date '2026-01-01'
# 立体声需明确加 -Channels separate
.\Run-ReadingAudioNotes.ps1 -Action asr -Job '<返回的 job>'
# 仅改阅读稿，绝不启动 ASR
.\Run-ReadingAudioNotes.ps1 -Action asr -Job '<已登记 job>' -RewriteOnly
```

完整操作和编辑 spec 约定见 [工作流](docs/AUDIO_WORKFLOW.md)。文件不会被后台监听自动处理。模型推理仅在用户指定新录音范围后执行。

## 目录与边界

`src` 是生产机械代码，`tests` 是合成测试，`requirements` 和 `profiles/runtime_versions.json` 固定依赖。`profiles/local_defaults_v1.1.json` 固定场景政策，`profiles/local_settings.example.json` 提供机器配置示例。

个人数据在 `recordings`、`outputs`、`work`、`阅读成品`；模型与工具在 `models`、`envs`、`tools`。这些目录均排除版本控制。迁移个人历史资料须另行处理绝对来源路径与哈希证据，不能批量替换既有 manifest。

源码变化会产生新的运行指纹；已完成的 delivery 仍优先复用。支持范围是 Windows/CUDA，不提供 CPU 推理 fallback；短音频 smoke 只验证运行链路，不承诺跨平台或全场质量。程序检查证明结构与保全，不代表音频听写、说话人或内容已获人工认可。CI 仅在 Windows / Python 3.12 运行上述合成测试与导出检查，不安装推理依赖或下载模型。

本项目代码与文档按 [Apache-2.0](LICENSE) 授权。第三方 Qwen/MOSS/Whisper 模型及源码、FFmpeg 和 Python 依赖遵循各自许可证，不随本项目重新授权；权重、第三方源码、可执行文件与安装环境不包含在公共导出中。

许可证原文来自 [Apache Software Foundation](https://www.apache.org/licenses/LICENSE-2.0.txt)。安装记录及尚未解决的发布边界见 [发布检查](docs/RELEASE_CHECK.md)。
