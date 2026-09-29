# AudioNotes v0.1.1 安装与短音频检查

适用 Windows x64、PowerShell、NVIDIA CUDA GPU；Python 基线为 3.12.14。本页对应公共软件 v0.1.1，内部 workflow/default policy 保持 v1.1。模型一次只加载一个，不提供 CPU 推理 fallback。以下步骤针对全新目录，不应在个人稳定环境重复安装。

## 1. 取得代码并创建两个环境

仓库为 [leiye314/AudioNotes](https://github.com/leiye314/AudioNotes)。先安装 Git 和官方 Python 3.12 x64；在 PowerShell 中选择下面一种取代码方式。

**使用最新 main**：取得持续维护的代码，内容可能晚于最近一次 Release，不保证等同于发布包。

```powershell
git clone https://github.com/leiye314/AudioNotes.git AudioNotes
Set-Location AudioNotes
```

**按 release tag 精确复现**：在另一个全新目录执行下面命令。以下固定到 `v0.1.1` tag。复现其他已发布版本时，替换 `--branch` 的值并使用独立目录；始终使用所选 tag 自带的 SETUP 和锁文件，不混用 main 的说明。

```powershell
git clone --branch v0.1.1 --depth 1 https://github.com/leiye314/AudioNotes.git AudioNotes-v0.1.1
Set-Location AudioNotes-v0.1.1
git describe --tags --exact-match
```

下面从选定代码的项目根目录继续。本地导出用户也从这里开始。`py` 不存在或未登记 Python 时，将每处 `py -3.12` 替换为已安装 Python 3.12 x64 的实际可执行文件调用。

```powershell
py -3.12 --version
py -3.12 -m venv envs/asr
py -3.12 -m venv envs/moss
$taskAsr = Join-Path $PWD 'envs/asr/Scripts/python.exe'
$taskMoss = Join-Path $PWD 'envs/moss/Scripts/python.exe'
$env:PYTHONUTF8 = '1'
```

使用官方 Python 3.12 x64；`py` 不存在时用该 Python 的实际可执行文件替换。不要启用 `--system-site-packages`。检查驱动和 CUDA wheel，先单独安装 CUDA 包，再从 PyPI 安装其余固定依赖，避免多个索引的优先级混用：

```powershell
nvidia-smi
& $taskAsr -m pip install --no-deps torch==2.11.0+cu128 torchaudio==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'ASR CUDA wheel install failed' }
& $taskMoss -m pip install --no-deps torch==2.11.0+cu128 torchaudio==2.11.0+cu128 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'MOSS CUDA wheel install failed' }
& $taskAsr -m pip install --index-url https://pypi.org/simple -r requirements/asr.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'ASR dependency install failed' }
& $taskMoss -m pip install --index-url https://pypi.org/simple -r requirements/moss.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'MOSS dependency install failed' }
```

下载失败时检查网络或包源可用性；不要放宽版本、替换 CPU Torch 或复制别人的虚拟环境。安装命令会下载公开依赖，不上传录音。

## 2. 安装固定提交的 MOSS 源码

以下仅下载公开源码压缩包，不创建额外 Git 仓库。源码保留上游许可证，安装到 MOSS 环境，运行时不依赖手工修改 `PYTHONPATH`。

```powershell
@'
import json, urllib.request, zipfile
from pathlib import Path, PurePosixPath
root = Path.cwd()
rev = json.loads((root/'profiles/runtime_versions.json').read_text())['moss_source_revision']
folder = root/'tools/moss-source'
folder.mkdir(parents=True, exist_ok=True)
archive = folder/(rev + '.zip')
urllib.request.urlretrieve('https://codeload.github.com/OpenMOSS/MOSS-Transcribe-Diarize/zip/' + rev, archive)
with zipfile.ZipFile(archive) as z:
    for item in z.infolist():
        parts = PurePosixPath(item.filename)
        assert not parts.is_absolute() and '..' not in parts.parts
        assert (folder/item.filename).resolve().is_relative_to(folder.resolve())
    z.extractall(folder)
print(folder/('MOSS-Transcribe-Diarize-' + rev))
'@ | & $taskAsr -B -
if ($LASTEXITCODE -ne 0) { throw 'MOSS source download failed' }
$taskPins = Get-Content profiles/runtime_versions.json -Raw | ConvertFrom-Json
$taskMossSource = Join-Path $PWD ('tools/moss-source/MOSS-Transcribe-Diarize-' + $taskPins.moss_source_revision)
& $taskMoss -m pip install --no-deps $taskMossSource
if ($LASTEXITCODE -ne 0) { throw 'MOSS source install failed' }
& $taskAsr -m pip check
if ($LASTEXITCODE -ne 0) { throw 'ASR dependency consistency check failed' }
& $taskMoss -m pip check
if ($LASTEXITCODE -ne 0) { throw 'MOSS dependency consistency check failed' }
```

## 3. 默认下载 Qwen + MOSS 固定 revision 权重并生成 manifest

固定值统一在 [runtime_versions.json](../profiles/runtime_versions.json)：Qwen、MOSS、Whisper 都使用完整提交号。MOSS 需要执行随权重固定的 remote code；先阅读上游代码和许可证。默认只下载 Qwen + MOSS 各自固定 revision 的全部文件；需要数 GB 空间和网络。Whisper 权重仅在需要局部 fallback 时按下方可选步骤安装。

```powershell
@'
import hashlib, json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download
root = Path.cwd()
pins = json.loads((root/'profiles/runtime_versions.json').read_text())
api = HfApi()
for repo in ['Qwen/Qwen3-ASR-1.7B-hf', 'OpenMOSS-Team/MOSS-Transcribe-Diarize']:
    pin = pins['models'][repo]
    rev = pin['revision']
    assert api.model_info(repo, revision=rev).sha == rev
    dest = root/'models'/repo.split('/')[-1]
    manifest = dest/'download_manifest.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        assert saved['revision'] == rev and saved['repo'] == repo
    snapshot_download(repo_id=repo, revision=rev, local_dir=dest)
    rows = []
    for path in sorted(dest.rglob('*')):
        relative = path.relative_to(dest)
        if not path.is_file() or '.cache' in relative.parts or path == manifest:
            continue
        with path.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        rows.append(dict(file=relative.as_posix(), bytes=path.stat().st_size, sha256=digest))
    manifest.write_text(json.dumps(dict(repo=repo, revision=rev, files=rows), indent=2), encoding='utf-8')
    print(repo, rev, len(rows))
'@ | & $taskAsr -B -
if ($LASTEXITCODE -ne 0) { throw 'Pinned model download/manifest creation failed' }
```

`download_manifest.json` 必须来自真实文件，不能仅填写 revision 冒充已下载。它记录本地 SHA-256；该清单不是来自第三方独立签名的文件认证。

## 3a. 可选：安装 Whisper fallback 权重

仅在中英课堂局部英语漏句等需要 Whisper 候选时执行；默认 Qwen/MOSS 流程可跳过。沿用同一固定 revision 和 ASR 环境，不改变 Whisper 支持代码。`refs/main` 明确指向固定 revision，不追随上游 main。

```powershell
@'
import hashlib, json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download
root = Path.cwd()
pins = json.loads((root/'profiles/runtime_versions.json').read_text())
api = HfApi()
for repo in ['Systran/faster-whisper-large-v3']:
    pin = pins['models'][repo]
    rev = pin['revision']
    assert api.model_info(repo, revision=rev).sha == rev
    cache = root/'models/hf-cache/models--Systran--faster-whisper-large-v3'
    dest = cache/'snapshots'/rev
    manifest = dest/'download_manifest.json'
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        assert saved['revision'] == rev and saved['repo'] == repo
    snapshot_download(repo_id=repo, revision=rev, local_dir=dest)
    rows = []
    for path in sorted(dest.rglob('*')):
        relative = path.relative_to(dest)
        if not path.is_file() or '.cache' in relative.parts or path == manifest:
            continue
        with path.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        rows.append(dict(file=relative.as_posix(), bytes=path.stat().st_size, sha256=digest))
    manifest.write_text(json.dumps(dict(repo=repo, revision=rev, files=rows), indent=2), encoding='utf-8')
    ref = cache/'refs/main'
    ref.parent.mkdir(parents=True, exist_ok=True)
    if ref.exists():
        assert ref.read_text().strip() == rev, 'Ref differs; review instead of replacing it'
    ref.write_text(rev + '\n', encoding='utf-8')
    print(repo, rev, len(rows))
'@ | & $taskAsr -B -
if ($LASTEXITCODE -ne 0) { throw 'Optional Whisper download/manifest creation failed' }
```

## 4. 配置 FFmpeg 并验证 CUDA

需要支持 CUDA 12.8 wheel 的 NVIDIA 驱动，`nvidia-smi` 必须可调用；其显示的 CUDA 版本不能替代下面的 Torch 实测。Qwen/MOSS 使用 CUDA bfloat16，Whisper 使用 CUDA float16；只有 RTX 5070 Laptop GPU 有当前 smoke 证据，其他 GPU 架构和显存容量未逐一认证。ASR 锁中的 `imageio-ffmpeg` wheel 自带 Windows FFmpeg，可复制到项目默认位置。该可执行文件受其自身许可证约束，不随项目公共包分发。

```powershell
@'
import shutil, subprocess
from pathlib import Path
import imageio_ffmpeg
dest = Path('tools/ffmpeg.exe')
dest.parent.mkdir(parents=True, exist_ok=True)
if not dest.exists():
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(), dest)
subprocess.run([str(dest.resolve()), '-version'], check=True)
'@ | & $taskAsr -B -
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg verification failed' }
if (-not (Test-Path profiles/local_settings.json)) {
    Copy-Item profiles/local_settings.example.json profiles/local_settings.json
}
foreach ($taskPython in @($taskAsr, $taskMoss)) {
    & $taskPython -B -c "import torch; assert torch.cuda.is_available(); assert torch.version.cuda == '12.8'; x=torch.randn(512,512,device='cuda'); y=x@x; torch.cuda.synchronize(); assert torch.isfinite(y).all(); print(torch.__version__,torch.cuda.get_device_name(0))"
    if ($LASTEXITCODE -ne 0) { throw 'CUDA verification failed' }
}
& $taskAsr -B -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Synthetic tests failed' }
& $taskAsr -B release/export_public.py --check
if ($LASTEXITCODE -ne 0) { throw 'Public export check failed' }
```

相对路径均以项目根解析。需要外置缓存时，只修改未跟踪的 `profiles/local_settings.json` 中 `whisper_cache` 或 `ffmpeg`；不要把个人绝对路径写进公共版本文件。

## 5. Qwen 与 MOSS 各一次短音频 smoke

下面将完整的公共生产代码复制到临时项目，用 Windows 自带语音合成产生两句测试语音，串行运行真实登记、计划、GPU 生成和来源后处理。只硬链接只读使用的本地模型文件，不复制个人录音。临时项目退出时删除，包含其测试音频与派生结果；简短通过结果打印到控制台。这不是准确率评估。测试使用预先生成且验证不超过 20 秒的短音频。

先在项目根目录执行 `New-Item -ItemType Directory -Force work | Out-Null`，把下列代码保存为 `work/setup_smoke.py`，然后运行后面的命令：

```python
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, wave
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--models', type=Path)
p.add_argument('--asr-python', type=Path)
p.add_argument('--moss-python', type=Path)
p.add_argument('--ffmpeg', type=Path)
p.add_argument('--scratch-parent', type=Path)
a = p.parse_args()
root = Path.cwd().resolve()
models = (a.models or root/'models').resolve()
asr = (a.asr_python or root/'envs/asr/Scripts/python.exe').resolve()
moss = (a.moss_python or root/'envs/moss/Scripts/python.exe').resolve()
ffmpeg = (a.ffmpeg or root/'tools/ffmpeg.exe').resolve()
parent = (a.scratch_parent or root/'work').resolve()
parent.mkdir(parents=True, exist_ok=True)
env = {**os.environ, 'PYTHONUTF8':'1', 'PYTHONDONTWRITEBYTECODE':'1',
       'HF_HUB_OFFLINE':'1', 'TRANSFORMERS_OFFLINE':'1'}
summary = []
with tempfile.TemporaryDirectory(prefix='audionotes-smoke-', dir=parent) as temporary:
    scratch = Path(temporary).resolve()
    assert scratch.parent == parent and not scratch.is_symlink()
    shutil.copytree(root/'src', scratch/'src', ignore=shutil.ignore_patterns('__pycache__'))
    (scratch/'profiles').mkdir()
    for name in ['runtime_versions.json', 'local_defaults_v1.1.json']:
        shutil.copy2(root/'profiles'/name, scratch/'profiles'/name)
    (scratch/'tools').mkdir()
    shutil.copy2(ffmpeg, scratch/'tools/ffmpeg.exe')
    for name in ['Qwen3-ASR-1.7B-hf', 'MOSS-Transcribe-Diarize']:
        source = models/name
        assert (source/'download_manifest.json').is_file()
        for file in source.rglob('*'):
            relative = file.relative_to(source)
            if not file.is_file() or '.cache' in relative.parts:
                continue
            dest = scratch/'models'/name/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Same-volume NTFS required. Hardlink deletion does not delete the original.
            os.link(file, dest)
    synth_code = '''$OutputFile=$env:AUDIONOTES_SMOKE_WAV
$Words=$env:AUDIONOTES_SMOKE_WORDS
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)
try { $speaker.SetOutputToWaveFile($OutputFile,$format); $speaker.Speak($Words) }
finally { $speaker.Dispose() }
'''
    for engine, python, profile, words in [
        ('qwen', asr, 'course_lecture', 'This is a short local audio test. One two three.'),
        ('moss', moss, 'research_meeting', 'This is a short meeting test. The task is complete.')]:
        audio = scratch/'recordings/inbox'/(engine+'.wav')
        audio.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['powershell.exe','-NoProfile','-Command',synth_code],
                       env={**env,'AUDIONOTES_SMOKE_WAV':str(audio),'AUDIONOTES_SMOKE_WORDS':words},check=True)
        with wave.open(str(audio)) as w:
            duration = w.getnframes()/w.getframerate()
            assert 0 < duration <= 20 and w.getnchannels() == 1
        command = [str(python),'-B',str(scratch/'src/audio_workflow.py'),'register',str(audio),
                   '--profile',profile,'--collection','SyntheticSmoke','--date','2000-01-01']
        registered = json.loads(subprocess.check_output(command,cwd=scratch,env=env,text=True,encoding='utf-8'))
        job = registered['job']
        subprocess.run([str(python),'-B',str(scratch/'src/run_full.py'),'--job',job,'--model',engine],
                       cwd=scratch,env=env,check=True)
        subprocess.run([str(python),'-B',str(scratch/'src/postprocess_full.py'),'--job',job],
                       cwd=scratch,env=env,check=True)
        runs = list((scratch/'outputs'/job/'full'/engine).glob('*/run.json'))
        assert len(runs) == 1
        run = json.loads(runs[0].read_text(encoding='utf-8'))
        assert run['status'] == 'completed_candidates_unverified' and run['gpu_matmul_verified']
        chunks = [json.loads((runs[0].parent/(cid+'.json')).read_text(encoding='utf-8'))
                  for sample in run['samples'] for cid in sample['chunks']]
        assert chunks and all(c['termination']=='eos' and any(s['text'].strip() for s in c['segments']) for c in chunks)
        quality = json.loads((scratch/'outputs'/job/'delivery/quality.json').read_text(encoding='utf-8'))
        assert quality['procedural_pass']
        summary.append(dict(engine=engine, audio_seconds=duration, eos=True,
                            chunks=len(chunks), procedural_pass=True, revision=run['config']['revision']))
    assert scratch.parent == parent and not any(p.is_symlink() or p.is_junction() for p in scratch.rglob('*'))
assert not scratch.exists()
print(json.dumps(dict(smoke=summary, temporary_audio_removed=True), indent=2))
```

```powershell
& $taskAsr -B work/setup_smoke.py
if ($LASTEXITCODE -ne 0) { throw 'Smoke failed; inspect the error without relaxing model policy' }
```

硬链接要求模型目录与临时目录位于同一 NTFS 卷；可用 `--scratch-parent` 指定该卷中的可写临时目录。模型文件只用于加载，不写入；请关闭其他占用 GPU 的推理任务。脚本的临时副本使用自己的 GPU 锁，不协调另一个项目的运行器。System.Speech 需 Windows 的本地语音组件；缺失时应安装组件后重试，不拿私人会议片段代替测试材料。

## 6. 开始实际工作

先阅读 [工作流](AUDIO_WORKFLOW.md)，然后按 README 登记实际录音。内容整理需要能读取项目文件的 AI agent（当前推荐 Codex）或人工完整阅读全文、写笔记、维护 spec 并审查来源。脚本不会自动完成高质量内容写作；注册或 ASR 成功不等于课堂笔记/会议纪要已完成。

第三方模型、MOSS 源码、FFmpeg 和依赖受各自许可证约束；Apache-2.0 只适用于本项目授权的代码与文档，不重新授权第三方组件。

## 常见失败排查

| 现象或报错 | 检查与处理 |
|---|---|
| `py` 找不到 Python、入口找不到 `envs/asr/Scripts/python.exe` | 完成第 1 步；可用实际 Python 3.12 路径创建环境。纯合成测试不要求安装 ASR 包。 |
| PowerShell 拒绝运行 `.ps1` | 依照本机执行策略运行已审阅脚本；也可在项目根用 `& $taskAsr -B src/audio_workflow.py --help` 查看等价 Python CLI，不修改全局策略。 |
| `FileNotFoundError` 指向 FFmpeg 或 `No readable audio stream` | 完成第 4 步，检查 `tools/ffmpeg.exe`、本地配置或 `AUDIONOTES_FFMPEG`；用该 FFmpeg 的 `-i` 检查输入。 |
| CUDA unavailable、DLL 加载失败、CUDA out of memory | 核对第 1/4 步的驱动、CUDA Torch wheel 与对应环境；关闭其他 GPU 任务。不要替换成 CPU Torch，或修改固定块长掩盖问题。 |
| 缺少 `download_manifest.json`、Whisper `refs/main` 或本地权重 | 完成第 3/3a 步；运行器离线加载，不会补下载。Qwen/MOSS 在 `models/<模型名>`，Whisper 使用配置的 cache 下 `snapshots/<revision>`。不要伪造 manifest。 |
| `No module named moss_transcribe_diarize` | 在 `envs/moss` 完成第 2 步源码安装；Qwen/Whisper 使用 `envs/asr`。 |
| `Stereo input`、日期或 collection 缺失 | 填实际事件日期、课程/项目名称；立体声检查后显式选 `-Channels separate`。 |
| `Source structure requires localized repair` | 查看该 job 的 `delivery/quality.json`；只有非 EOS 异常适用工作流中的自动 repair 命令，再选择候选、重建来源。其他疑点不能靠重复全量推理解决。 |
| 多个 completed runs 或 repair 的裸 `AssertionError` | 当前自动 repair 要求只有一个 full run 目录及一个 repair run 目录；检查 `run.json` 状态、计划与 chunk 哈希。保留原件，显式审查来源，不能删除旧证据绕过断言。 |
| `Source hash changed`、`Preserve human-edited delivery` 或手改保护报错 | 停止覆盖并核对来源/手改版本，按工作流保留与合并；不能改 hash 冒充原件。 |

安装及下载仍依赖上游源可用性；本次 maintenance 未重装依赖或重新下载权重，复用范围及未验证项目见 [发布检查](RELEASE_CHECK.md)。
