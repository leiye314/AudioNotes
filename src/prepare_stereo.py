"""Preserve independent stereo evidence: run each channel, never silently downmix."""
import json,subprocess,wave
from pathlib import Path
from project_paths import ffmpeg_path
from local_defaults import policy_for
from common import ROOT,sha,write_json

def plan(job,engine):
    assert engine in ['qwen','moss']
    row=next(r for r in json.loads((ROOT/'outputs/index.json').read_text(encoding='utf-8'))['items'] if r['job_id']==job)
    assert sha(Path(row['source_path']))==row['source_sha256']
    policy=row.get('production_policy') or policy_for(row['profile'],row.get('collection',''))
    assert engine==policy['model'], 'Use a scoped fallback plan for an alternate engine'
    work=ROOT/'work'/job/'full';work.mkdir(parents=True,exist_ok=True)
    if (work/'plan.json').exists():
        p=json.loads((work/'plan.json').read_text(encoding='utf-8'))
        assert p['channel_policy']=='separate_L_R_no_downmix'
        for r in p['channel_rows']:
            for c in r['chunks']:assert sha(Path(c['path']))==c['sha256']
        return p
    channels=[]
    for i,label in enumerate(['L','R']):
        path=work/f'source_{label}_16k.wav'
        if not path.exists():subprocess.run([str(ffmpeg_path(ROOT)),'-nostdin','-loglevel','error','-n','-i',row['source_path'],'-af',f'pan=mono|c0=c{i}','-ar','16000','-c:a','pcm_s16le',str(path)],check=True)
        chunks=[]
        with wave.open(str(path),'rb') as w:
            rate=w.getframerate();duration=w.getnframes()/rate;start=0
            while start<duration:
                end=min(start+policy['chunk_seconds'],duration);chunk=work/f'chunks_{label}'/f'{start:010.3f}_{end:010.3f}.wav';chunk.parent.mkdir(exist_ok=True)
                if not chunk.exists():
                    w.setpos(round(start*rate))
                    with wave.open(str(chunk),'wb') as out:out.setparams(w.getparams());out.writeframes(w.readframes(round(end*rate)-round(start*rate)))
                chunks.append({'start':start,'end':end,'path':str(chunk),'sha256':sha(chunk),'channel':label});start=end
        channels.append({**row,'sample_id':job+'_full_'+label,'channel':label,'local_path':str(path),'local_sha256':sha(path),'source_start_s':0,'source_end_s':duration,'duration_s':duration,'chunks':chunks})
    result={'job_id':job,'source_path':row['source_path'],'source_sha256':row['source_sha256'],'duration_s':duration,'channel_policy':'separate_L_R_no_downmix','channel_rows':channels,'human_verified':False}
    write_json(work/'plan.json',result);return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('job');parser.add_argument('engine',choices=['qwen','moss']);args=parser.parse_args()
    result=plan(args.job,args.engine);print(json.dumps({'channels':2,'chunks':sum(len(r['chunks']) for r in result['channel_rows'])}))
