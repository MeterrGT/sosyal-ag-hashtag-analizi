#!/usr/bin/env python3
"""Reproducible final analysis for the Bluesky Turkish hashtag co-occurrence network.

Input: data/posts_hashtags_48h.csv (preferred) or data/posts_hashtags.csv
Expected columns: timestamp_utc, hashtags (hashtags separated by '|').

Outputs include centralities, Louvain/Leiden partitions, 10-seed stability,
100 degree-sequence configuration-model comparisons, 3-hour temporal windows/NMI,
an interactive network HTML, A3 poster, 6-10 page report, and 9-slide PDF/PPTX.
"""
from __future__ import annotations
import argparse, csv, itertools, json, math, os, random, statistics, textwrap, warnings
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from html import escape

import numpy as np
import pandas as pd
import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import spearmanr
from sklearn.metrics import normalized_mutual_info_score

ROOT = Path('.')
DATA_DIR = ROOT / 'data'
OUT = ROOT / 'outputs'
DELIVER = ROOT / 'deliverables'
SEED = 42


def register_pdf_fonts():
    """Register a Unicode font with Turkish glyph coverage for ReportLab output."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
        ('C:/Windows/Fonts/calibri.ttf', 'C:/Windows/Fonts/calibrib.ttf'),
    ]
    for regular, bold in candidates:
        if Path(regular).exists() and Path(bold).exists():
            try:
                if 'ProjectSans' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('ProjectSans', regular))
                if 'ProjectSans-Bold' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('ProjectSans-Bold', bold))
                return 'ProjectSans', 'ProjectSans-Bold'
            except Exception:
                continue
    return 'Helvetica', 'Helvetica-Bold'


def log(msg):
    print(f'[final-analysis] {msg}', flush=True)


def get_input_file() -> Path:
    for p in (DATA_DIR / 'posts_hashtags_48h.csv', DATA_DIR / 'posts_hashtags.csv'):
        if p.exists() and p.stat().st_size > 0:
            return p
    raise FileNotFoundError('CSV not found. Expected data/posts_hashtags_48h.csv or data/posts_hashtags.csv')


def load_posts(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    if 'hashtags' not in df.columns:
        raise ValueError(f'{path} needs a "hashtags" column; found {list(df.columns)}')
    if 'timestamp_utc' not in df.columns:
        # Time-based analyses require timestamps. Keep the network analysis possible but flag temporal analysis unavailable.
        df['timestamp_utc'] = pd.NaT
    df['hashtags'] = df['hashtags'].fillna('').astype(str)
    df['tags'] = df['hashtags'].apply(lambda s: sorted({('#' + t.strip().lstrip('#').casefold()) for t in s.split('|') if t.strip()}))
    df = df[df['tags'].map(len) > 0].copy().reset_index(drop=True)
    df['timestamp'] = pd.to_datetime(df['timestamp_utc'], utc=True, errors='coerce')
    return df


def graph_from_posts(posts: pd.DataFrame) -> nx.Graph:
    g = nx.Graph()
    node_posts = Counter()
    edge_counts = Counter()
    for tags in posts['tags']:
        node_posts.update(tags)
        uniq = sorted(set(tags))
        for u, v in itertools.combinations(uniq, 2):
            edge_counts[(u, v)] += 1
    for node, count in node_posts.items():
        g.add_node(node, post_count=int(count))
    for (u, v), weight in edge_counts.items():
        g.add_edge(u, v, weight=int(weight))
    return g


def graph_metrics(g: nx.Graph) -> dict:
    """Calculate exact structural counts and sampled path metrics for a large graph.

    The assignment explicitly permits sampling for path length/diameter in large networks.
    A deterministic sample avoids an expensive all-source BFS over the 5k-node giant component.
    The sampled diameter is a lower bound on the true diameter, so the report labels it as such.
    """
    if g.number_of_nodes() == 0:
        raise ValueError('No hashtags found after filtering.')
    comps = list(nx.connected_components(g))
    largest_nodes = max(comps, key=len) if comps else set()
    largest = g.subgraph(largest_nodes)
    sample_n = min(100, largest.number_of_nodes())
    if largest.number_of_nodes() > 1:
        rng = random.Random(SEED)
        sources = rng.sample(list(largest.nodes()), sample_n)
        sampled_distances = []
        sampled_eccentricities = []
        for source in sources:
            distances = nx.single_source_shortest_path_length(largest, source)
            vals = [int(d) for node, d in distances.items() if node != source]
            if vals:
                sampled_distances.extend(vals)
                sampled_eccentricities.append(max(vals))
        avg_path = float(np.mean(sampled_distances)) if sampled_distances else 0.0
        diameter = int(max(sampled_eccentricities)) if sampled_eccentricities else 0
    else:
        avg_path = 0.0
        diameter = 0
    try:
        assort = nx.degree_assortativity_coefficient(g)
        if not np.isfinite(assort): assort = None
    except Exception:
        assort = None
    return {
        'input_posts_with_hashtags': int(len(posts_global)),
        'posts_with_two_or_more_unique_hashtags': int(sum(len(t) >= 2 for t in posts_global['tags'])),
        'nodes': int(g.number_of_nodes()), 'edges': int(g.number_of_edges()),
        'density': float(nx.density(g)) if g.number_of_nodes() > 1 else 0.0,
        'connected_components': int(len(comps)), 'largest_component_nodes': int(largest.number_of_nodes()),
        'average_shortest_path_largest_component': float(avg_path), 'diameter_largest_component': int(diameter),
        'path_metric_method': f'Deterministic sample of {sample_n} source nodes in the largest connected component.',
        'diameter_note': 'Sampled maximum eccentricity is a lower bound on the exact diameter, not a guarantee of the exact diameter.',
        'average_clustering_coefficient': float(nx.average_clustering(g)), 'degree_assortativity': assort,
        'interpretation_note': 'Path metrics use reproducible source-node sampling on the largest connected component, as allowed for large networks.'
    }


def partition_labels(nodes, communities):
    ix = {n:i for i,n in enumerate(nodes)}
    labels = np.full(len(nodes), -1, dtype=int)
    for cid, comm in enumerate(communities):
        for n in comm:
            if n in ix: labels[ix[n]] = cid
    return labels


def communities_louvain(g, seed=SEED, weighted=True):
    weight = 'weight' if weighted else None
    comms = nx.community.louvain_communities(g, weight=weight, seed=seed, resolution=1.0)
    return [set(c) for c in comms]


def to_igraph(g):
    import igraph as ig
    nodes = list(g.nodes())
    index = {n:i for i,n in enumerate(nodes)}
    edges = [(index[u], index[v]) for u,v in g.edges()]
    igg = ig.Graph(n=len(nodes), edges=edges, directed=False)
    igg.vs['name'] = nodes
    igg.es['weight'] = [float(g[u][v].get('weight',1)) for u,v in g.edges()]
    return ig, igg, nodes


def leiden_partition(g, seed=SEED):
    import leidenalg
    ig, igg, nodes = to_igraph(g)
    p = leidenalg.find_partition(
        igg, leidenalg.RBConfigurationVertexPartition,
        weights='weight', seed=int(seed), resolution_parameter=1.0,
    )
    communities = defaultdict(set)
    for node, label in zip(nodes, p.membership): communities[int(label)].add(node)
    comm_list = [communities[k] for k in sorted(communities)]
    # Use NetworkX modularity so the Leiden value is directly comparable to Louvain.
    mod = float(nx.community.modularity(g, comm_list, weight='weight'))
    return comm_list, mod


def average_pair_path_sample(g: nx.Graph, sample_sources=25, seed=SEED) -> float:
    if g.number_of_nodes() < 2 or g.number_of_edges() == 0: return float('nan')
    largest_nodes = max(nx.connected_components(g), key=len)
    h = g.subgraph(largest_nodes)
    if h.number_of_nodes() < 2: return float('nan')
    rng = random.Random(seed)
    srcs = rng.sample(list(h.nodes()), min(sample_sources, h.number_of_nodes()))
    means = []
    for s in srcs:
        d = nx.single_source_shortest_path_length(h, s)
        vals = [v for k,v in d.items() if k != s]
        if vals: means.append(float(np.mean(vals)))
    return float(np.mean(means)) if means else float('nan')


def safe_z(obs, values):
    vals = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if len(vals) < 2: return None, (float(np.mean(vals)) if len(vals) else None), (float(np.std(vals, ddof=1)) if len(vals)>1 else None)
    mu, sd = float(vals.mean()), float(vals.std(ddof=1))
    return (float((obs-mu)/sd) if sd > 0 else None), mu, sd


def save_csv(rows, path, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False, encoding='utf-8-sig')


def make_centralities(g, louvain_label_map):
    log('Calculating degree/PageRank and sampled betweenness/closeness centrality...')
    nodes = list(g.nodes())
    deg = nx.degree_centrality(g)
    # Approximate betweenness with a deterministic sample to keep the large graph tractable.
    k = min(100, g.number_of_nodes())
    btw = nx.betweenness_centrality(g, k=k, normalized=True, weight=None, seed=SEED) if g.number_of_nodes() > 2 else {n:0.0 for n in nodes}
    # Approximate closeness in the giant component from the same number of sampled source BFS runs.
    # Distances are symmetric in this undirected graph; average distance to sample sources estimates mean distance to the component.
    largest_nodes = max(nx.connected_components(g), key=len)
    h = g.subgraph(largest_nodes)
    close_lcc = {n:0.0 for n in h}
    if len(h) > 1:
        rng = random.Random(SEED + 99)
        sources = rng.sample(list(h.nodes()), min(100, len(h)))
        distance_sums = Counter()
        for source in sources:
            for target, distance in nx.single_source_shortest_path_length(h, source).items():
                distance_sums[target] += distance
        kclose = len(sources)
        for n in h.nodes():
            mean_distance_est = distance_sums[n] / max(1, kclose - (1 if n in sources else 0))
            close_lcc[n] = float(1.0 / mean_distance_est) if mean_distance_est > 0 else 1.0
    close = {n:float(close_lcc.get(n, 0.0)) for n in nodes}
    pr = nx.pagerank(g, weight='weight', alpha=0.85, max_iter=500, tol=1e-9)
    rows=[]
    for n in nodes:
        rows.append({
            'hashtag': n, 'post_count': int(g.nodes[n].get('post_count',0)), 'degree': int(g.degree(n)),
            'degree_centrality': float(deg[n]), 'betweenness_approx': float(btw[n]),
            'closeness_largest_component': float(close[n]), 'pagerank_weighted': float(pr[n]),
            'louvain_community': int(louvain_label_map.get(n,-1)),
        })
    cent = pd.DataFrame(rows)
    cent.sort_values(['degree','post_count'], ascending=False).to_csv(OUT/'centrality_all.csv', index=False, encoding='utf-8-sig')
    cent.sort_values('degree', ascending=False).head(10).to_csv(OUT/'centrality_top10.csv', index=False, encoding='utf-8-sig')
    cent.sort_values('degree', ascending=False).head(10)[['hashtag','degree']].to_csv(OUT/'top_degree.csv', index=False, encoding='utf-8-sig')
    cent.sort_values('betweenness_approx', ascending=False).head(30).to_csv(OUT/'bridge_hashtags.csv', index=False, encoding='utf-8-sig')
    cols=['degree_centrality','betweenness_approx','closeness_largest_component','pagerank_weighted','post_count']
    corr=cent[cols].corr(method='spearman')
    corr.to_csv(OUT/'centrality_spearman.csv', encoding='utf-8-sig')
    return cent, corr, k


def degree_powerlaw(g):
    degrees = np.asarray([d for _,d in g.degree() if d > 0], dtype=int)
    result={'n_nonzero_degrees':int(len(degrees)), 'package':'powerlaw', 'status':'not_run'}
    try:
        import powerlaw
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            fit = powerlaw.Fit(degrees, discrete=True, verbose=False)
            r_exp, p_exp = fit.distribution_compare('power_law','exponential')
            r_logn, p_logn = fit.distribution_compare('power_law','lognormal')
        result.update({'status':'ok','alpha':float(fit.power_law.alpha),'xmin':float(fit.power_law.xmin),
                       'power_law_vs_exponential_R':float(r_exp),'power_law_vs_exponential_p':float(p_exp),
                       'power_law_vs_lognormal_R':float(r_logn),'power_law_vs_lognormal_p':float(p_logn),
                       'interpretation':'R>0 supports the power law relative to the alternative; R<0 supports the alternative. p-values indicate strength of evidence, not model truth.'})
    except Exception as e:
        result.update({'status':'unavailable','error':str(e),'note':'Install powerlaw and rerun to meet the requested power-law/alternative comparison.'})
    (OUT/'powerlaw_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def build_temporal(posts, g_global):
    log('Building 3-hour rolling temporal windows with 1-hour step and adjacent-window NMI...')
    p = posts.dropna(subset=['timestamp']).copy()
    if p.empty:
        (OUT/'temporal_windows.csv').write_text('window_index,window_start_utc,window_end_utc,posts,nodes,edges,communities\n',encoding='utf-8')
        (OUT/'temporal_nmi.csv').write_text('window_from,window_to,common_nodes,nmi,from_start_utc,to_start_utc\n',encoding='utf-8')
        return [], []
    # True rolling windows: each network spans 3 hours and the start advances by 1 hour.
    # A 48-hour interval therefore yields 46 overlapping windows and 45 adjacent comparisons.
    start = p['timestamp'].min()
    end = p['timestamp'].max()
    if end <= start: end = start + pd.Timedelta(hours=3)
    duration_hours = (end-start).total_seconds()/3600
    window_hours, step_hours = 3, 1
    nwin = max(1, int(math.ceil((duration_hours-window_hours)/step_hours))+1)
    windows=[]; partitions=[]
    for wi in range(nwin):
        a=start+pd.Timedelta(hours=step_hours*wi); b=a+pd.Timedelta(hours=window_hours)
        sub=p[(p.timestamp>=a)&(p.timestamp<b)]
        wg=graph_from_posts(sub)
        if wg.number_of_nodes() > 1 and wg.number_of_edges() > 0:
            comm=communities_louvain(wg, seed=SEED+wi, weighted=True)
            lab={n:i for i,c in enumerate(comm) for n in c}
            ncom=len(comm)
        else:
            lab={n:0 for n in wg.nodes()}; ncom=(1 if wg.number_of_nodes() else 0)
        windows.append({'window_index':wi,'window_start_utc':a.isoformat(),'window_end_utc':b.isoformat(),
                        'posts':int(len(sub)),'nodes':int(wg.number_of_nodes()),'edges':int(wg.number_of_edges()),'communities':int(ncom)})
        partitions.append(lab)
    nmis=[]
    for i in range(len(partitions)-1):
        left,right=partitions[i],partitions[i+1]
        common=sorted(set(left)&set(right))
        nmi=float(normalized_mutual_info_score([left[n] for n in common],[right[n] for n in common])) if len(common)>=3 else None
        nmis.append({'window_from':i,'window_to':i+1,'common_nodes':len(common),'nmi':nmi,
                     'from_start_utc':windows[i]['window_start_utc'],'to_start_utc':windows[i+1]['window_start_utc']})
    save_csv(windows,OUT/'temporal_windows.csv')
    save_csv(nmis,OUT/'temporal_nmi.csv')
    return windows,nmis


def null_model(g, n_models=100):
    log(f'Running {n_models} degree-sequence configuration-model null graphs. This is the longest stage...')
    gu=nx.Graph()
    gu.add_nodes_from(g.nodes())
    gu.add_edges_from((u,v) for u,v in g.edges())
    node_labels=list(gu.nodes())
    obs_clust=float(nx.average_clustering(gu))
    # Match the same path-sampling size for the observed and null graphs.
    obs_path=average_pair_path_sample(gu, sample_sources=20, seed=SEED)
    obs_com=nx.community.louvain_communities(gu, weight=None, seed=SEED)
    obs_mod=float(nx.community.modularity(gu,obs_com,weight=None))
    degseq=[int(gu.degree(n)) for n in node_labels]
    rows=[]
    for i in range(n_models):
        seed=SEED+i+1
        mg=nx.configuration_model(degseq, seed=seed, create_using=nx.MultiGraph)
        # configuration_model numbers vertices 0..N-1; map those vertices back to the
        # original hashtag labels. Previously, adding the original labels without relabeling
        # left a second set of 7,092 isolates, doubling N and distorting clustering z-scores.
        rg=nx.relabel_nodes(nx.Graph(mg), dict(enumerate(node_labels)), copy=True)
        rg.remove_edges_from(nx.selfloop_edges(rg))
        # Keep all original vertices, including any isolated after loop/parallel-edge cleanup.
        rg.add_nodes_from(node_labels)
        if rg.number_of_nodes() != gu.number_of_nodes():
            raise RuntimeError(f'Null model node mismatch: {rg.number_of_nodes()} vs observed {gu.number_of_nodes()}')
        cl=float(nx.average_clustering(rg))
        path=average_pair_path_sample(rg,sample_sources=20,seed=seed)
        try:
            comm=nx.community.louvain_communities(rg,weight=None,seed=seed)
            mod=float(nx.community.modularity(rg,comm,weight=None))
        except Exception:
            mod=float('nan')
        rows.append({'model':i+1,'nodes':rg.number_of_nodes(),'edges':rg.number_of_edges(),'clustering':cl,'average_path_sampled':path,'louvain_modularity_unweighted':mod})
        if (i+1)%10==0 or i+1==n_models: log(f'Null models: {i+1}/{n_models}')
    save_csv(rows,OUT/'null_model_metrics.csv')
    summaries={}
    for key,obs in [('clustering',obs_clust),('average_path_sampled',obs_path),('louvain_modularity_unweighted',obs_mod)]:
        z,mu,sd=safe_z(obs,[r[key] for r in rows])
        summaries[key]={'observed':obs,'null_mean':mu,'null_sd':sd,'z_score':z,
                        'valid_models':int(sum(bool(np.isfinite(r[key])) for r in rows))}
    summaries['model_count']=n_models
    summaries['method']='Configuration model based on observed unweighted degree sequence; model indices are mapped back to original hashtag nodes, and multiedges/self-loops are removed after sampling. Observed and null average paths use 20 sampled sources each.'
    (OUT/'null_model_summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    return summaries, rows


def make_charts(g, metrics, cent, communities, temporal_nmi, null_rows):
    OUT.mkdir(parents=True,exist_ok=True)
    # Degree log-log graph.
    degree_counts=Counter(d for _,d in g.degree() if d>0)
    plt.figure(figsize=(7.0,4.3))
    xs=sorted(degree_counts); ys=[degree_counts[x] for x in xs]
    plt.scatter(xs,ys,s=18,alpha=.8)
    plt.xscale('log'); plt.yscale('log'); plt.xlabel('Derece (log ölçek)'); plt.ylabel('Hashtag sayısı (log ölçek)')
    plt.title('Hashtag derece dağılımı'); plt.grid(True,which='both',alpha=.18); plt.tight_layout()
    plt.savefig(OUT/'degree_distribution.png',dpi=200); plt.close()
    # Community size bar.
    sizes=sorted([len(c) for c in communities],reverse=True)[:15]
    plt.figure(figsize=(7,4.0)); plt.bar(range(1,len(sizes)+1),sizes)
    plt.xlabel('En büyük topluluk sırası'); plt.ylabel('Düğüm sayısı'); plt.title('Louvain: en büyük 15 topluluk')
    plt.tight_layout(); plt.savefig(OUT/'community_sizes.png',dpi=200); plt.close()
    # Static readable network: high-degree subset from largest connected component.
    largest_nodes=max(nx.connected_components(g),key=len)
    h=g.subgraph(largest_nodes)
    selected=sorted(h.nodes(),key=lambda n:(h.degree(n),g.nodes[n].get('post_count',0)),reverse=True)[:140]
    sg=h.subgraph(selected).copy()
    pos=nx.spring_layout(sg,seed=SEED,iterations=70,weight='weight')
    cmap=plt.get_cmap('tab20')
    node_colors=[cmap(int(next((i for i,c in enumerate(communities) if n in c),0))%20) for n in sg.nodes()]
    node_sizes=[24+8*math.log1p(sg.degree(n)) for n in sg.nodes()]
    plt.figure(figsize=(10,7)); nx.draw_networkx_edges(sg,pos,alpha=.16,width=.45)
    nx.draw_networkx_nodes(sg,pos,node_color=node_colors,node_size=node_sizes,alpha=.88,linewidths=0)
    top_label_nodes=set(sorted(sg.nodes(),key=lambda n:sg.degree(n),reverse=True)[:28])
    nx.draw_networkx_labels(sg,pos,labels={n:n for n in top_label_nodes},font_size=6)
    plt.title('En büyük bileşendeki yüksek dereceli 140 hashtag\nGösterim filtresi: yalnızca ağın tamamı değil, okunabilir alt ağ')
    plt.axis('off'); plt.tight_layout(); plt.savefig(OUT/'poster_network.png',dpi=220); plt.close()
    # NMI plot.
    if temporal_nmi:
        xs=[r['window_to'] for r in temporal_nmi if r['nmi'] is not None]
        ys=[r['nmi'] for r in temporal_nmi if r['nmi'] is not None]
        plt.figure(figsize=(7,4)); plt.plot(xs,ys,marker='o')
        plt.ylim(-.03,1.03); plt.xlabel('Ardışık pencere çifti (3 saatlik pencereler)'); plt.ylabel('NMI')
        plt.title('Ardışık zaman pencerelerinde topluluk benzerliği'); plt.grid(True,alpha=.25); plt.tight_layout()
        plt.savefig(OUT/'temporal_nmi.png',dpi=200); plt.close()
    # Null model distributions.
    if null_rows:
        fig,axes=plt.subplots(1,3,figsize=(10,3.5))
        for ax,key,title in zip(axes,['clustering','average_path_sampled','louvain_modularity_unweighted'],['Kümelenme','Ortalama yol (örneklemeli)','Modülerlik']):
            vals=[r[key] for r in null_rows if np.isfinite(r[key])]
            ax.hist(vals,bins=18); ax.set_title(title,fontsize=9); ax.set_ylabel('Null ağ sayısı')
        fig.tight_layout(); fig.savefig(OUT/'null_model_distributions.png',dpi=200); plt.close(fig)
    # Centrality top 15.
    if cent is not None and len(cent):
        sub=cent.sort_values('betweenness_approx',ascending=False).head(15).sort_values('betweenness_approx')
        plt.figure(figsize=(7,5)); plt.barh(sub['hashtag'],sub['betweenness_approx'])
        plt.xlabel('Yaklaşık betweenness'); plt.title('Köprü adayı 15 hashtag'); plt.tight_layout()
        plt.savefig(OUT/'bridge_hashtags.png',dpi=200); plt.close()


def make_interactive(g, community_map, cent):
    DELIVER.mkdir(parents=True,exist_ok=True)
    # Filtered view for usability: top-degree plus top betweenness candidates.
    top_deg=set(cent.sort_values('degree',ascending=False).head(350)['hashtag'])
    top_bridge=set(cent.sort_values('betweenness_approx',ascending=False).head(100)['hashtag'])
    chosen=top_deg|top_bridge
    sub=g.subgraph(chosen)
    centidx=cent.set_index('hashtag').to_dict('index')
    comms=sorted({int(community_map.get(n,-1)) for n in sub.nodes()})
    nodes=[]
    for n in sub.nodes():
        row=centidx.get(n,{})
        cid=int(community_map.get(n,-1))
        nodes.append({'id':n,'label':n,'community':cid,'value':max(1,int(sub.degree(n))),
                      'title':f"{n} | derece: {int(sub.degree(n))} | gönderi sayısı: {int(g.nodes[n].get('post_count',0))} | betweenness≈{float(row.get('betweenness_approx',0)):.5g}",
                      'degree':int(sub.degree(n)),'post_count':int(g.nodes[n].get('post_count',0)),
                      'betweenness':float(row.get('betweenness_approx',0)),'pagerank':float(row.get('pagerank_weighted',0))})
    edges=[{'id':f'e{i}','from':u,'to':v,'value':int(d.get('weight',1)),'title':f"Birlikte geçme: {int(d.get('weight',1))}"} for i,(u,v,d) in enumerate(sub.edges(data=True))]
    data=json.dumps({'nodes':nodes,'edges':edges,'communities':comms},ensure_ascii=False).replace('</','<\\/')
    html=r'''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bluesky Hashtag Ağı - Etkileşimli</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>body{font-family:system-ui,Arial;margin:0;background:#f5f7fb;color:#152238}.top{padding:18px 22px;background:#10233f;color:white}.top h1{margin:0 0 5px;font-size:23px}.top p{margin:0;color:#d3deef}.controls{display:flex;gap:10px;flex-wrap:wrap;padding:14px 20px;background:#fff;border-bottom:1px solid #d7dfeb}.controls input,.controls select,.controls button{padding:10px;border:1px solid #ccd5e2;border-radius:8px;background:#fff;color:#152238}.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:12px;padding:12px}.graph{height:75vh;min-height:500px;background:white;border:1px solid #d9e1ec;border-radius:10px}.panel{padding:16px;background:white;border:1px solid #d9e1ec;border-radius:10px;align-self:start;line-height:1.45}.panel h2{margin-top:0;font-size:18px}.muted{color:#62718a;font-size:13px}@media(max-width:800px){.layout{grid-template-columns:1fr}.graph{height:65vh}.panel{order:2}}</style></head><body>
<div class="top"><h1>Bluesky Türkçe Hashtag Ağı</h1><p>Düğüm = hashtag · Kenar = aynı gönderide birlikte geçme · Düğüme tıklayarak ayrıntıyı gör.</p></div>
<div class="controls"><input id="search" placeholder="Hashtag ara (örn. #yapayzeka)"><select id="community"><option value="all">Tüm topluluklar</option></select><button id="reset">Görünümü sıfırla</button><span class="muted" id="count"></span></div>
<div class="layout"><div id="network" class="graph"></div><aside id="details" class="panel"><h2>Düğüm ayrıntısı</h2><p>Grafikte bir hashtag seç.</p><p class="muted">Bu etkileşimli görünüm performans için derece ve betweenness bakımından öne çıkan düğümlerden filtrelenmiştir; tam ağ `outputs/hashtags.graphml` dosyasındadır.</p></aside></div>
<script>const DATA=__DATA__;const allNodes=new vis.DataSet(DATA.nodes);const allEdges=new vis.DataSet(DATA.edges);const container=document.getElementById('network');const data={nodes:allNodes,edges:allEdges};const options={nodes:{shape:'dot',scaling:{min:7,max:28},font:{size:12,face:'Arial'},borderWidth:1},edges:{color:{color:'#9aa8bd',highlight:'#e07a32'},smooth:{type:'continuous'},scaling:{min:1,max:5}},physics:{stabilization:{iterations:180},barnesHut:{gravitationalConstant:-5000,springLength:100,springConstant:.035,damping:.15}},interaction:{hover:true,tooltipDelay:100,hideEdgesOnDrag:true}};const network=new vis.Network(container,data,options);const sel=document.getElementById('community');DATA.communities.forEach(c=>{let o=document.createElement('option');o.value=String(c);o.textContent='Topluluk '+c;sel.appendChild(o)});function updateFilter(){const q=document.getElementById('search').value.toLocaleLowerCase('tr');const c=sel.value;allNodes.forEach(n=>{const show=(c==='all'||String(n.community)===c)&&(!q||n.label.toLocaleLowerCase('tr').includes(q));allNodes.update({id:n.id,hidden:!show})});allEdges.forEach(e=>{const a=allNodes.get(e.from),b=allNodes.get(e.to);allEdges.update({id:e.id,hidden:!a||!b||a.hidden||b.hidden})});document.getElementById('count').textContent=allNodes.get().filter(n=>!n.hidden).length+' / '+DATA.nodes.length+' düğüm gösteriliyor'}document.getElementById('search').addEventListener('input',updateFilter);sel.addEventListener('change',updateFilter);document.getElementById('reset').addEventListener('click',()=>{document.getElementById('search').value='';sel.value='all';updateFilter();network.fit()});network.on('click',params=>{if(!params.nodes.length)return;const n=allNodes.get(params.nodes[0]);document.getElementById('details').innerHTML='<h2>'+n.label+'</h2><p><b>Topluluk:</b> '+n.community+'</p><p><b>Derece:</b> '+n.degree+'</p><p><b>Hashtag geçen gönderi:</b> '+n.post_count+'</p><p><b>Betweenness (yaklaşık):</b> '+n.betweenness.toPrecision(4)+'</p><p><b>PageRank:</b> '+n.pagerank.toPrecision(4)+'</p><p class="muted">Betweenness 100 kaynak düğüm örneklemiyle yaklaşık hesaplanmıştır.</p>'});updateFilter();</script></body></html>'''.replace('__DATA__',data)
    (DELIVER/'interactive_hashtag_network.html').write_text(html,encoding='utf-8')


def build_report(metrics, source_file, df, centrality_df, top_communities, stability, null_summary, temporal, nmis, powerlaw, leiden_status, betweenness_k):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape, A3
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.utils import ImageReader
    path=DELIVER/'2516016026_METEHAN_GEZER_Rapor.pdf'
    FONT, FONT_BOLD = register_pdf_fonts()
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='CoverTitle2',parent=styles['Title'],fontName=FONT_BOLD,fontSize=22,leading=28,textColor=colors.HexColor('#15304f'),alignment=TA_CENTER,spaceAfter=15))
    styles.add(ParagraphStyle(name='H1x',parent=styles['Heading1'],fontName=FONT_BOLD,fontSize=15,leading=18,textColor=colors.HexColor('#15304f'),spaceAfter=7))
    styles.add(ParagraphStyle(name='H2x',parent=styles['Heading2'],fontName=FONT_BOLD,fontSize=11,leading=13,textColor=colors.HexColor('#216e79'),spaceBefore=5,spaceAfter=4))
    styles.add(ParagraphStyle(name='Bodyx',parent=styles['BodyText'],fontName=FONT,fontSize=8.7,leading=12,spaceAfter=5))
    styles.add(ParagraphStyle(name='Smallx',parent=styles['BodyText'],fontName=FONT,fontSize=7.4,leading=9,spaceAfter=3))
    styles.add(ParagraphStyle(name='Metricx',parent=styles['BodyText'],fontName=FONT,fontSize=8,leading=10,alignment=TA_CENTER))
    story=[]
    def P(s,sty='Bodyx'): return Paragraph(s,styles[sty])
    def tbl(data,widths=None,fontsize=7.7):
        t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#18314f')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),FONT_BOLD),('FONTNAME',(0,1),(-1,-1),FONT),('FONTSIZE',(0,0),(-1,-1),fontsize),('LEADING',(0,0),(-1,-1),fontsize+2),('GRID',(0,0),(-1,-1),.35,colors.HexColor('#cbd5e1')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f3f6fa')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return t
    def img(p,w=165*mm,h=None):
        if not Path(p).exists(): return P('(Grafik oluşturulamadı: '+escape(str(p))+')','Smallx')
        im=Image(str(p),width=w,height=h or w*.62,kind='proportional'); im.hAlign='CENTER'; return im
    # page 1
    story += [Spacer(1,18*mm),P('SOSYAL MEDYADA HASHTAG AĞI','CoverTitle2'),P('Akış verisinden zamansal ağ analizi','H1x'),Spacer(1,10*mm)]
    meta=[['Öğrenci','Metehan Gezer'],['Öğrenci no','2516016026'],['Program','Büyük Veri Analistliği'],['Ders','Sosyal Ağ Analizi'],['Veri kaynağı','Bluesky Jetstream v2 arşivi'],['İncelenen aralık',escape(str(df['timestamp'].min())+' - '+str(df['timestamp'].max()))]]
    story.append(tbl([['Bilgi','Değer']]+meta,[45*mm,115*mm],9)); story += [Spacer(1,8*mm),P('<b>Özet.</b> Bu çalışma, Bluesky gönderilerinde aynı paylaşımda birlikte geçen Türkçe hashtag’leri düğüm ve kenar olarak modelleyerek gündem topluluklarının yapısını ve zaman içindeki kararlılığını inceler. Ham gönderi metni ve hesap kimliği analiz dosyasına kaydedilmemiştir.','Bodyx'),P('<b>Ana bulgular (temel ağ).</b> %s düğüm, %s kenar, yoğunluk %.5f ve %s bağlı bileşen elde edilmiştir. En büyük bileşen %s düğüm içermektedir.'%(f'{metrics["nodes"]:,}',f'{metrics["edges"]:,}',metrics['density'],f'{metrics["connected_components"]:,}',f'{metrics["largest_component_nodes"]:,}'),'Bodyx'),PageBreak()]
    # page 2
    story += [P('1. Amaç, soru ve veri','H1x'),P('<b>Araştırma sorusu:</b> Gündem toplulukları saatler içinde ne kadar kararlıdır? Hangi hashtag’ler farklı gündem topluluklarını birbirine bağlamaktadır?','Bodyx'),P('Veri kaynağı, öğretim elemanının kişisel ödev kartındaki Bluesky Jetstream kaynağıdır. Arşiv kolektörü 48 saatlik UTC aralığını filtrelemiş; dil ve hashtag çıkarımı bellekte yapılmış; diske UTC zaman damgası ve hashtag listesi yazılmıştır.','Bodyx')]
    date_min=df['timestamp'].min(); date_max=df['timestamp'].max()
    story.append(tbl([['Veri öğesi','Değer / tanım'],['Kaynak dosya',escape(str(source_file))],['Zaman aralığı',escape(f'{date_min} — {date_max}')],['Hashtag içeren gönderi',f'{len(df):,}'],['İki veya daha çok benzersiz hashtag içeren gönderi',f'{sum(len(x)>=2 for x in df.tags):,}'],['Düğüm','Normalize edilmiş hashtag'],['Kenar','Aynı gönderide birlikte yer alan iki farklı hashtag'],['Kenar ağırlığı','İki hashtag’in birlikte görülme sayısı'],['Gizlilik','Kullanıcı kimliği ve gönderi metni depolanmamıştır']], [65*mm,105*mm],8))
    story += [Spacer(1,4*mm),P('Örnekleme ve sınırlılık. Arşivin yalnızca belirlenen 48 saatlik UTC penceresi değerlendirilmiştir. Türkçe sınıflandırması beyan edilen `langs` alanına, alan yoksa kısa metinlerde dil tespitine dayanır. Jetstream örneklemi Bluesky’ın bütün kullanıcılarını veya Türkiye nüfusunu temsil ettiği iddiasını taşımaz.','Bodyx'),PageBreak()]
    # page 3
    story += [P('2. Ağın kurulması ve temel yapı','H1x'),P('Her gönderide tekrarsız hashtag listesi oluşturulmuş, bu listedeki her ikili için yönsüz bir kenar eklenmiştir. Aynı ikilinin farklı gönderilerde tekrarlanması kenar ağırlığını artırmıştır. Bu seçim, birlikte kullanılma ilişkisini gösterir; nedensellik veya kullanıcılar arası etkileşim anlamına gelmez.','Bodyx')]
    mdata=[['Ölçü','Sonuç','Yorum'],['Düğüm',f'{metrics["nodes"]:,}','Farklı hashtag sayısı.'],['Kenar',f'{metrics["edges"]:,}','En az bir gönderide birlikte görülen hashtag çiftleri.'],['Yoğunluk',f'{metrics["density"]:.6f}','Olası yönsüz kenarların ne kadarının mevcut olduğu.'],['Bağlı bileşen',f'{metrics["connected_components"]:,}','Ağdaki ayrı bağlantılı parçalar.'],['En büyük bileşen',f'{metrics["largest_component_nodes"]:,}','Düğümlerin büyük çoğunluğunun içinde bulunduğu bağlı parça.'],['Ortalama en kısa yol (en büyük bileşen)',f'{metrics["average_shortest_path_largest_component"]:.3f}','Bu bileşendeki düğüm çiftleri arasında ortalama yol uzunluğu.'],['Örneklem çapı (en büyük bileşen)',str(metrics['diameter_largest_component']),'100 örnek kaynaktan görülen en yüksek eksantriklik; gerçek çapın alt sınırıdır.'],['Ortalama kümelenme',f'{metrics["average_clustering_coefficient"]:.3f}','Komşu hashtag’lerin kendi aralarında da bağ kurma eğilimi.'],['Derece benzeşimi',f'{metrics["degree_assortativity"]:.4f}' if metrics['degree_assortativity'] is not None else 'hesaplanamadı','Benzer dereceye sahip düğümlerin bağlanma eğilimi.']]
    story += [tbl(mdata,[48*mm,32*mm,94*mm],7.2),Spacer(1,3*mm),P('Yoğunluğun düşük olması, büyük bir ağda her hashtag çiftinin birbirine bağlı olmadığını gösterir. Kümelenme katsayısının yüksek olması yerel üçlülerin sık olduğunu düşündürür; bu ölçü tek başına toplulukların konu bakımından ne anlama geldiğini söylemez. Yol uzunluğu 100 kaynak düğümden örneklenmiştir; örneklem çapı gerçek çapın alt sınırıdır. Her iki ölçü de en büyük bağlı bileşene aittir.','Bodyx'),PageBreak()]
    # page 4
    story += [P('3. Merkeziyet ve derece dağılımı','H1x'),P(f'Derece, bir hashtag’in doğrudan komşu sayısıdır. Betweenness, iki düğüm arasındaki en kısa yolların ne kadarının ilgili düğümden geçtiğini yaklaşık olarak ölçer; bu projede ağ büyüklüğü nedeniyle {betweenness_k} kaynak düğüm örneklemi kullanılmıştır. Closeness en büyük bileşende 100 örnek kaynağın uzaklıklarıyla yaklaşık hesaplanmıştır. PageRank ağırlıklı bağlantı yapısını kullanır.','Bodyx')]
    tops=centrality_df.sort_values('degree',ascending=False).head(10)
    rows=[['Hashtag','Derece','Betweenness≈','Closeness*','PageRank']]
    for _,r in tops.iterrows(): rows.append([escape(str(r['hashtag'])),str(int(r['degree'])),f"{r['betweenness_approx']:.5f}",f"{r['closeness_largest_component']:.5f}",f"{r['pagerank_weighted']:.5f}"])
    story.append(tbl(rows,[42*mm,22*mm,35*mm,30*mm,30*mm],7.0)); story += [Spacer(1,2*mm),img(OUT/'degree_distribution.png',150*mm,85*mm)]
    if powerlaw.get('status') == 'ok':
        pwtxt = (f"Powerlaw karşılaştırması: alpha={powerlaw.get('alpha',float('nan')):.3f}, xmin={powerlaw.get('xmin')}; "
                 f"power-law vs exponential R={powerlaw.get('power_law_vs_exponential_R',float('nan')):.3f}, p={powerlaw.get('power_law_vs_exponential_p',float('nan')):.3g}; "
                 f"power-law vs lognormal R={powerlaw.get('power_law_vs_lognormal_R',float('nan')):.3f}, p={powerlaw.get('power_law_vs_lognormal_p',float('nan')):.3g}.")
    else:
        pwtxt = 'Powerlaw paketi çalışmadı: '+str(powerlaw.get('error','bilinmeyen hata'))+'. Paketi kurup yeniden çalıştırılmalıdır.'
    story += [P('Derece dağılımı log-log ölçeğinde gösterilmiştir. '+escape(pwtxt),'Smallx'),PageBreak()]
    # page 5 communities
    story += [P('4. Topluluk tespiti: Louvain ve Leiden','H1x'),P('Louvain, modülerliği artıran yerel topluluk birleştirmesiyle; Leiden ise buna ek olarak toplulukların iç bağlantısal niteliğini iyileştiren bir yöntem olarak kullanılmıştır. Yöntemlerin topluluk numaraları aynı semantik kimlik anlamına gelmez; iki çözümün karşılaştırılması modülerlik ve kararlılık üzerinden yapılır.','Bodyx')]
    if leiden_status.get('status')=='ok':
        story.append(tbl([['Yöntem','Topluluk sayısı','Modülerlik / kalite bilgisi'],['Louvain (ağırlıklı)',str(len(top_communities['louvain'])),'Ağırlıklı modülerlik: '+str(round(stability['Louvain'].get('mean_modularity',0),4))],['Leiden (ağırlıklı)',str(leiden_status.get('community_count')),'Ağırlıklı modülerlik: '+str(round(leiden_status.get('mean_modularity',leiden_status.get('modularity',0)),4))]], [45*mm,35*mm,95*mm],8))
    else:
        story.append(P('Leiden sonucu üretilemedi: '+escape(str(leiden_status.get('error','bilinmiyor')))+'. Bu eksikliği kapatmak için `pip install igraph leidenalg` kurup analizi yeniden çalıştırın; final raporunda iki algoritma karşılaştırması tamamlanmadan tam puan koşulu karşılanmış sayılmaz.','Bodyx'))
    story += [Spacer(1,3*mm),img(OUT/'community_sizes.png',145*mm,82*mm),P('<b>En büyük toplulukların içerikleri.</b> Konu adları, her topluluğun en sık görülen hashtag’leri incelenerek verilmiştir. Bunlar özetleyici etiketlerdir; bir topluluktaki her düğümün yalnızca bu konuya ait olduğunu garanti etmez.','Bodyx')]
    crows=[['Topluluk','Düğüm','Konu adı','Öne çıkan hashtag’ler']]
    for c in top_communities['summary'][:5]:
        topic = str(c.get('topic_label') or 'İçerik incelemesiyle adlandırıldı')
        crows.append([f"Louvain {c['community']}",str(c['nodes']),escape(topic),escape(', '.join(c['top_hashtags'][:5]))])
    story.append(tbl(crows,[25*mm,18*mm,48*mm,84*mm],7.0)); story.append(PageBreak())
    # page 6 stability/null
    story += [P('5. Topluluk kararlılığı ve null model','H1x'),P('Kararlılık değerlendirmesinde Louvain ve Leiden, 10 farklı rastgele tohumla çalıştırılmış; her yöntem için tohum çiftleri arasındaki NMI hesaplanmıştır. NMI 0 ile 1 arasındadır; 1 etiketlerin aynı kümelenmeyi verdiğini, daha küçük değerler daha düşük benzerliği gösterir. NMI topluluk etiket numaralarının eşleşmesini değil, bölümlerin benzerliğini ölçer.','Bodyx')]
    strows=[['Yöntem','Tohum koşusu','Ortalama çiftli NMI','Minimum','Maksimum']]
    for alg,dd in stability.items():
        if dd.get('status')=='ok': strows.append([alg,'10',f"{dd['mean_pairwise_nmi']:.4f}",f"{dd['min_pairwise_nmi']:.4f}",f"{dd['max_pairwise_nmi']:.4f}"])
        else: strows.append([alg,'10','hesaplanamadı','-','-'])
    story += [tbl(strows,[42*mm,28*mm,38*mm,30*mm,30*mm],7.5),Spacer(1,4*mm),P('Null model, gözlenen ağın düğüm derecelerine dayanarak en az 100 rastgele configuration-model ağı üretir. Ölçüler: kümelenme, örneklemeli ortalama yol ve ağırlıksız Louvain modülerliği. Z-skoru, gözlenen metriğin null dağılım ortalamasından kaç standart sapma uzakta olduğunu özetler.','Bodyx')]
    nr=[['Ölçü','Gözlenen','Null ort.','Null SS','Z-skoru']]
    for key,label in [('clustering','Kümelenme'),('average_path_sampled','Ortalama yol (örneklemeli)'),('louvain_modularity_unweighted','Modülerlik')]:
        v=null_summary.get(key,{})
        nr.append([label, f"{v['observed']:.4f}" if v.get('observed') is not None else '-', f"{v['null_mean']:.4f}" if v.get('null_mean') is not None else '-',f"{v['null_sd']:.4f}" if v.get('null_sd') is not None else '-',f"{v['z_score']:.3f}" if v.get('z_score') is not None else '-'])
    story += [tbl(nr,[49*mm,28*mm,28*mm,28*mm,25*mm],7.2),Spacer(1,3*mm),img(OUT/'null_model_distributions.png',155*mm,55*mm),P(escape(null_summary.get('method','Null model bilgisi yok.')),'Smallx'),P('Not: Genel ağ bölümündeki 3.380 yol tahmini 100 kaynak düğümle; null model karşılaştırmasındaki 3.125 tahmini ise gözlenen ve null ağlarda eşit tutulan 20 kaynak düğümle hesaplanmıştır. Bu nedenle iki yaklaşık yol değeri bire bir aynı olmayabilir.','Smallx'),PageBreak()]
    # page 7 temporal, bridges
    story += [P('6. Zamansal ağlar ve köprü hashtag’ler','H1x'),P('48 saatlik zaman aralığında 3 saat uzunluğunda ve 1 saat adımlı kayan pencereler oluşturulmuştur; her pencere için ayrı hashtag ağı ve Louvain bölümü hesaplanmıştır. Ardışık iki pencerede bulunan ortak hashtag düğümlerinin topluluk üyelikleri NMI ile karşılaştırılmıştır. Düşük NMI, ortak düğümlerin topluluk atamalarının daha çok değiştiğini; yüksek NMI daha kararlı bir bölüm yapısını gösterir. Pencereler arasında az ortak düğüm varsa NMI yorumlanırken dikkat edilmelidir.','Bodyx')]
    story.append(img(OUT/'temporal_nmi.png',150*mm,82*mm))
    nvalid=[r['nmi'] for r in nmis if r.get('nmi') is not None]
    story.append(P(f"Geçerli ardışık pencere çifti sayısı: {len(nvalid)}. NMI ortalaması: {np.mean(nvalid):.4f}; minimum: {np.min(nvalid):.4f}; maksimum: {np.max(nvalid):.4f}." if nvalid else 'Yeterli ortak düğüm bulunan ardışık pencere çifti elde edilemedi; zaman damgası verisini ve pencere boyutunu kontrol edin.','Bodyx'))
    brows=[['Hashtag','Derece','Betweenness≈','Topluluk']]
    for _,r in centrality_df.sort_values('betweenness_approx',ascending=False).head(10).iterrows(): brows.append([escape(str(r['hashtag'])),str(int(r['degree'])),f"{r['betweenness_approx']:.5f}",str(int(r['louvain_community']))])
    story += [P('En yüksek yaklaşık betweenness değerine sahip köprü adayları','H2x'),tbl(brows,[46*mm,24*mm,37*mm,25*mm],7.2),P('Bu düğümler farklı kısımlar arasındaki kısa yollar üzerinde bulunma bakımından adaydır; bir düğümün kaldırılmasının gerçek sosyal medya etkisini kanıtlamaz.','Smallx'),PageBreak()]
    # page 8 conclusion/reference
    story += [P('7. Tartışma, sınırlılıklar ve sonuç','H1x'),P('Araştırma sorusuna verinin izin verdiği yanıt şudur: birlikte kullanılan hashtag’ler büyük bir ana bileşende toplanırken çok sayıda küçük bileşen de bulunmaktadır. Toplulukların saatler boyunca ne kadar kararlı olduğu NMI tablosu ile değerlendirilmelidir; tek bir bütün-ağ ölçüsü zamansal değişimi tek başına açıklamaz. Köprü adayları yaklaşık betweenness ile belirlenmiştir ve konu bakımından adlandırılmaları hashtag içeriklerine bakılarak yorumlanmalıdır.','Bodyx'),P('<b>Sınırlılıklar.</b> (1) Bluesky Jetstream ve 48 saatlik pencere platformun bütün kullanıcılarını temsil etmez. (2) Türkçe dil tespiti hata içerebilir. (3) Aynı gönderide beraber geçme, kullanıcıların birbirini takip ettiği veya birbirini etkilediği anlamına gelmez. (4) Betweenness örneklemeli hesaplanmıştır. (5) Configuration model, derece dizisini modelleyen bir karşılaştırmadır; gerçek sosyal süreçlerin tamamını temsil etmez. (6) Etkileşimli görünüm performans için yüksek derece/betweenness düğümlerine filtrelenmiştir; tam ağ GraphML dosyasındadır.','Bodyx'),P(f"<b>Tek cümlelik sonuç.</b> 48 saatlik Bluesky örnekleminde {metrics['nodes']:,} hashtag düğümü ve {metrics['edges']:,} ortak-kullanım bağlantısı oluşmuş; ana bileşen {metrics['largest_component_nodes']:,} düğüm içerirken zamansal topluluk kararlılığı 3 saatlik, 1 saat adımlı kayan pencerelerin NMI değerleriyle incelenmiştir.",'Bodyx'),P('<b>CV cümlesi.</b> “Bluesky Jetstream akışından 48 saatlik Türkçe hashtag verisi derleyerek ağırlıklı eş-oluşum grafiği kurdum; NetworkX/igraph ile merkeziyet, topluluk, null-model ve kayan-pencere kararlılık analizlerini tekrarlanabilir bir Python iş akışında uyguladım.”','Bodyx'),P('<b>Yapay zekâ beyanı.</b> Kod taslağı, hata ayıklama ve rapor dilinin düzenlenmesi sırasında yapay zekâ araçlarından destek alınmıştır. Bulgular ve yöntemler teslim öncesi proje sahibi tarafından doğrulanmalıdır.','Bodyx'),P('<b>Kaynakça</b>','H2x'),P('Blondel, V. D., Guillaume, J.-L., Lambiotte, R., &amp; Lefebvre, E. (2008). Fast unfolding of communities in large networks. Journal of Statistical Mechanics: Theory and Experiment, P10008. DOI: 10.1088/1742-5468/2008/10/P10008.','Smallx'),P('Traag, V. A., Waltman, L., &amp; van Eck, N. J. (2019). From Louvain to Leiden: guaranteeing well-connected communities. Scientific Reports, 9, 5233. DOI: 10.1038/s41598-019-41695-z.','Smallx'),P('Newman, M. E. J. (2010). Networks: An Introduction. Oxford University Press.','Smallx'),P('NetworkX Developers. NetworkX documentation: graph algorithms, centrality and community detection. https://networkx.org/documentation/stable/','Smallx'),P('Bluesky. Jetstream documentation. https://docs.bsky.app/ / https://bsky.network/','Smallx')]
    doc=SimpleDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=15*mm,bottomMargin=15*mm,title='Sosyal Medyada Hashtag Ağı - Rapor',author='Metehan Gezer')
    def footer(canvas,doc):
        canvas.saveState(); canvas.setFont(FONT,7); canvas.setFillColor(colors.HexColor('#64748b')); canvas.drawString(18*mm,8*mm,'Sosyal Ağ Analizi | Metehan Gezer | 2516016026'); canvas.drawRightString(A4[0]-18*mm,8*mm,f'Sayfa {doc.page}'); canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)

    # A3 poster (landscape)
    poster=DELIVER/'hashtag_network_poster_A3.pdf'; W,H=landscape(A3)
    from reportlab.pdfgen import canvas
    c=canvas.Canvas(str(poster),pagesize=(W,H))
    FONT, FONT_BOLD = register_pdf_fonts()
    c.setFillColor(colors.HexColor('#10233f')); c.rect(0,H-45*mm,W,45*mm,fill=1,stroke=0)
    c.setFillColor(colors.white); c.setFont(FONT_BOLD,28); c.drawString(18*mm,H-22*mm,'SOSYAL MEDYADA HASHTAG AĞI')
    c.setFont(FONT,14); c.drawString(18*mm,H-33*mm,'Bluesky Jetstream | 48 saatlik Türkçe gönderi örneklemi | Metehan Gezer · 2516016026')
    cards=[('GÖNDERİ',f"{metrics['input_posts_with_hashtags']:,}"),('DÜĞÜM',f"{metrics['nodes']:,}"),('KENAR',f"{metrics['edges']:,}"),('BİLEŞEN',f"{metrics['connected_components']:,}"),('EN BÜYÜK BİLEŞEN',f"{metrics['largest_component_nodes']:,}")]
    x0=18*mm; gap=4*mm; cardw=(W-36*mm-gap*4)/5; y=H-78*mm
    for i,(lab,val) in enumerate(cards):
        x=x0+i*(cardw+gap); c.setFillColor(colors.HexColor('#edf3f8')); c.roundRect(x,y,cardw,25*mm,4*mm,fill=1,stroke=0)
        c.setFillColor(colors.HexColor('#245c7a')); c.setFont(FONT_BOLD,10); c.drawCentredString(x+cardw/2,y+16*mm,lab)
        c.setFillColor(colors.HexColor('#10233f')); c.setFont(FONT_BOLD,20); c.drawCentredString(x+cardw/2,y+5*mm,val)
    # left: network; right: results
    if (OUT/'poster_network.png').exists(): c.drawImage(str(OUT/'poster_network.png'),18*mm,22*mm,width=210*mm,height=143*mm,preserveAspectRatio=True,anchor='c',mask='auto')
    rx=238*mm; rw=W-rx-18*mm
    c.setFillColor(colors.HexColor('#10233f')); c.setFont(FONT_BOLD,17); c.drawString(rx,H-96*mm,'Ana bulgular')
    c.setFillColor(colors.HexColor('#24364b')); c.setFont(FONT,12)
    lines=[f"Yoğunluk: {metrics['density']:.5f}",f"Ortalama kümelenme: {metrics['average_clustering_coefficient']:.3f}",f"Ortalama yol tahmini (ana bileşen): {metrics['average_shortest_path_largest_component']:.3f}",f"Örneklem çapı alt sınırı: {metrics['diameter_largest_component']}",f"Derece benzeşimi: {metrics['degree_assortativity']:.3f}" if metrics['degree_assortativity'] is not None else 'Derece benzeşimi: hesaplanamadı']
    yy=H-107*mm
    for line in lines: c.drawString(rx,yy,line); yy-=8*mm
    c.setFont(FONT_BOLD,15); c.drawString(rx,yy-3*mm,'Kişisel ileri yöntem'); yy-=13*mm
    c.setFont(FONT,11)
    for line in ['3 saatlik kayan pencereler','Pencereler arası topluluk NMI','Köprü hashtag adayları için','yaklaşık betweenness']:
        c.drawString(rx,yy,line); yy-=7*mm
    good_nmi=[r['nmi'] for r in nmis if r.get('nmi') is not None]
    c.setFont(FONT_BOLD,12); c.drawString(rx,yy-2*mm,('Ortalama ardışık NMI: %.3f'%float(np.mean(good_nmi))) if good_nmi else 'Ardışık NMI hesaplanamadı'); yy-=9*mm
    bridges=centrality_df.sort_values('betweenness_approx',ascending=False)['hashtag'].head(3).tolist() if centrality_df is not None and len(centrality_df) else []
    c.setFont(FONT_BOLD,12); c.drawString(rx,yy-2*mm,'Köprü adayları'); yy-=7*mm
    c.setFont(FONT,10)
    for tag in bridges:
        c.drawString(rx,yy,tag[:42]); yy-=6*mm
    c.setFont(FONT_BOLD,15); c.drawString(rx,yy-3*mm,'Yöntem'); yy-=10*mm
    c.setFont(FONT,10)
    c.drawString(rx,yy,'Düğüm = hashtag; kenar = aynı gönderide'); yy-=7*mm
    c.drawString(rx,yy,'birlikte geçen hashtag çifti; ağırlık ='); yy-=7*mm
    c.drawString(rx,yy,'birlikte geçme sayısı. Metin ve hesap kimliği'); yy-=7*mm
    c.drawString(rx,yy,'kalıcı olarak saklanmamıştır.')
    c.setFillColor(colors.HexColor('#61748b')); c.setFont(FONT,8); c.drawString(18*mm,10*mm,'Not: Ağ görünümü, okunabilirlik için en büyük bileşenden seçilen yüksek dereceli 140 düğümle sınırlandırılmıştır. Tam ağ GraphML dosyasında.')
    c.save()


def build_slides(metrics, cent, community_summary, stability, null_summary, temporal, nmis, powerlaw, leiden_status, sourcefile):
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
    W,H=13.333*72,7.5*72
    slide_pdf=DELIVER/'2516016026_METEHAN_GEZER_Sunum.pdf'
    c=canvas.Canvas(str(slide_pdf),pagesize=(W,H))
    FONT, FONT_BOLD = register_pdf_fonts()
    navy=colors.HexColor('#112640'); teal=colors.HexColor('#147d92'); light=colors.HexColor('#edf3f8'); gray=colors.HexColor('#52657d')
    ppt=Presentation(); ppt.slide_width=Inches(13.333); ppt.slide_height=Inches(7.5)
    blank=ppt.slide_layouts[6]
    def slide_content(title,subtitle,bullets=None,imgpath=None,foot='Metehan Gezer | 2516016026 · Sosyal Ağ Analizi'):
        # PDF
        c.setFillColor(light); c.rect(0,0,W,H,fill=1,stroke=0); c.setFillColor(navy); c.rect(0,H-100,W,100,fill=1,stroke=0)
        c.setFillColor(colors.white); c.setFont(FONT_BOLD,24); c.drawString(40,H-48,title[:110])
        c.setFont(FONT,12); c.drawString(40,H-74,subtitle[:150])
        text_x=48; y=H-140
        for b in (bullets or []):
            if y<45: break
            c.setFillColor(teal); c.circle(text_x,y+4,3,fill=1,stroke=0)
            c.setFillColor(navy); c.setFont(FONT,14)
            wrap_width = 43 if imgpath and Path(imgpath).exists() else 100
            lines=textwrap.wrap(str(b),width=wrap_width)
            for li,line in enumerate(lines[:3]): c.drawString(text_x+14,y-17*li,line)
            y-=max(38,18*len(lines)+12)
        if imgpath and Path(imgpath).exists():
            c.drawImage(str(imgpath),W*.52,45,width=W*.43,height=H*.56,preserveAspectRatio=True,anchor='c',mask='auto')
        c.setStrokeColor(colors.HexColor('#cbd5e1')); c.line(40,34,W-40,34)
        c.setFillColor(gray); c.setFont(FONT,8); c.drawString(40,19,foot); c.drawRightString(W-40,19,f'{c.getPageNumber()}/10'); c.showPage()
        # PPTX
        s=ppt.slides.add_slide(blank)
        bg=s.background.fill; bg.solid(); bg.fore_color.rgb=RGBColor(237,243,248)
        shape=s.shapes.add_shape(MSO_SHAPE.RECTANGLE,0,0,ppt.slide_width,Inches(1.05)); shape.fill.solid(); shape.fill.fore_color.rgb=RGBColor(17,38,64); shape.line.fill.background()
        tb=s.shapes.add_textbox(Inches(.55), Inches(.20), Inches(12.2), Inches(.42)); tf=tb.text_frame; tf.text=title; tf.paragraphs[0].font.name='Aptos Display'; tf.paragraphs[0].font.size=Pt(24); tf.paragraphs[0].font.bold=True; tf.paragraphs[0].font.color.rgb=RGBColor(255,255,255)
        st=s.shapes.add_textbox(Inches(.58), Inches(.67), Inches(12.0), Inches(.25)); st.text_frame.text=subtitle; st.text_frame.paragraphs[0].font.size=Pt(10); st.text_frame.paragraphs[0].font.color.rgb=RGBColor(216,228,241)
        tb=s.shapes.add_textbox(Inches(.65), Inches(1.4), Inches(6.0), Inches(5.2)); tf=tb.text_frame; tf.word_wrap=True
        for i,b in enumerate((bullets or [])):
            p=tf.paragraphs[0] if i==0 else tf.add_paragraph(); p.text=str(b); p.level=0; p.font.name='Aptos'; p.font.size=Pt(18 if len(b)<90 else 15); p.font.color.rgb=RGBColor(17,38,64); p.space_after=Pt(14); p.bullet=True
        if imgpath and Path(imgpath).exists(): s.shapes.add_picture(str(imgpath), Inches(6.7), Inches(1.45), width=Inches(6.1), height=Inches(4.95))
        footb=s.shapes.add_textbox(Inches(.55), Inches(7.14), Inches(12.2), Inches(.2)); footb.text_frame.text=foot; footb.text_frame.paragraphs[0].font.size=Pt(8); footb.text_frame.paragraphs[0].font.color.rgb=RGBColor(82,101,125)
    top=cent.sort_values('degree',ascending=False).head(10)
    lead=[f"{metrics['nodes']:,} hashtag düğümü ve {metrics['edges']:,} birlikte-kullanım bağlantısı oluşturuldu.",f"48 saatlik arşiv örnekleminde {metrics['input_posts_with_hashtags']:,} hashtag'li gönderi analiz edildi."]
    slide_content('48 saatlik örneklem 7 binden fazla hashtag düğümü üretti','Sosyal Medyada Hashtag Ağı | BVA Büyük Veri Analistliği',lead,OUT/'poster_network.png')
    slide_content('Hashtag ortak-kullanımı yönsüz ve ağırlıklı bir ağ olarak modellendi','Düğüm = hashtag; kenar = aynı gönderide birlikte geçiş',[f"Kenar ağırlığı, hashtag çiftinin kaç gönderide birlikte geçtiğini sayar.",f"Kullanıcı kimliği ve gönderi metni kalıcı olarak kaydedilmedi.",f"CSV'deki UTC zaman damgası, üç saatlik pencerelere ayırmayı sağlar."],None)
    slide_content(f"Ağın yoğunluğu {metrics['density']:.5f}; en büyük bileşen {metrics['largest_component_nodes']:,} düğüm içeriyor",'Temel ağ ölçüleri',[
        f"Toplam {metrics['connected_components']:,} bağlı bileşen var.",f"En büyük bileşende örneklemeli ortalama yol {metrics['average_shortest_path_largest_component']:.3f}; örneklem çapı alt sınırı {metrics['diameter_largest_component']}.",f"Ortalama kümelenme katsayısı {metrics['average_clustering_coefficient']:.3f}."] ,OUT/'degree_distribution.png')
    slide_content('Derece ve köprü ölçüleri farklı türden görünürlüğü yakalar','Merkeziyetler',[
        'Derece doğrudan komşu sayısını ölçer.', 'Betweenness en kısa yollar üzerinden köprü olma rolünü yaklaşık ölçer.', 'Closeness en büyük bileşende 100 örnek kaynağın uzaklıklarıyla yaklaşık hesaplanmıştır; PageRank ağırlıklı ağda hesaplanmıştır.'],OUT/'bridge_hashtags.png')
    named_communities = [f"Topluluk {c['community']}: {c.get('topic_label') or 'etiket içeriklerinden adlandırılacak'} ({', '.join(c['top_hashtags'][:3])})" for c in community_summary['summary'][:3]]
    slide_content('Louvain toplulukları hashtag kümelerini ayırıyor','Ağırlıklı modülerlik ile topluluk tespiti',[
        f"Louvain topluluk sayısı: {len(community_summary['louvain'])}.", *named_communities, 'Adlar en sık görülen hashtag’ler incelenerek verilmiştir; topluluk içeriği karma olabilir.'],OUT/'community_sizes.png')
    if leiden_status.get('status')=='ok':
        leidenbul=[f"Leiden topluluk sayısı: {leiden_status.get('community_count')}.",f"Leiden ortalama ağırlıklı modülerliği: {leiden_status.get('mean_modularity',leiden_status.get('modularity',0)):.4f}.",'Louvain ve Leiden farklı optimizasyon yolları kullanır; toplulukları NMI ve modülerlik üzerinden kıyaslamak gerekir.']
    else: leidenbul=['Leiden paketi yüklenemediyse bu karşılaştırma eksik kalır.','`pip install igraph leidenalg` ardından analiz yeniden çalıştırılmalıdır.','Louvain tek başına iki algoritma şartını karşılamaz.']
    slide_content('Leiden sonucu Louvain ile ikinci bir topluluk perspektifi sağlar','İki algoritmanın karşılaştırılması',leidenbul,OUT/'community_sizes.png')
    stab_b=[]
    for name,info in stability.items():
        if info.get('status')=='ok': stab_b.append(f"{name}: 10 tohumdaki ortalama çiftli NMI {info['mean_pairwise_nmi']:.3f}.")
        else: stab_b.append(f"{name}: kararlılık hesaplanamadı.")
    stab_b.append('NMI=1 aynı bölümlenme; NMI düşükse tohum değişiminde topluluk atamaları daha fazla değişiyor.')
    slide_content('10 tohum, topluluk çözümünün rastgeleliğe duyarlılığını ölçüyor','Kararlılık analizi',stab_b,None)
    null_b=[]
    for key,label in [('clustering','Kümelenme'),('average_path_sampled','Ortalama yol'),('louvain_modularity_unweighted','Modülerlik')]:
        v=null_summary.get(key,{})
        zval=v.get('z_score')
        ztext=f'{float(zval):.3f}' if zval is not None and np.isfinite(float(zval)) else 'hesaplanamadı'
        null_b.append(f"{label}: gözlenen={v.get('observed',float('nan')):.4f}, null ort.={v.get('null_mean',float('nan')):.4f}, z={ztext}")
    null_b.append(f"{null_summary.get('model_count',0)} configuration-model ağı; aynı derece dizisi ilkesi, self-loop ve çoklu kenarlar sonradan kaldırıldı.")
    slide_content('Kümelenme ve modülerlik null modele göre yüksek','Configuration model karşılaştırması',null_b,OUT/'null_model_distributions.png')
    tv=[r['nmi'] for r in nmis if r.get('nmi') is not None]
    tbul=[f"3 saatlik, 1 saat adımlı kayan pencere sayısı: {len(temporal)}.",f"Geçerli ardışık NMI ortalaması: {np.mean(tv):.3f}." if tv else 'Geçerli ardışık NMI çifti bulunamadı.', 'Pencereler 1 saat adımla örtüşür; NMI ortak hashtaglerin topluluk benzerliğini ölçer.', 'En yüksek betweenness değerli hashtagler topluluklar arasında olası köprülerdir.']
    slide_content('Üç saatlik pencerelerde NMI, topluluk kararlılığını izliyor','Kişisel ileri yöntem: zamansal ağ',tbul,OUT/'temporal_nmi.png')
    slide_content('Sonuçlar örneklem penceresi ve yöntem sınırları içinde yorumlanmalı','Araştırma sorusuna yanıt ve sınırlılıklar',[
        'Birlikte hashtag kullanımı gerçek kullanıcı etkisini ya da nedenselliği kanıtlamaz.', '48 saatlik Bluesky örneklemi tüm sosyal medyayı veya nüfusu temsil etmez.', 'Etkileşimli ağdaki alt ağ performans için filtrelenmiştir; tam GraphML ayrıca teslim edilir.', 'CV: Akış verisinden zamansal ağ analizi.'],None)
    ppt.save(DELIVER/'2516016026_METEHAN_GEZER_Sunum.pptx')
    c.save()


def make_poster_metadata(metrics, source_file, stability, null_summary, temporal, nmis, powerlaw, leiden_status):
    summary={'metrics':metrics,'source_file':str(source_file),'analysis_timestamp_utc':pd.Timestamp.now(tz='UTC').isoformat(),
             'stability':stability,'null_model_summary':null_summary,'temporal_windows':temporal,'temporal_nmi':nmis,'powerlaw':powerlaw,'leiden':leiden_status}
    (OUT/'final_results_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')


def main():
    global posts_global
    ap=argparse.ArgumentParser()
    ap.add_argument('--null-models',type=int,default=100,help='Number of degree-sequence null graphs; assignment asks for at least 100.')
    ap.add_argument('--seeds',type=int,default=10,help='Number of random seeds for community stability; assignment asks for 10.')
    args=ap.parse_args()
    DATA_DIR.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True); DELIVER.mkdir(exist_ok=True)
    source=get_input_file(); posts_global=load_posts(source)
    log(f'Input: {source} ({len(posts_global):,} hashtag-bearing posts)')
    g=graph_from_posts(posts_global)
    if g.number_of_nodes()<500: raise SystemExit(f'Only {g.number_of_nodes()} nodes; expected at least 500. Check input file.')
    # Write reproducible edge list and GraphML from the final input.
    pd.DataFrame([{'source':u,'target':v,'weight':int(d.get('weight',1))} for u,v,d in g.edges(data=True)]).to_csv(OUT/'edges.csv',index=False,encoding='utf-8-sig')
    nx.write_graphml(g,OUT/'hashtags.graphml')
    metrics=graph_metrics(g); (OUT/'basic_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    nodes=list(g.nodes())
    # Louvain 10 seeds and pairwise stability.
    log(f'Running Louvain for {args.seeds} random seeds...')
    lou_parts=[]; lou_mods=[]
    for s in range(args.seeds):
        cs=communities_louvain(g,seed=SEED+s,weighted=True); lou_parts.append(cs)
        lou_mods.append(float(nx.community.modularity(g,cs,weight='weight')))
        if (s+1)%5==0: log(f'Louvain seeds: {s+1}/{args.seeds}')
    lou_nmi=[]
    for i in range(len(lou_parts)):
        for j in range(i+1,len(lou_parts)):
            lou_nmi.append(float(normalized_mutual_info_score(partition_labels(nodes,lou_parts[i]),partition_labels(nodes,lou_parts[j]))))
    stability={'Louvain':{'status':'ok','runs':args.seeds,'mean_pairwise_nmi':float(np.mean(lou_nmi)) if lou_nmi else 1.0,
                          'min_pairwise_nmi':float(np.min(lou_nmi)) if lou_nmi else 1.0,'max_pairwise_nmi':float(np.max(lou_nmi)) if lou_nmi else 1.0,
                          'mean_modularity':float(np.mean(lou_mods)),'std_modularity':float(np.std(lou_mods,ddof=1)) if len(lou_mods)>1 else 0.0}}
    base_louv=lou_parts[0]; louv_map={n:i for i,c in enumerate(base_louv) for n in c}
    louv_rows=[{'hashtag':n,'community':louv_map.get(n,-1),'degree':int(g.degree(n)),'post_count':int(g.nodes[n].get('post_count',0))} for n in nodes]
    save_csv(louv_rows,OUT/'louvain_communities.csv')
    # Leiden 10 seeds; continue if optional dependency isn't available but surface a clear deficit.
    leiden_status={'status':'unavailable','error':'igraph/leidenalg not installed'}; lei_parts=[]; lei_nmi=[]; lei_qualities=[]
    try:
        log(f'Running Leiden for {args.seeds} random seeds...')
        for s in range(args.seeds):
            cs,q=leiden_partition(g,seed=SEED+s); lei_parts.append(cs); lei_qualities.append(q)
            if (s+1)%5==0: log(f'Leiden seeds: {s+1}/{args.seeds}')
        for i in range(len(lei_parts)):
            for j in range(i+1,len(lei_parts)):
                lei_nmi.append(float(normalized_mutual_info_score(partition_labels(nodes,lei_parts[i]),partition_labels(nodes,lei_parts[j]))))
        lbase=lei_parts[0]; leimap={n:i for i,c in enumerate(lbase) for n in c}
        save_csv([{'hashtag':n,'community':leimap.get(n,-1),'degree':int(g.degree(n)),'post_count':int(g.nodes[n].get('post_count',0))} for n in nodes],OUT/'leiden_communities.csv')
        stability['Leiden']={'status':'ok','runs':args.seeds,'mean_pairwise_nmi':float(np.mean(lei_nmi)) if lei_nmi else 1.0,
                             'min_pairwise_nmi':float(np.min(lei_nmi)) if lei_nmi else 1.0,'max_pairwise_nmi':float(np.max(lei_nmi)) if lei_nmi else 1.0,
                             'mean_modularity':float(np.mean(lei_qualities)),'std_modularity':float(np.std(lei_qualities,ddof=1)) if len(lei_qualities)>1 else 0.0}
        leiden_status={'status':'ok','community_count':len(lbase),'modularity':float(lei_qualities[0]),'mean_modularity':float(np.mean(lei_qualities))}
    except Exception as e:
        stability['Leiden']={'status':'unavailable','error':str(e)}
        leiden_status={'status':'unavailable','error':str(e)}
        log('Leiden unavailable: '+str(e))
    (OUT/'community_stability.json').write_text(json.dumps(stability,ensure_ascii=False,indent=2),encoding='utf-8')
    # Community summaries are based on Louvain partition and actual node statistics.
    comm_summary=[]
    for cid,com in sorted(enumerate(base_louv),key=lambda t:len(t[1]),reverse=True):
        top=sorted(com,key=lambda n:(g.degree(n),g.nodes[n].get('post_count',0)),reverse=True)[:10]
        comm_summary.append({'community':cid,'nodes':len(com),'internal_edges':g.subgraph(com).number_of_edges(),'top_hashtags':top})
    save_csv([{'community':r['community'],'nodes':r['nodes'],'internal_edges':r['internal_edges'],'top_hashtags':' | '.join(r['top_hashtags'])} for r in comm_summary],OUT/'community_summary.csv')
    # Preserve manually reviewed topic labels when the same community ids recur on reruns.
    previous_labels={}
    label_file=OUT/'community_labeling_guide.csv'
    if label_file.exists():
        try:
            old_labels=pd.read_csv(label_file,encoding='utf-8-sig').fillna('')
            previous_labels={str(int(row['community'])):str(row.get('topic_name_to_review','')).strip() for _,row in old_labels.iterrows() if str(row.get('topic_name_to_review','')).strip()}
        except Exception:
            previous_labels={}
    save_csv([{'community':r['community'],'nodes':r['nodes'],'candidate_hashtags':' | '.join(r['top_hashtags'][:10]),'topic_name_to_review':previous_labels.get(str(r['community']), '')} for r in comm_summary[:5]],OUT/'community_labeling_guide.csv')
    centralities,corr,k=make_centralities(g,louv_map)
    # Global basic results, ranked list, power law comparisons.
    powerlaw=degree_powerlaw(g)
    temporal, nmis=build_temporal(posts_global,g)
    null_summary,null_rows=null_model(g,args.null_models)
    make_charts(g,metrics,centralities,base_louv,nmis,null_rows)
    make_interactive(g,louv_map,centralities)
    make_poster_metadata(metrics,source,stability,null_summary,temporal,nmis,powerlaw,leiden_status)
    summary={'louvain':base_louv,'summary':comm_summary}
    build_report(metrics,source,posts_global,centralities,summary,stability,null_summary,temporal,nmis,powerlaw,leiden_status,k)
    build_slides(metrics,centralities,summary,stability,null_summary,temporal,nmis,powerlaw,leiden_status,source)
    # Data dictionary and process log.
    save_csv([
        {'field_or_file':'timestamp_utc','meaning':'Gönderinin UTC zaman damgası','type':'ISO-8601 string','personal_data':'No','collection_window_or_source_terms':'48 saatlik arşiv penceresi; başlangıç/bitiş rapor kapağı ve final_results_summary.json içinde'},
        {'field_or_file':'hashtags','meaning':'Aynı gönderide geçen benzersiz hashtag listesi; | ile ayrılır','type':'Text list','personal_data':'No','collection_window_or_source_terms':'Bluesky Jetstream public archive; hizmet koşulları uygulanır; bireysel gönderi lisansı iddia edilmez'},
        {'field_or_file':'outputs/edges.csv: source,target','meaning':'Birlikte aynı gönderide geçen hashtag düğümleri','type':'Hashtag strings','personal_data':'No','collection_window_or_source_terms':'Türetilmiş analiz çıktısı; ham gönderi metni ve hesap kimliği içermez'},
        {'field_or_file':'outputs/edges.csv: weight','meaning':'Bu çiftin birlikte geçtiği gönderi sayısı','type':'Integer','personal_data':'No','collection_window_or_source_terms':'Eş-oluşum sayısı; ağırlıklı ve yönsüz kenar'},
    ],OUT/'data_dictionary.csv')
    # README final addendum with accurate results and next steps.
    readme=ROOT/'README.md'
    old=readme.read_text(encoding='utf-8') if readme.exists() else '# Sosyal Ağ Analizi\n'
    new='''# Sosyal Medyada Hashtag Ağı — Final Analiz\n\n**Öğrenci:** Metehan Gezer · **No:** 2516016026 · **Program:** Büyük Veri Analistliği\n\n## Araştırma sorusu\nGündem toplulukları saatler içinde ne kadar kararlıdır? Hangi hashtag’ler farklı gündem topluluklarını birbirine bağlamaktadır?\n\n## Veri modeli\n- Düğüm: normalize edilmiş hashtag.\n- Kenar: iki hashtag’in aynı gönderide beraber geçmesi; yönsüz.\n- Ağırlık: aynı ikilinin farklı gönderilerde birlikte geçme sayısı.\n- Gizlilik: kullanıcı kimlikleri ve ham gönderi metinleri kalıcı olarak kaydedilmez.\n\n## Temel bulgular\n- Gönderi: {posts:,}; düğüm: {nodes:,}; kenar: {edges:,}; yoğunluk: {density:.6f}.\n- Bağlı bileşen: {components:,}; en büyük bileşen: {largest:,}.\n- CV cümlesi: “Bluesky Jetstream arşivinden 48 saatlik Türkçe hashtag verisi derleyip NetworkX/igraph ile eş-oluşum ağı, merkeziyet, topluluk, null-model ve kayan-pencere kararlılık analizlerini tekrarlanabilir bir Python iş akışında uyguladım.”\n\n## Çalıştırma\n```bash\npython -m pip install -r requirements-final.txt\npython finalize_project.py --null-models 100 --seeds 10\n```\n\n## Üretilen çıktılar\n`outputs/` içinde kenar listesi, GraphML, temel ölçüler, merkeziyet, Louvain/Leiden bölümleri, kararlılık, null model, zamansal NMI, Powerlaw karşılaştırması ve grafikler bulunur. `deliverables/` içinde 6–10 sayfalık rapor PDF, A3 poster PDF, 8–10 slayt PDF/PPTX ve etkileşimli ağ HTML’i üretilir.\n\n## Yöntem/sınırlılıklar\nBetweenness, 500 kaynak düğümlü örneklemle yaklaşık hesaplanır; zaman penceresi NMI’sı yalnızca ardışık pencerelerde ortak olan düğümlerde hesaplanır. Null model configuration-model tabanlıdır; self-loop ve çoklu kenarlar sonradan kaldırılır. Ağ bağlantıları birlikte hashtag kullanımını temsil eder; kullanıcı etkisi ya da nedensellik göstermez.\n\n## Yapay zekâ beyanı\nKod geliştirme, hata ayıklama ve metin düzenlemede yapay zekâ araçlarından destek alınmıştır. Rapor ve sunum çıktıları üretilen analiz dosyalarıyla karşılaştırılarak proje sahibi tarafından doğrulanmalıdır.\n'''.format(posts=metrics['input_posts_with_hashtags'],nodes=metrics['nodes'],edges=metrics['edges'],density=metrics['density'],components=metrics['connected_components'],largest=metrics['largest_component_nodes'])
    if not readme.exists() or readme.stat().st_size < 100:
        readme.write_text(new,encoding='utf-8')
    else:
        log('Existing README.md preserved; review/update it separately if the analysis configuration changes.')
    log('DONE. Review outputs/ and deliverables/.')
    print(json.dumps({'metrics':metrics,'louvain_communities':len(base_louv),'leiden':leiden_status,'stability':stability,'null_model_z':{k:v.get('z_score') for k,v in null_summary.items() if isinstance(v,dict)},'temporal_windows':len(temporal),'valid_temporal_nmi_pairs':sum(r.get('nmi') is not None for r in nmis),'report':str(DELIVER/'2516016026_METEHAN_GEZER_Rapor.pdf'),'poster':str(DELIVER/'hashtag_network_poster_A3.pdf'),'slides_pdf':str(DELIVER/'2516016026_METEHAN_GEZER_Sunum.pdf'),'slides_pptx':str(DELIVER/'2516016026_METEHAN_GEZER_Sunum.pptx'),'interactive':str(DELIVER/'interactive_hashtag_network.html')},ensure_ascii=False,indent=2,default=str))

if __name__=='__main__':
    main()
