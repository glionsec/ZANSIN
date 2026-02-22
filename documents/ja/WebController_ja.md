# ZANSIN Web Controller

ZANSIN Web Controller は、Red Controller をブラウザから操作するためのインターフェースです。
インストラクターは CLI を使わずに、複数学習者への同時演習実行・ログのリアルタイム監視・スコアの比較・攻撃シナリオの編集・VPN ピアの管理・マシンのプロビジョニングをすべてブラウザ上で行えます。

---

## アーキテクチャ概要

```
[ブラウザ]  ←HTTP/SSE→  [Web Controller :8888]  ←サブプロセス→  [red_controller.py]
                              │
                              ├── auth.py              (認証 + ユーザー管理)
                              ├── session_manager.py   (プロセス管理 + ログストリーミング)
                              ├── db_reader.py          (セッション別 SQLite 読み取り)
                              ├── config_editor.py      (attack_config.ini の読み書き)
                              ├── vpn_manager.py        (WireGuard 設定ファイル生成)
                              ├── setup_runner.py       (ansible-playbook 実行 + SSE)
                              └── training_checker.py   (SSH 経由サービス監視)
```

- **バックエンド**: FastAPI + Server-Sent Events (SSE)
- **フロントエンド**: シングルページ HTML（Vanilla JS + Tailwind CSS CDN、ビルド不要）
- **ポート**: 8888（コントロールサーバー上）
- **セッション分離**: 学習者ごとに独立したプロセスで演習を実行し、SQLite データベースを `/opt/zansin/red-controller/sessions/<session-id>/sqlite3/` に隔離して保存

---

## 前提条件

> [!IMPORTANT]
> Web Controller は**コントロールサーバー上**で動作します。
> Ansible プレイブックによるデプロイが完了していないと動作しません。
> ローカル開発マシン上でのテストは、デプロイなしには行えません。

作業を始める前に以下を確認してください：

- `zansin.sh` / Ansible プレイブックにより、両マシン（コントロールサーバー・トレーニングマシン）のプロビジョニングが完了している
- `zansin` ユーザーでコントロールサーバーに SSH できる
- コントロールサーバー上に `/opt/zansin/red-controller/` が存在する（Ansible が作成）

---

## 認証

### ログイン

`http://<コントロールサーバーIP>:8888` を開くと、ログインオーバーレイが表示されます。
ユーザー名とパスワードを入力してログインしてください。認証情報はコントロールサーバー上の `users.json` で検証されます。

- **エンドポイント**: `POST /auth/login`
- **セッション Cookie**: `zansin_session`（HTTP-only、SameSite=Strict、有効期限 24 時間）
- **ログアウト**: 画面右上のログアウトボタンをクリック、または `POST /auth/logout`

### ロールと権限

| タブ | admin | trainee |
|------|-------|---------|
| 演習管理 | ✅ 開始 / 停止 | 👁 閲覧のみ |
| リアルタイムモニター | ✅ | ✅ |
| ランキング・比較 | ✅ | ✅ |
| シナリオ編集 | ✅ | ❌ 非表示 |
| セットアップ | ✅ | ❌ 非表示 |
| トレーニング環境 | ✅ | ❌ 非表示 |
| ドキュメント | ✅ | ✅ |
| VPN管理 | ✅ | ❌ 非表示 |

### デフォルト認証情報

| ユーザー名 | パスワード | ロール |
|-----------|-----------|--------|
| `admin` | `admin` | admin |
| `trainee` | `trainee` | trainee |

> [!WARNING]
> 実際の演習を実施する前に、デフォルトパスワードを必ず変更してください。
> 変更方法は後述の[ユーザー管理](#ユーザー管理)セクションを参照してください。

### パスワードの保存形式

パスワードは `users.json` に `sha256:<salt>:<hash>` 形式で保存されます：

```
sha256:<16バイト16進数ソルト>:<sha256(ソルト + パスワード)>
```

パスワードを変更するには、ユーザー管理 API（admin のみ）を使用するか、`users.json` を直接編集してサービスを再起動してください。

---

## デプロイ方法

### Web UI — セットアップタブを使う（推奨）

**ZANSIN のプロビジョニングはブラウザから行うのが最も簡単です。**

1. リポジトリをチェックアウトしたマシンで `./web_controller.sh` を実行する
2. `http://localhost:8888` をブラウザで開き、ログインする（デフォルト: `admin` / `admin`）
3. **タブ 5（セットアップ）** を開く
4. トレーニングマシンの IP（複数可）、コントロールサーバーの IP、SSH パスワードを入力する
5. プロビジョニング対象（スコープ）を選択し、**▶ Ansible 実行** をクリックする

Ansible の実行と WireGuard の設定が自動で行われます — ターミナル操作は不要です。

> [!NOTE]
> ブラウザを開く**前に** `./web_controller.sh` が起動している必要があります。また、同じマシンに Ansible がインストールされている必要があります。詳細は後述の[サービスの起動・停止](#サービスの起動停止)を参照してください。

### 代替手段：zansin.sh（ブラウザが使えない環境）

ローカルでブラウザを起動できない場合（CI パイプラインやリモート専用環境）はこちらを使用してください：

```bash
chmod +x zansin.sh
./zansin.sh
```

スクリプトは内部で以下を順番に実行します：

1. Ansible プレイブックでトレーニングマシンを構築
2. `rsync` でコントロールサーバーへファイルを転送（`web_controller/` および `documents/` を含む）
3. コントロールサーバー上で venv 作成 + `pip install`（`fastapi`・`uvicorn` を含む）
4. `sessions/` ディレクトリを作成
5. `wireguard_setup.sh` を実行して WireGuard サーバー鍵を生成
6. `zansin-web-controller` systemd サービスを登録・起動

`zansin.sh` の完了後、コントロールサーバー上でサービスが自動起動した状態になります。

### 手動デプロイ（特定部分の再デプロイ時）

コントロールサーバーに `zansin` ユーザーで SSH した後：

```bash
# 1. ファイルのコピー（リポジトリからコントロールサーバーへ）
rsync -avz playbook/roles/zansin-control-server/files/. zansin@<control-ip>:/opt/zansin/red-controller/
rsync -avz documents/ zansin@<control-ip>:/opt/zansin/red-controller/documents/

# 2. コントロールサーバー上で依存パッケージをインストール
source /opt/zansin/red-controller/red_controller_venv/bin/activate
pip install -r /opt/zansin/red-controller/requirements.txt
deactivate

mkdir -p /opt/zansin/red-controller/sessions

# 3. systemd サービスを登録・起動
sudo tee /etc/systemd/system/zansin-web-controller.service > /dev/null << 'EOF'
[Unit]
Description=ZANSIN Web Controller
After=network.target

[Service]
Type=simple
User=zansin
WorkingDirectory=/opt/zansin/red-controller
ExecStart=/opt/zansin/red-controller/red_controller_venv/bin/uvicorn web_controller.main:app --host 0.0.0.0 --port 8888 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now zansin-web-controller
```

---

## サービスの起動・停止

### デプロイ後の動作

デプロイ完了後（セットアップタブまたは `zansin.sh` 経由）、Web Controller は systemd によって自動的に起動し、ブート時も自動で立ち上がります。手動操作は不要です。

### 状態確認・トラブルシューティング（systemd）

```bash
# 状態確認
sudo systemctl status zansin-web-controller

# ログを流す
sudo journalctl -u zansin-web-controller -f

# 必要に応じて再起動
sudo systemctl restart zansin-web-controller
```

これらのコマンドは状態確認やトラブルシューティング専用です。Ansible によって一度有効化されると、サービスはブート時に自動起動します。

### 再プロビジョニング時：web_controller.sh

`web_controller.sh` はリポジトリルートにあるスクリプトで、リポジトリがチェックアウトされたマシン上でローカルから Web Controller を起動します。[セットアップタブ](#タブ-5--セットアップ)を使って Ansible プレイブックをブラウザから実行したい場合は、このスクリプトでの起動が**必須**です。

```bash
# 起動（デフォルト）
./web_controller.sh

# 明示的に指定する場合：
./web_controller.sh start

# 停止
./web_controller.sh stop

# 停止してから起動
./web_controller.sh restart

# プロセスとポートの状態を確認
./web_controller.sh status
```

`web_controller.sh start` が行う処理：

1. リポジトリルートに `.web_venv/` を作成し（存在しない場合）、`requirements.txt` をインストール
2. 環境変数を設定：
   - `ZANSIN_REPO_DIR` — リポジトリルートのパス（セットアップタブを有効化）
   - `ZANSIN_WG_DIR=/opt/zansin/red-controller/wireguard` — WireGuard 鍵ディレクトリ
   - `ZANSIN_RC_DIR=/opt/zansin/red-controller` — デプロイ済み Red Controller のパス
3. `sg zansin -c "..."` ラッパー経由で `uvicorn` を起動し、`usermod -aG zansin ubuntu` 直後でも再ログインなしで `zansin` グループを有効化

> [!NOTE]
> `web_controller.sh` も同じポート 8888 を使用します。systemd サービスが動作中の場合はあらかじめ停止してください（ポートが競合します）。

---

## Web UI へのアクセス

ブラウザで以下の URL を開きます：

```
http://<コントロールサーバーのIPアドレス>:8888
```

> [!NOTE]
> インストラクターのマシンからポート 8888 に到達できる必要があります。
> コントロールサーバーにファイアウォールが設定されている場合は、ポートを開放してください：
> ```bash
> sudo ufw allow 8888/tcp
> ```

---

## UI の構成（8タブ）

| # | タブ | アクセス |
|---|-----|---------|
| 1 | 演習管理 | 全ユーザー |
| 2 | リアルタイムモニター | 全ユーザー |
| 3 | ランキング・比較 | 全ユーザー |
| 4 | シナリオ編集 | Admin のみ |
| 5 | セットアップ | Admin のみ |
| 6 | トレーニング環境 | Admin のみ |
| 7 | ドキュメント | 全ユーザー |
| 8 | VPN管理 | Admin のみ |

---

### タブ 1 — 演習管理

複数学習者の演習を一元管理します。

| 入力項目 | 説明 |
|---------|------|
| 学習者名 | ログとスコアに使用する識別子（例：`learnerA`）|
| Training IP | 学習者のトレーニングマシンの IP アドレス |
| Control IP | このコントロールサーバーの IP アドレス |
| シナリオ | 設定済みのシナリオから選択（デフォルト: `0`=Dev、`1`=最難度、`2`=中難度）|

**▶ 開始** をクリックすると演習が起動し、セッション一覧に表示されます。

- **● 実行中** — 演習が進行中
- **■ 終了** — 演習終了済み。Technical Point と Operation Ratio が表示されます
- **■ 停止** — 実行中のセッションに SIGTERM を送信して停止

> [!NOTE]
> セッションの開始・停止は admin ユーザーのみ可能です。trainee ユーザーはセッション一覧の閲覧のみできます。

---

### タブ 2 — リアルタイムモニター

複数のセッションのログを並べてリアルタイムで確認できます。

1. ドロップダウンからセッションを選択し **+ 追加** をクリック
2. SSE によってログが自動的にストリーミング表示されます
3. ペインごとに **自動スクロール** のオン/オフを切り替え可能
4. ✕ ボタンで個別ペインを閉じられます

ログ行の色分け：

| 色 | タグ | 意味 |
|----|------|------|
| 緑 | `[*]` | 成功 / OK |
| 青 | `[+]` | 情報 / 注記 |
| 赤 | `[-]` | 失敗 |
| 黄 | `[!]` | 警告 |

---

### タブ 3 — ランキング・比較

演習終了後にスコアを確認・比較できます。

**ランキング表** — Technical Point の降順で学習者を表示。上位 3 名にはメダル 🥇🥈🥉 を表示。

**比較表（詳細）** — 全学習者を横並びで比較：

| 指標 | データ元 |
|------|---------|
| Technical Point | `judge.db` の `JudgeAttackTBL` |
| Operation Ratio | `crawler_<名前>.db` の `GameStatusTBL` |
| シナリオ | セッションメタデータ |
| チート検出回数 | `GameStatusTBL.is_cheat` |
| 平均 Charge/Epoch | `GameStatusTBL.charge_amount` |

セッション終了後に **↻ 更新** をクリックすると最新データが反映されます。

---

### タブ 4 — シナリオ編集

`attack_config.ini` の内容をブラウザ上で直接編集できます。*（Admin のみ）*

1. リストからシナリオを選択
2. ステップ ID・遅延時間・アクション・Cheat Count をインラインで編集。アクション名にカーソルを合わせるとツールチップで説明が表示されます
3. **+ ステップ追加** で新規ステップを追加、**✕ 削除** で削除
4. **💾 保存** をクリックすると `attack_config.ini` に書き込まれます
5. **+ 新規シナリオ** で新しいシナリオを作成（既存シナリオからのコピーも可能）
6. **🗑 削除** でシナリオを削除

> [!WARNING]
> 実行中のセッションがある場合、保存・削除は HTTP 409 でブロックされます。
> 編集前にすべての実行中セッションを停止してください。

---

### タブ 5 — セットアップ

ブラウザ上から ZANSIN の Ansible プレイブックを実行できます。*（Admin のみ）*

**利用可能条件**（両方を満たす必要があります）：
- `./web_controller.sh` で Web Controller を起動している（`ZANSIN_REPO_DIR` が設定されている）
- `web_controller.sh` を実行しているマシンの PATH に `ansible-playbook` がある

どちらかの条件を満たしていない場合、タブには利用不可の理由が表示されます。

**使い方：**

1. トレーニングマシンの IP（複数可）、コントロールサーバーの IP、SSH パスワードを入力
2. プロビジョニング対象（スコープ）を選択：
   - **全体** — トレーニングマシンとコントロールサーバーの両方を構築
   - **トレーニングのみ** — トレーニングマシンのみ構築（`zansin-control-server` ロールをスキップ）
3. **▶ Ansible 実行** をクリックしてプレイブックを開始
4. Ansible の出力が SSE でリアルタイムにストリーミング表示されます

> [!NOTE]
> セットアップタブは systemd でサービスを起動している場合は意図的に無効化されます（`ZANSIN_REPO_DIR` が設定されないため）。
> ブラウザからプロビジョニングを行いたい場合は、ローカルマシンから `./web_controller.sh` で起動してください。

---

### タブ 6 — トレーニング環境

SSH 経由でトレーニングマシンのサービス状態を確認・制御できます。*（Admin のみ）*

トレーニングマシンの IP を入力し **🔍 確認** をクリックすると、SSH で接続してサービス状態を取得します。

**監視対象サービス：**

| サービス | ポート | 確認方法 | Docker コンテナ |
|---------|------|---------|--------------|
| nginx | 80 | HTTP | — （ホストプロセス）|
| phpapi | 8080 | HTTP | `phpapi` |
| apidebug | 3000 | HTTP | `apidebug` |
| phpmyadmin | 5555 | HTTP | `phpmyadmin` |
| mysql (db) | 3306 | TCP | `db` |
| redis | 6379 | TCP | `redis` |

**操作：**

| ボタン | 動作 |
|-------|------|
| **▶ 全サービス起動** | トレーニングマシンで `docker-compose up -d` を実行 |
| **■ 全サービス停止** | トレーニングマシンで `docker-compose down` を実行 |
| **↺ 再起動**（各行） | 対象サービスの `docker restart <コンテナ名>` を実行 |

SSH 接続に使用する認証情報: `vendor` / `Passw0rd!23`（CLAUDE.md に記載の意図的なデフォルト値）

---

### タブ 7 — ドキュメント

ZANSIN のドキュメントをブラウザ上で閲覧できます。*（全ユーザー）*

- **ファイル一覧** — コントロールサーバーの `documents/` 配下のファイルが表示されます
  - `.md` ファイルをクリックすると Markdown としてレンダリングされます
  - **EN**（英語）・**JA**（日本語）ボタンで言語を切り替えられます
  - **⬇ ダウンロード** をクリックするとファイルをローカルに保存できます
- **画像対応** — Markdown 内で参照される画像（`/api/images/` 経由）は `documents/` と並列の `images/` ディレクトリから配信されます
- **再読み込み** — 更新ボタン（↺）でファイル一覧を再取得できます

---

### タブ 8 — VPN管理

WireGuard VPN ピアの管理と学習者への割り当てを行います。*（Admin のみ）*

#### ネットワーク概要

```
[学習者のラップトップ]  ──WireGuard──▶  [コントロールサーバー :51820 UDP]  ──SSH/HTTP──▶  [トレーニングマシン]
    10.100.0.2–31                             10.100.0.1                              <training_ip>
```

- **サブネット**: `10.100.0.0/24`
- **サーバー IP**: `10.100.0.1`（コントロールサーバーの WireGuard アドレス）
- **クライアント IP**: `10.100.0.2` 〜 `10.100.0.31`（client1 〜 client30）
- **ポート**: UDP 51820
- **ルーティング**: スプリットトンネル — 学習者が割り当てられた特定のトレーニングマシン IP へのトラフィックのみ VPN 経由でルーティング

#### 前提条件

WireGuard の鍵は Ansible デプロイ（セットアップタブまたは `zansin.sh`）の一部として自動生成されます。手動手順は不要です。

コントロールサーバーの IP 変更後など、鍵を再生成する必要がある場合のみ以下を実行してください：

```bash
bash /opt/zansin/red-controller/wireguard_setup.sh <コントロールサーバーのIP>
```

これにより `/opt/zansin/red-controller/wireguard/` 以下のサーバーおよびクライアントの鍵ペアが再生成されます。

#### ピアの割り当て手順

1. **ユーザー一覧** — 登録済みの全ユーザーと現在のピア割り当て状況が表示されます
2. **ピア一覧** — 30 個の WireGuard ピア（`client1`〜`client30`）と割り当て状況が表示されます
3. ピアを割り当てる：
   - ピア行のドロップダウンからユーザー名を選択
   - **Training IP**（学習者のトレーニングマシンの IP）を入力
   - **割り当て** をクリック
4. 割り当て解除：ドロップダウンで「— 解除 —」を選択して **割り当て** をクリック

#### クライアント設定ファイルのダウンロード

Training IP が割り当てられたピアの行にある **⬇ ダウンロード** をクリックすると `.conf` ファイルをダウンロードできます。

設定ファイルはオンデマンドで生成され、以下の情報を組み合わせて作成されます：
- クライアント秘密鍵（`wireguard/clients/<peer-id>_private.key`）
- サーバー公開鍵（`wireguard/server_public.key`）
- コントロールサーバー IP（`wireguard/control_ip.txt`）
- トレーニングマシン IP（ピア割り当てから取得）

割り当てられた学習者は、タブ上部の **My VPN Config** から自分の設定ファイルをダウンロードすることもできます。

#### 設定ファイルのインストール（学習者側）

```bash
# WireGuard をインストール
sudo apt install wireguard

# .conf ファイルを配置
sudo cp client1.conf /etc/wireguard/zansin.conf

# VPN の起動・停止
sudo wg-up zansin     # 起動
sudo wg-down zansin   # 停止
```

Windows・macOS の場合は WireGuard GUI アプリに `.conf` ファイルをインポートしてください。

---

## ユーザー管理

*（Admin のみ — VPN 管理タブのユーザー一覧セクションから操作）*

### ユーザーの作成（Web UI）

1. **タブ 8（VPN 管理）** を開き、**ユーザー管理** セクションまでスクロールする
2. ユーザー名・パスワード・ロールを入力する
3. **＋ 作成** をクリックする

### ユーザーの削除（Web UI）

1. **タブ 8（VPN 管理）** を開き、ユーザー一覧から対象ユーザーを見つける
2. そのユーザーの行にある **[削除]** ボタンをクリックする

> [!NOTE]
> `admin` ユーザーは削除できません。

### 代替手段：API（CLI）

スクリプトから操作する場合や Web UI にアクセスできない場合は以下の `curl` コマンドを使用してください。

**ユーザーの追加：**

```bash
# セッション Cookie の取得（実際の認証情報に置き換えてください）
curl -s -c /tmp/z.cookie -X POST http://<コントロールIP>:8888/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# trainee ユーザーの作成
curl -s -b /tmp/z.cookie -X POST http://<コントロールIP>:8888/api/admin/users \
  -H "Content-Type: application/json" \
  -d '{"username":"learnerA","password":"<パスワード>","role":"trainee"}'
```

**ユーザーの削除：**

```bash
curl -s -b /tmp/z.cookie -X DELETE http://<コントロールIP>:8888/api/admin/users/learnerA
```

### users.json の構造

```json
[
  {
    "username": "admin",
    "password": "sha256:<salt>:<hash>",
    "role": "admin"
  },
  {
    "username": "trainee",
    "password": "sha256:<salt>:<hash>",
    "role": "trainee",
    "wg_peer": null,
    "training_ip": null
  }
]
```

| フィールド | 説明 |
|-----------|------|
| `username` | ログイン名 |
| `password` | `sha256:<16文字16進数ソルト>:<sha256の16進数ハッシュ>` |
| `role` | `"admin"` または `"trainee"` |
| `wg_peer` | 割り当て済みの WireGuard ピア ID（例: `"client1"`）または `null` |
| `training_ip` | VPN ルーティング用のトレーニングマシン IP、または `null` |

---

## ファイル構成

```
/opt/zansin/red-controller/              ← コントロールサーバーにデプロイされる場所
├── red_controller.py                    ← CLI エントリポイント
├── config.ini
├── requirements.txt                     ← fastapi・uvicorn・paramiko を追加済み
├── users.json                           ← ユーザー認証情報（自動生成）
├── attack/
│   └── attack_config.ini               ← シナリオ編集タブから変更される
├── crawler/
│   └── crawler_sql.py                  ← ZANSIN_SESSION_DIR 対応済み
├── judge/
│   └── judge_sql.py                    ← ZANSIN_SESSION_DIR 対応済み
├── sessions/                           ← 演習実行時に自動生成
│   └── <session-id>/
│       └── sqlite3/
│           ├── judge.db
│           └── crawler_<学習者名>.db
├── wireguard/                          ← wireguard_setup.sh が作成
│   ├── server_public.key
│   ├── control_ip.txt
│   └── clients/
│       ├── client1_private.key
│       ├── client1_public.key
│       └── ... (client30 まで)
├── documents/                          ← zansin.sh がリポジトリから同期
│   ├── WebController.md
│   └── ja/
│       └── WebController_ja.md
└── web_controller/
    ├── main.py                          ← FastAPI エントリポイント
    ├── models.py                        ← Pydantic モデル定義
    ├── auth.py                          ← 認証 + ユーザー CRUD
    ├── session_manager.py               ← セッション管理・ログストリーミング
    ├── db_reader.py                     ← SQLite 読み取り・スコア集計
    ├── config_editor.py                 ← シナリオ設定の読み書き
    ├── vpn_manager.py                   ← WireGuard 設定ファイル生成
    ├── setup_runner.py                  ← ansible-playbook 実行 + SSE
    ├── training_checker.py              ← SSH 経由サービス監視
    └── static/
        └── index.html                   ← 8タブ シングルページフロントエンド
```

---

## 動作確認チェックリスト

デプロイ後、以下の項目を順番に確認してください。

```bash
# 1. サービスが起動しているか
sudo systemctl status zansin-web-controller
# 期待値: Active: active (running)

# 2. ポートが LISTEN 状態か
ss -tlnp | grep 8888
# 期待値: 0.0.0.0:8888

# 3. 未認証リクエストが拒否されるか
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/api/sessions
# 期待値: 401

# 4. ログインして Cookie を取得
curl -s -c /tmp/z.cookie -X POST http://localhost:8888/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'
# 期待値: {"username":"admin","role":"admin"}

# 5. 認証済みリクエストが成功するか
curl -s -b /tmp/z.cookie http://localhost:8888/api/sessions
# 期待値: [] （初回は空リスト）

# 6. sessions ディレクトリが存在するか
ls /opt/zansin/red-controller/sessions/
# 期待値: ディレクトリが存在する（初回は空）

# 7. VPN の設定状態を確認
curl -s -b /tmp/z.cookie http://localhost:8888/api/vpn/status
# 期待値: {"configured": true, ...}  （wireguard_setup.sh 実行済みの場合）

# 8. セットアップタブの利用可否を確認（web_controller.sh 経由の場合のみ有効）
curl -s -b /tmp/z.cookie http://localhost:8888/api/setup/available
# web_controller.sh 経由: {"available": true, "reasons": []}
# systemd 経由:           {"available": false, "reasons": ["ZANSIN_REPO_DIR 未設定..."]}
```

### テスト：API からセッションを起動する

```bash
curl -s -b /tmp/z.cookie -X POST http://localhost:8888/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "learner_name": "test",
    "training_ip": "<トレーニングマシンのIP>",
    "control_ip": "<コントロールサーバーのIP>",
    "scenario": 0
  }'
# 期待値: {"session_id":"<UUID>"}
```

### テスト：SQLite の隔離を確認する

```bash
# セッションディレクトリが作成されているか
ls /opt/zansin/red-controller/sessions/
# セッション ID ごとのディレクトリが表示される

# SQLite ファイルが隔離されているか
ls /opt/zansin/red-controller/sessions/<session-id>/sqlite3/
# 期待値: judge.db と crawler_test.db が演習開始後に生成される
```

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `http://<IP>:8888` に繋がらない | ファイアウォールでポートがブロックされている | `sudo ufw allow 8888/tcp` |
| サービスが起動しない | `fastapi`/`uvicorn` がインストールされていない | Ansible を再実行するか `pip install -r requirements.txt` を手動実行 |
| ログイン画面が消えない | Cookie が設定されないかセッション切れ | ブラウザの Cookie をクリアし、ポート 8888 からの Cookie を受け入れているか確認 |
| すべての API リクエストで 401 | ログインしていない、または Cookie がない | ブラウザからログインするか、curl に `-b <cookieファイル>` を付与 |
| セッションを開始したがログが流れない | `red_controller.py` へのパスが誤っている | `ZANSIN_RC_DIR` 環境変数を確認し、`/opt/zansin/red-controller/red_controller.py` が存在するか確認 |
| 演習終了後もスコアが `—` のまま | SQLite への書き込みが未完了 | 少し待ってから **↻ 更新** を押す。ジャッジはクロール+攻撃スレッドの終了後に実行される |
| 「実行中のセッションがあるため保存できません」 | 実行中のセッションがある | 実行中のセッションを全て停止してから保存する |
| `ModuleNotFoundError: web_controller` | uvicorn を間違ったディレクトリで起動している | systemd ユニットの `WorkingDirectory` が `/opt/zansin/red-controller` になっているか確認 |
| VPN タブに「WireGuard が未設定」と表示される | Ansible 未実行または鍵ファイルが消失 | セットアップタブ（または `zansin.sh`）を再実行する。鍵を再生成する必要がある場合は `bash /opt/zansin/red-controller/wireguard_setup.sh <コントロールIP>` を実行 |
| VPN .conf ダウンロードで 409 エラー | ピアに Training IP が設定されていない | ダウンロード前にピアへ Training IP を割り当てる |
| WireGuard 鍵が読み込めない | `zansin` グループが未追加または未反映 | `sudo usermod -aG zansin $USER` を実行後、`./web_controller.sh restart` で再起動 |
| セットアップタブに「利用不可」と表示される | `ZANSIN_REPO_DIR` が未設定 | systemd ではなく `./web_controller.sh` で起動する |
| セットアップタブ：「ansible-playbook が見つかりません」 | Ansible がインストールされていない | `web_controller.sh` を実行するマシン上で `sudo apt install ansible` を実行 |
