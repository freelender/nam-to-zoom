# nam2zoom (macOS)

`freelender/nam-to-zoom` の macOS ネイティブ移植版。NAM (`.nam`) ファイルを
Zoom MS Plus ペダル用のカスタムエフェクト (N2Z Bank) に変換・書き込みする。

オリジナル (Windows/WinForms) との違い:
- GUI は SwiftUI ネイティブアプリ (`Package.swift`, `Sources/`)。ロジックは元プロジェクトと同じ
  Python バックエンド (`tools/nam2zoom`, `tools/msplus*.py`) をそのまま利用
- `release/templates/` は公開済み Windows ポータブル版から抽出したもの。DSPソースの
  ハッシュが一致することを確認済みで、これにより TI C6000 コンパイラ(Windows/Linux専用)
  なしでバンク生成ができる。DSPカーネル自体を変更する場合のみ TI ツールチェーンが別途必要
- `tools/nam2zoom/adapt.py`, `tools/nam2zoom/bank.py`, `tools/offline_effect_audit.py` の
  Windows専用パス(`core_render.exe`, `.venv/Scripts/python.exe`)を macOS 向けに条件分岐

## セットアップ

前提: Xcode Command Line Tools と Homebrew (`cmake`, `ninja`, `python@3.13`, `python@3.12`) が
インストール済みであること。

```bash
xcode-select --install
brew install cmake ninja python@3.13 python@3.12
./setup-mac.sh
```

`setup-mac.sh` は `.tooling/` に外部依存(stomphacks, neural-amp-modeler,
NeuralAmpModelerCore, および stomphacks が要求する mungewell/zoom-zt2)を取得し、
Python venv を2つ(標準の `venv`/`pip`で)構築し、CMake+Ninja+clang で `core_render` を
ビルドし、オフラインテストを実行する。ペダルへの書き込みは一切行わない。

補足: `uv` は当初この用途で使う想定だったが、この環境ではHomebrewでインストールした
直後のPythonが `$HOME` 配下でパッケージインストール時のアトミックリネームを行うと
`Operation not permitted` になる(macOSの何らかの新しい信頼性/provenanceチェックと
見られる)。システム標準Pythonや `/tmp` 配下では問題なく、`uv` も同じ症状だったため
標準の `python -m venv` + `pip` に切り替え、さらに venv は一旦 `/tmp` に作ってから
最終的な場所へ `mv` する回避策を取っている。

## SwiftUIアプリの起動

`swift run` はSPMが素の実行ファイルとして起動するため、macOSのDock/Window Serverに
「アプリ」として登録されずウィンドウが表示されないことがある。`build-app.sh` で
ちゃんとした`.app`バンドル(リソース込み、ad-hoc署名)を作ってから`open`で起動すること。

```bash
./build-app.sh
open nam2zoom.app
```

ソースを変更したら`build-app.sh`を再実行すれば`nam2zoom.app`が更新される
(出力はリポジトリ直下、`Package.swift`と同じ場所)。実行中のインスタンスがあれば
先に終了しておくこと(`pkill -f nam2zoom.app/Contents/MacOS/nam2zoom`)。

## バックエンドCLIを直接叩く場合

```bash
PYTHONPATH=tools .tooling/stomphacks/.venv/bin/python3 -m nam2zoom --help
```

## 安全上の注意

ペダルへの実書き込み (`Build + Install` / `Uninstall from pedal`) は元プロジェクトと同じ
ガード・確認フローを経る。実機を壊す可能性がある操作のため、
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) の安全手順(autosave OFF、バックアップ、
USB/電源維持など)を必ず確認すること。

## ライセンス

nam2zoom 本体コードは [LICENSE](LICENSE) (MIT, copyright 2026 Aleksandar Vukasinovic) に従う。
`.tooling/` にピン留めされる `stomphacks` / `neural-amp-modeler` / `NeuralAmpModelerCore` は
各プロジェクト自身のライセンスに従う。
