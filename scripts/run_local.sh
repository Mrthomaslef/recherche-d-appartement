#!/bin/zsh
# Collecte quotidienne depuis le Mac (IP résidentielle : SeLoger/Logic-Immo et PAP passent).
# Lancé par launchd : ~/Library/LaunchAgents/com.thomaslefevre.appart-scrape.plist
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/bin:/bin"
echo "=== $(date '+%F %T') ==="
[ -x .venv/bin/python ] || { /opt/homebrew/bin/python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
git pull -q --rebase -X theirs || git rebase --abort
.venv/bin/python scripts/scrape.py
git add data/
if ! git diff --cached --quiet; then
  git commit -q -m "data: annonces du $(date '+%Y-%m-%d %H:%M') (Mac)"
  git push -q || { git pull -q --rebase -X ours && git push -q; }
fi
echo "OK"
