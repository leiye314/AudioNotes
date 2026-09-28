"""Prepare an explicit small fallback interval, never alter existing ASR/delivery."""
import argparse, hashlib, json, subprocess, wave
from pathlib import Path
from project_paths import ffmpeg_path
from common import ROOT, sha, write_json

def validate_plan(path,job,engine):
    path=Path(path).resolve()
    assert path.is_relative_to((ROOT/'work'/job/'local_fallback').resolve())
    rows=json.loads(path.read_text(encoding='utf-8'))
    source=next(r for r in json.loads((ROOT/'outputs/index.json').read_text(encoding='utf-8'))['items'] if r['job_id']==job)
    for r in rows:
        assert r['job_id']==job and r['engine']==engine
        assert r['source_sha256']==source['source_sha256']==sha(Path(source['source_path']))
        assert sha(Path(r['local_path']))==r['local_sha256']
        assert 0<r['duration_s']<=120
        assert 0<=r['source_start_s']<r['source_end_s']<=source['source_duration_s']
        assert r['source_end_s']-r['source_start_s']==r['duration_s']
        cursor=0
        for c in r['chunks']:
            assert c['start']==cursor and 0<c['end']-c['start']<=30
            assert sha(Path(c['path']))==c['sha256']
            with wave.open(c['path'],'rb') as w:
                assert w.getnchannels()==1 and w.getframerate()==16000
                assert abs(w.getnframes()/16000-(c['end']-c['start']))<0.001
            cursor=c['end']
        assert cursor==r['duration_s']
    return rows

def prepare(job,start,end,channel,engine,reason):
    row=next(r for r in json.loads((ROOT/'outputs/index.json').read_text(encoding='utf-8'))['items'] if r['job_id']==job)
    assert 0<=start<end<=row['source_duration_s'] and end-start<=120
    assert sha(Path(row['source_path']))==row['source_sha256']
    stereo=row.get('channel_policy')=='separate_L_R_no_downmix'
    assert (channel in ['L','R']) if stereo else channel=='MONO'
    request=dict(job=job,start=start,end=end,channel=channel,engine=engine,reason=reason,source_sha256=row['source_sha256'])
    identity=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()[:16]
    folder=ROOT/'work'/job/'local_fallback'/identity;folder.mkdir(parents=True,exist_ok=True)
    dest=folder/'plan.json'
    if dest.exists():validate_plan(dest,job,engine);return dest
    wav=folder/'source.wav'
    cmd=[str(ffmpeg_path(ROOT)),'-nostdin','-loglevel','error','-n','-i',row['source_path'],'-ss',str(start),'-t',str(end-start)]
    if stereo:cmd+=['-af','pan=mono|c0=c'+('0' if channel=='L' else '1')]
    cmd+=['-ar','16000','-ac','1','-c:a','pcm_s16le',str(wav)]
    if not wav.exists():subprocess.run(cmd,check=True)
    chunks=[]
    with wave.open(str(wav),'rb') as w:
        cursor=0
        while cursor<end-start:
            stop=min(cursor+30,end-start);p=folder/f'{cursor:07.2f}_{stop:07.2f}.wav'
            w.setpos(round(cursor*16000))
            if not p.exists():
                with wave.open(str(p),'wb') as out:out.setparams(w.getparams());out.writeframes(w.readframes(round((stop-cursor)*16000)))
            chunks.append(dict(path=str(p),start=cursor,end=stop,sha256=sha(p)));cursor=stop
    write_json(folder/'request.json',request)
    write_json(dest,[{**row,'engine':engine,'channel':channel,'sample_id':job+'_fallback_'+identity,'source_start_s':start,'source_end_s':end,'duration_s':end-start,'local_path':str(wav),'local_sha256':sha(wav),'chunks':chunks}])
    validate_plan(dest,job,engine);return dest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True);p.add_argument('--channel',choices=['L','R','MONO'],required=True);p.add_argument('--engine',choices=['qwen','moss','whisper'],required=True);p.add_argument('--reason',required=True)
    a=p.parse_args();print(prepare(a.job,a.start,a.end,a.channel,a.engine,a.reason))
