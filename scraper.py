#!/usr/bin/env python3
"""
司法試験・予備試験 全年度データ スクレイパー
法務省サイトから問題・解答・出題趣旨・採点実感をダウンロードしてテキスト化する
"""

import os
import re
import time
import json
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pdfplumber

# ─── 設定 ────────────────────────────────────────────────────────────────────
BASE_URL = "https://www.moj.go.jp"
INDEX_URLS = {
    "yobi": "https://www.moj.go.jp/jinji/shihoushiken/jinji07_00026.html",
    "honshiken": "https://www.moj.go.jp/jinji/shihoushiken/jinji08_00025.html",
}
DATA_DIR = Path(__file__).parent / "data"
LOG_FILE = Path(__file__).parent / "scraper.log"

# ページ種別のキーワードマッピング
PAGE_TYPE_KEYWORDS = {
    "mondai": ["試験問題", "問題"],
    "seito": ["正答", "配点"],
    "shuppaitsushi": ["出題の趣旨", "出題趣旨"],
    "saitenjikkan": ["採点実感"],
    "iinkai": ["委員会決定"],
}

SLEEP_BETWEEN_REQUESTS = 1.5  # 法務省サーバへの負荷軽減

# ─── ロギング ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── ユーティリティ ───────────────────────────────────────────────────────────
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (research/bar-exam-archive)"})


def fetch_html(url):
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.error(f"HTML取得失敗: {url} → {e}")
        return None


def download_pdf(url, dest):
    if dest.exists():
        log.info(f"スキップ（既存）: {dest.name}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = session.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        log.info(f"ダウンロード完了: {dest}")
        time.sleep(SLEEP_BETWEEN_REQUESTS)
        return True
    except Exception as e:
        log.error(f"PDFダウンロード失敗: {url} → {e}")
        return False


def pdf_to_text(pdf_path):
    txt_path = pdf_path.with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8")
    text_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t:
                    text_parts.append(f"--- Page {i+1} ---\n{t}")
        text = "\n\n".join(text_parts)
        txt_path.write_text(text, encoding="utf-8")
        log.info(f"テキスト化完了: {txt_path.name} ({len(text)} chars)")
        return text
    except Exception as e:
        log.error(f"テキスト化失敗: {pdf_path} → {e}")
        return ""


def classify_page_type(text):
    for ptype, keywords in PAGE_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return ptype
    return "other"


def abs_url(href, base):
    if href.startswith("http"):
        return href
    return urljoin(base, href)


def is_moj_exam_link(href):
    return "moj.go.jp/jinji/shihoushiken/" in href


def normalize_year(text):
    """令和N年 / 平成N年 → reiwa_NN / heisei_NN"""
    text = text.strip()
    m = re.search(r"令和\s*(\d+|元)年", text)
    if m:
        n = 1 if m.group(1) == "元" else int(m.group(1))
        return f"reiwa_{n:02d}"
    m = re.search(r"平成\s*(\d+|元)年", text)
    if m:
        n = 1 if m.group(1) == "元" else int(m.group(1))
        return f"heisei_{n:02d}"
    return re.sub(r"\s+", "_", text)[:30]


# ─── スクレイプ本体 ───────────────────────────────────────────────────────────

def get_year_links(index_url):
    """インデックスページから年度別リンクを取得"""
    soup = fetch_html(index_url)
    if not soup:
        return []
    results = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not href or href.startswith("#"):
            continue
        full = abs_url(href, index_url)
        if not is_moj_exam_link(full):
            continue
        if re.search(r"(令和|平成)\s*(\d+|元)年", text):
            year_id = normalize_year(text)
            results.append({"year_id": year_id, "label": text, "url": full})
            log.info(f"年度リンク発見: {year_id} → {full}")
    return results


def get_subpages(year_url):
    """年度ページからサブページ（問題・趣旨・採点等）のリンクを取得"""
    soup = fetch_html(year_url)
    if not soup:
        return []
    results = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not href or href.startswith("#"):
            continue
        full = abs_url(href, year_url)
        if not is_moj_exam_link(full) or full in seen:
            continue
        # 年度インデックスリンクを除外
        if re.search(r"(令和|平成)\s*(\d+|元)年", text):
            continue
        ptype = classify_page_type(text)
        results.append({"label": text, "url": full, "page_type": ptype})
        seen.add(full)
    return results


def get_pdf_and_sub_links(page_url):
    """ページ内のPDFリンクと関連サブページリンクを取得"""
    soup = fetch_html(page_url)
    if not soup:
        return [], []
    pdf_links = []
    sub_links = []
    seen_pdfs = set()
    seen_subs = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not href:
            continue

        full = abs_url(href, page_url)

        if href.lower().endswith(".pdf") and full not in seen_pdfs:
            seen_pdfs.add(full)
            pdf_links.append({"label": text, "url": full})
        elif is_moj_exam_link(full) and full not in seen_subs:
            ptype = classify_page_type(text)
            if ptype in ("seito", "shuppaitsushi", "saitenjikkan"):
                seen_subs.add(full)
                sub_links.append({"label": text, "url": full, "page_type": ptype})

    return pdf_links, sub_links


def safe_filename(label, url):
    """PDF URLとラベルから安全なファイル名を生成"""
    pdf_id = Path(urlparse(url).path).stem
    safe_label = re.sub(r"[^\w]", "_", label, flags=re.ASCII)
    # 日本語をUnicodeとして保持しつつASCII制御文字のみ除去
    safe_label = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', "_", label)
    safe_label = safe_label[:50].strip("_")
    return f"{safe_label}_{pdf_id}.pdf"


def scrape_exam(exam_type, index_url):
    """指定試験種別の全年度データをスクレイプ"""
    log.info(f"=== {exam_type} スクレイプ開始 ===")
    year_links = get_year_links(index_url)
    log.info(f"{len(year_links)} 年度を発見")

    manifest = []

    for year_info in year_links:
        year_id = year_info["year_id"]
        year_url = year_info["url"]
        log.info(f"--- 年度: {year_id} ({year_url}) ---")

        subpages = get_subpages(year_url)
        time.sleep(SLEEP_BETWEEN_REQUESTS)

        year_manifest = {
            "year_id": year_id,
            "label": year_info["label"],
            "url": year_url,
            "files": [],
        }

        visited_subpages = set()

        def process_page(page_url, page_type, page_label):
            if page_url in visited_subpages:
                return
            visited_subpages.add(page_url)
            log.info(f"  サブページ処理: [{page_type}] {page_label} → {page_url}")

            pdf_links, extra_sub_links = get_pdf_and_sub_links(page_url)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

            for pdf_info in pdf_links:
                dest_dir = DATA_DIR / exam_type / year_id / page_type
                fname = safe_filename(pdf_info["label"], pdf_info["url"])
                dest = dest_dir / fname
                ok = download_pdf(pdf_info["url"], dest)
                if ok:
                    text = pdf_to_text(dest)
                    year_manifest["files"].append({
                        "page_type": page_type,
                        "page_label": page_label,
                        "pdf_url": pdf_info["url"],
                        "label": pdf_info["label"],
                        "local_path": str(dest.relative_to(DATA_DIR.parent)),
                        "text_chars": len(text),
                    })

            for sub in extra_sub_links:
                process_page(sub["url"], sub["page_type"], sub["label"])

        for sp in subpages:
            process_page(sp["url"], sp["page_type"], sp["label"])

        manifest.append(year_manifest)
        log.info(f"年度 {year_id}: {len(year_manifest['files'])} ファイル処理済み")

    return manifest


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    full_manifest = {}

    for exam_type, index_url in INDEX_URLS.items():
        manifest = scrape_exam(exam_type, index_url)
        full_manifest[exam_type] = manifest

    manifest_path = DATA_DIR.parent / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(full_manifest, f, ensure_ascii=False, indent=2)
    log.info(f"マニフェスト保存: {manifest_path}")

    for exam_type, years in full_manifest.items():
        total_files = sum(len(y["files"]) for y in years)
        log.info(f"{exam_type}: {len(years)} 年度, {total_files} ファイル")


if __name__ == "__main__":
    main()
