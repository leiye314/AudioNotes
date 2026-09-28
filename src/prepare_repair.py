"""Repair only objectively truncated chunks, preserving their raw evidence."""
import json,wave
from pathlib import Path
from common import ROOT,sha,write_json

def plan(job,engine):
    assert engine in {'qwen','moss'}
    runs=list((ROOT/'outputs'/job/'full'/engine).glob('*/run.json'));assert len(runs)==1
    run=json.loads(runs[0].read_text(encoding='utf-8'));assert run['status']=='completed_candidates_unverified'
    broken=[]
    for sample in run['samples']:
        for cid in sample['chunks']:
            p=runs[0].parent/(cid+'.json');d=json.loads(p.read_text(encoding='utf-8'))
            if d['termination']!='eos':broken.append((p,d))
    assert broken
    work=ROOT/'work'/job/'repairs';work.mkdir(parents=True,exist_ok=True)
    if (work/'plan.json').exists():
        plan=json.loads((work/'plan.json').read_text(encoding='utf-8'))
        rows=plan if isinstance(plan,list) else [plan]
        assert {r['original_chunk_id'] for row in rows for r in row['replacements']}=={d['chunk_id'] for p,d in broken}
        for row in rows:
            for c in row['chunks']:assert sha(Path(c['path']))==c['sha256']
        return plan
    fullplan=json.loads((ROOT/'work'/job/'full/plan.json').read_text(encoding='utf-8'))
    results=[]
    for channel in sorted({d['channel'] for p,d in broken}):
        results.append(channel_plan(job,engine,channel,fullplan,broken,work))
    result=results[0] if len(results)==1 else results
    write_json(work/'plan.json',result);return result

def channel_plan(job,engine,channel,fullplan,broken,work):
    source=next(r for r in fullplan['channel_rows'] if r['channel']==channel)
    assert source['source_start_s']==0, 'Full channel source must start at zero'
    assert sha(Path(source['local_path']))==source['local_sha256']
    chunks=[];replacements=[]
    with wave.open(source['local_path'],'rb') as w:
        rate=w.getframerate()
        for original,d in broken:
            if d['channel']!=channel:continue
            assert sha(Path(d['input_path']))==d['input_sha256']
            start=d['source_start_s'];end=d['source_end_s'];bounds=[]
            while start<end-0.00001:
                stop=min(start+(10 if engine=='qwen' else 30),end);p=work/f'{channel}_{start:010.3f}_{stop:010.3f}.wav'
                if not p.exists():
                    w.setpos(round(start*rate))
                    with wave.open(str(p),'wb') as out:out.setparams(w.getparams());out.writeframes(w.readframes(round(stop*rate)-round(start*rate)))
                chunks.append({'start':start,'end':stop,'path':str(p),'sha256':sha(p)});bounds.append([start,stop]);start=stop
            replacements.append({'original_chunk_id':d['chunk_id'],'original_path':str(original),'original_sha256':sha(original),'reason':'non_eos_token_limit','replacement_bounds':bounds})
    return {**source,'sample_id':job+'_repair_'+channel,'chunks':chunks,'replacements':replacements,'repair_policy':'only_non_eos_shrink_chunks_keep_failed_raw'}
