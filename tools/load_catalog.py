#!/usr/bin/env python3
"""Quick helper to inspect and optionally index the synthetic catalog into Elasticsearch."""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from elasticsearch import Elasticsearch
from sentence_transformers import SentenceTransformer
import re

# Normalization and translit functions
def normalize_text(text: str) -> str:
    text = text.lower().replace('ё', 'е').strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text

LAT_TO_RU = {
    'a': 'ф', 'b': 'и', 'c': 'с', 'd': 'в', 'e': 'у', 'f': 'а', 'g': 'п', 'h': 'р', 'i': 'ш', 'j': 'о',
    'k': 'л', 'l': 'д', 'm': 'ь', 'n': 'т', 'o': 'щ', 'p': 'з', 'q': 'й', 'r': 'к', 's': 'ы', 't': 'е',
    'u': 'г', 'v': 'м', 'w': 'ц', 'x': 'ч', 'y': 'н', 'z': 'я'
}
RU_TO_LAT = {v: k for k, v in LAT_TO_RU.items()}

def generate_translit_variants(text: str) -> list:
    lat_variant = ''.join(RU_TO_LAT.get(c, c) for c in text if c.isalpha() or c.isdigit() or c == ' ')
    ru_variant = ''.join(LAT_TO_RU.get(c, c) for c in text if c.isalpha() or c.isdigit() or c == ' ')
    variants = set([text, lat_variant, ru_variant])
    return list(variants)

# Elasticsearch setup
es = Elasticsearch("http://localhost:9200")
model = SentenceTransformer('paraphrase-MiniLM-L6-v2')

def create_index():
    if es.indices.exists(index="products"):
        es.indices.delete(index="products")
    settings = {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "name": {"type": "text", "analyzer": "edge_ngram_analyzer", "search_analyzer": "standard"},
                "name_variants": {"type": "text", "analyzer": "edge_ngram_analyzer"},
                "description": {"type": "text"},
                "price": {"type": "float"},
                "category": {"type": "keyword"},
                "brand": {"type": "keyword"},
                "weight": {"type": "keyword"},  # e.g., "10л", "3 кг"
                "vector": {"type": "dense_vector", "dims": 384, "index": True, "similarity": "cosine"}
            }
        }
    }
    analyzers = {
        "analysis": {
            "analyzer": {"edge_ngram_analyzer": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase", "edge_ngram_filter"]}},
            "filter": {"edge_ngram_filter": {"type": "edge_ngram", "min_gram": 1, "max_gram": 20}}
        }
    }
    settings["settings"].update(analyzers)
    es.indices.create(index="products", body=settings)
    print("Created Elasticsearch index 'products'.")

def load_and_index(xml_path: str):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    bulk_data = []
    for product in root.findall('.//product'):
        doc = {
            "name": product.findtext('name', '').strip(),
            "description": product.findtext('description', '').strip(),
            "price": float(product.findtext('price', '0.0')),
            "category": product.findtext('category', ''),
            "brand": product.findtext('brand', ''),
            "weight": product.findtext('weight', '')
        }
        if not doc["name"]:
            continue
        norm_name = normalize_text(doc["name"])
        doc["name_variants"] = generate_translit_variants(norm_name)
        embedding_text = f"{norm_name} {doc['description']}"
        doc["vector"] = model.encode(embedding_text).tolist()
        bulk_data.append({"index": {"_index": "products"}})
        bulk_data.append(doc)
    if bulk_data:
        es.bulk(operations=bulk_data)
    print(f"Indexed {len(bulk_data)//2} products.")

def summarize_catalog(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    products = root.findall("product")
    categories = Counter(prod.findtext("category", default="unknown") for prod in products)
    brands = Counter(prod.findtext("brand", default="unknown") for prod in products)

    print(f"Loaded {len(products)} products from {path}")
    print("Top categories:")
    for category, count in categories.most_common(10):
        print(f"  • {category}: {count}")

    print("\nTop brands:")
    for brand, count in brands.most_common(10):
        print(f"  • {brand}: {count}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and optionally index catalog_products.xml to Elasticsearch")
    parser.add_argument("catalog", nargs="?", default="data/catalog_products.xml", help="Path to the XML catalog")
    parser.add_argument("--index", action="store_true", help="Index the catalog to Elasticsearch")
    args = parser.parse_args()

    path = Path(args.catalog)
    if not path.exists():
        raise SystemExit(f"Catalog not found: {path}")

    summarize_catalog(path)
    
    if args.index:
        create_index()
        load_and_index(args.catalog)

if __name__ == "__main__":
    main()