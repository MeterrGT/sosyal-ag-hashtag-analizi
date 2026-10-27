#!/usr/bin/env python3
"""Build a hashtag co-occurrence graph and calculate initial network statistics."""
from __future__ import annotations

import csv
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd

INPUT = Path("data/posts_hashtags.csv")
OUT = Path("outputs")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    if not INPUT.exists():
        raise SystemExit(f"Input not found: {INPUT}. Run collect_hashtags.py first.")

    posts = pd.read_csv(INPUT).dropna(subset=["hashtags"])
    edge_weights: Counter[tuple[str, str]] = Counter()
    hashtag_counts: Counter[str] = Counter()
    usable_posts = 0

    for value in posts["hashtags"].astype(str):
        tags = sorted({f"#{t.strip().lstrip('#').casefold()}" for t in value.split("|") if t.strip()})
        hashtag_counts.update(tags)
        if len(tags) >= 2:
            usable_posts += 1
            for u, v in combinations(tags, 2):
                if u != v:
                    edge_weights[(u, v)] += 1

    graph = nx.Graph()
    for tag, count in hashtag_counts.items():
        graph.add_node(tag, post_count=int(count))
    for (u, v), weight in edge_weights.items():
        graph.add_edge(u, v, weight=int(weight))

    # Edge list is a portable CSV with one undirected edge per row.
    with (OUT / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source", "target", "weight"])
        writer.writeheader()
        for u, v, data in graph.edges(data=True):
            writer.writerow({"source": u, "target": v, "weight": data.get("weight", 1)})

    nx.write_graphml(graph, OUT / "hashtags.graphml")

    if graph.number_of_nodes() > 0:
        components = list(nx.connected_components(graph))
        largest_nodes = max(components, key=len)
        largest = graph.subgraph(largest_nodes).copy()
        avg_shortest_path = nx.average_shortest_path_length(largest) if largest.number_of_nodes() > 1 else 0.0
        diameter = nx.diameter(largest) if largest.number_of_nodes() > 1 else 0
        avg_clustering = nx.average_clustering(graph)
        try:
            assortativity = nx.degree_assortativity_coefficient(graph)
            if assortativity != assortativity:  # NaN
                assortativity = None
        except Exception:
            assortativity = None
    else:
        components, largest, avg_shortest_path, diameter, avg_clustering, assortativity = [], graph, None, None, None, None

    metrics = {
        "input_posts_with_hashtags": int(len(posts)),
        "posts_with_two_or_more_unique_hashtags": int(usable_posts),
        "nodes": int(graph.number_of_nodes()),
        "edges": int(graph.number_of_edges()),
        "density": float(nx.density(graph)) if graph.number_of_nodes() > 1 else 0.0,
        "connected_components": int(len(components)),
        "largest_component_nodes": int(largest.number_of_nodes()),
        "average_shortest_path_largest_component": avg_shortest_path,
        "diameter_largest_component": diameter,
        "average_clustering_coefficient": avg_clustering,
        "degree_assortativity": assortativity,
        "interpretation_note": "Paths and diameter are calculated on the largest connected component; justify this in the report.",
    }
    (OUT / "basic_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    top = sorted(graph.degree(weight=None), key=lambda item: item[1], reverse=True)[:10]
    pd.DataFrame(top, columns=["hashtag", "degree"]).to_csv(OUT / "top_degree.csv", index=False)

    degrees = [degree for _, degree in graph.degree() if degree > 0]
    if degrees:
        plt.figure(figsize=(7, 5))
        counts = Counter(degrees)
        xs = sorted(counts)
        ys = [counts[x] for x in xs]
        plt.scatter(xs, ys)
        plt.xscale("log")
        plt.yscale("log")
        plt.xlabel("Degree (log scale)")
        plt.ylabel("Number of hashtags (log scale)")
        plt.title("Hashtag Degree Distribution")
        plt.tight_layout()
        plt.savefig(OUT / "degree_distribution.png", dpi=200)
        plt.close()

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Wrote results to: {OUT.resolve()}")
    if graph.number_of_nodes() < 500:
        print("WARNING: fewer than 500 nodes so far; continue collecting and re-run analysis.")


if __name__ == "__main__":
    main()
