import xml.etree.ElementTree as ET
import csv
import re
import json
import difflib
from typing import List

def normalize_text(text: str) -> str:
    """Универсальная нормализация: lower, strip, remove punct (keep unicode letters/digits), squeeze spaces."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)  # Удаляем пунктуацию, оставляем буквы (вкл. кириллицу), цифры, _
    text = re.sub(r'\s+', ' ', text)  # Сжимаем пробелы
    return text

# Маппинг для wrong keyboard (latin keys to ru chars)
LAT_TO_RU_KEYMAP = {
    'a': 'ф', 'b': 'и', 'c': 'с', 'd': 'в', 'e': 'у', 'f': 'а', 'g': 'п', 'h': 'р', 'i': 'ш', 'j': 'о',
    'k': 'л', 'l': 'д', 'm': 'ь', 'n': 'т', 'o': 'щ', 'p': 'з', 'q': 'й', 'r': 'к', 's': 'ы', 't': 'е',
    'u': 'г', 'v': 'м', 'w': 'ц', 'x': 'ч', 'y': 'н', 'z': 'я', ';': 'ж', "'": 'э', ',': 'б', '.': 'ю',
    '/': '.', '[': 'х', ']': 'ъ', # Добавил распространённые
}

def lat_to_ru_keymap(text: str) -> str:
    """Translit latin to ru via keyboard map."""
    return ''.join(LAT_TO_RU_KEYMAP.get(c, c) for c in text)

def load_product_names(xml_path: str) -> List[str]:
    """Парсинг XML и извлечение уникальных имён продуктов (оригинальные, но нормализуем для поиска)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    names = set()
    for product in root.findall('.//product'):
        name_elem = product.find('name')
        if name_elem is not None and name_elem.text:
            original = name_elem.text.strip()
            if original:
                names.add(original)  # Храним оригинальные для вывода
    return sorted(list(names))  # Отсортированные оригинальные

def prefix_search(product_names: List[str], prefix: str) -> List[str]:
    """Префиксный поиск с variants: fuzzy, no-space, translit."""
    if not prefix:
        return []
    
    norm_prefix = normalize_text(prefix)
    norm_prefix_ns = norm_prefix.replace(' ', '')  # Без пробелов
    is_ascii = all(ord(c) < 128 for c in norm_prefix)  # Проверяем на ASCII (возможный wrong keyboard)
    translit_prefix = lat_to_ru_keymap(norm_prefix) if is_ascii else ''
    translit_prefix_ns = translit_prefix.replace(' ', '') if translit_prefix else ''
    
    results = set()  # Избегаем дубликатов
    threshold = 0.8  # Fuzzy threshold
    
    for original_name in product_names:
        norm_name = normalize_text(original_name)
        norm_name_ns = norm_name.replace(' ', '')
        
        prefix_len = len(norm_prefix)
        prefix_len_ns = len(norm_prefix_ns)
        
        # Strict/fuzzy startswith
        if norm_name.startswith(norm_prefix) or \
           difflib.SequenceMatcher(None, norm_name[:prefix_len], norm_prefix).ratio() >= threshold:
            results.add(original_name)
            continue
        
        # No-space variant
        if norm_name_ns.startswith(norm_prefix_ns) or \
           difflib.SequenceMatcher(None, norm_name_ns[:prefix_len_ns], norm_prefix_ns).ratio() >= threshold:
            results.add(original_name)
            continue
        
        # Translit variant
        if translit_prefix:
            translit_len = len(translit_prefix)
            if norm_name.startswith(translit_prefix) or \
               difflib.SequenceMatcher(None, norm_name[:translit_len], translit_prefix).ratio() >= threshold:
                results.add(original_name)
                continue
            
            translit_len_ns = len(translit_prefix_ns)
            if norm_name_ns.startswith(translit_prefix_ns) or \
               difflib.SequenceMatcher(None, norm_name_ns[:translit_len_ns], translit_prefix_ns).ratio() >= threshold:
                results.add(original_name)
    
    return sorted(list(results))  # Отсортированные оригинальные имена

if __name__ == '__main__':
    xml_path = 'data/catalog_products.xml'
    csv_path = 'data/prefix_queries.csv'
    
    product_names = load_product_names(xml_path)
    print(f"Loaded {len(product_names)} unique product names.")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            prefix = row['query']  # Изменено на 'query'
            results = prefix_search(product_names, prefix)
            print(f"Prefix '{prefix}': {results[:5]}...")  # Топ-5 для примера