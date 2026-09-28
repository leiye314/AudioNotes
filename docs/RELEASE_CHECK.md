# v0.1.0 发布检查

检查日期：2026-09-28。公共软件版本 v0.1.0；内部 workflow/default policy v1.1、阅读状态 `reading-v1` 保持不变。此次只调整公共文档、许可、测试及导出边界，没有修改稳定 ASR 流程。

## 已完成验证

- 公共合成测试 10/10 通过。无公共调用者的 `prepare_round1.py` 和唯一历史兼容导入测试已从公共版移除。
- 两个全新 Python 3.12.14 venv 未启用 system site-packages；ASR 66 项、MOSS 68 项固定依赖全部匹配，MOSS 源码作为第 69 个包单独安装。使用 uv 安装、部分复用下载缓存，缺失包从官方源取得；没有复制现有环境的 site-packages。
- MOSS 源码从指定完整提交重新下载后构建安装，Python 源码与原验证版本逐字节一致。依赖一致性检查通过。
- 两个环境均验证 Torch `2.11.0+cu128`、CUDA 12.8、GPU 矩阵运算；测试设备为 RTX 5070 Laptop GPU。
- 按 SETUP 的短音频测试代码，在临时公开项目副本中真实执行登记、计划、GPU 推理和来源后处理。Qwen 输入 5.25 秒，MOSS 输入 5.11 秒；两者各 1 块、到达 EOS、有非空转写、程序质量检查通过。
- 短音频来自 Windows 本地语音合成，未使用个人录音；临时项目、测试音频和派生音频均已清理。权重只从已有固定 revision 文件加载，原文件哈希已核对。
- 公共文件使用显式 allowlist、机器路径/常见 secret 扫描、已知个人上下文扫描、Markdown 本地链接检查与导出清单 SHA-256 校验。源代码和 SETUP 代码块通过语法检查。

## Pre-public 最小修订验证（2026-09-28）

- README/SETUP 改为正式 Public v0.1.0 说明；默认权重下载仅 Qwen + MOSS，Whisper 为可选 fallback，固定 revision 不变。
- 移除新 mono 计划对历史实验 fingerprint/allowlist 的依赖，统一历史 workflow/质量字段命名；三个 runner 移除无公共用途的 `--profile`、`--smoke`、`--chunk-seconds`，保留推理主体和已有计划的哈希校验。
- 合成测试 12/12 通过，覆盖政策分块、缓存完整性和旧 CLI 参数拒绝。公共文件 secret/私人上下文/绝对路径扫描、本地 Markdown 链接、Python 与 SETUP 代码块语法检查通过；离线模拟验证默认/可选下载范围、manifest 哈希与固定 revision。
- 本轮未重新运行 GPU 推理；上方安装与短音频结果是修订前的历史验证。源码变化会产生新的运行指纹，既有完整 delivery 的优先复用不变。

## 发布边界与风险

1. **原生 mono 的自动 EOS 修复仍有旧边界。** `prepare_repair.py` 自动路径依赖 `channel/channel_rows` 结构；正常 mono 识别及完整结果复用已验证，异常自动修复未在本次扩展。明确局部 `--plan` 候选不等于已经自动替换。
2. **短音频 smoke 不是识别质量认证。** 未重新评估长录音、说话人跨块身份、复杂重叠音频或人工内容质量。Whisper 已固定 revision 并给出安装步骤，本轮未新增 Whisper GPU 推理测试。
3. **只验证 Windows/CUDA。** 权重使用本地已有文件，未再次从零下载全部模型；完整新机器下载仍依赖上游网络和包源可用性。锁文件没有 wheel 哈希。安装时不要混用索引优先级或静默放宽版本。
4. **本地语音组件与执行上下文。** System.Speech 在受限沙盒中无法初始化，本次在正常用户会话中完成合成与推理；新机器需本地语音组件。测试脚本用自己的临时 GPU 锁，运行时应避免其他项目并行占用 GPU。
5. **MOSS 上游弃用提示。** 固定版本运行成功，但 Transformers 对其 `feature_extractor_class` 发出弃用提示；未来升级需要重新验证，不在本轮改上游代码。
6. **内容整理依赖外部作者。** 需要能读取项目文件的 AI agent（当前推荐 Codex）或人工阅读全文、整理与审查。机械脚本不会自行生成高质量课堂笔记或会议纪要。

项目代码与文档使用 [Apache-2.0](../LICENSE)。第三方模型、源码、FFmpeg 和依赖遵循各自许可证，不在本项目下重新授权。以上安装与 smoke 检查完成于 Git 初始化之前。v0.1.0 首次提交目标为 [private 仓库](https://github.com/leiye314/AudioNotes)；不创建 tag 或 GitHub Release，也不调用云端模型。
