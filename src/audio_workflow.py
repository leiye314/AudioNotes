"""Small incremental audio registry. Editorial work stays in the active Codex session."""
import argparse,datetime,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
from project_paths import ffmpeg_path
from local_defaults import policy_for
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'work/reading_v1/incremental.json'
EXT={'.m4a','.wav','.mp3','.flac','.aac','.ogg','.opus','.mp4'}
def read(p,default=None):return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default
def write(p,data):
 p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,p)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def stable_hash(p,wait=2):
 a=p.stat();time.sleep(wait);b=p.stat()
 if (a.st_size,a.st_mtime_ns)!=(b.st_size,b.st_mtime_ns) or not b.st_size:raise ValueError('still_copying_or_empty')
 digest=sha(p);c=p.stat()
 if (b.st_size,b.st_mtime_ns)!=(c.st_size,c.st_mtime_ns):raise ValueError('changed_while_hashing')
 return digest,c.st_size
def contained(path,parent):return path.resolve().is_relative_to(parent.resolve())
def infer(p):
 profile='research_meeting' if 'meetings' in p.parts or re.search('会议|组会',p.name) else 'course_lecture' if 'courses' in p.parts else 'logic_lecture' if 'logic' in p.parts or '逻辑' in p.name else 'course_lecture' if re.search('课程|课堂|讲课',p.name) else None
 m=re.search(r'(?<!\d)(20\d\d|\d\d)[.年_-](\d{1,2})[.月_-](\d{1,2})(?!\d)',p.stem)
 date=None
 if m:
  y,mo,d=map(int,m.groups())
  try:date=datetime.date(y+2000 if y<100 else y,mo,d).isoformat()
  except ValueError:pass
 return profile,date
def catalog():return read(ROOT/'outputs/index.json',{'items':[]})
def existing_by_hash():return {r['source_sha256']:r for r in catalog()['items']}
def source_ready(raw,digest):
 if raw is None or not raw.exists():return False
 provenance=read(raw.with_name('provenance.json'),{})
 quality=read(raw.with_name('quality.json'),{})
 return provenance.get('source_sha256')==digest and quality.get('procedural_pass') is True and bool(read(raw,[]))
def publications():
 result={}
 for p in (ROOT/'work/reading_v1/specs').glob('*.json'):
  s=read(p);q=read(p.parent.parent/s['unit']/'publication.json',{})
  for job in s['jobs']:result[job]=q
 return result
def scan(wait=2):
 known=existing_by_hash();pub=publications();files=[]
 for folder in ['inbox','courses','logic','meetings']:
  for p in sorted((ROOT/'recordings'/folder).rglob('*')):
   if p.is_file() and p.suffix.lower() in EXT and contained(p,ROOT/'recordings'):files.append(p)
 # Observe all files over the same stability interval, avoiding a wait per recording.
 before={p:(p.stat().st_size,p.stat().st_mtime_ns) for p in files};time.sleep(wait);rows=[]
 for p in files:
  try:
   st=p.stat()
   if before[p]!=(st.st_size,st.st_mtime_ns):raise ValueError('still_copying')
   digest,size=stable_hash(p,0);profile,date=infer(p);old=known.get(digest);job=old['job_id'] if old else None
   raw=ROOT/'outputs'/job/'delivery/raw_segments.json' if job else None
   provenance=read(raw.with_name('provenance.json'),{}) if raw else {}
   complete=source_ready(raw,digest)
   q=pub.get(job,{})
   rows.append(dict(path=str(p),sha256=digest,size=size,profile=old['profile'] if old else profile,event_date=date,job=job,asr='reused_complete' if complete else 'registered_pending' if job else 'new',text=q.get('text','pending'),publication=q.get('publication','pending'),directory=q.get('directory'),asr_config=provenance.get('config'),workflow='reading-v1'))
  except (OSError,ValueError) as e:rows.append(dict(path=str(p),asr='deferred',reason=str(e)))
 write(STATE,{'workflow':'reading-v1','items':rows});return rows
def register(source,profile=None,date=None,channel_policy=None,collection=None,scene=None):
 p=Path(source).resolve()
 if not contained(p,ROOT/'recordings') or p.suffix.lower() not in EXT:raise ValueError('Input must be supported audio inside recordings')
 digest,size=stable_hash(p);old=existing_by_hash().get(digest)
 if old:return dict(action='reuse',job=old['job_id'],source=str(p))
 inferred,day=infer(p);profile=profile or inferred;date=date or day
 if profile not in ['course_lecture','logic_lecture','research_meeting'] or not date:raise ValueError('Need course/meeting profile and actual event date; input kept in place')
 lecture=profile in ['course_lecture','logic_lecture']
 branch='courses' if lecture else 'meetings'
 relative=p.relative_to(ROOT/'recordings')
 if not collection and len(relative.parts)>=3 and relative.parts[0]==branch:collection=relative.parts[1]
 if not collection and profile=='logic_lecture':collection='逻辑与推理'
 if collection and (collection in ['.','..'] or re.search(r'[<>:"/\\|?*\x00-\x1f]',collection) or collection.rstrip(' .')!=collection):raise ValueError('Collection must be one safe course/project directory name')
 if not collection and relative.parts[0]=='inbox':raise ValueError('Need --collection course/project name; input kept in place')
 datetime.date.fromisoformat(date)
 policy=policy_for(profile,collection,scene)
 probe=subprocess.run([str(ffmpeg_path(ROOT)),'-hide_banner','-i',str(p)],capture_output=True,text=True,encoding='utf-8',errors='replace').stderr
 if 'Audio:' not in probe:raise ValueError('No readable audio stream')
 m=re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',probe)
 if not m:raise ValueError('Could not determine duration')
 h,mi,se=map(float,m.groups());duration=h*3600+mi*60+se
 stereo='stereo' in probe
 if stereo and channel_policy!='separate':
  raise ValueError('Stereo input: inspect channel content first; use --channels separate to preserve both; no silent downmix')
 if not stereo and 'mono' not in probe:raise ValueError('Unrecognized channel layout; inspect before processing')
 # Existing archived sources stay in place; only inbox is moved into the new layout.
 target=ROOT/'recordings'/branch/collection/p.name if relative.parts[0]=='inbox' else p
 if target!=p and target.exists():raise FileExistsError(f'Archive collision: {target}; original retained')
 if sha(p)!=digest:raise ValueError('Source changed before archive')
 job=('lecture_' if lecture else 'meeting_')+date.replace('-','')+'_'+digest[:12]
 c=catalog()
 if any(r['job_id']==job for r in c['items']):raise ValueError('Job ID collision')
 original=str(p)
 if target!=p:
  target.parent.mkdir(parents=True,exist_ok=True)
  # Same filesystem rename fails on an existing target, never replaces it.
  p.rename(target)
  if target.stat().st_size!=size or sha(target)!=digest:raise RuntimeError('Archive verification failed; preserve destination for recovery')
 part_match=re.search(r'(?i)(?:_|\b)(p\d+)',target.stem)
 row=dict(job_id=job,source_path=str(target),source_sha256=digest,source_duration_s=duration,event_date=date,event_date_basis='user_or_filename_not_upload_time',profile=profile,collection=collection,partial_recording=bool(re.search('部分|缺',target.name)),missing_recording_note='文件名标注缺前10min；不补造内容' if '缺前10min' in target.name else None,part=part_match.group(1) if part_match else None,selected_engine='Qwen/Qwen3-ASR-1.7B-hf' if lecture else 'OpenMOSS-Team/MOSS-Transcribe-Diarize',selection_status='established_default',processing_status='registered',unresolved=[],full_recording_raw_transcript=None,channel_policy='separate_L_R_no_downmix' if stereo else 'mono')
 row.update(production_policy=policy,selection_status='local_default_v1.1')
 c['items'].append(row);write(ROOT/'outputs/index.json',c)
 write(ROOT/'work'/job/'registration.json',dict(original_path=original,archived_path=str(target),size=size,sha256=digest,row=row,probe=probe,workflow='reading-v1'))
 return dict(action='registered',job=job,source=str(target))
def ensure_asr(job,rewrite_only=False):
 row=next(r for r in catalog()['items'] if r['job_id']==job)
 if sha(Path(row['source_path']))!=row['source_sha256']:raise ValueError('Source hash changed')
 base=ROOT/'outputs'/job;raw=base/'delivery/raw_segments.json'
 if source_ready(raw,row['source_sha256']):
  return dict(job=job,action='reuse_complete',raw=str(raw),asr_calls=0,next='Codex full reading and editorial writing')
 if rewrite_only:raise ValueError('No complete transcript to rewrite; ASR was not called')
 policy=row.get('production_policy') or policy_for(row['profile'],row.get('collection',''))
 engine=policy['model']
 done=[p for p in (base/'full'/engine).glob('*/run.json') if read(p).get('status')=='completed_candidates_unverified']
 if len(done)>1:raise ValueError('Multiple completed runs; select source explicitly')
 if not done:
  python=ROOT/'envs'/('asr' if engine=='qwen' else 'moss')/'Scripts/python.exe'
  runner='run_stereo_full.py' if row.get('channel_policy')=='separate_L_R_no_downmix' else 'run_full.py'
  subprocess.run([str(python),'-B',str(ROOT/'src'/runner),'--model',engine,'--job',job],cwd=ROOT,check=True,env={**os.environ,'PYTHONUTF8':'1'},creationflags=0x08000000)
 from postprocess_full import process
 q=process(job,reading_source_only=True)
 if not q['procedural_pass']:raise RuntimeError('Source structure requires localized repair; originals preserved')
 return dict(job=job,action='source_ready',raw=str(raw),asr_calls=0 if done else 1,next='Codex full reading and editorial writing')
def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('scan')
 r=sub.add_parser('register');r.add_argument('source');r.add_argument('--profile',choices=['course_lecture','logic_lecture','research_meeting']);r.add_argument('--date');r.add_argument('--channels',choices=['separate']);r.add_argument('--collection');r.add_argument('--scene',choices=['technical_class','mixed_class','humanities','meeting'])
 a=sub.add_parser('asr');a.add_argument('job');a.add_argument('--rewrite-only',action='store_true')
 args=p.parse_args()
 if args.command=='scan':
  rows=scan();result=[{k:v for k,v in r.items() if k!='asr_config'} for r in rows]
 elif args.command=='register':result=register(args.source,args.profile,args.date,args.channels,args.collection,args.scene)
 else:result=ensure_asr(args.job,args.rewrite_only)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
