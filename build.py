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
from itertools import combinations, permutations
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
VENUE_ORDER = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]
MARK_CHARS = ["◎", "◯", "▲", "△", "△", "△"]

# WIN5: 各自信度で何頭まで流すか (◎◯▲△の順)。基本2頭まで、混戦(C)のみ3頭を許容
WIN5_PICKS = {"S": 1, "A": 2, "B": 2, "C": 3}
# 合計点数の上限 (100円×50点=5,000円)
WIN5_MAX_POINTS = 50


def _combo(nums):
    """着順を問わない式別（馬連・ワイド・三連複）の組を作る。

    実際の投票表記に合わせて必ず馬番の小さい順に並べる。確率順のまま出すと
    「2-1-3」のような並びになり、投票画面と見比べにくいため。
    """
    return "-".join(str(x) for x in sorted(nums))


def _nums(nums):
    """BOX・流しの対象馬を小さい順に「1・2・3」形式で並べる"""
    return "・".join(str(x) for x in sorted(nums))


def derive(p):
    """AIが出した各馬の確率(p_win/p_top3)から、印と式別ごとの買い目を機械的に組む。

    印と馬連・ワイド・三連複は「3着内率」の並び(T)を使う。AIの見立てで最も信頼できる
    のが3着内に来る馬の判別だと検証で分かっているため。1着の特定が要る単勝・三連単だけ
    「勝率」の並び(W)を使う。旧形式(marks/betsを直接持つ予想)はそのまま通す。
    """
    hs = [dict(h) for h in p.get("horses", []) if h.get("num")]
    if not hs:
        return p.get("marks", []), p.get("bets", {}), p.get("formations", {}), None

    for h in hs:
        h["p_win"] = max(0.0, float(h.get("p_win", 0)))
        h["p_top3"] = max(float(h.get("p_top3", 0)), h["p_win"])  # 3着内率は勝率以上

    by_top3 = sorted(hs, key=lambda h: (-h["p_top3"], -h["p_win"]))
    by_win = sorted(hs, key=lambda h: (-h["p_win"], -h["p_top3"]))
    T = [h["num"] for h in by_top3]
    W = [h["num"] for h in by_win]
    if len(T) < 3:
        return p.get("marks", []), p.get("bets", {}), p.get("formations", {}), None

    marks = [{"mark": MARK_CHARS[i], "num": h["num"], "name": h.get("name", ""),
              "comment": h.get("comment", ""),
              "p_win": round(h["p_win"]), "p_top3": round(h["p_top3"])}
             for i, h in enumerate(by_top3[:5])]

    rest = [n for n in T if n != W[0]][:3]
    umaren_partners = T[1:4]      # 馬連は T[0] を軸にした流し
    wide_box = T[:3]              # ワイドは3頭BOX
    sanpuku_box = T[:4]           # 三連複は4頭BOX

    # 一覧そのものも馬番順に並べる。組の中だけ昇順にしても、一覧が確率順のままだと
    # 「2-7, 7-11, 4-7」のように散らばって投票画面と突き合わせにくいため。
    def _sorted_combos(combos):
        return [_combo(c) for c in sorted(sorted(c) for c in combos)]

    bets = {
        "tansho": [str(W[0])],
        "umaren": _sorted_combos([T[0], n] for n in umaren_partners),
        "wide": _sorted_combos(combinations(wide_box, 2)),
        "sanrenpuku": _sorted_combos(combinations(sanpuku_box, 3)),
        # 三連単は着順を問うので組の中は並べ替えない。1着は固定なので
        # 2着・3着の馬番順に並べて一覧だけ見やすくする。
        "sanrentan": [f"{W[0]}→{a}→{b}"
                      for a, b in sorted(permutations(rest, 2))],
    }

    # 実際に投票するときの入力方法。買い目の一覧より前に表示する。
    # BOXや流しで一括入力できる形にしておくと、1点ずつ入れる必要がなくなる。
    formations = {
        "tansho": f"{W[0]}（1点）",
        "umaren": f"{T[0]} → {_nums(umaren_partners)}"
                  f"（軸1頭ながし・{len(bets['umaren'])}点）",
        "wide": f"{_nums(wide_box)}（{len(wide_box)}頭BOX・{len(bets['wide'])}点）",
        "sanrenpuku": f"{_nums(sanpuku_box)}"
                      f"（{len(sanpuku_box)}頭BOX・{len(bets['sanrenpuku'])}点）",
        "sanrentan": f"{W[0]} → {_nums(rest)} → {_nums(rest)}"
                     f"（1着固定・{len(bets['sanrentan'])}点）",
    }

    warn = None
    total_win = sum(h["p_win"] for h in hs)
    if total_win > 100:
        warn = f"勝率の合計が{total_win:.0f}%"
    return marks, bets, formations, warn


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
    for rid in ids:
        venue, r, _ = all_races[rid]
        n = WIN5_PICKS.get(r.get("confidence", "B"), 2)
        # WIN5は1着を当てる馬券なので、勝率の見立てがあればその順で選ぶ
        ms = r.get("marks", [])
        if ms and ms[0].get("p_win") is not None:
            ms = sorted(ms, key=lambda m: -m.get("p_win", 0))
        picks = [{"num": m["num"], "name": m["name"]} for m in ms[:n]]
        if not picks:
            return
        legs.append({
            "race_id": rid, "venue": venue, "no": r["no"], "name": r["name"],
            "time": r["time"], "confidence": r.get("confidence", "B"), "picks": picks,
        })

    def total(ls):
        p = 1
        for l in ls:
            p *= len(l["picks"])
        return p

    # 上限を超えたら、頭数の多いレースから1頭ずつ削る (△→▲の順に外す)
    while total(legs) > WIN5_MAX_POINTS:
        widest = max(legs, key=lambda l: len(l["picks"]))
        if len(widest["picks"]) <= 1:
            break
        widest["picks"].pop()

    out["win5"] = {"races": legs, "points": total(legs)}


def main():
    date = sys.argv[1]

    # --rebuild-bets: 公開済みの予想ファイルの買い目と投票方法だけを組み直す。
    # 印(marks)に各馬の p_win / p_top3 が入っているので、予想そのものは変えずに
    # 買い目の並びや表示形式の変更を既存分へ反映できる。
    if "--rebuild-bets" in sys.argv:
        path = os.path.join(BASE, "predictions", f"{date}.json")
        with open(path, encoding="utf-8") as f:
            out = json.load(f)
        n = 0
        for v in out.get("venues", []):
            for r in v.get("races", []):
                ms = [m for m in r.get("marks", []) if m.get("p_top3") is not None]
                if len(ms) < 3:
                    continue
                marks, bets, formations, _ = derive({"horses": [
                    {"num": m["num"], "name": m.get("name", ""),
                     "p_win": m.get("p_win", 0), "p_top3": m.get("p_top3", 0)}
                    for m in ms
                ]})
                if not bets:
                    continue
                r["bets"] = bets
                r["formations"] = formations
                n += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"買い目を組み直しました: {path} ({n}レース)")
        return

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
    warnings = []
    for v in sorted(data["venues"], key=lambda x: VENUE_ORDER.index(x["name"]) if x["name"] in VENUE_ORDER else 99):
        races = []
        for r in v["races"]:
            p = preds.get(r["race_id"])
            if not p:
                missing.append(r["race_id"])
                continue
            marks, bets, formations, warn = derive(p)
            if warn:
                warnings.append(f"{v['name']}{r['no']}R: {warn}")
            if not marks:
                missing.append(r["race_id"])
                continue
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
                "marks": marks,
                "summary": p.get("summary", ""),
                "confidence": p.get("confidence", "B"),
                "bets": bets,
                "formations": formations,
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
    if warnings:
        print("確率の見立てが不自然なレース:")
        for w in warnings:
            print(f"  {w}")
    if missing:
        print(f"警告: 予想が見つからないレース: {missing}")
        sys.exit(2)


if __name__ == "__main__":
    main()
