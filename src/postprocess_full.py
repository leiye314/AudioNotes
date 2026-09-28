"""Source-linked conservative first editing pass; never claim acoustic verification."""
import argparse, collections, datetime, html, json, math, re, wave
from pathlib import Path
from common import ROOT, sha, write_json

def stamp(s,ms=False):
    n=round(s*1000);h,n=divmod(n,3600000);m,n=divmod(n,60000);sec,mil=divmod(n,1000)
    return f'{h:02}:{m:02}:{sec:02}'+(f',{mil:03}' if ms else '')

def process(job,reading_source_only=True):
    if not reading_source_only:raise ValueError("Legacy excerpt notes retired; use reading_publish.py after editorial review")
    row=next(r for r in json.loads((ROOT/'outputs/index.json').read_text(encoding='utf-8'))['items'] if r['job_id']==job)
    engine='qwen' if row['profile'] in ['course_lecture','logic_lecture'] else 'moss';base=ROOT/'outputs'/job
    runs=list((base/'full'/engine).glob('*/run.json'))
    complete=[p for p in runs if json.loads(p.read_text(encoding='utf-8'))['status']=='completed_candidates_unverified']
    assert len(complete)==1, 'Select a single completed full run explicitly'
    runpath=complete[0];run=json.loads(runpath.read_text(encoding='utf-8'));out=base/'delivery';out.mkdir(exist_ok=True)
    seal=out/'delivery_manifest.json'
    if seal.exists():
        previous=json.loads(seal.read_text(encoding='utf-8'))
        for rel,expected in previous['protected_files'].items():
            current=out/rel
            if current.exists() and sha(current)!=expected:
                raise RuntimeError(f'Preserve human-edited delivery: {current}; generate a new delivery version instead of overwriting it')
    plan=json.loads((ROOT/'work'/job/'full/plan.json').read_text(encoding='utf-8'))
    selection_path=base/'repair_selection.json'
    selection=json.loads(selection_path.read_text(encoding='utf-8')) if selection_path.exists() else {'replacements':{},'repair_runs':[]}
    repair_configs=[];repair_seconds=0
    for meta in selection['repair_runs']:
        rp=Path(meta['path']);assert sha(rp)==meta['sha256']
        rr=json.loads(rp.read_text(encoding='utf-8'));assert rr['status']=='completed_candidates_unverified'
        repair_configs.append({'path':str(rp),'sha256':meta['sha256'],'config':rr['config']})
        repair_seconds+=rr['new_inference_seconds']
        run['nvidia_device_peak_used_mib']=max(run['nvidia_device_peak_used_mib'],rr['nvidia_device_peak_used_mib'])
    run['new_inference_seconds']+=repair_seconds
    run['new_audio_rtf']=run['new_inference_seconds']/run['new_audio_seconds']
    records=[];raw_provenance=[];issues=[];chunks=[];cursor=0
    for sample in run['samples']:
        cursor=0
        selected_paths=[]
        for cid in sample['chunks']:
            if cid in selection['replacements']:
                replacement=selection['replacements'][cid]
                assert sha(Path(replacement['original_path']))==replacement['original_sha256']
                for meta in replacement['replacement_files']:
                    p=Path(meta['path']);assert sha(p)==meta['sha256'];selected_paths.append(p)
            else:selected_paths.append(runpath.parent/(cid+'.json'))
        for p in selected_paths:
            cid=p.stem;c=json.loads(p.read_text(encoding='utf-8'));chunks.append(c)
            if abs(c['source_start_s']-cursor)>0.003:issues.append({'type':'input_coverage_gap_or_overlap','start':cursor,'next':c['source_start_s']})
            cursor=c['source_end_s'];flags=list(c.get('review_flags',[]))
            if c.get('termination')!='eos':issues.append({'type':'generation_termination_not_eos','chunk':cid})
            # Signal diagnostics are indicators, never listening or a speech detector.
            import numpy as np
            with wave.open(c['input_path'],'rb') as w:
                arr=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype('float32')/32768
            rms=float(np.sqrt(np.mean(arr**2))) if len(arr) else 0
            db=20*math.log10(max(rms,1e-12))
            if db<-42:flags.append('low_level_rms_below_minus42dBFS_not_speech_detection')
            raw_provenance.append({'chunk_id':cid,'path':str(p),'sha256':sha(p),'source_start_s':c['source_start_s'],'source_end_s':c['source_end_s'],'reused_from':c.get('reused_from'),'rms_dbfs':round(db,2),'flags':flags})
            if c.get('reused_from'):
                original=json.loads(Path(c['reused_from']).read_text(encoding='utf-8'))
                assert original['source_start_s']==c['source_start_s'] and original['source_end_s']==c['source_end_s']
                raw_provenance[-1]['original_sample_provenance']={'sample_id':original['sample_id'],'sample_start_s':original['sample_start_s'],'sample_end_s':original['sample_end_s'],'original_raw_path':c['reused_from'],'original_raw_sha256':c['reused_sha256'],'input_path':original['input_path'],'input_sha256':original['input_sha256']}
                raw_provenance[-1]['wrapper_time_note']='Full wrapper retains the origin sample_id label; its sample_start/end fields use the full recording axis. Authoritative original sample-relative fields are above and in untouched reused_from JSON. All delivery timestamps use source_start_s plus segment offset.'
            for j,s in enumerate(c['segments']):
                a=c['source_start_s']+s['start'];b=c['source_start_s']+s['end'];rid=f'S{len(records)+1:05}'
                if a<0 or b<a or b>plan['duration_s']+1:issues.append({'type':'invalid_source_timestamp','segment':rid})
                records.append({'id':rid,'source_start_s':a,'source_end_s':b,'text':s['text'],'channel':c.get('channel'),'speaker':s.get('speaker'),'speaker_scope':cid if s.get('speaker') else None,'recording_speaker_id':None,'verified_name':None,'timestamp_kind':c['timestamp_kind'],'raw_path':str(p),'raw_segment_index':j,'review_flags':flags,'human_verified':False})
        if abs(cursor-plan['duration_s'])>.003:issues.append({'type':'channel_input_tail_not_covered','sample':sample['sample_id'],'end':cursor})
    if abs(cursor-plan['duration_s'])>.003:issues.append({'type':'input_tail_not_covered','end':cursor})
    assert sha(Path(row['source_path']))==row['source_sha256']
    provenance={'job_id':job,'source_path':row['source_path'],'source_sha256':row['source_sha256'],'duration_s':plan['duration_s'],'engine':engine,'run_path':str(runpath),'run_sha256':sha(runpath),'config':run['config'],'chunks':raw_provenance,'repair_runs':repair_configs,'repair_selection':selection,'timestamp_mapping':'source_time=chunk.source_start_s+segment.start/end; no silence removal; original sample-relative fields remain in original_sample_provenance for reused chunks','human_verified':False}
    write_json(out/'provenance.json',provenance);write_json(out/'raw_segments.json',records)
    if engine=='moss':
        identities=sorted({(r['speaker_scope'],r['speaker']) for r in records if r['speaker']})
        write_json(out/'speaker_mapping.json',[{'chunk_id':scope,'local_speaker':speaker,'recording_speaker_id':None,'verified_name':None,'status':'unmapped_requires_voice_evidence'} for scope,speaker in identities])
    header=[f'# {Path(row["source_path"]).name}', '',f'源录音：`{row["source_path"]}`  ',f'SHA256：`{row["source_sha256"]}`  ',f'引擎：{run["config"]["model"]}；revision `{run["config"]["revision"]}`。源时间从本文件00:00起算。', '', '**尚未人工复听；原始模型文本不等于已核实原话。** '+('时间为约30秒输入块范围，非字词对齐。' if engine=='qwen' else '时间为模型预测；Speaker仅在对应120秒块内有效，不能跨块合并为同一人。')]
    if row['partial_recording']:header+=['','**缺录声明：'+(row.get('missing_recording_note') or '文件名标注“部分”；仅记录现存音频，缺失范围未知。')+' 不补造未录内容。**']
    if row['part']:header+=['',f'**分段来源：{row["part"]}独立文件。没有另一部分在原现场的精确偏移，不拼接时间轴。**']
    if plan.get('channel_policy'):
        header+=['','**双声道独立识别：L、R各覆盖完整录音，不混音。两套文本可重复，同一源时间的L/R不是先后两次发言，也不按多数票合成真值。任务候选可能重复提及。**']
    if selection['replacements']:
        header+=['',f'**异常局部重试：{len(selection["replacements"])}个原块曾未正常结束，原始失败输出保留。正式候选改用30秒短块重试，Speaker范围也相应限于各短块；这是生成完整性修复，不是人工听音纠错。**']
    raw=header+['','## 原始转写（未经改字）'];edited=header+['','## 初校说明','', '本稿完成来源、时间和疑点标注，尚无听音依据支持关键改字，因此保留原始用词。段落格式调整不算纠错；可疑英文、数字、否定、板书指代和人名不擅自补齐。','', '姓名须依据对应来源范围的人工确认；不据此绑定未知声音身份。' if engine=='moss' else '“这个式子／这里”等指代缺少课件或板书依据，不能仅由音频候选恢复公式。','', '## 校订逐字稿（初校，待人工听音）']
    srt=[]
    for i,r in enumerate(records):
        speaker=f' [{r["speaker_scope"]}:{r["speaker"]}；身份未知]' if r['speaker'] else ''
        title=f'### {r["id"]} [{stamp(r["source_start_s"])}–{stamp(r["source_end_s"])}]{" 声道"+r["channel"] if r["channel"] else ""}{speaker}'
        raw.extend(['',f'<a id="{r["id"].lower()}"></a>',title,'',r['text'] or '〔模型返回空文本〕'])
        edited.extend(['',f'<a id="{r["id"].lower()}"></a>',title,'',r['text'] or '〔模型返回空文本；不能据此判断静音或漏转〕'])
        if r['review_flags']:edited.extend(['','> 自动疑点：'+', '.join(r['review_flags'])+'。仅为复核线索，尚未确认错误。'])
        srt.extend([str(i+1),f'{stamp(r["source_start_s"],True)} --> {stamp(r["source_end_s"],True)}',r['text'],''])
    (out/'raw_transcript.md').write_text('\n'.join(raw),encoding='utf-8');(out/'corrected_transcript.md').write_text('\n'.join(edited),encoding='utf-8');(out/'raw_timestamps.srt').write_text('\n'.join(srt),encoding='utf-8')
    if plan.get('channel_policy'):
        for channel in ['L','R','combined']:
            rs=[r for r in records if channel=='combined' or r['channel']==channel]
            rs.sort(key=lambda r:(r['source_start_s'],r['channel']))
            subs=[]
            for i,r in enumerate(rs):subs.extend([str(i+1),f'{stamp(r["source_start_s"],True)} --> {stamp(r["source_end_s"],True)}',f'[{r["channel"]}] '+r['text'],''])
            target='raw_timestamps.srt' if channel=='combined' else f'raw_timestamps_{channel}.srt'
            (out/target).write_text('\n'.join(subs),encoding='utf-8')
    write_json(out/'corrections.json',{'human_audio_verified':False,'substantive_text_changes':[],'model_candidate_replacements':selection['replacements'],'format_only':['source time and stable segment IDs','chunk-local speaker namespaces','uncertainty annotations'],'reason':'No acoustic or documentary evidence sufficient to adjudicate uncertain words; retries replace truncated candidates, not human proofreading.'})
    name_note='姓名文字确认不等于已识别声音身份。' if engine=='moss' else ''
    (out/'CHANGES.md').write_text('# 关键修改记录\n\n目前没有已确认的内容改字。原始文字逐段保留；只增加来源时间、稳定段号、片内Speaker命名空间和疑点标注。'+name_note+'\n\n后续每次实质修改须记录段号、原文、改文、证据、人工确认状态。',encoding='utf-8')
    if selection['replacements']:
        with (out/'CHANGES.md').open('a',encoding='utf-8') as f:
            f.write('\n\n## 模型候选局部替换（非人工改字）\n\n')
            for old in selection['replacements'].values():
                bounds=old['replacement_bounds'];f.write(f'- 源时间{stamp(bounds[0][0])}–{stamp(bounds[-1][1])}：原候选未到EOS，触发输出上限，改用{len(bounds)}个30秒以内短块的原始模型候选。原失败记录 `{old["original_path"]}`，SHA256 `{old["original_sha256"]}` 保留。完整替换文件/hash见corrections.json，尚未听音核实。\n')
    flagged=[x for x in raw_provenance if x['flags']]
    q={'job_id':job,'procedural_pass':not issues,'human_full_text_verified':False,'audio_coverage_s':cursor,'source_duration_s':plan['duration_s'],'chunks':len(chunks),'reused_chunks':sum(bool(x.get('reused_from')) for x in chunks),'segments':len(records),'flagged_chunks':len(flagged),'structural_issues':issues,'flag_counts':dict(collections.Counter(f for c in flagged for f in c['flags'])),'new_inference_seconds':run['new_inference_seconds'],'new_audio_rtf':run['new_audio_rtf'],'gpu':run['gpu'],'peak_device_mib':run['nvidia_device_peak_used_mib'],'raw_text_equals_initial_corrected_text':True}
    q.update(replaced_truncated_chunks=len(selection['replacements']),repair_inference_seconds=repair_seconds,rtf_note='All original attempts plus selected repairs divided by original unique new audio duration; stereo channels counted separately.')
    write_json(out/'quality.json',q)
    md=['# 程序质量检查','',f'输入分块覆盖：00:00:00–{stamp(cursor)}；{len(chunks)}块，复用 {q["reused_chunks"]}块；{len(records)}条原始段。',f'来源hash一致；结构检查：{"通过" if not issues else "有未解决问题"}；**不是全文已核实无误**。',f'新推理{run["new_inference_seconds"]:.2f}秒，RTF {run["new_audio_rtf"]:.3f}（仅新音频、新推理；复用耗时不重复计入）。',f'GPU：{run["gpu"]}；运行采样全设备显存峰值{run["nvidia_device_peak_used_mib"]:.0f} MiB，可能包含其他应用。','', '## 局限','', '- 输入覆盖完整不保证每句话均识别。空输出、静音和遗漏不能仅据文字区别；15秒间隙、低能量和重复检测都不是已确认错误。','- 无重叠分块的边界词可能受损；Qwen时间粗，MOSS说话人跨块未知；不报告WER/CER。','- 后处理未使用生成式模型重写原文，未调用额外ASR冒充听音。','', '## 自动疑点区间','', '| 源时间 | 块 | 标记 | RMS dBFS |','|---|---|---|---|']
    for x in flagged:md.append(f'| {stamp(x["source_start_s"])}–{stamp(x["source_end_s"])} | {x["chunk_id"]} | {", ".join(x["flags"])} | {x["rms_dbfs"]} |')
    if not flagged:md+=['未触发当前自动规则；不表示没有错误。']
    if issues:md+=['','结构问题：',json.dumps(issues,ensure_ascii=False)]
    if selection['replacements']:md+=['','## 已保留原件的局部修复','',f'{len(selection["replacements"])}个原块达到输出上限，已用30秒短块重试并检查EOS和时间覆盖。原始失败JSON不删除；修复映射见provenance.json中的repair_selection。耗时/RTF包含失败尝试和{repair_seconds:.2f}秒重试，分母不重复增加同一段音频。未作人工听音裁决。']
    (out/'quality.md').write_text('\n'.join(md),encoding='utf-8')
    make_review(out,row,records)
    print(json.dumps(q,ensure_ascii=False))
    return q

def make_review(out,row,records):
    body=['<!doctype html><meta charset="utf-8"><title>完整录音复核</title><style>body{font:17px/1.7 sans-serif;max-width:1100px;margin:24px auto;padding:20px}header{position:sticky;top:0;background:white;padding:12px;border-bottom:1px solid #bbb}article{border-bottom:1px solid #ddd;padding:14px}button{padding:8px}small{color:#775}</style>',f'<h1>{html.escape(Path(row["source_path"]).name)}</h1>','<p>未人工核验。片内Speaker不代表全场身份；Qwen时间为输入块范围。</p>',f'<header><audio id="audio" controls preload="metadata" src="{html.escape(Path(row["source_path"]).as_uri())}"></audio></header>']
    for r in records:
        body.append(f'<article id="{r["id"]}"><button onclick="let a=document.getElementById(\'audio\');a.currentTime={r["source_start_s"]};a.play()">{r["id"]} {stamp(r["source_start_s"])}–{stamp(r["source_end_s"])}</button><small> {html.escape(str(r["speaker_scope"] or ""))} {html.escape(str(r["speaker"] or ""))}</small><p>{html.escape(r["text"])}</p></article>')
    (out/'review.html').write_text('\n'.join(body),encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--job',required=True);a=p.parse_args()
    process(a.job,reading_source_only=True)
