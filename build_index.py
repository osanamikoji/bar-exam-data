#!/usr/bin/env python3
"""
ChromaDBへの全文インデックス構築スクリプト
日本語対応の多言語埋め込みモデルを使用
"""

import re
import json
import logging
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "bar_exam"
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

# チャンクサイズ（文字数）
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# ページ区切りパターン
PAGE_SEP = re.compile(r"--- Page \d+ ---\n?")

# doc_type の日本語マッピング
DOCTYPE_LABEL = {
    "mondai": "試験問題",
    "seito": "正答・配点",
    "shuppaitsushi": "出題の趣旨",
    "saitenjikkan": "採点実感",
    "iinkai": "委員会決定",
    "other": "その他",
}

EXAM_LABEL = {
    "yobi": "予備試験",
    "honshiken": "司法試験（本試験）",
}


def year_id_to_label(year_id: str) -> str:
    """reiwa_05 → 令和5年 など"""
    m = re.match(r"(reiwa|heisei)_(\d+)", year_id)
    if not m:
        return year_id
    era = "令和" if m.group(1) == "reiwa" else "平成"
    n = int(m.group(2))
    return f"{era}{n}年"


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    """テキストを重複ありチャンクに分割"""
    # ページ単位で分割してからチャンク化
    pages = PAGE_SEP.split(text)
    chunks = []
    for page in pages:
        page = page.strip()
        if not page:
            continue
        if len(page) <= chunk_size:
            chunks.append(page)
            continue
        # 長いページは滑りウィンドウで分割
        start = 0
        while start < len(page):
            end = start + chunk_size
            chunks.append(page[start:end])
            start += chunk_size - overlap
    return [c for c in chunks if len(c.strip()) >= 20]


def parse_path(txt_path: Path):
    """data/yobi/reiwa_05/mondai/憲法_001234.txt → メタデータ dict"""
    parts = txt_path.relative_to(DATA_DIR).parts
    # parts = (exam_type, year_id, doc_type, filename)
    if len(parts) < 4:
        return None
    exam_type, year_id, doc_type, fname = parts[0], parts[1], parts[2], parts[3]
    subject = re.sub(r"_\d+\.txt$", "", fname)
    return {
        "exam_type": exam_type,
        "exam_label": EXAM_LABEL.get(exam_type, exam_type),
        "year_id": year_id,
        "year_label": year_id_to_label(year_id),
        "doc_type": doc_type,
        "doc_label": DOCTYPE_LABEL.get(doc_type, doc_type),
        "subject": subject,
        "filename": fname,
        "source_path": str(txt_path.relative_to(DATA_DIR.parent)),
    }


def build_index():
    log.info(f"ChromaDB構築開始: {CHROMA_DIR}")
    CHROMA_DIR.mkdir(exist_ok=True)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # 既存コレクションを削除して再構築
    try:
        client.delete_collection(COLLECTION_NAME)
        log.info("既存コレクション削除")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    txt_files = sorted(DATA_DIR.rglob("*.txt"))
    log.info(f"{len(txt_files)} TXTファイルを処理")

    ids, documents, metadatas = [], [], []
    skipped = 0

    for txt_path in txt_files:
        meta = parse_path(txt_path)
        if meta is None:
            skipped += 1
            continue

        text = txt_path.read_text(encoding="utf-8").strip()
        if not text:
            skipped += 1
            continue

        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            doc_id = f"{meta['exam_type']}__{meta['year_id']}__{meta['doc_type']}__{meta['filename']}__{i}"
            ids.append(doc_id)
            documents.append(chunk)
            metadatas.append({**meta, "chunk_index": i, "chunk_total": len(chunks)})

        # バッチ追加（メモリ効率）
        if len(ids) >= 500:
            collection.add(ids=ids, documents=documents, metadatas=metadatas)
            log.info(f"  {collection.count()} チャンク登録済み...")
            ids, documents, metadatas = [], [], []

    if ids:
        collection.add(ids=ids, documents=documents, metadatas=metadatas)

    total = collection.count()
    log.info(f"インデックス完了: {total} チャンク ({skipped} ファイルスキップ)")
    return total


if __name__ == "__main__":
    build_index()
