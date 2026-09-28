"""Serial GPU-only ASR with immutable, fingerprinted chunk checkpoints."""
import argparse, dataclasses, hashlib, importlib.metadata, json, os, subprocess, sys, threading, time, traceback, wave
from pathlib import Path
from common import ROOT, sha, write_json
from local_defaults import effective_config
from project_paths import whisper_cache, moss_source_revision
from prepare_stereo import plan

os.environ['HF_HOME']=str(ROOT/'models/hf-cache')
os.environ['HF_HUB_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['TEMP']=str(ROOT/'work/tmp')
os.environ['TMP']=str(ROOT/'work/tmp')
os.environ['PATH']=str(ROOT/'tools')+os.pathsep+os.environ['PATH']

def gpu_info():
    p=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,creationflags=0x08000000)
    return p.stdout.strip()

class Monitor:
    def __init__(self,path): self.path=path;self.stop=threading.Event();self.peak=0
    def start(self):
        def loop():
            with self.path.open('a',encoding='utf-8') as f:
                while not self.stop.is_set():
                    info=gpu_info()
                    try:self.peak=max(self.peak,float(info.split(',')[-2]))
                    except (ValueError,IndexError):pass
                    f.write(json.dumps({'time':time.time(),'nvidia_smi':info})+'\n');f.flush()
                    self.stop.wait(0.5)
        self.thread=threading.Thread(target=loop,daemon=True);self.thread.start()
    def finish(self):self.stop.set();self.thread.join()

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True,choices=['qwen','whisper','moss']);p.add_argument('--profile',choices=['logic_lecture','research_meeting']);p.add_argument('--smoke',action='store_true');p.add_argument('--chunk-seconds',type=int);p.add_argument('--job',required=True);args=p.parse_args()
    # OS file lock automatically releases on crash; never run two GPU models together.
    (ROOT/'work/tmp').mkdir(parents=True,exist_ok=True)
    import msvcrt
    lock=(ROOT/'work/gpu.lock').open('a+b');lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:raise RuntimeError('Another AudioNotes GPU process is active')
    import torch
    torch.set_num_threads(4)
    assert torch.cuda.is_available(),'CUDA unavailable; CPU fallback is prohibited'
    x=torch.randn((512,512),device='cuda'); y=x@x;torch.cuda.synchronize();assert torch.isfinite(y).all();del x,y
    dll=Path(torch.__file__).parent/'lib';dll_handle=os.add_dll_directory(str(dll));os.environ['PATH']=str(dll)+os.pathsep+os.environ['PATH']
    profile=args.profile or ('research_meeting' if args.model=='moss' else 'logic_lecture')
    rows=plan(args.job,args.model)['channel_rows']
    if args.smoke:rows=rows[:1]
    model_id={'qwen':'Qwen/Qwen3-ASR-1.7B-hf','moss':'OpenMOSS-Team/MOSS-Transcribe-Diarize','whisper':'Systran/faster-whisper-large-v3'}[args.model]
    if args.model=='whisper':
        cache=whisper_cache(ROOT)
        revision=(cache/'refs/main').read_text().strip();model_path=cache/'snapshots'/revision
    else:
        model_path=ROOT/'models'/model_id.split('/')[-1]
        revision=json.loads((model_path/'download_manifest.json').read_text())['revision']
    seconds=args.chunk_seconds or {'qwen':30,'whisper':120,'moss':120}[args.model]
    config={'model':model_id,'revision':revision,'device':'cuda:0','dtype':'float16' if args.model=='whisper' else 'bfloat16','attention':'CTranslate2' if args.model=='whisper' else 'sdpa','chunk_seconds':seconds,'batch_size':1,'max_new_tokens':1024 if args.model=='qwen' else 4096,'do_sample':False,'language':'zh' if args.model=='whisper' else 'auto','hotwords':None,'vad':False,'beam_size':5 if args.model=='whisper' else 1,'smoke':args.smoke,'script_sha256':sha(Path(__file__))}
    effective_config(config,rows,args.model,args.chunk_seconds)
    packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
    config['packages']=packages
    config['source_sha256']=rows[0]['source_sha256']
    config['plan_sha256']=sha(ROOT/'work'/args.job/'full/plan.json')
    config['workflow']='full_recording_reuse_formal_round1_v1'
    if args.model=='moss':
        from moss_transcribe_diarize.inference_utils import DEFAULT_PROMPT
        config['prompt']=DEFAULT_PROMPT
        config['source_commit']=moss_source_revision(ROOT)
    fingerprint=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:16]
    run=ROOT/'outputs'/rows[0]['job_id']/'full'/args.model/fingerprint
    run.mkdir(parents=True,exist_ok=True)
    if not (run/'runner_source.py').exists():
        (run/'runner_source.py').write_bytes(Path(__file__).read_bytes())
    helper=Path(__file__).with_name('local_defaults.py')
    if not (run/'policy_helper_source.py').exists():(run/'policy_helper_source.py').write_bytes(helper.read_bytes())
    report={'status':'running','config':config,'fingerprint':fingerprint,'gpu':gpu_info(),'torch_cuda':torch.version.cuda,'torch_arch_list':torch.cuda.get_arch_list(),'gpu_capability':torch.cuda.get_device_capability(),'gpu_matmul_verified':True,'samples':[]}
    write_json(run/'run.json',report)
    monitor=Monitor(run/'gpu.jsonl');monitor.start();t0=time.perf_counter()
    try:
        if args.model=='qwen':
            from transformers import AutoModelForMultimodalLM,AutoProcessor
            processor=AutoProcessor.from_pretrained(str(model_path),local_files_only=True)
            model=AutoModelForMultimodalLM.from_pretrained(str(model_path),dtype=torch.bfloat16,attn_implementation='sdpa',local_files_only=True).to('cuda').eval()
        elif args.model=='whisper':
            from faster_whisper import WhisperModel
            model=WhisperModel(str(model_path),device='cuda',compute_type='float16',local_files_only=True,num_workers=1,cpu_threads=4)
            assert model.model.device=='cuda'
        else:
            from transformers import AutoModelForCausalLM,AutoProcessor
            from moss_transcribe_diarize import parse_transcript
            from moss_transcribe_diarize.inference_utils import build_transcription_messages,prepare_inputs
            model=AutoModelForCausalLM.from_pretrained(str(model_path),trust_remote_code=True,local_files_only=True,dtype=torch.bfloat16,attn_implementation='sdpa').to('cuda').eval()
            processor=AutoProcessor.from_pretrained(str(model_path),trust_remote_code=True,local_files_only=True)
        torch.cuda.synchronize();report['load_seconds']=time.perf_counter()-t0
        all_channel_records=[]
        for row in rows:
            sample_records=[]
            assert sha(Path(row['local_path']))==row['local_sha256'],'Input changed; regenerate manifest explicitly'
            for chunk in row['chunks']:
                cid=f"{row['sample_id']}_{chunk['start']:07.2f}_{chunk['end']:07.2f}"
                dest=run/(cid+'.json')
                if chunk.get('reused_from'):
                    original=Path(chunk['reused_from'])
                    assert sha(original)==chunk['reused_sha256']
                    saved=json.loads(original.read_text(encoding='utf-8'))
                    reused=dict(saved)
                    reused.update(chunk_id=cid,fingerprint=fingerprint,sample_start_s=chunk['start'],sample_end_s=chunk['end'],reused_from=str(original),reused_sha256=chunk['reused_sha256'],original_fingerprint=saved['fingerprint'])
                    if not dest.exists():write_json(dest,reused)
                    else:assert json.loads(dest.read_text(encoding='utf-8'))==reused
                    sample_records.append(reused)
                    continue
                if dest.exists():
                    saved=json.loads(dest.read_text(encoding='utf-8'))
                    assert saved['input_sha256']==chunk['sha256'] and saved['fingerprint']==fingerprint
                    sample_records.append(saved);continue
                torch.cuda.reset_peak_memory_stats();t=time.perf_counter()
                item={'chunk_id':cid,'fingerprint':fingerprint,'input_sha256':chunk['sha256'],'input_path':chunk['path'],'sample_id':row['sample_id'],'channel':row['channel'],'sample_start_s':chunk['start'],'sample_end_s':chunk['end'],'source_start_s':row['source_start_s']+chunk['start'],'source_end_s':row['source_start_s']+chunk['end'],'segments':[]}
                if args.model=='qwen':
                    import soundfile as sf
                    audio,rate=sf.read(chunk['path'],dtype='float32')
                    inputs=processor.apply_transcription_request(audio=audio).to('cuda',torch.bfloat16)
                    with torch.inference_mode():ids=model.generate(**inputs,max_new_tokens=config['max_new_tokens'],do_sample=False)
                    generated=ids[:,inputs['input_ids'].shape[1]:]
                    raw=processor.decode(generated)[0]
                    parsed=processor.decode(generated,return_format='parsed')[0]
                    text=parsed['transcription'];tokens=generated[0].tolist()
                    eos=model.generation_config.eos_token_id;eos=[eos] if isinstance(eos,int) else eos
                    item.update(raw=raw,parsed=parsed,token_ids=tokens,generated_tokens=len(tokens),termination='eos' if tokens and tokens[-1] in (eos or []) else 'token_limit_or_other',timestamp_kind='source_chunk_bounds_not_word_alignment')
                    item['segments']=[{'start':0,'end':chunk['end']-chunk['start'],'text':text,'speaker':None}]
                    del inputs,ids,generated
                elif args.model=='whisper':
                    segments,info=model.transcribe(chunk['path'],**config['effective_transcribe_kwargs'])
                    item['segments']=[dataclasses.asdict(s) for s in segments]
                    item['raw_info']=dataclasses.asdict(info)
                    text=''.join(s['text'] for s in item['segments'])
                    item.update(raw=text,termination='generator_exhausted',timestamp_kind='model_segment_and_word')
                else:
                    with torch.inference_mode(),torch.amp.autocast('cuda',dtype=torch.bfloat16):
                        inputs=prepare_inputs(processor,build_transcription_messages(chunk['path']),device=torch.device('cuda:0')).to('cuda')
                        prompt_len=inputs['input_ids'].shape[1]
                        ids=model.generate(input_ids=inputs['input_ids'],attention_mask=inputs['attention_mask'],input_features=inputs['input_features'],audio_feature_lengths=inputs['audio_feature_lengths'],audio_chunk_mapping=inputs['audio_chunk_mapping'],max_new_tokens=config['max_new_tokens'],do_sample=False)
                    tokens=ids[0,prompt_len:].tolist()
                    result={'text':processor.tokenizer.decode(tokens,skip_special_tokens=True).strip(),'prompt_len':prompt_len,'generated_tokens':len(tokens)}
                    eos=model.generation_config.eos_token_id;eos=[eos] if isinstance(eos,int) else eos
                    item.update(raw=result['text'],raw_result=result,token_ids=tokens,generated_tokens=len(tokens),termination='eos' if tokens and tokens[-1] in (eos or []) else 'token_limit_or_other',timestamp_kind='model_segment')
                    item['segments']=[{'start':s.start,'end':s.end,'text':s.text,'speaker':s.speaker,'recording_speaker_id':None,'name':None,'identity_status':'unmapped_chunk_local_only'} for s in parse_transcript(result['text'])]
                    text=''.join(s['text'] for s in item['segments'])
                    del inputs,ids
                torch.cuda.synchronize();elapsed=time.perf_counter()-t
                item.update(seconds=elapsed,rtf=elapsed/(chunk['end']-chunk['start']),torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_mib=torch.cuda.max_memory_reserved()/2**20)
                flags=[]
                if not text.strip():flags.append('empty_output')
                if item['termination'] in ['token_limit','token_limit_or_other']:flags.append('termination_requires_review')
                if args.model!='qwen' and not item['segments']:flags.append('no_parsed_segments')
                last=0
                for s in item['segments']:
                    if s['start']<0 or s['end']<s['start'] or s['end']>chunk['end']-chunk['start']+1:flags.append('invalid_timestamp')
                    if s['start']<last:flags.append('overlap_or_time_reversal')
                    if s['start']-last>15:flags.append('gap_over_15s_not_proof_of_omission')
                    last=max(last,s['end'])
                if chunk['end']-chunk['start']-last>15:flags.append('tail_gap_over_15s')
                if any(text.count(text[i:i+20])>=3 for i in range(0,max(0,len(text)-20),20)):flags.append('repeated_phrase')
                item['review_flags']=sorted(set(flags));item['status']='needs_review' if flags else 'candidate_unverified'
                write_json(dest,item);sample_records.append(item)
                print(json.dumps({'model':args.model,'chunk':cid,'seconds':round(elapsed,2),'rtf':round(item['rtf'],3),'flags':item['review_flags']},ensure_ascii=False),flush=True)
            all_channel_records.extend(sample_records)
            report['samples'].append({'sample_id':row['sample_id'],'chunks':[i['chunk_id'] for i in sample_records],'duration_s':sum(i['sample_end_s']-i['sample_start_s'] for i in sample_records),'inference_seconds':sum(i['seconds'] for i in sample_records),'flagged_chunks':sum(bool(i['review_flags']) for i in sample_records)})
            write_json(run/'run.json',report)
        sample_records=all_channel_records
        report['channel_policy']='separate_L_R_no_downmix'
        report['status']='completed_candidates_unverified'
        report['reused_chunks']=sum(bool(c.get('reused_from')) for c in sample_records)
        report['new_inference_seconds']=sum(c['seconds'] for c in sample_records if not c.get('reused_from'))
        report['new_audio_seconds']=sum(c['sample_end_s']-c['sample_start_s'] for c in sample_records if not c.get('reused_from'))
        report['new_audio_rtf']=report['new_inference_seconds']/report['new_audio_seconds']
    except Exception as exc:
        report['status']='failed';report['error']=repr(exc);report['traceback']=traceback.format_exc();raise
    finally:
        monitor.finish();report['wall_seconds']=time.perf_counter()-t0;report['nvidia_device_peak_used_mib']=monitor.peak
        report['memory_note']='nvidia-smi sampled whole-device usage, includes other processes; torch peaks exclude CTranslate2 allocations'
        write_json(run/'run.json',report)
        print(json.dumps({'run':str(run),'status':report['status']}),flush=True)

if __name__=='__main__':main()
