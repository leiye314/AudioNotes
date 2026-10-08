"""Synthetic native-mono and separated-stereo repair; no ASR dependencies."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import common
import postprocess_full
import prepare_repair
import select_repair


class RepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='audionotes-repair-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in [prepare_repair, select_repair, postprocess_full]:
            patcher = patch.object(module, 'ROOT', self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fixture(self, engine, stereo=False, broken_channels=None):
        job = engine + ('_stereo' if stereo else '_mono')
        channels = ['L', 'R'] if stereo else ['MONO']
        broken_channels = channels if broken_channels is None else broken_channels
        work = self.root/'work'/job/'full'
        work.mkdir(parents=True)
        run_dir = self.root/'outputs'/job/'full'/engine/'synthetic'
        rows, samples = [], []
        for label in channels:
            source = work/(label + '.wav')
            # Distinct channel samples detect accidental channel substitution.
            with wave.open(str(source), 'wb') as out:
                out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                out.writeframes((b'\x01\x00' if label != 'R' else b'\x02\x00') * 16000 * 70)
            row = dict(job_id=job, sample_id=job+'_'+label, local_path=str(source),
                       local_sha256=common.sha(source), source_path=str(source),
                       source_sha256=common.sha(source), source_start_s=0,
                       source_end_s=70, duration_s=70, chunks=[])
            if stereo:
                row['channel'] = label
            else:
                row['channel_policy'] = 'mono'
            rows.append(row)
            ids = []
            # A nonzero start and partial final slice exercise source offsets.
            for start, end in [(0, 5), (5, 70)]:
                cid = f'{job}_{label}_{start}'
                ids.append(cid)
                chunk = dict(chunk_id=cid, input_path=str(source), input_sha256=common.sha(source),
                             source_start_s=start, source_end_s=end,
                             timestamp_kind='synthetic',
                             segments=[dict(start=0, end=end-start, text=cid,
                                            speaker='speaker_0' if engine == 'moss' else None)],
                             termination='token_limit_or_other' if start and label in broken_channels else 'eos')
                if stereo:
                    chunk['channel'] = label
                common.write_json(run_dir/(cid+'.json'), chunk)
            samples.append(dict(sample_id=row['sample_id'], chunks=ids))
        full = dict(channel_rows=rows, channel_policy='separate_L_R_no_downmix', duration_s=70) if stereo else rows[0]
        common.write_json(work/'plan.json', full)
        common.write_json(run_dir/'run.json', dict(
            status='completed_candidates_unverified', samples=samples,
            config=dict(model=engine, revision='synthetic', chunk_seconds=30 if engine == 'qwen' else 120),
            new_inference_seconds=1, new_audio_seconds=70*len(channels),
            nvidia_device_peak_used_mib=0, gpu='synthetic; no GPU'))
        common.write_json(self.root/'outputs/index.json', {'items': [dict(
            job_id=job, profile='course_lecture' if engine == 'qwen' else 'research_meeting',
            source_path=rows[0]['source_path'], source_sha256=rows[0]['source_sha256'],
            partial_recording=False, part=None)]})
        before = {p: p.read_bytes() for p in [*work.rglob('*'), *run_dir.glob('*')] if p.is_file()}
        return job, before

    def check_plan_and_selection(self, engine, stereo=False, broken_channels=None):
        job, before = self.fixture(engine, stereo, broken_channels)
        result = prepare_repair.plan(job, engine)
        rows = result if isinstance(result, list) else [result]
        expected = broken_channels or (['L', 'R'] if stereo else ['MONO'])
        self.assertEqual([r['channel'] for r in rows], expected)
        self.assertEqual(isinstance(result, list), len(expected) > 1)
        step = 10 if engine == 'qwen' else 30
        bounds = [(a, min(a+step, 70)) for a in range(5, 70, step)]
        retry = self.root/'outputs'/job/'repairs'/engine/'synthetic'
        samples = []
        for row in rows:
            self.assertEqual([(c['start'], c['end']) for c in row['chunks']], bounds)
            self.assertEqual(len(row['replacements']), 1)
            self.assertEqual(row['replacements'][0]['replacement_bounds'], [list(b) for b in bounds])
            ids = []
            for chunk in row['chunks']:
                with wave.open(row['local_path'], 'rb') as source, wave.open(chunk['path'], 'rb') as cut:
                    source.setpos(chunk['start'] * 16000)
                    frames = (chunk['end'] - chunk['start']) * 16000
                    self.assertEqual(cut.getnframes(), frames)
                    self.assertEqual(cut.readframes(frames), source.readframes(frames))
                cid = row['sample_id'] + '_' + str(chunk['start'])
                ids.append(cid)
                common.write_json(retry/(cid+'.json'), dict(
                    channel=row['channel'], source_start_s=chunk['start'], source_end_s=chunk['end'],
                    input_path=chunk['path'], timestamp_kind='synthetic', termination='eos',
                    segments=[dict(start=0, end=chunk['end']-chunk['start'], text=cid,
                                   speaker='speaker_0' if engine == 'moss' else None)], review_flags=[]))
            samples.append(dict(chunks=ids))
        common.write_json(retry/'run.json', dict(
            status='completed_candidates_unverified', samples=samples,
            config=dict(model=engine, revision='synthetic', chunk_seconds=step),
            new_inference_seconds=2, nvidia_device_peak_used_mib=0))
        self.assertEqual(prepare_repair.plan(job, engine), result)
        with patch.object(sys, 'argv', ['select_repair', '--job', job, '--engine', engine]), contextlib.redirect_stdout(io.StringIO()):
            select_repair.main()
        selected = json.loads((self.root/'outputs'/job/'repair_selection.json').read_text())
        self.assertFalse(selected['human_verified'])
        self.assertEqual(len(selected['replacements']), len(expected))
        for row in rows:
            old = row['replacements'][0]
            chosen = selected['replacements'][old['original_chunk_id']]['replacement_files']
            self.assertEqual(len(chosen), len(bounds))
            for meta, bound in zip(chosen, bounds):
                path = Path(meta['path'])
                chunk = json.loads(path.read_text())
                self.assertEqual((chunk['channel'], chunk['source_start_s'], chunk['source_end_s']), (row['channel'], *bound))
                self.assertEqual(common.sha(path), meta['sha256'])
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        return job, rows, retry

    def process_delivery(self, job):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        # Only RMS arithmetic is stubbed: keep the stdlib-only CI contract.
        # WAV reads, selection, hashes, time mapping and output rendering are real.
        numpy = MagicMock()
        numpy.frombuffer.return_value.astype.return_value.__truediv__.return_value.__len__.return_value = 1
        numpy.sqrt.return_value = 0.25
        with patch.dict(sys.modules, {'numpy': numpy}), contextlib.redirect_stdout(io.StringIO()):
            quality = postprocess_full.process(job)
        self.assertTrue(quality['procedural_pass'])
        self.assertFalse(quality['human_full_text_verified'])
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content, str(path))
        out = self.root/'outputs'/job/'delivery'
        records = json.loads((out/'raw_segments.json').read_text(encoding='utf-8'))
        for record in records:
            chunk = json.loads(Path(record['raw_path']).read_text(encoding='utf-8'))
            segment = chunk['segments'][record['raw_segment_index']]
            self.assertEqual(record['text'], segment['text'])
            self.assertEqual(record['source_start_s'], chunk['source_start_s'] + segment['start'])
            self.assertEqual(record['source_end_s'], chunk['source_start_s'] + segment['end'])
            self.assertFalse(record['human_verified'])
        return out, records

    def test_postprocess_channel_outputs_without_repairs(self):
        for engine in ['qwen', 'moss']:
            for stereo in [False, True]:
                with self.subTest(engine=engine, stereo=stereo):
                    job, _ = self.fixture(engine, stereo, broken_channels=[])
                    out, records = self.process_delivery(job)
                    self.check_channel_outputs(out, records, stereo)
                    for name in ['raw_transcript.md', 'corrected_transcript.md']:
                        self.assertNotIn('异常局部重试', (out/name).read_text(encoding='utf-8'))

    def check_channel_outputs(self, out, records, stereo):
        for name in ['raw_transcript.md', 'corrected_transcript.md']:
            self.assertEqual('双声道独立识别' in (out/name).read_text(encoding='utf-8'), stereo)
        combined = (out/'raw_timestamps.srt').read_text(encoding='utf-8')
        for channel in ['L', 'R']:
            path = out/f'raw_timestamps_{channel}.srt'
            self.assertEqual(path.exists(), stereo)
            if stereo:
                content = path.read_text(encoding='utf-8')
                self.assertTrue(content.strip())
                expected = [r for r in records if r['channel'] == channel]
                self.assertEqual(content.count(' --> '), len(expected))
                for record in expected:
                    self.assertIn(f'[{channel}] ' + record['text'], content)
                    self.assertIn(f'[{channel}] ' + record['text'], combined)
                self.assertNotIn('[R]' if channel == 'L' else '[L]', content)
        self.assertEqual(combined.count(' --> '), len(records))
        if not stereo:
            for label in ['[L]', '[R]', '[MONO]', '[None]']:
                self.assertNotIn(label, combined)

    def test_postprocess_repair_notes_and_provenance(self):
        for engine, seconds in [('qwen', 10), ('moss', 30)]:
            for stereo in [False, True]:
                with self.subTest(engine=engine, stereo=stereo):
                    job, _, _ = self.check_plan_and_selection(engine, stereo)
                    out, records = self.process_delivery(job)
                    self.check_channel_outputs(out, records, stereo)
                    for name in ['raw_transcript.md', 'corrected_transcript.md', 'CHANGES.md', 'quality.md']:
                        text = (out/name).read_text(encoding='utf-8')
                        self.assertIn(f'{seconds}秒以内短块', text)
                        self.assertNotIn(f'{30 if seconds == 10 else 10}秒以内短块', text)
                    selection = json.loads((out.parent/'repair_selection.json').read_text(encoding='utf-8'))
                    provenance = json.loads((out/'provenance.json').read_text(encoding='utf-8'))
                    self.assertEqual(provenance['repair_selection'], selection)
                    corrections = json.loads((out/'corrections.json').read_text(encoding='utf-8'))
                    self.assertFalse(corrections['human_audio_verified'])
                    self.assertEqual(corrections['substantive_text_changes'], [])
                    self.assertEqual(corrections['model_candidate_replacements'], selection['replacements'])

    def test_native_mono_qwen_and_moss_repair(self):
        for engine in ['qwen', 'moss']:
            with self.subTest(engine=engine):
                self.check_plan_and_selection(engine)

    def test_stereo_identical_bounds_keep_both_channels(self):
        for engine in ['qwen', 'moss']:
            with self.subTest(engine=engine):
                self.check_plan_and_selection(engine, stereo=True)

    def test_stereo_only_failed_right_channel_is_repaired(self):
        for engine in ['qwen', 'moss']:
            with self.subTest(engine=engine):
                self.check_plan_and_selection(engine, stereo=True, broken_channels=['R'])

    def test_cached_repair_rejects_changed_audio(self):
        job, rows, _ = self.check_plan_and_selection('qwen')
        Path(rows[0]['chunks'][0]['path']).write_bytes(b'changed')
        with self.assertRaises(AssertionError):
            prepare_repair.plan(job, 'qwen')

    def test_selection_rejects_incomplete_or_invalid_retry(self):
        job, rows, retry = self.check_plan_and_selection('moss')
        path = next(p for p in retry.glob('*.json') if p.name != 'run.json')
        good = json.loads(path.read_text())
        selection = self.root/'outputs'/job/'repair_selection.json'
        before = selection.read_bytes()
        for bad in [dict(termination='token_limit_or_other'), dict(segments=[]), dict(review_flags=['invalid_timestamp'])]:
            common.write_json(path, {**good, **bad})
            with patch.object(sys, 'argv', ['select_repair', '--job', job, '--engine', 'moss']), self.assertRaises(AssertionError):
                select_repair.main()
            self.assertEqual(selection.read_bytes(), before)

    def test_mono_repair_rejects_unsplit_stereo_audio(self):
        job, _ = self.fixture('qwen')
        plan_path = self.root/'work'/job/'full/plan.json'
        full = json.loads(plan_path.read_text())
        with wave.open(full['local_path'], 'wb') as out:
            out.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(b'\x00' * 4 * 16000)
        full['local_sha256'] = common.sha(Path(full['local_path']))
        common.write_json(plan_path, full)
        with self.assertRaisesRegex(AssertionError, 'Repair source must be mono'):
            prepare_repair.plan(job, 'qwen')


if __name__ == '__main__':
    unittest.main()
