import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import shutil
import sys
from typing import List, Tuple

from receipt_scanner.config import Config
from receipt_scanner.extractor import ReceiptExtractor
from receipt_scanner.models import ReceiptData
from receipt_scanner.sheets import SheetsClient

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

def find_receipt_images(inbox_dir: Path) -> List[Path]:
    """inbox フォルダ内の対応画像ファイルを収集"""
    files = []
    for item in inbox_dir.iterdir():
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(item)
    return sorted(files)

def move_to_archive(file_path: Path, archive_dir: Path):
    """処理済み画像を archive/YYYY-MM/ へ移動"""
    month_folder = archive_dir / datetime.now().strftime("%Y-%m")
    month_folder.mkdir(parents=True, exist_ok=True)
    destination = month_folder / file_path.name
    if destination.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = month_folder / f"{file_path.stem}_{timestamp}{file_path.suffix}"
    shutil.move(str(file_path), str(destination))

def move_to_failed(file_path: Path, failed_dir: Path):
    """解析失敗画像を failed/ へ移動"""
    failed_dir.mkdir(parents=True, exist_ok=True)
    destination = failed_dir / file_path.name
    if destination.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = failed_dir / f"{file_path.stem}_{timestamp}{file_path.suffix}"
    shutil.move(str(file_path), str(destination))

def process_image_worker(extractor: ReceiptExtractor, img_path: Path) -> Tuple[Path, ReceiptData | None, Exception | None]:
    """1枚のレシート画像を解析するワーカースレッド用関数"""
    try:
        data = extractor.extract_from_image(img_path)
        return (img_path, data, None)
    except Exception as e:
        return (img_path, None, e)

def main():
    parser = argparse.ArgumentParser(description="Receipt Scanner - Batch scan and export to Google Sheets")
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel workers for Gemini API requests (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction without writing to Google Sheets or moving files",
    )
    args = parser.parse_args()

    Config.ensure_dirs()
    image_files = find_receipt_images(Config.INBOX_DIR)

    if not image_files:
        print(f"ℹ️  '{Config.INBOX_DIR}' に対象の画像ファイルが見つかりませんでした。")
        print("   画像を配置してから再度実行してください。対応形式:", ", ".join(SUPPORTED_EXTENSIONS))
        sys.exit(0)

    total_images = len(image_files)
    workers = min(args.workers, total_images)
    print(f"🚀 {total_images} 枚のレシート画像を検出しました。並列数 {workers} で解析を開始します...\n")

    extractor = ReceiptExtractor()
    successful_results: List[Tuple[ReceiptData, Path]] = []
    failed_files: List[Tuple[Path, Exception]] = []

    # スレッドプールによる並列処理
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_file = {
            executor.submit(process_image_worker, extractor, path): path
            for path in image_files
        }

        completed_count = 0
        for future in as_completed(future_to_file):
            completed_count += 1
            img_path, data, error = future.result()

            if error is None and data is not None:
                print(f"[{completed_count}/{total_images}] ✅ 成功: {img_path.name} "
                      f"(店舗: {data.store_name}, 金額: {data.total_amount:,}円, 日付: {data.date}, カテゴリ: {data.category})")
                successful_results.append((data, img_path))
            else:
                print(f"[{completed_count}/{total_images}] ❌ 失敗: {img_path.name} -> {error}")
                failed_files.append((img_path, error))

    print("\n--------------------------------------------------")
    print(f"📊 解析完了: 成功 {len(successful_results)} 件 / 失敗 {len(failed_files)} 件")
    print("--------------------------------------------------\n")

    if args.dry_run:
        print("🔍 [--dry-run モード] スプレッドシートへの書き込みおよびファイル移動はスキップしました。")
        return

    # スプレッドシートへの一括書き込み
    if successful_results:
        print("📝 Google スプレッドシートに一括書き込み中...")
        sheets_client = SheetsClient()
        sheets_payload = [(data, path.name) for data, path in successful_results]
        count = sheets_client.append_receipts(sheets_payload)
        print(f"✅ スプレッドシートに {count} 行を正常に追記しました！")

        # 処理完了画像のアーカイブ移動
        for _, path in successful_results:
            move_to_archive(path, Config.ARCHIVE_DIR)
        print(f"📦 処理済み画像を '{Config.ARCHIVE_DIR}' へ移動しました。")

    # 失敗ファイルの移動
    if failed_files:
        for path, _ in failed_files:
            move_to_failed(path, Config.FAILED_DIR)
        print(f"⚠️  解析失敗した画像を '{Config.FAILED_DIR}' へ移動しました。")

    print("\n🎉 すべての処理が完了しました！")

if __name__ == "__main__":
    main()
