"""历史诊断脚本：检查 requests-location-v5 的 Session/Adapter 调用边。

脚本中的数据库路径已按隐私要求脱敏为占位符，复现时请替换为你自己的本地路径；仅用于保留当时的排障过程，不是当前 benchmark 入口。
"""
import sqlite3

DB = r"<benchmark-root>\requests-location-v1\repomind-data-v5\repomind.sqlite3"  # 已脱敏：复现时替换为你的本地数据库路径
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

snap = conn.execute("SELECT id FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
snapshot_id = snap["id"]

names = ["send", "get_adapter", "mount", "__enter__", "__exit__", "__init__"]
rows = conn.execute(
    "SELECT id, qualified_name, name, symbol_kind, start_line, end_line "
    "FROM symbols WHERE snapshot_id=? AND name IN (%s)" % ",".join("?" * len(names)),
    [snapshot_id, *names],
).fetchall()
by_name = {}
for r in rows:
    d = dict(r)
    if "sessions.py" not in "" and True:
        pass
    by_name.setdefault(r["name"], []).append(d)
    print(d)

print("---- ids of interest ----")
session_send = [r for r in rows if r["qualified_name"] == "src.requests.sessions.Session.send"]
http_send = [r for r in rows if r["qualified_name"] == "src.requests.adapters.HTTPAdapter.send"]
get_adapter = [r for r in rows if r["qualified_name"] == "src.requests.sessions.Session.get_adapter"]
session_init = [r for r in rows if r["qualified_name"] == "src.requests.sessions.Session.__init__"]
print("session.send", [dict(r) for r in session_send])
print("http.send", [dict(r) for r in http_send])
print("get_adapter", [dict(r) for r in get_adapter])
print("session.__init__", [dict(r) for r in session_init])

ids_of_interest = {r["id"] for r in session_send + http_send + get_adapter + session_init}
print("---- relations touching these ----")
rels = conn.execute(
    "SELECT * FROM relations WHERE snapshot_id=? AND relation_type='calls'", (snapshot_id,)
).fetchall()
for rel in rels:
    rel = dict(rel)
    if rel["source_symbol_id"] in ids_of_interest or rel["target_symbol_id"] in ids_of_interest:
        print(rel["source_symbol_id"][:20], "->", rel.get("target_ref"), "| resolved:", rel["resolver_status"], "observed:", rel["observed"], "line:", rel["line"])
