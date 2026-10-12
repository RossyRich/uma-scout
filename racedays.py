#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ウマスカウト 開催日カレンダー
土日に限らず、月曜祝日や年始の平日開催も含めて中央競馬の開催日を扱う。

使い方:
  python3 racedays.py            # 今月・来月の開催日を predictions/schedule.json に保存
  python3 racedays.py --check    # 今日(JST)が開催日なら終了コード0、非開催日なら1
  python3 racedays.py --check 20261012

カレンダーは netkeiba の開催カレンダーを読む。出馬表が出る前の日付でも
競馬場名が載るので、数週間先の開催日まで分かる。
"""
import sys
import os
import re
import json
import urllib.request
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def month_racedays(year, month):
    """その月の開催日(YYYYMMDD)の一覧。競馬場名が書かれたマスを開催日とみなす"""
    html = fetch(f"https://race.netkeiba.com/top/calendar.html?year={year}&month={month}")
    days = []
    for cell in re.findall(r'<td class="RaceCellBox">(.*?)</td>', html, re.S):
        m = re.search(r'class="Day">(\d+)<', cell)
        if m and "JyoName" in cell:
            days.append(f"{year:04d}{month:02d}{int(m.group(1)):02d}")
    return days


def is_raceday(date):
    """当日の判定は出馬表一覧で行う(カレンダーより確実)"""
    html = fetch(f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date}")
    return bool(re.search(r"race_id=\d{12}", html))


def update_schedule():
    now = datetime.now(JST)
    months = [(now.year, now.month)]
    nxt = (now.replace(day=1) + timedelta(days=32))
    months.append((nxt.year, nxt.month))

    path = os.path.join(BASE, "predictions", "schedule.json")
    known = set()
    if os.path.exists(path):
        known = set(json.load(open(path, encoding="utf-8")).get("dates", []))

    fetched = set()
    for y, m in months:
        fetched |= set(month_racedays(y, m))
    if not fetched:
        print("カレンダーを取得できませんでした（既存の schedule.json を維持）")
        return

    # 取得した月は取得結果で置き換え(中止・追加を反映)、それ以外の月は残す。
    # ただし60日より前は捨てる
    prefixes = {f"{y:04d}{m:02d}" for y, m in months}
    cutoff = (now - timedelta(days=60)).strftime("%Y%m%d")
    dates = {d for d in known if d[:6] not in prefixes and d >= cutoff} | fetched
    out = {"updated": now.strftime("%Y-%m-%d %H:%M"), "dates": sorted(dates)}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    upcoming = [d for d in out["dates"] if d >= now.strftime("%Y%m%d")]
    print(f"開催日を保存: 今後 {len(upcoming)}日 {upcoming[:8]}")


def main():
    if "--check" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--check"]
        date = args[0] if args else datetime.now(JST).strftime("%Y%m%d")
        if is_raceday(date):
            print(f"{date} は開催日")
            sys.exit(0)
        print(f"{date} は非開催日")
        sys.exit(1)
    update_schedule()


if __name__ == "__main__":
    main()
