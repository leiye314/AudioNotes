"""Full recording plans using the registered production policy."""
import json, subprocess, wave
from pathlib import Path
from project_paths import ffmpeg_path
from local_defaults import policy_for
from common import ROOT, sha, write_json

def plan(job, engine):
    catalog=json.loads((ROOT/'outputs/index.json').read_text(encoding='utf-8'))
    row=next(x for x in catalog['items'] if x['job_id']==job)
    source=Path(row['source_path'])
    assert sha(source)==row['source_sha256'], 'Source hash changed'
    policy=row.get('production_policy') or policy_for(row['profile'],row.get('collection',''))
    assert engine==policy['model'], 'Use a scoped fallback plan for an alternate engine'
    work=ROOT/'work'/job/'full';work.mkdir(parents=True,exist_ok=True)
    if (work/'plan.json').exists():
        existing=json.loads((work/'plan.json').read_text(encoding='utf-8'))
        assert existing['source_sha256']==row['source_sha256']
        assert (engine=='qwen')==(existing['profile'] in ['course_lecture','logic_lecture'])
        for c in existing['chunks']:
            assert sha(Path(c['path']))==c['sha256']
            if c.get('reused_from'):assert sha(Path(c['reused_from']))==c['reused_sha256']
        return existing
    wav=work/'source_16k_mono.wav'
    probe=subprocess.run([str(ffmpeg_path(ROOT)),'-hide_banner','-i',str(source)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    (work/'source_probe.txt').write_text(probe.stderr,encoding='utf-8')
    assert 'mono' in probe.stderr, 'Stereo requires the separate-channel runner; no implicit downmix'
    if not wav.exists():
        subprocess.run([str(ffmpeg_path(ROOT)),'-nostdin','-loglevel','error','-n','-i',str(source),'-map','0:a:0','-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)],check=True)
    with wave.open(str(wav),'rb') as w: duration=w.getnframes()/w.getframerate()
    seconds=policy['chunk_seconds']
    chunks=[];cursor=0
    with wave.open(str(wav),'rb') as w:
        rate=w.getframerate()
        def gap(end):
            nonlocal cursor
            while cursor<end-0.00001:
                stop=min(end,cursor+seconds);p=work/'chunks'/f'{cursor:010.3f}_{stop:010.3f}.wav';p.parent.mkdir(exist_ok=True)
                if not p.exists():
                    w.setpos(round(cursor*rate))
                    with wave.open(str(p),'wb') as out:
                        out.setparams(w.getparams());out.writeframes(w.readframes(round(stop*rate)-round(cursor*rate)))
                chunks.append({'start':cursor,'end':stop,'path':str(p),'sha256':sha(p)});cursor=stop
        gap(duration)
    result={**row,'sample_id':job+'_full','local_path':str(wav),'local_sha256':sha(wav),'source_start_s':0,'source_end_s':duration,'duration_s':duration,'chunks':chunks,'reused_chunks':0,'time_basis':'original_recording_seconds_no_silence_removal','human_verified':False}
    write_json(work/'plan.json',result)
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('job');p.add_argument('engine');a=p.parse_args()
    r=plan(a.job,a.engine);print(json.dumps({'job':a.job,'duration':r['duration_s'],'chunks':len(r['chunks']),'reuse':r['reused_chunks']}))
