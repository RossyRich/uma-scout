#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウマスカウト データ収集スクリプト
netkeibaから指定日の中央競馬 全レースの出馬表(過去5走つき)とオッズを取得し、
data/YYYYMMDD.json に保存する。

使い方: python3 scrape.py 20260719
"""
import sys
import os
import re
import json
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))

PLACE = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def get_race_ids(date):
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}"
    html = fetch(url)
    ids = sorted(set(re.findall(r"race_id=(\d{12})", html)))
    return ids


def get_odds(race_id):
    """単勝オッズ {馬番int: (odds, 人気)} を返す。未発売ならNone"""
    url = f"https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=init"
    try:
        j = json.loads(fetch(url))
        odds1 = j.get("data", {}).get("odds", {}).get("1") if isinstance(j.get("data"), dict) else None
        if not odds1:
            return None
        out = {}
        for num, v in odds1.items():
            try:
                out[int(num)] = (float(v[0]), int(v[2]))
            except (ValueError, IndexError):
                pass
        return out or None
    except Exception:
        return None


def parse_past(cell_html):
    """過去1走分のPastセルを1行のテキストに圧縮"""
    def pick(cls):
        m = re.search(r'class="' + cls + r'"[^>]*>(.*?)</div>', cell_html, re.S)
        return strip_tags(m.group(1)) if m else ""
    d1 = pick("Data01")   # 2025.12.28 中山 16(着順)
    d2 = pick("Data02")   # レース名 クラス
    d5 = pick("Data05")   # 芝1600(外) 1:36.4 良
    d3 = pick("Data03")   # 16頭 14番 16人 騎手 54.0
    d6 = pick("Data06")   # 通過順 (上がり) 馬体重
    d7 = pick("Data07")   # 勝ち馬(着差)
    if not d1:
        return None
    m = re.match(r"([\d.]+)\s*(\S+)\s*(\d+)?", d1)
    date_place = f"{m.group(1)} {m.group(2)}" if m else d1
    chaku = m.group(3) if m and m.group(3) else "?"
    return f"{date_place} {chaku}着 {d2} {d5} {d3} 通過{d6} 相手{d7}".strip()


def parse_race(race_id, html):
    race = {"race_id": race_id}
    race["venue"] = PLACE.get(race_id[4:6], race_id[4:6])
    race["no"] = int(race_id[10:12])

    m = re.search(r'class="RaceName"[^>]*>\s*([^<\n]+)', html)
    if not m:
        m = re.search(r'RaceList_Item02">\s*([^<\n]+)', html)
    race["name"] = m.group(1).strip() if m else f"{race['no']}R"

    m = re.search(r'RaceData01">(.*?)</div>', html, re.S)
    rd1 = strip_tags(m.group(1)) if m else ""
    m = re.search(r"(\d{1,2}:\d{2})発走", rd1)
    race["time"] = m.group(1) if m else ""
    m = re.search(r"(芝|ダ|障)\S*\d+m", rd1)
    race["course"] = m.group(0) if m else ""
    m = re.search(r"馬場:(\S+)", rd1)
    race["going"] = m.group(1) if m else ""
    m = re.search(r"天候:(\S+)", rd1)
    race["weather"] = m.group(1) if m else ""

    m = re.search(r'RaceData02">(.*?)</div>', html, re.S)
    rd2 = strip_tags(m.group(1)) if m else ""
    race["cond"] = rd2.split("本賞金")[0].strip()

    odds = get_odds(race_id)

    horses = []
    for row in re.findall(r'<tr class="HorseList".*?</tr>', html, re.S):
        info = re.search(r'class="Horse_Info"[^>]*>(.*?)</td>', row, re.S)
        if not info:
            continue
        info = info.group(1)
        h = {}
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        nums = [strip_tags(t) for t in tds[:2]]
        h["waku"] = int(nums[0]) if nums and nums[0].isdigit() else None
        h["num"] = int(nums[1]) if len(nums) > 1 and nums[1].isdigit() else None

        def horse_div(cls):
            m = re.search(r'class="' + cls + r'[^"]*"[^>]*>(.*?)</div>', info, re.S)
            return strip_tags(m.group(1)) if m else ""

        h["father"] = horse_div("Horse01")
        h["name"] = horse_div("Horse02")
        h["mother"] = horse_div("Horse03")
        h06 = horse_div("Horse06")  # 脚質+間隔  例: 先 中28週
        m2 = re.search(r"(逃|先|差|追|自在)", h06)
        h["style"] = m2.group(1) if m2 else ""
        m2 = re.search(r"(中\d+週|連闘)", h06)
        h["interval"] = m2.group(1) if m2 else ""
        h["stable"] = horse_div("Horse05").replace(" ", "")

        jk = re.search(r'class="Jockey"[^>]*>(.*?)</td>', row, re.S)
        if jk:
            jk = jk.group(1)
            m2 = re.search(r'class="Barei"[^>]*>([^<]+)', jk)
            h["sexage"] = m2.group(1).strip() if m2 else ""
            m2 = re.search(r'jockey/result/recent/[^>]*>([^<]+)', jk)
            h["jockey"] = m2.group(1).strip() if m2 else ""
            m2 = re.search(r"<span>([\d.]+)</span>", jk)
            h["load"] = float(m2.group(1)) if m2 else None

        rest = re.search(r'class="Rest"[^>]*>(.*?)</td>', row, re.S)
        h["rest"] = strip_tags(rest.group(1)) if rest else ""

        pasts = []
        for p in re.findall(r'<td[^>]*class="Past"[^>]*>(.*?)</td>', row, re.S):
            t = parse_past(p)
            if t:
                pasts.append(t)
        h["past"] = pasts

        if odds and h.get("num") in odds:
            h["odds"], h["pop"] = odds[h["num"]]

        if h.get("num"):
            horses.append(h)

    race["head"] = len(horses)
    race["odds_available"] = odds is not None
    race["horses"] = horses
    return race


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y%m%d")
    ids = get_race_ids(date)
    if not ids:
        print(f"開催なし: {date}")
        sys.exit(1)
    print(f"{date}: {len(ids)}レース")

    venues = {}
    for rid in ids:
        html = fetch(f"https://race.netkeiba.com/race/shutuba_past.html?race_id={rid}&rf=shutuba_submenu")
        race = parse_race(rid, html)
        venues.setdefault(race["venue"], []).append(race)
        print(f"  {race['venue']}{race['no']}R {race['name']} {race['head']}頭 odds={'あり' if race['odds_available'] else 'なし'}")
        time.sleep(0.5)

    out = {
        "date": date,
        "venues": [{"name": v, "races": sorted(rs, key=lambda r: r["no"])} for v, rs in venues.items()],
    }
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    path = os.path.join(BASE, "data", f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"保存: {path}")


if __name__ == "__main__":
    main()
