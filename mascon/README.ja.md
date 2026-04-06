# Master Control

[English README](README.md)

`Master Control` は、WSL を前提にした個人開発向けのコマンドセンターです。

CLI コマンド `mascon` ひとつで、次のような日常作業をまとめて扱えます。

- workspace と複数リポジトリの状態確認
- AWS profile / AWS SSO の診断
- WSL と Windows 間のパス変換
- Windows Explorer やクリップボードとの連携
- Codex / Claude Code / ローカル LLM を task-first に呼び出す AI 操作
- 毎日の起点になる軽量ダッシュボード

これは汎用シェルの置き換えではありません。WSL 上で日常的に繰り返す開発操作を、速く・分かりやすく・まとめて扱うための実務寄り CLI です。

## こんな人向け

`mascon` は次のような人を想定しています。

- 普段の開発環境が WSL 中心
- `~/workspace` のような配下に複数の Git リポジトリを持っている
- AWS CLI や AWS SSO を日常的に使う
- Codex / Claude Code / Ollama を都度切り替えながら使いたい
- IDE や巨大な統合基盤より、軽量で手元に馴染む CLI を好む

## 30秒で導入

パッケージとしてインストールする場合:

```bash
pipx install mascon
mascon init
mascon doctor
mascon ai doctor
mascon start
```

ソースから使う場合:

```bash
cd /path/to/mascon
python3 -m pip install -e .
mascon init
mascon doctor
mascon ai doctor
mascon start
```

## 主な機能

### 環境診断

`mascon doctor` は、日常利用に必要な環境が整っているかをまとめて確認します。

チェック例:

- Python と実行環境
- config 読込
- workspace の存在
- Git の有無と repo 数
- AWS CLI / AWS profile / AWS 認証状態
- Codex や WSL 連携コマンドの有無
- jump 設定の妥当性

出力例:

```text
Mascon doctor
────────────────────────────────────────────────────────────────────────
[ OK ] python                   3.12.3
[ OK ] platform                 WSL (Linux)
[ OK ] config                   loaded from /home/user/.config/mascon/config.toml
[ OK ] workspace                /home/user/workspace
[ OK ] git                      git found
[ OK ] repos                    12 repositories under /home/user/workspace
[ OK ] aws cli                  aws found
[ OK ] aws profile              dev
[ WARN ] aws auth               sso login required
[ OK ] codex                    codex found
[ OK ] explorer.exe             explorer.exe found
[ OK ] clip.exe                 clip.exe found
[ OK ] jumps                    4 jumps valid
────────────────────────────────────────────────────────────────────────
Summary: OK=12 WARN=1 FAIL=0
Suggested actions:
  - Run `mascon aws login` to refresh AWS SSO.
```

JSON 出力:

```bash
mascon doctor --json
```

### AI 操作

`mascon ai` は provider-first ではなく task-first です。

「どのAIを使うか」より先に、「何をしたいか」から始められます。

```bash
mascon ai review .
mascon ai explain mastercontrol/cli.py
mascon ai plan "add ai compare command"
```

必要なら provider を明示できます。

```bash
mascon ai review . --provider codex
mascon ai run --provider claude "Review this repository structure"
```

現時点の AI MVP コマンド:

- `mascon ai doctor`
- `mascon ai list`
- `mascon ai review [path]`
- `mascon ai explain <path>`
- `mascon ai plan "<task>"`
- `mascon ai run --provider <name> "<prompt>"`

`mascon ai doctor` の出力例:

```text
Mascon AI doctor
────────────────────────────────────────────────────────────────────────
[ OK ] ai config                loaded
[ OK ] codex                    cli, available
[ WARN ] claude                 cli, not found
[ WARN ] local                  ollama, not found
[ OK ] local model              qwen3-coder
────────────────────────────────────────────────────────────────────────
Summary: OK=3 WARN=2 FAIL=0
Suggested actions:
  - Install or expose `claude` in PATH.
  - Install or expose `ollama` in PATH.
```

JSON 出力:

```bash
mascon ai doctor --json
```

### リポジトリ操作

代表的なコマンド:

```bash
mascon repo check
mascon repo dirty
mascon repo scan
mascon repo ship -m "feat: add dashboard" --dry-run
mascon repo ship -m "feat: add dashboard"
mascon repo ship -m "feat: add dashboard" --yes
```

`repo ship` は次をまとめて実行します。

```text
git pull --rebase
git add -A
git commit -m "..."
git push
```

安全性のために:

- `--dry-run` で事前確認できる
- 通常実行では branch と changed files を表示して確認を求める
- `--yes` で確認をスキップできる

### WSL 便利機能

日常向けの補助コマンド:

```bash
mascon path win . --copy
mascon path wsl "C:\\Users\\..."
mascon open .
mascon jump workspace
mascon aws whoami
mascon aws login
```

## AI Provider 設定

`mascon ai` は `~/.config/mascon/config.toml` の AI 設定を使います。

最小構成例:

```toml
[ai]
default_provider = "codex"
fallback_provider = "local"

[ai.default_task_provider]
review = "claude"
explain = "codex"
plan = "claude"

[ai.providers.codex]
type = "cli"
command = "codex"
enabled = true

[ai.providers.claude]
type = "cli"
command = "claude"
enabled = true

[ai.providers.local]
type = "ollama"
command = "ollama"
model = "qwen3-coder"
enabled = true
```

挙動:

- `review` / `explain` / `plan` は `ai.default_task_provider` を優先
- task ごとの設定がなければ `default_provider` を使う
- 指定 provider が見つからない場合は `fallback_provider` を使える
- `mascon ai run --provider ...` は task routing を通さずに直接実行する

## 設定

初期設定は `mascon init` を推奨します。

```bash
mascon init
```

手動設定も可能です。

```bash
mkdir -p ~/.config/mascon
cat > ~/.config/mascon/config.toml <<'TOML'
profile = "default"
mode = "work"
workspace = "~/workspace"
default_aws_profile = "dev"

[jumps]
workspace = "~/workspace"
mastercontrol = "~/workspace/mastercontrol"

[ai]
default_provider = "codex"
fallback_provider = "local"

[ai.default_task_provider]
review = "claude"
explain = "codex"
plan = "claude"

[ai.providers.codex]
type = "cli"
command = "codex"
enabled = true

[ai.providers.claude]
type = "cli"
command = "claude"
enabled = true

[ai.providers.local]
type = "ollama"
command = "ollama"
model = "qwen3-coder"
enabled = true
TOML
```

## コマンド一覧のイメージ

```bash
mascon start
mascon init
mascon doctor
mascon ai doctor
mascon ai list
mascon ai review .
mascon ai explain mastercontrol/cli.py
mascon ai plan "add ai compare command"
mascon repo check
mascon repo dirty
mascon aws whoami
mascon path win . --copy
mascon open .
mascon jump workspace
```

## WSL 前提について

`Master Control` は主に WSL を対象に設計されています。

一部の機能は Windows 側との連携を前提としています。

- `mascon open` は `explorer.exe` を使う
- クリップボード連携は `clip.exe` を使う
- パス変換は WSL と Windows の相互変換を前提としている

WSL 外でも一部は動作しますが、想定されている利用体験は WSL 上です。

## このツールが目指していないこと

- Git の完全な抽象化
- 巨大なマルチエージェント基盤
- シェルやエディタや CI の置き換え
- すべての AI provider 差異を重い抽象化で吸収すること

今の AI 層は意図的に軽量です。まずは task-first の入口、provider override、診断機能を整えることを優先しています。

## 開発

テスト:

```bash
python3 -m unittest discover -s tests -v
```

構文チェック:

```bash
python3 -m py_compile mastercontrol/config.py mastercontrol/services.py mastercontrol/ai.py mastercontrol/cli.py
```

## 要件

- Python 3.11+
- WSL 推奨
- Git: repo 機能に必要
- AWS CLI: AWS 機能に必要
- `codex`, `claude`, `ollama` のいずれか: AI provider 機能に必要
