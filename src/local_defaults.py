"""Local ASR v1.1 policy; cached deliveries remain authoritative for reuse."""
import copy, hashlib, json
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / 'profiles/local_defaults_v1.1.json'

def policy_for(profile, collection='', scene=None):
    data = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    if scene is None:
        scene = ('meeting' if profile == 'research_meeting' else
                 'mixed_class' if '英语' in (collection or '') else
                 'humanities' if any(w in (collection or '') for w in ['文学', '剧作', '曹禺', '人文']) else
                 'technical_class')
    if (scene == 'meeting') != (profile == 'research_meeting'):
        raise ValueError('Scene and course/meeting profile disagree')
    return dict(version=data['version'], scene=scene, **copy.deepcopy(data['scenes'][scene]))

def whisper_options():
    # Passed to the library on EACH block, never carry info.language forward.
    return dict(language=None, task='transcribe', beam_size=5, vad_filter=False,
                condition_on_previous_text=False, word_timestamps=True,
                temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0])

def effective_config(config, rows, model, requested_seconds=None):
    lengths = sorted({round(c['end']-c['start'], 6) for r in rows for c in r['chunks']})
    if not lengths or min(lengths) <= 0:
        raise ValueError('Invalid planned chunk bounds')
    if requested_seconds is not None:
        raise ValueError('--chunk-seconds does not rechunk a cached plan; prepare a new scoped plan instead')
    config['chunk_seconds'] = max(lengths)
    config['actual_chunk_durations_s'] = lengths
    config['policy_helper_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    config['local_defaults_version'] = '1.1'
    if model == 'whisper':
        for key in ['max_new_tokens', 'do_sample', 'hotwords', 'vad']:
            config.pop(key, None)
        config.update(language=None, task='transcribe', effective_transcribe_kwargs=whisper_options(),
                      language_detection='per block; language=None passed anew')
    else:
        # These runner metadata fields were not arguments to either model.
        for key in ['beam_size', 'hotwords', 'vad']:
            config.pop(key, None)
        config['language'] = 'unforced; processor/model inference'
    return config
