#!/bin/bash
# 開催中の途中経過(results/live.json)を更新して push する。
# launchd (com.rossyrich.umascout.live) から15分おきに呼ばれる。
# 開催時間外・非開催日は即終了するので、平日に呼ばれても実害はない。
# AI判断を使わない純Python処理なので、Claudeを起動しなくても動く。
set -u
export PATH="$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$(dirname "$0")" || exit 0

# 自滅タイマー。どこかで固まっても10分で必ず終了する。
# launchdは前回の実行が終わるまで次を起動しないので、これが無いと
# 1回のハングで以降の更新が永久に止まる(2026-08-16に3時間停止した)。
( sleep 600; kill -9 $$ 2>/dev/null ) &
WATCHDOG=$!
trap 'kill "$WATCHDOG" 2>/dev/null' EXIT

# 土日の9〜18時台のみ動く
DOW=$(date +%u)
HOUR=$(date +%H)
[ "$DOW" -ge 6 ] || exit 0
{ [ "$HOUR" -ge 9 ] && [ "$HOUR" -le 18 ]; } || exit 0

DATE=$(date +%Y%m%d)
[ -f "predictions/$DATE.json" ] || exit 0   # 予想がない日は何もしない
[ -f "results/$DATE.json" ] && exit 0       # 確定済みなら途中経過は不要

python3 results.py --live >/dev/null 2>&1 || exit 0

# 変化がなければ push しない
[ -n "$(git status --porcelain -- results/live.json)" ] || exit 0

# gh は30秒で打ち切る(alarmはexec後も維持される)。ハングしても居座らせない。
TOKEN=$(perl -e 'alarm 30; exec @ARGV' gh auth token --user RossyRich 2>>/tmp/umascout-live.log)
[ -n "$TOKEN" ] || { echo "$(date '+%F %T') gh token取得失敗"; exit 0; }
export UMA_GH_TOKEN="$TOKEN"

git add results/live.json
git -c user.name="uma-scout-live" -c user.email="actions@users.noreply.github.com" \
    commit -q -m "live: $(date +%H:%M) 途中経過" || exit 0

# Claudeやworkflowのpushと衝突しないよう rebase してから push
git pull -q --rebase --autostash origin main 2>/dev/null || git rebase --abort 2>/dev/null

if git -c credential.helper='!f(){ echo username=RossyRich; echo password=$UMA_GH_TOKEN; };f' \
       push -q origin main 2>/dev/null; then
  echo "$(date '+%F %T') 途中経過を公開"
else
  echo "$(date '+%F %T') push失敗(次回リトライ)"
fi
