"""Print bounded full-source ranges; record requested coverage, not comprehension."""
import argparse, datetime, hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('job'); p.add_argument('start', type=int); p.add_argument('end', type=int)
p.add_argument('--channel')
p.add_argument('--snapshot', help='Immutable backend raw-segment snapshot while another source/channel is still running')
a = p.parse_args()
path = Path(a.snapshot).resolve() if a.snapshot else ROOT/'outputs'/a.job/'delivery/raw_segments.json'
if a.snapshot and not path.is_relative_to((ROOT/'work/reading_v1').resolve()):raise ValueError('Snapshot must stay inside the reading backend')
rows = json.loads(path.read_text(encoding='utf-8'))
selected = [r for i,r in enumerate(rows,1) if a.start <= i <= a.end and (not a.channel or r.get('channel') == a.channel)]
scope = None
for r in selected:
    if r.get('speaker_scope') != scope:
        scope = r.get('speaker_scope'); print('LOCAL SCOPE', scope)
    print(f"{r['id']} {r['source_start_s']:.1f} {r.get('speaker') or '-'} {r.get('channel') or '-'} | {r['text']}")
print(f'END RANGE {a.start}-{a.end}; {len(selected)} rows; total {len(rows)}')
log = ROOT/'work/reading_v1/read_log.jsonl'; log.parent.mkdir(parents=True,exist_ok=True)
with log.open('a',encoding='utf-8') as f:
    f.write(json.dumps({'job':a.job,'source_path':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'start':a.start,'end':a.end,'channel':a.channel,'ids':[r['id'] for r in selected],'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'meaning':'printed_in_full; model confirms comprehension in content review; snapshot rows require equality with final delivery'},ensure_ascii=False)+'\n')
