
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN=""

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  osascript -e 'display dialog "未找到 Python 3，请先安装 Python 3。" buttons {"确定"} default button "确定"'
  exit 1
fi

cd "$SCRIPT_DIR"

"$PYTHON_BIN" "$SCRIPT_DIR/soft.py"

REPORT_FILE="$SCRIPT_DIR/software_report.html"
if [ -f "$REPORT_FILE" ]; then
  open "$REPORT_FILE"
else
  osascript -e 'display dialog "报告生成失败：未找到 software_report.html" buttons {"确定"} default button "确定"'
  exit 1
fi