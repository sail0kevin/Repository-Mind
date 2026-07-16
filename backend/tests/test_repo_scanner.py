"""验证仓库扫描器对文本属性、测试文件和索引边界的判断。"""
from pathlib import Path

from service.core.repo_scanner import scan_repository_files
from service.storage.chunk_store import list_indexable_file_records
from service.storage.repository_store import create_repo_record, replace_file_records


def test_scan_repository_files_records_correct_metadata(mixed_repository: Path) -> None:
    """混合仓库中的每种文件都应获得真实且一致的扫描元数据。"""
    records = {
        item["relative_path"]: item
        for item in scan_repository_files(mixed_repository)
    }

    assert "node_modules/ignored.js" not in records
    assert records["src/app.py"]["line_count"] == 2
    assert records["empty.txt"]["line_count"] == 0
    assert records["utf16.txt"]["line_count"] == 2
    assert records["utf16.txt"]["is_binary"] is False

    assert records["tests/test_app.py"]["is_test_file"] is True
    assert records["widget.spec.ts"]["is_test_file"] is True
    assert records["src/app.py"]["is_test_file"] is False

    assert records["assets/logo.png"]["is_binary"] is True
    assert records["assets/logo.png"]["ignored_reason"] == "binary"
    assert records["assets/logo.png"]["parse_status"] == "skipped"
    assert records["notes.custom"]["ignored_reason"] == "unsupported_file_type"
    assert records["notes.custom"]["line_count"] is None
    assert records["src/app.py"]["file_type"] == "text"
    assert records["src/app.py"]["parse_status"] == "pending"


def test_indexable_query_reuses_scanner_decision(mixed_repository: Path) -> None:
    """存储层只能返回扫描器已经认定为可读取文本的文件。"""
    repo_id = create_repo_record(mixed_repository, alias="fixture")
    replace_file_records(repo_id, scan_repository_files(mixed_repository))

    indexable_paths = {
        item["relative_path"]
        for item in list_indexable_file_records(repo_id)
    }

    assert "src/app.py" in indexable_paths
    assert "README.md" in indexable_paths
    assert "utf16.txt" in indexable_paths
    assert "assets/logo.png" not in indexable_paths
    assert "notes.custom" not in indexable_paths
