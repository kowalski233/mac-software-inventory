

扫描你的电脑(Mac OS) 上所有软件包信息, 包括来自Homebrew, pip, npm, gem, cargo, PKG,Applications 等. 然后联网查询, 并给出一个HTML报告. 

HTML报告里包含软件包名字, 版本, 大小, 时间, 作者, 用途, 依赖关系, 文件位置等详细信息.

需要 python3 , Mac OS 15.7. 

文件描述: 
- `scan.command` — 在MacOS下双击运行的脚本
- `soft.py` — 主要扫描器,用于生成报告.

运行方法:
1. 下载这个 repository
   
2. 打开命令行, 转到当前目录, 输入下列命令给脚本加运行权限:
   
   chmod +x scan.command
   
3. 双击can.command

4. 运行后会自动弹出浏览器窗口向您展示报告 , 并在当前文件夹生成 software_report.HTML



以下为英文readme

# mac-software-inventory
Scan Homebrew, pip, npm, gem, cargo, PKG receipts, and Applications on macOS, then export an HTML report.


A macOS software inventory tool that scans installed applications and package-manager content, then generates a local HTML report.


## Features

- Scan installed software and packages on macOS
- Support multiple ecosystems:
  - Homebrew formulae
  - Homebrew casks
  - Python packages (`pip`)
  - Node.js packages (`npm`)
  - Ruby gems (`gem`)
  - Rust binaries (`cargo`)
  - PKG receipts (`pkgutil`)
  - Application bundles in `/Applications` and `~/Applications`
- Generate a local HTML report with:
  - package/app name
  - version
  - description / purpose
  - developer / author
  - release time or local inferred time
  - install path
  - size
  - homepage
  - dependencies / reverse dependencies when available
- Try to enrich metadata from public registries:
  - PyPI
  - npm
  - RubyGems
  - crates.io
  - Homebrew API

## Requirements

- macOS
- Python 3
- Optional package managers / tools for richer results:
  - `brew`
  - `pip`
  - `npm`
  - `gem`
  - `cargo`
  - `pkgutil`

## Files

- `scan.command` — double-click launcher for macOS
- `soft.py` — main scanner and HTML report generator

## Usage

### Option 1: Double-click

1. Download this repository
2. Make the launcher executable:
   ```bash
   chmod +x scan.command
