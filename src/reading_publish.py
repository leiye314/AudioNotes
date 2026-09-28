"""Mechanical rendering/publishing of Codex-authored editorial material. No ASR/LLM."""
import argparse, datetime, hashlib, json, os, re, shutil
from pathlib import Path
from project_paths import settings
ROOT=Path(__file__).resolve().parents[1]
BACK=ROOT/'work/reading_v1'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def append_text(left,right,mixed_language=False):
    # Layout only: adjacent English chunks need a word/sentence separator.
    space=' ' if mixed_language and re.search(r'[A-Za-z0-9,;:?!.)]$',left) and re.match(r'[A-Za-z0-9(]',right) else ''
    return left+space+right
def readable_paragraphs(text,mixed_language=False):
    # Layout only: retain every character; break exclusively after complete sentences.
    parts=[];current=''
    pattern=r'.*?(?:[。！？](?:[”’」』])?|[.!?](?=\s|$))|.+$' if mixed_language else r'.*?[。！？](?:[”’」』])?|.+$'
    for sentence in re.findall(pattern,text,flags=re.S):
        current+=sentence
        if len(current)>=260:parts.append(current);current=''
    if current:parts.append(current)
    assert ''.join(parts)==text
    return parts or [text]
def clean(text,mixed_language=False):
    # Only disfluencies, never replace substantive words using an automatic lexicon.
    text=re.sub(r'(?<=[，。？！；：])(?:呃[，、 ]*|嗯[，、 ]*|啊[，、 ]+)+(?=\S)', '', text) if len(text)>8 else text
    text=re.sub(r'^(?:呃[，、 ]*|嗯[，、 ]*|啊[，、 ]+)+(?=\S)', '', text) if len(text)>8 else text
    text=re.sub(r'(?<=\w)呃[， ]*','',text)
    text=re.sub(r'啊(?=[，。；])','',text) if len(text)>8 else text
    for word in ['我','它','他','你','这','那','然后','就是','这个','那个','所以','对吧','我们','他们','可能','应该','可以','一个','根据','最后','当前','现在','因为','进行','比较','通过','生成','选择','调用','还有','把','会','要','是','有','在','如果','重新','需要','必须要','模拟','出来','可','能','总','两','但','不','就']:
        text=re.sub(r'(?:'+word+r'){2,}',word,text)
    text=re.sub(r' {2,}',' ',text).strip()
    text=re.sub(r'。{2,}','。',text)
    text=text.replace('，。','。')
    if mixed_language:
        text=re.sub(r'\b(?:uh|um|ah)\b[, ]*','',text,flags=re.I)
        for _ in range(3):
            text=re.sub(r'\b(I|the|my|we|you|our|for|if|to|and|that|but)\s+\1\b',r'\1',text,flags=re.I)
    return text
def build(spec):
    mixed_language=spec.get('mixed_language_layout',False)
    unit=spec['unit']; target=ROOT/'阅读成品'/spec['directory']; back=BACK/unit
    back.mkdir(parents=True,exist_ok=True)
    rows=[]; sources=[]
    for job in spec['jobs']:
        p=ROOT/'outputs'/job/'delivery/raw_segments.json'
        sources.append({'job':job,'path':str(p),'sha256':sha(p),'provenance':str(p.with_name('provenance.json'))})
        for r in load(p): rows.append({**r,'job':job,'key':job+':'+r['id']})
    heads={x['at']:x['title'] for x in spec['headings']}
    omit=spec.get('omit',{}); edits=spec.get('edits',{}); rules=spec.get('replacements',[])
    maps=[]; changes=[]; content=[f"# {spec['title']}｜整理逐字稿",'', '依据自动转写整理，已做文本初校；关键疑点见末尾。','',spec['intro'],'']
    section='开场'; scope=None; current=None; para=0
    for r in rows:
        k=r['key']; text=r['text']; i=int(r['id'][1:])
        heading=heads.get(k)
        reason=omit.get(k)
        if not text.strip(): reason=reason or '模型空文本；保留后台，未推断为静音'
        if spec.get('primary_channel') and r.get('channel')!=spec['primary_channel']:
            reason=reason or '同一录音重复声道的平行候选；主阅读稿固定采用'+spec['primary_channel']+'声道，差异逐段存后台'
        if reason:
            maps.append({**{x:r.get(x) for x in ['key','job','id','source_start_s','source_end_s','channel','speaker_scope','speaker']},'disposition':'omitted_or_parallel','reason':reason,'section':section});continue
        if k in edits:
            e=edits[k]; changes.append({'key':k,'before':text,'after':e['text'],'basis':e['basis']});text=e['text']
        for rule in rules:
            if rule.get('job',r['job'])!=r['job'] or not(rule.get('start',1)<=i<=rule.get('end',99999)):continue
            if rule['old'] in text:
                before=text;text=text.replace(rule['old'],rule['new'])
                changes.append({'key':k,'before':before,'after':text,'basis':rule['basis']})
        before=text
        if not edits.get(k,{}).get('preserve_verbatim',False):text=clean(text,mixed_language)
        if text!=before:changes.append({'key':k,'before':before,'after':text,'basis':'去无信息填充词及紧邻口吃；未删实质强调'})
        # Explicitly reviewed chunk junctions; no inference from time windows.
        joined=k in spec.get('join_before',[]) and current is not None and not r.get('speaker')
        carried_para=None;carried_text=''
        if joined:
            old=content[-1];content[-1]=old.rstrip('。？！'+('.' if mixed_language else ''))
            if old!=content[-1]:changes.append({'key':k,'before':old[-30:],'after':content[-1][-30:],'basis':'完整阅读后指定的跨识别块续句；只去错误句末标点'})
            if heading:
                m=re.search(r'[。！？]',text)
                if m:
                    carried_text=text[:m.end()];content[-1]=append_text(content[-1],carried_text,mixed_language);carried_para=para;text=text[m.end():]
                else:
                    carried_text=text;content[-1]=append_text(content[-1],text,mixed_language);carried_para=para;text=''
        if heading:
            content+=['',f'## {heading}',''];section=heading;current=None
        # Paragraphs retain each substantive speech turn; lecture grouping was reviewed by the writer.
        if r.get('speaker'):
            if scope!=r['speaker_scope']:
                if scope is not None:content+=['','*（新一组局部发言标签）*','']
                scope=r['speaker_scope'];current=None
            label='本段发言人 '+chr(64+int(re.search(r'(\d+)$',r['speaker']).group(1)))
            label=spec.get('speaker_overrides',{}).get(k,{}).get('label',label)
            if current==(scope,label) and not heading:
                content[-1]=append_text(content[-1],text,mixed_language)
            else:
                para+=1;content+=['',f'**{label}：** {text}'];current=(scope,label)
        else:
            # Group boundaries supplied by the writer after full reading; no time windows.
            if (k in spec.get('paragraph_starts',[]) and not joined) or current is None:
                para+=1;content+=['',text];current=('lecture',)
            else: content[-1]=append_text(content[-1],text,mixed_language)
        maps.append({**{x:r.get(x) for x in ['key','job','id','source_start_s','source_end_s','channel','speaker_scope','speaker']},'disposition':'included','paragraph':para,'carried_paragraph':carried_para,'carried_text':carried_text,'section':section,'edited_text':text})
        if k in spec.get('speaker_overrides',{}):maps[-1]['display_role_override']=spec['speaker_overrides'][k]
    # Keep logical source-block indices and record all displayed subparagraphs.
    if spec['kind']=='lecture':
        formatted=[];in_body=False;logical=0;displayed=0;layout=[]
        for line in content:
            if line.startswith('## '):in_body=True
            if in_body and line and not line.startswith('#'):
                logical+=1;pieces=readable_paragraphs(line,mixed_language)
                start=displayed+1;displayed+=len(pieces)
                layout.append({'logical_paragraph':logical,'display_paragraphs':list(range(start,displayed+1)),'text':line})
                formatted.append('\n\n'.join(pieces))
            else:formatted.append(line)
        content=formatted;dump(back/'paragraph_layout.json',layout)
    content+=['','## 关键疑点','',spec['uncertainties']]
    relative=os.path.relpath(back/'来源与核验记录.md',target).replace('\\','/')
    footer=f'\n\n[来源与核验记录]({relative})\n'
    transcript=re.sub(r'\n{3,}','\n\n','\n'.join(content)).strip()+footer
    notes=(BACK/'drafts'/spec['notes']).read_text(encoding='utf-8').strip()+footer
    names=['01_整理逐字稿.md','02_课堂笔记.md' if spec['kind']=='lecture' else '02_会议纪要.md']
    stage=back/'staging';stage.mkdir(exist_ok=True)
    for name,text in zip(names,[transcript,notes]):(stage/name).write_text(text,encoding='utf-8')
    dump(back/'paragraph_map.json',maps);dump(back/'changes.json',changes)
    manifest={'spec_sha256':sha(BACK/'specs'/(unit+'.json')),'sources':sources,'human_audio_verified':False,'writing_model':'current Codex session','workflow':'reading-v1'}
    if spec.get('human_reviews'):
        manifest.update(scoped_human_reviews=spec['human_reviews'],speaker_overrides=spec.get('speaker_overrides',{}),human_scope='Only listed spans/items; choices are not verbatim gold')
    dump(back/'source_manifest.json',manifest)
    evidence=['# 来源与核验记录','',spec['title'],'',spec.get('processing_note','本轮由当前 Codex 完整阅读转写，按主题校订与写作，并作一次内容审查；没有重新识别音频或声称人工听音核验。'),'', '## 完整来源','']
    for s in sources:
        d=ROOT/'outputs'/s['job']/'delivery'
        rel=os.path.relpath(d,back).replace('\\','/')
        evidence.append(f'- {s["job"]}：[原始逐字稿]({rel}/raw_transcript.md)、[原段落]({rel}/raw_segments.json)、[来源配置]({rel}/provenance.json)、[定位播放器]({rel}/review.html)。')
    evidence+=['','## 内容检查','',spec['review'],'','## 覆盖与修改','',f'总来源段数 {len(rows)}；进入正文 {sum(x["disposition"]=="included" for x in maps)}；其余空白、非教学间歇或重复声道均逐条记录去向。','', '[逐段来源映射](paragraph_map.json) · [修改记录](changes.json) · [来源指纹](source_manifest.json)','',spec.get('source_policy',''),'','程序覆盖检查证明段落有去向，不证明原音识别正确。']
    if spec['kind']=='lecture':evidence+=['','[逻辑段与阅读段的对应](paragraph_layout.json)：跨小标题续句保留 carried_text 及 carried_paragraph；每段只在完整句末排版换段。']
    if (back/'notes_source_map.json').exists():evidence+=['','[笔记主题、关键结论及任务的来源](notes_source_map.json)']
    if spec.get('primary_channel'):evidence+=['','[左右声道逐段时间对应](stereo_alignment.json)']
    (back/'来源与核验记录.md').write_text('\n'.join(evidence)+'\n',encoding='utf-8')
    return target,stage,names
def publish(spec):
    target,stage,names=build(spec);state=BACK/spec['unit']/'publication.json'
    previous=load(state) if state.exists() else {}
    for name in names:
        p=target/name
        if p.exists() and sha(p)!=previous.get('files',{}).get(name):
            raise RuntimeError(f'保留未登记或手改成品；待合并新稿已在 {stage}; {p}')
    target.mkdir(parents=True,exist_ok=True)
    changed=[n for n in names if not (target/n).exists() or sha(target/n)!=sha(stage/n)]
    if changed and any((target/n).exists() for n in names):
        archive=BACK/spec['unit']/'versions'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');archive.mkdir(parents=True)
        for name in names:
            if (target/name).exists():shutil.copy2(target/name,archive/name)
    for name in changed:
        temp=target/(name+'.tmp');shutil.copy2(stage/name,temp);os.replace(temp,target/name)
    dump(state,{'unit':spec['unit'],'directory':str(target),'asr':spec.get('asr_status','reused_complete'),'text':'complete_content_reviewed','publication':'published','workflow':'reading-v1','files':{n:sha(target/n) for n in names}})
    print(spec['unit'], 'published' if changed else 'unchanged',len(changed))
def index():
    specs=[load(p) for p in (BACK/'specs').glob('*.json') if (BACK/load(p)['unit']/'publication.json').exists()]
    count=len({j for s in specs for j in s['jobs']})
    lines=['# 阅读成品总目录','',f'当前 {count} 份源转写，整理为 {len(specs)} 个阅读单元。每单元两份主文件；疑点和来源在文末链接。状态“已整理”指完成文本初校、内容写作和覆盖检查。','','| 日期 | 课程／项目 | 主题 | 整理逐字稿 | 笔记／纪要 | 状态 |','|---|---|---|---|---|---|']
    for p in sorted((BACK/'specs').glob('*.json')):
        s=load(p)
        if not (BACK/s['unit']/'publication.json').exists():continue
        d=s['directory'];name='02_课堂笔记.md' if s['kind']=='lecture' else '02_会议纪要.md'
        lines.append(f'| {s["date"]} | {s["project"]} | {s["topic"]} | [阅读]({d}/01_整理逐字稿.md) | [阅读]({d}/{name}) | 已整理{s.get("status_note","")} |')
    lines+=settings(ROOT).get('reading_index_footer',[])
    target=ROOT/'阅读成品/00_总目录.md';state=BACK/'index_publication.json'
    new='\n'.join(lines)+'\n'
    if target.exists():
        previous=load(state) if state.exists() else None
        if not previous or sha(target)!=previous['sha256']:raise RuntimeError('总目录未登记或有手改，保留原件；请先合并')
        if target.read_text(encoding='utf-8')!=new:
            archive=BACK/'index_versions';archive.mkdir(exist_ok=True)
            shutil.copy2(target,archive/(datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.md'))
    if not target.exists() or target.read_text(encoding='utf-8')!=new:target.write_text(new,encoding='utf-8')
    dump(state,{'sha256':sha(target)})
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('unit',nargs='?');p.add_argument('--index',action='store_true');a=p.parse_args()
    if a.index:index()
    else:publish(load(BACK/'specs'/(a.unit+'.json')))
