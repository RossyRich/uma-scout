#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウマスカウト 結果集計スクリプト
netkeibaの結果ページから着順・払戻を取得し、predictions/YYYYMMDD.json の
買い目と突き合わせて results/YYYYMMDD.json に保存する。

使い方:
  python3 results.py 20260718   # 指定日を集計
  python3 results.py --auto     # 未集計の過去日をまとめて集計(当日は17時以降のみ)
"""
import sys
import os
import re
import json
import glob
import time
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
JST = timezone(timedelta(hours=9))

# 券種: (netkeibaのtrクラス, 1組の頭数, 順序を問うか)
BET_TYPES = {
    "tansho": ("Tansho", 1, False),
    "umaren": ("Umaren", 2, False),
    "sanrenpuku": ("Fuku3", 3, False),
    "sanrentan": ("Tan3", 3, True),
}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_payouts(html):
    """{券種key: [(組(list), 配当円(int)), ...]} 同着で複数組があり得る"""
    out = {}
    for key, (cls, n, _) in BET_TYPES.items():
        m = re.search(r'<tr class="' + cls + r'">(.*?)</tr>', html, re.S)
        if not m:
            continue
        seg = m.group(1)
        res = re.search(r'class="Result"[^>]*>(.*?)</td>', seg, re.S)
        nums = [int(x) for x in re.findall(r"<span>(\d+)</span>", res.group(1))] if res else []
        pays = [int(p.replace(",", "")) for p in re.findall(r"([\d,]+)円", seg)]
        groups = [nums[i:i + n] for i in range(0, len(nums), n)]
        groups = [g for g in groups if len(g) == n]
        out[key] = list(zip(groups, pays))
    return out


def judge(bets, payouts):
    """予想の買い目と払戻を突き合わせ。{券種: {points, hit, payout}}"""
    res = {}
    for key, (_, n, ordered) in BET_TYPES.items():
        pts = bets.get(key, [])
        entry = {"points": len(pts), "hit": False, "payout": 0}
        for combo, pay in payouts.get(key, []):
            for p in pts:
                nums = [int(x) for x in re.findall(r"\d+", str(p))]
                if len(nums) != n:
                    continue
                if (nums == combo) if ordered else (set(nums) == set(combo)):
                    entry["hit"] = True
                    entry["payout"] += pay
                    break
        res[key] = entry
    return res


def collect(date):
    pred_path = os.path.join(BASE, "predictions", f"{date}.json")
    if not os.path.exists(pred_path):
        print(f"予想なし: {date}")
        return False
    pred = json.load(open(pred_path, encoding="utf-8"))
    races = []
    for v in pred["venues"]:
        for r in v["races"]:
            html = fetch(f"https://race.netkeiba.com/race/result.html?race_id={r['race_id']}")
            time.sleep(0.4)
            payouts = parse_payouts(html)
            if "sanrentan" not in payouts:
                print(f"  結果未確定: {v['name']}{r['no']}R → この日はスキップ")
                return False
            top3 = payouts["sanrentan"][0][0]
            nm = {h["num"]: h["name"] for h in r.get("horses", [])}
            hon = (r.get("marks") or [{}])[0]
            races.append({
                "race_id": r["race_id"],
                "venue": v["name"],
                "no": r["no"],
                "name": r["name"],
                "confidence": r.get("confidence", "B"),
                "top3": [{"num": x, "name": nm.get(x, "")} for x in top3],
                "honmei": {"num": hon.get("num"), "name": hon.get("name", ""),
                           "win": hon.get("num") == top3[0]},
                "bets": judge(r.get("bets", {}), payouts),
            })
            print(f"  {v['name']}{r['no']}R 1着:{top3[0]} " +
                  " ".join(k for k, e in races[-1]["bets"].items() if e["hit"]))
    out = {"date": date, "races": races}
    os.makedirs(os.path.join(BASE, "results"), exist_ok=True)
    with open(os.path.join(BASE, "results", f"{date}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    dates = sorted(
        [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(BASE, "results", "*.json"))
         if re.fullmatch(r"\d{8}", os.path.basename(p)[:-5])],
        reverse=True,
    )
    with open(os.path.join(BASE, "results", "index.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates}, f)
    print(f"保存: results/{date}.json ({len(races)}レース)")
    return True


def main():
    if "--auto" in sys.argv:
        now = datetime.now(JST)
        today = now.strftime("%Y%m%d")
        done = False
        for p in sorted(glob.glob(os.path.join(BASE, "predictions", "*.json"))):
            d = os.path.basename(p)[:-5]
            if not re.fullmatch(r"\d{8}", d):
                continue
            if os.path.exists(os.path.join(BASE, "results", f"{d}.json")):
                continue
            if d > today or (d == today and now.hour < 17):
                continue
            print(f"集計: {d}")
            done = collect(d) or done
        if not done:
            print("集計対象なし")
    else:
        collect(sys.argv[1])


if __name__ == "__main__":
    main()
