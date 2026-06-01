#!/usr/bin/env python3
"""
司法試験・予備試験 ローカルRAG検索
ChromaDB + Claude API (claude-opus-4-8) による自然言語検索
"""

import os
import sys
import textwrap
from pathlib import Path

import anthropic
import chromadb
from chromadb.utils import embedding_functions

CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "bar_exam"
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

N_RESULTS = 12          # 検索で取得するチャンク数
MAX_CONTEXT_CHARS = 18000  # Claudeに渡す最大文字数

SYSTEM_PROMPT = """\
あなたは司法試験・予備試験の専門家アシスタントです。
法務省が公開した以下の資料（問題・解答・出題の趣旨・採点実感）のデータベースを参照して質問に答えます。

【回答の原則】
- 提供されたコンテキストに含まれる情報のみを根拠として回答する
- 年度・試験種別（予備試験 or 本試験）・科目を明示する
- コンテキストに情報がない場合は「この資料では確認できませんでした」と答える
- 必要に応じて複数年度を横断して比較する
- 出典（例:「令和5年予備試験 論文式 憲法 出題の趣旨」）を必ず記載する
"""


def get_collection():
    if not CHROMA_DIR.exists():
        print("エラー: インデックスが見つかりません。先に build_index.py を実行してください。")
        sys.exit(1)
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_collection(name=COLLECTION_NAME, embedding_function=ef)


def search_chunks(collection, query: str, n_results: int = N_RESULTS):
    """クエリに関連するチャンクを検索"""
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    return list(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ))


def format_context(chunks) -> str:
    """検索チャンクをClaudeへ渡すコンテキストにフォーマット"""
    parts = []
    total_chars = 0
    for doc, meta, dist in chunks:
        header = (
            f"[{meta['exam_label']} {meta['year_label']} {meta['doc_label']} {meta['subject']}]"
            f" (類似度: {1 - dist:.2f})"
        )
        entry = f"{header}\n{doc}"
        if total_chars + len(entry) > MAX_CONTEXT_CHARS:
            break
        parts.append(entry)
        total_chars += len(entry)
    return "\n\n---\n\n".join(parts)


def ask_claude(query: str, context: str) -> str:
    """Claude claude-opus-4-8 + プロンプトキャッシュで回答生成"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("エラー: ANTHROPIC_API_KEY が設定されていません。")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    user_content = f"""以下は司法試験・予備試験の資料から検索した関連箇所です。
この情報を参照して質問に答えてください。

=== 検索結果（関連資料） ===
{context}

=== 質問 ===
{query}"""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def print_sources(chunks):
    """ヒットした出典を表示"""
    seen = set()
    print("\n📚 参照した資料:")
    for _, meta, dist in chunks:
        key = (meta["exam_label"], meta["year_label"], meta["doc_label"], meta["subject"])
        if key not in seen:
            seen.add(key)
            sim = 1 - dist
            print(f"  • {meta['exam_label']} {meta['year_label']} {meta['doc_label']} {meta['subject']}  (類似度: {sim:.2f})")


def main():
    collection = get_collection()
    total = collection.count()
    print(f"✅ インデックス読み込み完了: {total:,} チャンク")
    print("💡 終了するには Ctrl+C または 'q' を入力\n")

    while True:
        try:
            query = input("🔍 質問> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if not query or query.lower() in ("q", "quit", "exit"):
            break

        print("  検索中...")
        chunks = search_chunks(collection, query)

        if not chunks:
            print("  関連する資料が見つかりませんでした。")
            continue

        context = format_context(chunks)
        print("  Claude が回答を生成中...")

        answer = ask_claude(query, context)
        print("\n" + "=" * 60)
        print(answer)
        print("=" * 60)
        print_sources(chunks)
        print()


if __name__ == "__main__":
    main()
