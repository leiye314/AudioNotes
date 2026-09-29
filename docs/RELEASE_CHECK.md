# v0.1.1 发布验证记录

检查日期：2026-09-29。公共软件版本 v0.1.1；内部 workflow/default policy 保持 v1.1，阅读状态保持 `reading-v1`。

仓库已为 [Public](https://github.com/leiye314/AudioNotes)，[v0.1.0 tag 与 Release](https://github.com/leiye314/AudioNotes/releases/tag/v0.1.0) 已发布，对应提交 `3195625`。v0.1.1 为 maintenance release，内部政策版本不变。

## 本轮改动与实际验证

- 原生 mono 的自动 EOS repair 兼容缺省 `channel` 与无 `channel_rows` 的完整计划，内部明确使用 `MONO`；Qwen 缩为 10 秒、MOSS 缩为 30 秒，保留原始失败证据。L/R 仍独立选择；没有改写 runner、模型、依赖锁或 v1.1 policy。
- 公共合成回归 **18/18 通过**（Windows / Python 3.12.14）。覆盖 mono 两引擎、双声道相同时间范围不串选、仅右声道失败、音频切片字节与源偏移、缓存哈希、不完整候选拒绝及既有发布保护。
- 使用合成 WAV 和合成模型输出，额外执行 Qwen/MOSS × mono/stereo 共 4 条“repair 计划 → 选择 → 来源后处理”链路，均 `procedural_pass=true`，原 full run JSON 哈希不变。此项没有调用模型，也不是 GPU repair smoke。
- 一个轻量 GitHub Actions workflow：Windows / Python 3.12，只运行 `unittest discover -s tests -v` 与 `release/export_public.py --check`。不安装 ASR 依赖、下载模型或运行 GPU，无 matrix。提交 `4c99e51ab2eab987009d521a8a5a2e8bbd120c11` 的托管 [Synthetic checks #1](https://github.com/leiye314/AudioNotes/actions/runs/36591384512) 已成功：Windows / Python 3.12（实际 3.12.10）上 **18/18 synthetic tests 通过**，**Public export check 通过（34 文件）**。这项验证不包含 GPU/ASR 推理。
- 显式 allowlist 共 34 文件（另附导出 manifest）；secret/绝对路径/已知个人上下文扫描、本地 Markdown 链接、Python 与文档代码块语法、CLI help、生成物忽略规则及导出 SHA-256 核验通过。CI 文件仅按明确路径加入允许类型。
- 全新 allowlist 导出在禁用 site-packages（`-S`）的 Python 3.12.14 下通过全部 18 项测试与导出检查。相同新增用例在 v0.1.0 repair 代码上复现两个引擎的 mono `KeyError: 'channel'`，stereo 用例仍通过。
- 个人项目仅回移两个通用 repair 文件，备份原文件后执行既有 11 + 6 + 4 项回归，全部通过；248 个代码、文档、配置与交付文件的前后哈希核对只有这两个文件变化，公共 README、CI 和 release 元数据未同步。
- 文档明确 main 与 release tag 的区别、首次 inbox 创建、环境分工、repair 后重建来源和常见错误。未新增 doctor、安装器、配置系统或额外文档。

## 复用的 v0.1.0 证据（2026-09-28）

以下是已有验证，本轮重新核对原始记录及模型 revision，没有重新安装或执行 GPU 推理。v0.1.0 最终公共合成回归为 **12/12**，替代早期中间计数。

- 两个全新 Python 3.12.14 venv，未启用 system site-packages；ASR 66 项、MOSS 68 项固定依赖匹配，MOSS 源码作为第 69 个包安装，依赖一致性通过。历史安装使用 uv，部分复用下载缓存，没有复制 site-packages；本轮未声称逐条重跑 SETUP 的 pip 命令。
- MOSS 指定提交源码重新下载、构建安装，Python 源码与原验证版逐字节一致。
- 两环境 Torch `2.11.0+cu128`、CUDA 12.8、GPU 矩阵运算通过，设备为 RTX 5070 Laptop GPU。
- Windows 本地语音合成短音频：Qwen 5.25 秒、MOSS 5.11 秒，各 1 块，到达 EOS、有非空转写、来源程序质量通过。临时项目与音频已清理；权重从已有固定 revision 加载并核对原文件哈希。该 smoke 早于 v0.1.0 最后的公共 CLI/元数据收口，不是 v0.1.1 新的 GPU 验证。

## 陌生用户可复现性审计

| 检查项 | 结果与边界 |
|---|---|
| 从全新 clone 安装 | Git/Python 前置条件、两个 venv、CUDA wheel、依赖、MOSS 源码、模型 manifest、FFmpeg、CUDA 检查与 smoke 步骤齐备；main 不再被称为精确发布版。 |
| 模型路径与 revision | Qwen/MOSS 默认下载路径与 runner 一致；Whisper 可选，cache 的 `refs/main` 指向固定 revision。三个权重与 MOSS 源码完整提交号未改。对 SETUP 下载代码做离线模拟，验证下载范围、哈希 manifest 与 ref，不冒充真实下载。 |
| 生效配置 | 课堂 Qwen 30 秒、会议 MOSS 120 秒，Whisper 局部 30 秒且每块 `language=None`；实际调用来自 `local_defaults.py`，无 CPU 推理 fallback。 |
| 示例与 CLI | README、工作流命令及 SETUP 代码块与 CLI 对照；文件/job 是明确占位符。自动 EOS 修复须显式执行，ASR 入口遇到结构问题会停止；局部 fallback 不自动并入正文。 |
| 故障诊断 | SETUP 给出环境、FFmpeg、CUDA、缺失权重、MOSS 安装、输入登记、修复及手改保护的排查入口。多 fingerprint 和部分哈希错误仍以断言报错，需审查证据，不删除旧输出绕过。 |
| 导出与隐私 | 公共文件集合严格等于 allowlist 加 manifest；录音、阅读成品、模型、环境、工具、配置、输出、后台证据均排除。忽略规则与 allowlist 双重核对；不导出个人回归材料。 |

## 已知限制与发布判断

1. 本轮未新增 GPU repair 或 Whisper GPU smoke，未重新从零下载全部权重，也未认证其他显卡、长录音、复杂重叠音频和听写准确率；复用验证只证明其当时的运行链路。
2. 全新机器仍依赖上游包源/网络、兼容 NVIDIA 驱动、本地语音组件与同卷 NTFS 硬链接；锁文件没有 wheel 哈希。历史 System.Speech 在受限沙盒中无法初始化，smoke 在正常用户会话完成。临时 smoke GPU 锁不协调其他项目。
3. 自动 repair 要求一个 full run 和一个 repair run；多个历史 fingerprint 需显式审查。新增 mono 支持不放宽该既有边界。
4. 后台展示有已有硬编码：mono 的 `channel_policy` 可能触发双声道说明/空 L/R 字幕，Qwen repair 的部分 Markdown 提示仍写 30 秒。实际 mono 修复字段为 `MONO`，Qwen 计划为 10 秒；以 `plan.json`、`raw_segments.json` 和质量 JSON 为准。本轮不扩改后处理器。
5. MOSS 上游有 `feature_extractor_class` 弃用提示；内容整理仍需 AI agent 或人工完整阅读、写作与审查。程序结构检查不是听音验收。

**发布结论：v0.1.1 maintenance 的本地验证与上述托管 CI 均通过；以上未验证范围和已知限制随版本保留。** 项目代码与文档按 [Apache-2.0](../LICENSE) 授权；第三方组件各自授权，不重新授权。
