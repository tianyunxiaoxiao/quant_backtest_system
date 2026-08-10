"""数据摄取脚本: 把原始 CSV 和指数成分 Excel 转成 Parquet 仓库。"""

from pathlib import Path

from qbt.data.ingest_index import INDEX_SPECS, ingest_index_membership
from qbt.data.ingest_prices import IngestConfig, ingest_prices

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT.parent / "data_backup_before_511_merge"
INDEX_DIR = ROOT / "data" / "index_membership_source"
WAREHOUSE = ROOT / "warehouse"


def main():
    print("摄取个股行情...")
    price_cfg = IngestConfig(
        source_dir=SOURCE_DIR,
        output_dir=WAREHOUSE,
        start_date="2015-06-01",
        end_date="2026-04-07",
    )
    stats = ingest_prices(price_cfg)
    print(stats)

    print("摄取指数成分...")
    for index_id in INDEX_SPECS:
        monthly, index_stats = ingest_index_membership(
            INDEX_DIR, INDEX_SPECS[index_id], output_dir=WAREHOUSE
        )
        print(index_id, index_stats["snapshots"], "snapshots")

    print("完成。仓库:", WAREHOUSE)


if __name__ == "__main__":
    main()
