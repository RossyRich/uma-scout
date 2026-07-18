#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウマスカウト ビルドスクリプト
data/YYYYMMDD.json (レースデータ) と predictions/tmp_*.json (AI予想) をマージして
predictions/YYYYMMDD.json と predictions/index.json を生成する。

使い方: python3 build.py 20260719
"""
import sys
import os
import json
import glob
import re
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
VENUE_ORDER = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]


def main():
    date = sys.argv[1]
    with open(os.path.join(BASE, "data", f"{date}.json"), encoding="utf-8") as f:
        data = json.load(f)

    # 予想を race_id で引けるように
    preds = {}
    for p in glob.glob(os.path.join(BASE, "predictions", "tmp_*.json")):
        with open(p, encoding="utf-8") as f:
            pj = json.load(f)
        for r in pj.get("races", []):
            preds[r["race_id"]] = r

    jst = timezone(timedelta(hours=9))
    out = {
        "date": date,
        "updated": datetime.now(jst).strftime("%Y-%m-%d %H:%M"),
        "venues": [],
    }
    missing = []
    for v in sorted(data["venues"], key=lambda x: VENUE_ORDER.index(x["name"]) if x["name"] in VENUE_ORDER else 99):
        races = []
        for r in v["races"]:
            p = preds.get(r["race_id"])
            if not p:
                missing.append(r["race_id"])
                continue
            cond = r.get("cond", "")
            m = re.search(r"(新馬|未勝利|１勝クラス|２勝クラス|３勝クラス|オープン|G[123]|重賞)", r.get("name", "") + cond)
            races.append({
                "race_id": r["race_id"],
                "no": r["no"],
                "name": r["name"],
                "time": r["time"],
                "course": r["course"],
                "head": r["head"],
                "horses": [
                    {"num": h["num"], "waku": h.get("waku"), "name": h["name"],
                     "jockey": h.get("jockey", ""), "odds": h.get("odds"), "pop": h.get("pop")}
                    for h in r["horses"]
                ],
                "marks": p.get("marks", []),
                "summary": p.get("summary", ""),
                "confidence": p.get("confidence", "B"),
                "bets": p.get("bets", {}),
            })
        out["venues"].append({"name": v["name"], "races": races})

    os.makedirs(os.path.join(BASE, "predictions"), exist_ok=True)
    path = os.path.join(BASE, "predictions", f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # 日付インデックス更新 (新しい順)
    dates = sorted(
        [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(BASE, "predictions", "*.json"))
         if re.fullmatch(r"\d{8}", os.path.basename(p)[:-5])],
        reverse=True,
    )
    with open(os.path.join(BASE, "predictions", "index.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f)

    total = sum(len(v["races"]) for v in out["venues"])
    print(f"生成: {path} ({total}レース)")
    if missing:
        print(f"警告: 予想が見つからないレース: {missing}")
        sys.exit(2)


if __name__ == "__main__":
    main()
