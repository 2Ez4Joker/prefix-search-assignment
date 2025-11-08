#!/usr/bin/env python3
"""Evaluation script for prefix queries with Elasticsearch integration.

This script runs a hybrid prefix search on Elasticsearch and fills the evaluation CSV
with top-3 results, scores, latency, and judgements.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import time
import re
import json
from typing import List, Dict
from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer

# Columns for the output CSV
TEMPLATE_COLUMNS = [
    "query",
    "site",
    "type",
    "notes",
    "top_1",
    "top_1_score",
    "top_2",
    "top_2_score",
    "top_3",
    "top_3_score",
    "latency_ms",
    "judgement",
]

# Инициализация клиента ES и модели SBERT
# !!! ПРОВЕРЬТЕ АДРЕС ES !!!
es = Elasticsearch("http://localhost:9200") 
model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2') 

def normalize_text(text: str) -> str:
    """Универсальная нормализация."""
    text = text.lower().replace('ё', 'е').strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text

LAT_TO_RU_KEYMAP = {
    'a': 'ф', 'b': 'и', 'c': 'с', 'd': 'в', 'e': 'у', 'f': 'а', 'g': 'п', 'h': 'р', 'i': 'ш', 'j': 'о',
    'k': 'л', 'l': 'д', 'm': 'ь', 'n': 'т', 'o': 'щ', 'p': 'з', 'q': 'й', 'r': 'к', 's': 'ы', 't': 'е',
    'u': 'г', 'v': 'м', 'w': 'ц', 'x': 'ч', 'y': 'н', 'z': 'я', ';': 'ж', "'": 'э', ',': 'б', '.': 'ю',
    '/': '.', '[': 'х', ']': 'ъ',
}

RU_TO_LAT_KEYMAP = {v: k for k, v in LAT_TO_RU_KEYMAP.items() if v != k} 

def lat_to_ru_keymap(text: str) -> str:
    return ''.join(LAT_TO_RU_KEYMAP.get(c, c) for c in text)

def ru_to_lat_keymap(text: str) -> str:
    return ''.join(RU_TO_LAT_KEYMAP.get(c, c) for c in text)

def generate_translit_variants(text: str) -> List[str]:
    # Генерируем варианты, сохраняя исходный текст в списке
    lat_variant = ru_to_lat_keymap(text)
    ru_variant = lat_to_ru_keymap(text)
    return list(set([text, lat_variant, ru_variant]))

def extract_numeric_filter(query: str) -> Dict:
    """Извлечь numeric/weight из query для фильтра (e.g., '10л')."""
    match = re.search(r'(\d+)(л|кг|г|мл|шт)', query.lower())
    if match:
        # Используем match для поиска веса/объема с небольшим бустом
        return {"match": {"weight": {"query": match.group(0), "boost": 2}}}
    return {}

def search_es(original_query: str) -> tuple[List[dict], int, dict]:
    norm_query = normalize_text(original_query)
    variants = ' '.join(generate_translit_variants(norm_query))
    query_vector = model.encode(norm_query).tolist()
    
    # ВОССТАНОВЛЕНО: Определение numeric_filter для избежания NameError
    numeric_filter = extract_numeric_filter(original_query) 

    es_query = {
        # ИСПРАВЛЕНО: script_score обернут в основной "query"
        "query": {
            "script_score": {
                "query": {
                    "bool": {
                        # MUST для точных фильтров
                        "must": [numeric_filter] if numeric_filter else [], 
                        
                        # SHOULD для текстового поиска
                        "should": [
                            # A. Основной префиксный/fuzzy поиск
                            {"multi_match": {
                                "query": norm_query, 
                                "fields": ["name^3", "name_variants^2", "description"], 
                                "type": "bool_prefix", 
                                "fuzziness": "AUTO"
                            }},
                            # B. Транслитерация
                            {"multi_match": {
                                "query": variants, 
                                "fields": ["name_variants", "name"], 
                                "fuzziness": "AUTO"
                            }},
                            # C. Точное совпадение начала (дополнительный boost)
                            {"match_phrase_prefix": {"name": {"query": norm_query, "boost": 4}}},
                        ],
                        "minimum_should_match": 1
                    }
                },
                # D. Скрипт ранжирования (price decay)
                "script": {
                    "source": "decay_numeric_linear(params.origin, params.scale, params.offset, params.decay, doc['price'].value) + _score", 
                    "params": {"origin": 100, "scale": 50, "offset": 0, "decay": 0.999}
                }
            }
        },
        # KNN остается на верхнем уровне для гибридного поиска
        "knn": {"field": "vector", "query_vector": query_vector, "k": 20, "num_candidates": 100},
        
        "size": 10,
        "min_score": 0.5, 
        "_source": ["name", "category", "price", "weight"]
    }

    start_time = time.time()
    # !!! ПРОВЕРЬТЕ ИМЯ ИНДЕКСА: "products" !!!
    res = es.search(index="products", body=es_query) 
    latency_ms = int((time.time() - start_time) * 1000)
    hits = res['hits']['hits']

    # Simple RAG rerank: Boost exact prefix matches (добавляем boost в Python)
    for hit in hits:
        name = normalize_text(hit['_source']['name'])
        # Добавляем 1.0 к оценке, если название товара начинается с нормализованного запроса
        hit['_score'] += 1.0 if name.startswith(norm_query) else 0.0

    reranked = sorted(hits, key=lambda h: h['_score'], reverse=True)
    return reranked, latency_ms, es_query

def get_judgement(score: float) -> str:
    if score > 0.7: return "good"
    elif score >= 0.5: return "fair"
    else: return "bad"

def evaluate_and_fill(queries_path: Path, output_path: Path) -> None:
    total = success = precision_at_3 = 0
    logs = []

    with queries_path.open(newline="", encoding="utf-8") as src, output_path.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()

        for row in reader:
            total += 1
            query = row.get("query", "")
            results, latency_ms, es_q = search_es(query)
            top_results = results[:3]

            # Безопасное извлечение результатов
            top_1 = top_results[0]['_source']['name'] if len(top_results) > 0 else ""
            top_1_score = f"{top_results[0]['_score']:.2f}" if len(top_results) > 0 else ""
            top_2 = top_results[1]['_source']['name'] if len(top_results) > 1 else ""
            top_2_score = f"{top_results[1]['_score']:.2f}" if len(top_results) > 1 else ""
            top_3 = top_results[2]['_source']['name'] if len(top_results) > 2 else ""
            top_3_score = f"{top_results[2]['_score']:.2f}" if len(top_results) > 2 else ""

            # Безопасная конвертация float для judgement
            judgement = get_judgement(float(top_1_score) if top_1_score else 0.0)
            if len(results) > 0:
                success += 1
                # Precision@3: Count how many top-3 have score >0.7
                precision_at_3 += sum(1 for r in top_results if r['_score'] > 0.7) / 3

            # Логирование запроса ES
            logs.append(f"Original query: '{query}', Normalized: '{normalize_text(query)}', ES query: {json.dumps(es_q, ensure_ascii=False, indent=2)}, Results count: {len(results)}")

            writer.writerow({
                "query": query,
                "site": row.get("site"),
                "type": row.get("type"),
                "notes": row.get("notes"),
                "top_1": top_1,
                "top_1_score": top_1_score,
                "top_2": top_2,
                "top_2_score": top_2_score,
                "top_3": top_3,
                "top_3_score": top_3_score,
                "latency_ms": latency_ms,
                "judgement": judgement,
            })

    coverage = (success / total) * 100 if total > 0 else 0
    avg_precision_at_3 = (precision_at_3 / total) * 100 if total > 0 else 0
    print(f"Coverage: {coverage:.2f}% (queries with results)")
    print(f"Average Precision@3: {avg_precision_at_3:.2f}%")

    logs_dir = output_path.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    with open(logs_dir / "evaluation_logs.txt", 'w', encoding='utf-8') as f:
        f.write('\n'.join(logs))
    with open(logs_dir / "metrics.json", 'w', encoding='utf-8') as f:
        json.dump({'coverage': coverage, 'total': total, 'success': success, 'avg_precision_at_3': avg_precision_at_3}, f, ensure_ascii=False)

    print(f"Evaluation written to {output_path}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate prefix queries on Elasticsearch catalog")
    parser.add_argument("--queries", default="data/prefix_queries.csv", help="CSV with open/hidden queries")
    parser.add_argument("--output", default="reports/evaluation_template.csv", help="Where to store the evaluation")
    args = parser.parse_args()

    queries_path = Path(args.queries)
    if not queries_path.exists():
        raise SystemExit(f"Queries file not found: {queries_path}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    evaluate_and_fill(queries_path, output_path)

if __name__ == "__main__":
    main()