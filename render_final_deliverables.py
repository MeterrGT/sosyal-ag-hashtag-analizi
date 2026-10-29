#!/usr/bin/env python3
"""Rebuild report, poster, slides and interactive HTML from saved final analysis outputs.
This is intentionally fast and does not re-run the 100 null models.
"""
from pathlib import Path
import json
import pandas as pd
import numpy as np
import finalize_project as fp

ROOT=Path('.')
OUT=ROOT/'outputs'; DELIVER=ROOT/'deliverables'; DATA=ROOT/'data'

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    for path in ['basic_metrics.json','centrality_all.csv','louvain_communities.csv','community_summary.csv','community_stability.json','null_model_summary.json','null_model_metrics.csv','temporal_windows.csv','temporal_nmi.csv','powerlaw_comparison.json','final_results_summary.json']:
        if not (OUT/path).exists():
            raise SystemExit(f'Missing {OUT/path}. Run finalize_project.py first.')
    source=fp.get_input_file()
    posts=fp.load_posts(source)
    graph=fp.graph_from_posts(posts)
    metrics=read_json(OUT/'basic_metrics.json')
    cent=pd.read_csv(OUT/'centrality_all.csv')
    lc=pd.read_csv(OUT/'louvain_communities.csv')
    comms=[]
    comm_map={}
    for cid, part in lc.groupby('community', sort=False):
        group=set(part['hashtag'].astype(str))
        comms.append(group)
        for n in group: comm_map[n]=int(cid)
    cs=pd.read_csv(OUT/'community_summary.csv').fillna('')
    guide=OUT/'community_labeling_guide.csv'
    labelmap={}
    if guide.exists():
        gd=pd.read_csv(guide).fillna('')
        for _,r in gd.iterrows():
            if str(r.get('topic_name_to_review','')).strip(): labelmap[int(r['community'])]=str(r['topic_name_to_review']).strip()
    summary=[]
    for _,r in cs.iterrows():
        tags=[x.strip() for x in str(r['top_hashtags']).split('|') if x.strip()]
        cid=int(r['community'])
        summary.append({'community':cid,'nodes':int(r['nodes']),'internal_edges':int(r['internal_edges']),
                        'top_hashtags':tags,'topic_label':labelmap.get(cid,'')})
    community_data={'louvain':comms,'summary':summary}
    stability=read_json(OUT/'community_stability.json')
    null_summary=read_json(OUT/'null_model_summary.json')
    null_rows=pd.read_csv(OUT/'null_model_metrics.csv').replace({np.nan:np.nan}).to_dict('records')
    temporal=pd.read_csv(OUT/'temporal_windows.csv').fillna('').to_dict('records')
    nmis=pd.read_csv(OUT/'temporal_nmi.csv').to_dict('records')
    for r in nmis:
        if pd.isna(r.get('nmi')): r['nmi']=None
        else: r['nmi']=float(r['nmi'])
    powerlaw=read_json(OUT/'powerlaw_comparison.json')
    full=read_json(OUT/'final_results_summary.json')
    leiden_status=full.get('leiden', {'status':'unavailable','error':'Not found in summary'})
    DELIVER.mkdir(parents=True,exist_ok=True)
    fp.make_charts(graph,metrics,cent,comms,nmis,null_rows)
    fp.make_interactive(graph,comm_map,cent)
    fp.build_report(metrics,source,posts,cent,community_data,stability,null_summary,temporal,nmis,powerlaw,leiden_status,min(500,graph.number_of_nodes()))
    fp.build_slides(metrics,cent,community_data,stability,null_summary,temporal,nmis,powerlaw,leiden_status,source)
    print('Deliverables rebuilt from saved results:')
    for p in sorted(DELIVER.iterdir()): print(f' - {p}')
    if not labelmap:
        print('NOTE: Fill topic_name_to_review in outputs/community_labeling_guide.csv and run this script again to replace placeholder community labels.')
    else:
        print(f'Applied {len(labelmap)} manually reviewed community topic labels.')

if __name__=='__main__': main()
