# 固定依赖

公共软件版本准备升为 v0.1.1（待发布），内部 workflow/default policy 保持 v1.1。支持 Windows x64 / NVIDIA CUDA。完整可执行安装步骤见 [SETUP](SETUP.md)。

- Python 基线 3.12.14，两个独立虚拟环境 `envs/asr` 与 `envs/moss`。
- CUDA Torch / torchaudio 为 `2.11.0+cu128`；Transformers 为 `5.17.0`。
- `requirements/asr.lock.txt` 固定 66 项包；`requirements/moss.lock.txt` 固定 68 项包，MOSS 源码另按 `profiles/runtime_versions.json` 的提交安装。
- Qwen、MOSS、Whisper 权重与 MOSS 源码均固定完整 revision，见 [版本记录](../profiles/runtime_versions.json)。不使用自动浮动的 latest/main 代替该记录。
- 纯合成测试只使用标准库；来源后处理需要 NumPy，探测/切块需要 FFmpeg，GPU 推理无 CPU 回退。

这些锁是原环境的版本固定清单，不带 wheel 哈希，也不能保证包源永久提供相同文件。不得为了安装成功静默放宽版本。新环境实际验收范围与阻塞见 [发布检查](RELEASE_CHECK.md)。第三方组件均遵循各自许可证。
