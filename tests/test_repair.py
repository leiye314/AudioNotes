"""Synthetic native-mono and separated-stereo repair; no ASR dependencies."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import common
import prepare_repair
import select_repair


class RepairTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='audionotes-repair-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for module in [prepare_repair, select_repair]:
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
                             termination='token_limit_or_other' if start and label in broken_channels else 'eos')
                if stereo:
                    chunk['channel'] = label
                common.write_json(run_dir/(cid+'.json'), chunk)
            samples.append(dict(sample_id=row['sample_id'], chunks=ids))
        full = dict(channel_rows=rows, channel_policy='separate_L_R_no_downmix') if stereo else rows[0]
        common.write_json(work/'plan.json', full)
        common.write_json(run_dir/'run.json', dict(status='completed_candidates_unverified', samples=samples))
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
                    termination='eos', segments=[dict(text='synthetic')], review_flags=[]))
            samples.append(dict(chunks=ids))
        common.write_json(retry/'run.json', dict(status='completed_candidates_unverified', samples=samples))
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
