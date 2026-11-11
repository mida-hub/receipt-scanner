import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import shutil
import sys
import time
from typing import List, Tuple

from receipt_scanner.config import Config
from receipt_scanner.extractor import ReceiptExtractor
from receipt_scanner.models import PendingReceipt, ReceiptData
from receipt_scanner.sheets import SheetsClient

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

def find_receipt_images(inbox_dir: Path) -> List[Path]:
    """inbox フォルダ内の対応画像ファイルを収集"""
    files = []
    for item in inbox_dir.iterdir():
        if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(item)
    return sorted(files)

def find_pending_jsons(pending_dir: Path) -> List[Path]:
    """pending フォルダ内の未記帳JSONファイルを収集"""
    files = []
    for item in pending_dir.iterdir():
        if item.is_file() and item.suffix.lower() == ".json":
            files.append(item)
    return sorted(files)

def save_pending_receipt(data: ReceiptData, original_filename: str, pending_dir: Path) -> Path:
    """Gemini解析結果を pending/ ディレクトリにJSONとして保存"""
    pending_dir.mkdir(parents=True, exist_ok=True)
    target_path = pending_dir / f"{original_filename}.json"
    if target_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_path = pending_dir / f"{original_filename}_{timestamp}.json"

    record = PendingReceipt(filename=original_filename, data=data)
    target_path.write_text(
        record.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return target_path

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

def process_image_worker(
    extractor: ReceiptExtractor, img_path: Path
) -> Tuple[Path, ReceiptData | None, Exception | None]:
    """1枚のレシート画像を解析するワーカースレッド用関数"""
    try:
        data = extractor.extract_from_image(img_path)
        return (img_path, data, None)
    except Exception as e:
        return (img_path, None, e)

def main():
    parser = argparse.ArgumentParser(
        description="Receipt Scanner - Batch scan and export to Google Sheets"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel workers for Gemini API requests (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction without saving pending JSONs, writing to Google Sheets, or moving files",
    )
    args = parser.parse_args()

    Config.ensure_dirs()
    image_files = find_receipt_images(Config.INBOX_DIR)
    existing_pending = find_pending_jsons(Config.PENDING_DIR)

    if not image_files and not existing_pending:
        print(f"ℹ️  '{Config.INBOX_DIR}' に未処理の画像がなく、'{Config.PENDING_DIR}' にも未記帳データがありません。")
        print("   画像を配置してから再度実行してください。対応形式:", ", ".join(SUPPORTED_EXTENSIONS))
        sys.exit(0)

    start_time = time.perf_counter()

    # =========================================================================
    # Step 1: Gemini による画像解析 (inbox に画像がある場合)
    # =========================================================================
    if image_files:
        total_images = len(image_files)
        workers = min(args.workers, total_images)
        print(f"🚀 {total_images} 枚のレシート画像を検出しました。並列数 {workers} で解析を開始します...\n")

        extractor = ReceiptExtractor()
        success_count = 0
        failed_count = 0

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
                    success_count += 1
                    print(
                        f"[{completed_count}/{total_images}] ✅ 成功: {img_path.name} "
                        f"(店舗: {data.store_name}, 金額: {data.total_amount:,}円, 日付: {data.date}, カテゴリ: {data.category})"
                    )
                    if not args.dry_run:
                        # 解析結果を pending/ に保存し、元画像を archive/ へ移動
                        save_pending_receipt(data, img_path.name, Config.PENDING_DIR)
                        move_to_archive(img_path, Config.ARCHIVE_DIR)
                else:
                    failed_count += 1
                    print(f"[{completed_count}/{total_images}] ❌ 失敗: {img_path.name} -> {error}")
                    if not args.dry_run:
                        # 失敗画像を failed/ へ移動
                        move_to_failed(img_path, Config.FAILED_DIR)

        print("\n--------------------------------------------------")
        print(f"📊 解析完了: 成功 {success_count} 件 / 失敗 {failed_count} 件")
        if not args.dry_run:
            if success_count > 0:
                print(f"📦 成功した解析結果を '{Config.PENDING_DIR}' に保存し、元画像を '{Config.ARCHIVE_DIR}' へ移動しました。")
            if failed_count > 0:
                print(f"⚠️  解析失敗した画像を '{Config.FAILED_DIR}' へ移動しました。")
        print("--------------------------------------------------\n")
    else:
        print(f"ℹ️  '{Config.INBOX_DIR}' に新規画像はありません。未記帳データの書き込み処理へ進みます。\n")

    if args.dry_run:
        elapsed = time.perf_counter() - start_time
        print(f"🔍 [--dry-run モード] ファイル保存・移動およびスプレッドシートへの書き込みはスキップしました。 (所要時間: {elapsed:.2f}秒)")
        return

    # =========================================================================
    # Step 2: pending ディレクトリの結果を Google スプレッドシートへ一括書き込み
    # =========================================================================
    pending_files = find_pending_jsons(Config.PENDING_DIR)
    if not pending_files:
        elapsed = time.perf_counter() - start_time
        print(f"🎉 すべての処理が完了しました！（記帳対象データ 0 件 / 所要時間: {elapsed:.2f}秒）")
        return

    print(f"📝 '{Config.PENDING_DIR}' 内の {len(pending_files)} 件のデータを Google スプレッドシートに一括書き込み中...")

    records_to_write: List[Tuple[ReceiptData, str]] = []
    valid_json_paths: List[Path] = []

    for json_path in pending_files:
        try:
            record = PendingReceipt.model_validate_json(json_path.read_text(encoding="utf-8"))
            records_to_write.append((record.data, record.filename))
            valid_json_paths.append(json_path)
        except Exception as e:
            print(f"⚠️  '{json_path.name}' の読み込みに失敗しました（スキップします）: {e}")

    if records_to_write:
        try:
            sheets_client = SheetsClient()
            count = sheets_client.append_receipts(records_to_write)
            print(f"✅ スプレッドシートに {count} 行を正常に追記しました！")

            # 書き込み成功後に pending ファイルを削除
            for json_path in valid_json_paths:
                json_path.unlink(missing_ok=True)
            print(f"🗑️  書き込み完了した '{Config.PENDING_DIR}' 内の {len(valid_json_paths)} 件の一時ファイルを削除しました。")
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            print(f"\n❌ スプレッドシートへの書き込みに失敗しました (経過時間: {elapsed:.2f}秒): {e}")
            print(f"💡 解析済みデータは '{Config.PENDING_DIR}' に保持されています。次回実行時に再試行されます。")
            sys.exit(1)

    elapsed = time.perf_counter() - start_time
    print(f"\n🎉 すべての処理が完了しました！ (所要時間: {elapsed:.2f}秒)")

if __name__ == "__main__":
    main()
