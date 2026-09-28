"""Portable synthetic invariants. No user data, network, models or GPU required."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'release'))
import audio_workflow as workflow
import common
import export_public
import local_defaults
import project_paths
import reading_publish as publication


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audionotes-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_four_routes_and_no_shared_mutable_whisper_config(self):
        for scene, model, seconds in [('technical_class', 'qwen', 30), ('mixed_class', 'qwen', 30),
                                      ('humanities', 'qwen', 30), ('meeting', 'moss', 120)]:
            p = local_defaults.policy_for('research_meeting' if scene == 'meeting' else 'course_lecture', scene=scene)
            self.assertEqual((p['model'], p['chunk_seconds'], p['stereo_policy']),
                             (model, seconds, 'separate_L_R_no_downmix'))
        local_defaults.whisper_options()['temperature'].append(99)
        self.assertEqual(local_defaults.whisper_options(), dict(language=None, task='transcribe', beam_size=5,
            vad_filter=False, condition_on_previous_text=False, word_timestamps=True,
            temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0]))

    def test_plan_bounds_are_not_overridden(self):
        rows = [dict(chunks=[dict(start=0, end=30), dict(start=30, end=41)])]
        result = local_defaults.effective_config({'max_new_tokens':4096}, rows, 'whisper')
        self.assertEqual(result['actual_chunk_durations_s'], [11, 30])
        self.assertNotIn('max_new_tokens', result)
        with self.assertRaises(ValueError):
            local_defaults.effective_config({}, rows, 'qwen', 10)

    def test_relative_paths_and_environment_override(self):
        common.write_json(self.root/'profiles/local_settings.json', {'ffmpeg':'custom/ffmpeg.exe'})
        with patch.dict(project_paths.os.environ, {}, clear=True):
            self.assertEqual(project_paths.ffmpeg_path(self.root), self.root/'custom/ffmpeg.exe')
            self.assertEqual(project_paths.whisper_cache(self.root),
                             self.root/'models/hf-cache/models--Systran--faster-whisper-large-v3')
            with patch.dict(project_paths.os.environ, {'AUDIONOTES_FFMPEG':'alternate/ffmpeg.exe'}):
                self.assertEqual(project_paths.ffmpeg_path(self.root), self.root/'alternate/ffmpeg.exe')

    def test_cached_rewrite_never_starts_process(self):
        source=self.root/'source.wav';source.write_bytes(b'synthetic fixture only')
        job='synthetic';digest=common.sha(source)
        common.write_json(self.root/'outputs/index.json', {'items':[dict(job_id=job,
                          source_path=str(source), source_sha256=digest)]})
        raw=self.root/'outputs'/job/'delivery/raw_segments.json'
        with patch.object(workflow,'ROOT',self.root), patch.object(workflow.subprocess,'run',side_effect=AssertionError('No inference')):
            with self.assertRaisesRegex(ValueError,'No complete transcript'):
                workflow.ensure_asr(job,True)
            common.write_json(raw,[{'text':'synthetic'}])
            common.write_json(raw.with_name('provenance.json'),{'source_sha256':digest})
            common.write_json(raw.with_name('quality.json'),{'procedural_pass':True})
            self.assertEqual(workflow.ensure_asr(job,True)['asr_calls'],0)
            source.write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError,'Source hash changed'):
                workflow.ensure_asr(job,True)

    def test_publication_guards_archive_and_idempotency(self):
        back=self.root/'work/reading_v1';unit='synthetic'
        raw=self.root/'outputs/synthetic/delivery/raw_segments.json'
        common.write_json(raw,[dict(id='S00001',text='合成测试内容。',speaker=None,source_start_s=0,source_end_s=1)])
        spec=dict(unit=unit,jobs=[unit],kind='lecture',directory='课程/测试/一',title='测试',
                  notes='synthetic.md',intro='测试。',uncertainties='无。',review='合成资料。',
                  headings=[dict(at='synthetic:S00001',title='测试')])
        common.write_json(back/'specs/synthetic.json',spec)
        (back/'drafts').mkdir();draft=back/'drafts/synthetic.md';draft.write_text('# 合成笔记\n第一版',encoding='utf-8')
        with patch.object(publication,'ROOT',self.root),patch.object(publication,'BACK',back),contextlib.redirect_stdout(io.StringIO()):
            publication.publish(spec)
            final=self.root/'阅读成品'/spec['directory']/'02_课堂笔记.md'
            first=final.read_bytes();mtime=final.stat().st_mtime_ns
            publication.publish(spec);self.assertEqual(final.stat().st_mtime_ns,mtime)
            draft.write_text('# 合成笔记\n第二版',encoding='utf-8');publication.publish(spec)
            versions=list((back/unit/'versions').glob('*/02_课堂笔记.md'))
            self.assertEqual(len(versions),1);self.assertEqual(versions[0].read_bytes(),first)
            final.write_text('用户手改',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'手改'):publication.publish(spec)
            self.assertEqual(final.read_text(encoding='utf-8'),'用户手改')

    def make_export_fixture(self):
        (self.root/'src').mkdir();(self.root/'src/ok.py').write_text('print(1)\n',encoding='utf-8')
        common.write_json(self.root/'release/public_allowlist.json',{'files':[dict(source='src/ok.py',target='src/ok.py')]})

    def test_export_only_allowlisted_files_and_refuses_overwrite(self):
        self.make_export_fixture()
        (self.root/'src/private.py').write_text('personal data',encoding='utf-8')
        target=self.root/'new-export';result=export_public.export(self.root,target)
        self.assertEqual(set(result),{'src/ok.py'});self.assertFalse((target/'src/private.py').exists())
        self.assertEqual(common.sha(target/'src/ok.py'),result['src/ok.py'])
        with self.assertRaises(FileExistsError):export_public.export(self.root,target)

    def test_export_rejects_private_paths_and_traversal(self):
        for path in ['../outside.py','/absolute.py','recordings/secret.md','profiles/local_settings.json','src/../../outside.py']:
            with self.subTest(path=path),self.assertRaises(ValueError):
                export_public.safe_path(self.root,path)

    def test_export_rejects_duplicate_targets(self):
        self.make_export_fixture()
        common.write_json(self.root/'release/public_allowlist.json',{'files':[
            dict(source='src/ok.py',target='src/ok.py'),dict(source='src/ok.py',target='src/OK.py')]})
        with self.assertRaisesRegex(ValueError,'Duplicate'):export_public.prepare(self.root)

    def test_export_scans_paths_and_credentials(self):
        for value in ['Z'+':'+chr(92)+'private', 'sk-'+'a'*25, 'ghp_'+'a'*25]:
            with self.assertRaises(ValueError):export_public.scan_text(value)
        export_public.scan_text('relative/path example; no private material')
        export_public.scan_text('https://example.org/public/docs')

    def test_export_policy_transform_preserves_scenes(self):
        source=ROOT/'profiles/local_defaults_v1.1.json'
        common.write_json(self.root/'profiles/local_defaults_v1.1.json',json.loads(source.read_text(encoding='utf-8')))
        common.write_json(self.root/'release/public_allowlist.json',{'files':[dict(
            source='profiles/local_defaults_v1.1.json',target='profiles/local_defaults_v1.1.json',transform='policy_evidence')]})
        result=json.loads(export_public.prepare(self.root)['profiles/local_defaults_v1.1.json'])
        self.assertEqual(result['scenes'],json.loads(source.read_text(encoding='utf-8'))['scenes'])
        self.assertEqual(result['evidence'],'docs/AUDIO_WORKFLOW.md')


if __name__=='__main__':
    unittest.main()
