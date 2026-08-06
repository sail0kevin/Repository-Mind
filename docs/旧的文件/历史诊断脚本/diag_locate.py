"""历史诊断脚本：检查 requests-location-v5 中特定符号的调用关系。

脚本中的数据库路径已按隐私要求脱敏为占位符，复现时请替换为你自己的本地路径；仅用于保留当时的排障过程，不是当前 benchmark 入口。
"""
import sqlite3, json, sys

DB = r"<benchmark-root>\requests-location-v1\repomind-data-v5\repomind.sqlite3"  # 已脱敏：复现时替换为你的本地数据库路径
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

snap = conn.execute("SELECT id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
snapshot_id = snap["id"]
print("snapshot_id", snapshot_id)

names = ["merge_environment_settings", "prepare_request", "request", "get_adapter", "mount", "send"]
rows = conn.execute(
    "SELECT id, qualified_name, name, symbol_kind, start_line, end_line, evidence_id "
    "FROM symbols WHERE snapshot_id=? AND name IN (%s)" % ",".join("?" * len(names)),
    [snapshot_id, *names],
).fetchall()
sym_by_name = {}
for r in rows:
    if "sessions.py" in (r["qualified_name"] or "") or True:
        print(dict(r))
    sym_by_name.setdefault(r["name"], []).append(dict(r))

print("---- relations calls involving merge_environment_settings / request ----")
target_ids = {r["id"] for r in rows if r["name"] == "merge_environment_settings"}
source_ids = {r["id"] for r in rows if r["name"] == "request"}
rels = conn.execute(
    "SELECT * FROM relations WHERE snapshot_id=? AND relation_type='calls'", (snapshot_id,)
).fetchall()
for rel in rels:
    rel = dict(rel)
    if rel["source_symbol_id"] in target_ids or rel["target_symbol_id"] in target_ids or rel["source_symbol_id"] in source_ids or rel["target_symbol_id"] in source_ids:
        print(rel)
