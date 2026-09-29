"""Select verified-complete retry candidates; never change original model outputs."""
import argparse,json
from pathlib import Path
from common import ROOT,sha,write_json

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);parser.add_argument('--engine',choices=['moss','qwen'],default='moss');args=parser.parse_args()
    job=args.job;plan=json.loads((ROOT/'work'/job/'repairs/plan.json').read_text(encoding='utf-8'))
    plans=plan if isinstance(plan,list) else [plan]
    paths=list((ROOT/'outputs'/job/'repairs'/args.engine).glob('*/run.json'));assert len(paths)==1
    path=paths[0];run=json.loads(path.read_text(encoding='utf-8'));assert run['status']=='completed_candidates_unverified'
    chunks=[]
    for sample in run['samples']:
        for cid in sample['chunks']:
            p=path.parent/(cid+'.json');c=json.loads(p.read_text(encoding='utf-8'))
            assert c['termination']=='eos' and c['segments'] and 'invalid_timestamp' not in c['review_flags']
            chunks.append((p,c))
    mapping={}
    for old in [r for row in plans for r in row['replacements']]:
        selected=[]
        for a,b in old['replacement_bounds']:
            channel=json.loads(Path(old['original_path']).read_text(encoding='utf-8')).get('channel','MONO')
            p,c=next((p,c) for p,c in chunks if c['channel']==channel and c['source_start_s']==a and c['source_end_s']==b)
            selected.append({'path':str(p),'sha256':sha(p)})
        mapping[old['original_chunk_id']]={**old,'replacement_files':selected}
    write_json(ROOT/'outputs'/job/'repair_selection.json',{'replacements':mapping,'repair_runs':[{'path':str(path),'sha256':sha(path)}],'human_verified':False,'selection_basis':'retry reaches_eos_and_valid_timestamps_not_acoustic_truth'})
    print(json.dumps({'replaced_failed_chunks':len(mapping),'successful_short_chunks':len(chunks),'original_outputs_preserved':True}))
if __name__=='__main__':main()
