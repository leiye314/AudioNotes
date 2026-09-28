"""Machine-local paths. No model loading, downloads, or environment mutation."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def settings(root=None):
    path = (root or ROOT) / 'profiles/local_settings.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def configured_path(key, default, root=None):
    root = root or ROOT
    value = os.environ.get('AUDIONOTES_' + key.upper()) or settings(root).get(key) or default
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def ffmpeg_path(root=None):
    return configured_path('ffmpeg', 'tools/ffmpeg.exe', root)


def whisper_cache(root=None):
    return configured_path('whisper_cache', 'models/hf-cache/models--Systran--faster-whisper-large-v3', root)


def moss_source_revision(root=None):
    root = root or ROOT
    # Preserve the installed private baseline; clean exports use the public pin.
    existing = root / 'reports/moss-source-revision.txt'
    if existing.exists():
        return existing.read_text(encoding='utf-8').strip()
    return json.loads((root / 'profiles/runtime_versions.json').read_text(encoding='utf-8'))['moss_source_revision']
