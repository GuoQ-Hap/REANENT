from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pmc_agent.env import load_env_file
from pmc_agent.external_integrations.feishu_directory import (
    FeishuDirectoryClient,
    FeishuDirectoryConfig,
    FeishuDirectorySyncService,
    InMemoryCompanyDirectoryRepository,
    JsonlCompanyDirectoryRepository,
)


def main() -> None:
    load_env_file(override=False)
    parser = argparse.ArgumentParser(description="Sync Feishu directory departments and active employees.")
    parser.add_argument("--force", action="store_true", help="Run even when FEISHU_DIRECTORY_SYNC_ENABLED is false.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch data and print counts without writing JSONL files.")
    parser.add_argument("--root-department-id", default="", help="Root parent department ID. Defaults to FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID or 0.")
    parser.add_argument("--output-dir", default="", help="Directory for JSONL output. Defaults to FEISHU_DIRECTORY_OUTPUT_DIR.")
    args = parser.parse_args()

    config = FeishuDirectoryConfig.from_env()
    if args.force:
        config = replace(config, enabled=True)
    if args.root_department_id:
        config = replace(config, root_department_id=args.root_department_id)
    if args.output_dir:
        config = replace(config, output_dir=args.output_dir)
    if not config.ready:
        print("Feishu directory sync is disabled or missing FEISHU_APP_ID/FEISHU_APP_SECRET.")
        print("Set FEISHU_DIRECTORY_SYNC_ENABLED=true, or pass --force after credentials are configured.")
        raise SystemExit(2)

    repository = InMemoryCompanyDirectoryRepository() if args.dry_run else JsonlCompanyDirectoryRepository(config.output_dir)
    service = FeishuDirectorySyncService(
        client=FeishuDirectoryClient(config=config),
        repository=repository,
    )
    result = service.sync()
    print(f"Batch: {result.batch_id}")
    print(f"OK: {result.ok}")
    print(f"Departments: {result.department_count}")
    print(f"Employees: {result.employee_count}")
    print(f"Employee departments: {result.employee_department_count}")
    print(f"Inactive marked: {result.inactive_employee_count}")
    if result.errors:
        print("Errors:")
        for error in result.errors:
            print(f"- {error}")
    if not args.dry_run:
        print(f"Output: {Path(config.output_dir).resolve()}")


if __name__ == "__main__":
    main()
