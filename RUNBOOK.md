# ウマスカウト 週次更新手順（自動更新エージェント用）

毎週土曜・日曜の朝8時(JST)に実行し、当日の中央競馬全レースのAI予想を生成して公開する。

## 手順

1. 今日の日付を `YYYYMMDD` 形式で確認する（JST基準）。
2. データ収集を実行する:
   ```
   python3 scrape.py YYYYMMDD
   ```
   - 「開催なし」と出た場合は中央競馬の開催がない日なので、何もせず終了してよい。
   - 成功すると `data/YYYYMMDD.json` ができる。
3. `data/YYYYMMDD.json` を読み、**全レースを自分で予想**して `predictions/tmp_<会場ローマ字>.json` を会場ごとに書く（会場が3つなら3ファイル）。フォーマットは下記「予想JSONフォーマット」を厳守。
   - 分析観点: 過去5走の着順・上がり・通過順・相手関係、距離/コース適性、馬場、脚質とペース想定、騎手、斤量、間隔、オッズ(市場評価)。過剰人気を疑い中穴も拾う。
   - 新馬戦は血統(父)・厩舎・騎手・オッズから判断。
   - 買い目の主軸は馬連。単勝1点、馬連3〜5点、三連複4〜6点、三連単4〜8点。
   - レース数が多いので、サブエージェントを会場ごとに並列で使ってよい。
4. マージしてサイト用JSONを生成する:
   ```
   python3 build.py YYYYMMDD
   ```
   - 「警告: 予想が見つからないレース」が出たら、そのレースの予想を追加してからやり直す。
5. `predictions/tmp_*.json` を削除し、コミットしてpushする:
   ```
   rm predictions/tmp_*.json
   git add -A
   git commit -m "predict: YYYYMMDD"
   git push
   ```
6. push後、https://rossyrich.github.io/uma-scout/ に反映される（GitHub Pagesのビルドに1〜2分かかる）。

## 予想JSONフォーマット（predictions/tmp_*.json）

```json
{
 "venue": "函館",
 "races": [
  {
   "race_id": "202602011201",
   "no": 1,
   "marks": [
    {"mark": "◎", "num": 5, "name": "馬名", "comment": "本命理由を30字程度"},
    {"mark": "◯", "num": 8, "name": "馬名", "comment": "..."},
    {"mark": "▲", "num": 2, "name": "馬名", "comment": "..."},
    {"mark": "△", "num": 10, "name": "馬名", "comment": "..."},
    {"mark": "△", "num": 3, "name": "馬名", "comment": "..."}
   ],
   "summary": "展開予想と狙いを2〜3文",
   "confidence": "A",
   "bets": {
    "tansho": ["5"],
    "umaren": ["5-8", "5-2", "5-10"],
    "sanrenpuku": ["5-8-2", "5-8-10", "5-2-10"],
    "sanrentan": ["5→8→2", "5→8→10", "8→5→2"]
   }
  }
 ]
}
```

- `confidence`: S(鉄板) / A(有力) / B(混戦) / C(荒れ模様)
- 買い目の数字はすべて馬番
- 全レース分を必ず出力（12R開催なら12レース）
