# ウマスカウト◎ — AI競馬予想

Claudeが毎週土日の朝8時に中央競馬の全レースを予想するWebサイト。

**公開URL**: https://rossyrich.github.io/uma-scout/

## 仕組み

```
netkeiba ──scrape.py──▶ data/YYYYMMDD.json（出馬表+過去5走+オッズ）
                              │
                     Claude（クラウドエージェント）が全レース予想
                              │
        predictions/tmp_*.json ──build.py──▶ predictions/YYYYMMDD.json
                              │
                        git push ──▶ GitHub Pages
```

- 毎週土曜・日曜 朝8時(JST)にスケジュール実行のClaudeエージェントが自動更新（手順は [RUNBOOK.md](RUNBOOK.md)）
- 予想の主軸は馬連。単勝・馬連・三連複・三連単の買い目を出す
- API課金なし（Claudeサブスクリプション内で動作）

## ファイル構成

| ファイル | 役割 |
|---|---|
| `scrape.py` | netkeibaから当日の全レースデータを収集 |
| `build.py` | レースデータとAI予想をマージしてサイト用JSONを生成 |
| `index.html` | スマホ向けトップ画面（会場タブ + 1R〜12R予想） |
| `data/` | 収集した生データ |
| `predictions/` | 公開用の予想JSON（`index.json`が日付一覧） |
| `RUNBOOK.md` | 自動更新エージェント用の手順書 |

## 免責

予想はAIによる参考情報であり、的中を保証するものではありません。馬券の購入は自己責任で。
