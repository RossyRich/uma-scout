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
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
VENUE_ORDER = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]

# WIN5: 各自信度で何頭まで流すか (◎◯▲△の順)
WIN5_PICKS = {"S": 1, "A": 2, "B": 3, "C": 4}


def win5_race_ids_from_netkeiba(date):
    """netkeibaのWIN5ページから対象レースIDを取得。当該日のものでなければNone"""
    try:
        url = "https://race.netkeiba.com/top/win5.html"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="replace")
        ids = []
        for i in re.findall(r"race_id=(\d{12})", html):
            if i not in ids:
                ids.append(i)
        ids = ids[:5]
        if len(ids) == 5 and all(i.startswith(date[:4]) for i in ids):
            # 対象レースが全て当日のレース群に含まれるか呼び出し側で照合する
            return ids
    except Exception:
        pass
    return None


def add_win5(out):
    """マージ済みデータにWIN5予想を追加する。
    対象レース: netkeibaのWIN5ページで当日分が確認できればそれ、
    なければ「各場の最終レースを除いた発走時刻の遅い5レース」(JRAの選定パターン)"""
    all_races = {}
    for v in out["venues"]:
        last_no = max((r["no"] for r in v["races"]), default=0)
        for r in v["races"]:
            all_races[r["race_id"]] = (v["name"], r, r["no"] == last_no)
    if len(all_races) < 5:
        return

    ids = win5_race_ids_from_netkeiba(out["date"])
    if ids and not all(i in all_races for i in ids):
        ids = None
    if not ids:
        cands = [rid for rid, (_, r, is_last) in all_races.items() if not is_last and r.get("time")]
        cands.sort(key=lambda rid: all_races[rid][1]["time"], reverse=True)
        ids = sorted(cands[:5], key=lambda rid: all_races[rid][1]["time"])
        if len(ids) < 5:
            return

    legs = []
    points = 1
    for rid in ids:
        venue, r, _ = all_races[rid]
        n = WIN5_PICKS.get(r.get("confidence", "B"), 3)
        picks = [{"num": m["num"], "name": m["name"]} for m in r.get("marks", [])[:n]]
        if not picks:
            return
        legs.append({
            "race_id": rid, "venue": venue, "no": r["no"], "name": r["name"],
            "time": r["time"], "confidence": r.get("confidence", "B"), "picks": picks,
        })
        points *= len(picks)
    out["win5"] = {"races": legs, "points": points}


def main():
    date = sys.argv[1]

    # --win5-only: 既存の予想ファイルにWIN5だけ追加し直す
    if "--win5-only" in sys.argv:
        path = os.path.join(BASE, "predictions", f"{date}.json")
        with open(path, encoding="utf-8") as f:
            out = json.load(f)
        add_win5(out)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        w5 = out.get("win5")
        if w5:
            print(f"WIN5追加: {[(l['venue'], l['no']) for l in w5['races']]} {w5['points']}点")
        else:
            print("WIN5は追加されませんでした")
        return

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

    add_win5(out)

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
