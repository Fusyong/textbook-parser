# -*- coding: utf-8 -*-
import json

d = json.load(open(r"d:/ah21/textbook-parser/output/2026-09-16/b11_写字表.json", encoding="utf-8"))
for i, r in enumerate(d["rows"]):
    u = r.get("unit") or {}
    chars = "".join(r.get("chars") or [])
    print(
        f"{i:02d} sec={r.get('section')!r:8} les={r.get('lesson')!r:4} "
        f"g={r.get('garden')!r:4} chars={chars!r:12} unit={u.get('label') if u else None!r}"
    )
print("---warnings---")
for w in d.get("toc_warnings") or []:
    print(w)
