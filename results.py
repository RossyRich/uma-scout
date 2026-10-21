#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウマスカウト 結果集計スクリプト
netkeibaの結果ページから着順・払戻を取得し、predictions/YYYYMMDD.json の
買い目と突き合わせて results/YYYYMMDD.json に保存する。

使い方:
  python3 results.py 20260718   # 指定日を集計
  python3 results.py --auto     # 未集計の過去日をまとめて集計(当日は17時以降のみ)
  python3 results.py --live     # 当日の途中経過を results/live.json に書き出す
  python3 results.py --backfill-weighted  # 集計済みの結果に配分方式の払戻を追記
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
    "wide": ("Wide", 2, False),
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


# 配分方式(払戻をそろえる買い方)の計算に使う確定オッズ。netkeibaオッズAPIの種別番号
ODDS_TYPE = {"umaren": 4, "wide": 5, "sanrenpuku": 7, "sanrentan": 8}


def fetch_odds(race_id, key):
    """{"0102": オッズ(float), ...}。取消・除外(負の値)は含めない"""
    t = ODDS_TYPE[key]
    try:
        j = json.loads(fetch("https://race.netkeiba.com/api/api_get_jra_odds.html"
                             f"?race_id={race_id}&type={t}&action=init"))
    except Exception:
        return {}
    d = j.get("data")
    raw = d.get("odds", {}).get(str(t), {}) if isinstance(d, dict) else {}
    out = {}
    for k, v in raw.items():
        try:
            o = float(str(v[0]).replace(",", ""))   # ワイドは幅の下限
        except (ValueError, IndexError, TypeError):
            continue
        if o > 0:
            out[k] = o
    return out


def add_weighted(race_id, bets, payouts, judged):
    """配分方式で買った場合の払戻 payout_w を judged[券種] に書き足す。

    総額は均等買いと同じ(点数×100円)にそろえ、それを 1/オッズ に比例して配分する。
    低オッズの目ほど厚く買うので、どの目が当たっても払戻がほぼ同額になる。
    オッズは確定オッズを使う(購入時のオッズとは少しずれる)。
    """
    for key, (_, n, ordered) in BET_TYPES.items():
        e = judged.get(key)
        if not e or not e["points"]:
            continue
        if key not in ODDS_TYPE:            # 単勝は1点なので均等買いと同じ
            e["payout_w"] = e["payout"]
            continue
        odds = fetch_odds(race_id, key)
        time.sleep(0.3)
        if not odds:
            continue
        pts = []
        for p in bets.get(key, []):
            nums = [int(x) for x in re.findall(r"\d+", str(p))]
            if len(nums) != n:
                continue
            k = "".join(f"{x:02d}" for x in (nums if ordered else sorted(nums)))
            if k in odds:
                pts.append((nums, odds[k]))
        if not pts:
            continue
        total = e["points"] * 100
        inv = sum(1 / o for _, o in pts)
        ret = 0.0
        for combo, pay in payouts.get(key, []):
            for nums, o in pts:
                if (nums == combo) if ordered else (set(nums) == set(combo)):
                    ret += total * (1 / o) / inv * pay / 100
                    break
        e["payout_w"] = round(ret)


def backfill_weighted():
    """集計済みの結果ファイルに payout_w を後から書き足す(途中で止めても再開できる)"""
    for path in sorted(glob.glob(os.path.join(BASE, "results", "2*.json"))):
        d = json.load(open(path, encoding="utf-8"))
        pred_path = os.path.join(BASE, "predictions", f"{d['date']}.json")
        if not os.path.exists(pred_path):
            continue
        pred = json.load(open(pred_path, encoding="utf-8"))
        pm = {r["race_id"]: r for v in pred["venues"] for r in v["races"]}
        todo = [r for r in d["races"]
                if any(e.get("points") and "payout_w" not in e for e in r["bets"].values())]
        if not todo:
            continue
        for r in todo:
            p = pm.get(r["race_id"])
            if not p:
                continue
            try:
                html = fetch(f"https://race.netkeiba.com/race/result.html?race_id={r['race_id']}")
            except Exception:
                continue
            time.sleep(0.3)
            add_weighted(r["race_id"], p.get("bets", {}), parse_payouts(html), r["bets"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  配分方式を追記: {d['date']} ({len(todo)}レース)", flush=True)


def collect(date, live=False):
    """live=True なら確定済みのレースだけを results/live.json に書き出す(途中経過)"""
    pred_path = os.path.join(BASE, "predictions", f"{date}.json")
    if not os.path.exists(pred_path):
        print(f"予想なし: {date}")
        return False
    pred = json.load(open(pred_path, encoding="utf-8"))

    # 途中経過モードでは、既に取得済みのレースを再取得しない(netkeibaへの負荷軽減)
    cached = {}
    if live:
        live_path = os.path.join(BASE, "results", "live.json")
        if os.path.exists(live_path):
            prev = json.load(open(live_path, encoding="utf-8"))
            if prev.get("date") == date:
                cached = {r["race_id"]: r for r in prev.get("races", [])}
        now_hm = datetime.now(JST).strftime("%H:%M")

    races = []
    pending = 0
    for v in pred["venues"]:
        for r in v["races"]:
            if live:
                if r["race_id"] in cached:
                    races.append(cached[r["race_id"]])
                    continue
                # 発走時刻を過ぎていないレースは問い合わせない
                if r.get("time") and r["time"] > now_hm:
                    pending += 1
                    continue
            try:
                html = fetch(f"https://race.netkeiba.com/race/result.html?race_id={r['race_id']}")
            except Exception as e:
                if live:
                    pending += 1
                    continue
                raise
            time.sleep(0.4)
            payouts = parse_payouts(html)
            if "sanrentan" not in payouts:
                if live:
                    pending += 1
                    continue
                print(f"  結果未確定: {v['name']}{r['no']}R → この日はスキップ")
                return False
            top3 = payouts["sanrentan"][0][0]
            judged = judge(r.get("bets", {}), payouts)
            if not live:
                add_weighted(r["race_id"], r.get("bets", {}), payouts, judged)
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
                "bets": judged,
            })
            print(f"  {v['name']}{r['no']}R 1着:{top3[0]} " +
                  " ".join(k for k, e in races[-1]["bets"].items() if e["hit"]))
    # WIN5の答え合わせ (予想にwin5がある日のみ)
    win5 = None
    w5 = pred.get("win5")
    if w5:
        winners = {r["race_id"]: r["top3"][0]["num"] for r in races}
        legs = []
        hits = 0
        for l in w5["races"]:
            win = winners.get(l["race_id"])
            hit = any(p["num"] == win for p in l["picks"])
            hits += 1 if hit else 0
            legs.append({"venue": l["venue"], "no": l["no"], "name": l["name"],
                         "picks": [p["num"] for p in l["picks"]], "winner": win,
                         "hit": hit, "pending": win is None})
        payout = 0
        if hits == 5:
            # 的中時はnetkeibaのWIN5ページから払戻金を取得(当日集計前提)
            try:
                html = fetch("https://race.netkeiba.com/top/win5.html")
                m = re.search(r"払戻金?.{0,300}?([\d,]{4,})円", html, re.S)
                payout = int(m.group(1).replace(",", "")) if m else None
            except Exception:
                payout = None
        win5 = {"legs": legs, "hits": hits, "points": w5.get("points", 0), "payout": payout}
        print(f"  WIN5: {hits}/5" + (f" 払戻{payout}円" if payout else ""))

    out = {"date": date, "races": races, "win5": win5}
    os.makedirs(os.path.join(BASE, "results"), exist_ok=True)

    if live:
        out["updated"] = datetime.now(JST).strftime("%H:%M")
        out["pending"] = pending
        with open(os.path.join(BASE, "results", "live.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"途中経過: 確定{len(races)}レース / 残り{pending}レース")
        return True

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
    if "--backfill-weighted" in sys.argv:
        backfill_weighted()
        return
    if "--live" in sys.argv:
        # 当日の途中経過を results/live.json に書き出す(開催時間中に繰り返し実行)
        date = datetime.now(JST).strftime("%Y%m%d")
        if os.path.exists(os.path.join(BASE, "results", f"{date}.json")):
            print("確定済みのため途中経過は不要")
            return
        collect(date, live=True)
    elif "--auto" in sys.argv:
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
