# ZANSIN Web Controller

ZANSIN Web Controller は、Red Controller をブラウザから操作するためのインターフェースです。
インストラクターは CLI を使わずに、複数学習者への同時演習実行・ログのリアルタイム監視・スコアの比較・攻撃シナリオの編集をすべてブラウザ上で行えます。

---

## アーキテクチャ概要

```
[ブラウザ]  ←HTTP/SSE→  [Web Controller :8888]  ←サブプロセス→  [red_controller.py]
                              │
                              ├── session_manager.py   (プロセス管理 + ログストリーミング)
                              ├── db_reader.py          (セッション別 SQLite 読み取り)
                              └── config_editor.py      (attack_config.ini の読み書き)
```

- **バックエンド**: FastAPI + Server-Sent Events (SSE)
- **フロントエンド**: シングルページ HTML（Vanilla JS + Tailwind CSS CDN、ビルド不要）
- **ポート**: 8888（コントロールサーバー上）
- **セッション分離**: 学習者ごとに独立したプロセスで演習を実行し、SQLite データベースを `~/red-controller/sessions/<session-id>/sqlite3/` に隔離して保存

---

## 前提条件

> [!IMPORTANT]
> Web Controller は**コントロールサーバー上**で動作します。
> Ansible プレイブックによるデプロイが完了していないと動作しません。
> ローカル開発マシン上でのテストは、デプロイなしには行えません。

作業を始める前に以下を確認してください：

- `zansin.sh` / Ansible プレイブックにより、両マシン（コントロールサーバー・トレーニングマシン）のプロビジョニングが完了している
- `zansin` ユーザーでコントロールサーバーに SSH できる
- コントロールサーバー上に `~/red-controller/` が存在する（Ansible が作成）

---

## デプロイ方法

### 自動デプロイ（推奨）

**`zansin.sh` を実行するだけで、Web Controller も含めてすべてが自動でセットアップされます。**

```bash
chmod +x zansin.sh
./zansin.sh
```

スクリプトは内部で以下を順番に実行します：

1. Ansible プレイブックでトレーニングマシンを構築
2. `rsync` でコントロールサーバーへファイルを転送（`web_controller/` を含む）
3. コントロールサーバー上で venv 作成 + `pip install`（`fastapi`・`uvicorn` を含む）
4. `sessions/` ディレクトリを作成
5. `zansin-web-controller` systemd サービスを登録・起動

`zansin.sh` の完了後、コントロールサーバー上でサービスが自動起動した状態になります。

### 手動デプロイ（再デプロイや既存環境への追加時）

コントロールサーバーに `zansin` ユーザーで SSH した後：

```bash
# 1. ファイルのコピー（リポジトリからコントロールサーバーへ）
rsync -avz playbook/roles/zansin-control-server/files/. zansin@<control-ip>:~/red-controller/

# 2. コントロールサーバー上で依存パッケージをインストール
source ~/red-controller/red_controller_venv/bin/activate
pip install -r ~/red-controller/requirements.txt
deactivate

mkdir -p ~/red-controller/sessions

# 3. systemd サービスを登録・起動
sudo tee /etc/systemd/system/zansin-web-controller.service > /dev/null << 'EOF'
[Unit]
Description=ZANSIN Web Controller
After=network.target

[Service]
Type=simple
User=zansin
WorkingDirectory=/home/zansin/red-controller
ExecStart=/home/zansin/red-controller/red_controller_venv/bin/uvicorn web_controller.main:app --host 0.0.0.0 --port 8888 --workers 1
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

```bash
# 状態確認
sudo systemctl status zansin-web-controller

# 起動
sudo systemctl start zansin-web-controller

# 停止
sudo systemctl stop zansin-web-controller

# ログ確認
sudo journalctl -u zansin-web-controller -f
```

デバッグ時などにフォアグラウンドで直接起動することもできます：

```bash
cd ~/red-controller
source red_controller_venv/bin/activate
uvicorn web_controller.main:app --host 0.0.0.0 --port 8888
```

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

## UI の構成（4タブ）

### タブ 1 — 演習管理

複数学習者の演習を一元管理します。

| 入力項目 | 説明 |
|---------|------|
| 学習者名 | ログとスコアに使用する識別子（例：`learnerA`）|
| Training IP | 学習者のトレーニングマシンの IP アドレス |
| Control IP | このコントロールサーバーの IP アドレス |
| シナリオ | `0`=Dev、`1`=最難度（全攻撃）、`2`=中難度 |

**▶ 開始** をクリックすると演習が起動し、セッション一覧に表示されます。

- **● 実行中** — 演習が進行中
- **■ 終了** — 演習終了済み。Technical Point と Operation Ratio が表示されます
- **■ 停止** — 実行中のセッションに SIGTERM を送信して停止

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

### タブ 4 — シナリオ編集

`attack_config.ini` の内容をブラウザ上で直接編集できます。

1. シナリオ番号（0・1・2）を選択
2. ステップ ID・遅延時間・アクション・Cheat Count をインラインで編集
3. **+ ステップ追加** で新規ステップを追加、**✕ 削除** で削除
4. **💾 保存** をクリックすると `attack_config.ini` に書き込まれます

> [!WARNING]
> 実行中のセッションがある場合、保存は HTTP 409 でブロックされます。
> 編集前にすべての実行中セッションを停止してください。

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

# 3. API が応答するか
curl http://localhost:8888/api/sessions
# 期待値: [] （初回は空リスト）

# 4. sessions ディレクトリが存在するか
ls ~/red-controller/sessions/
# 期待値: ディレクトリが存在する（初回は空）
```

### テスト：API からセッションを起動する

```bash
curl -X POST http://localhost:8888/api/sessions \
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
ls ~/red-controller/sessions/
# セッション ID ごとのディレクトリが表示される

# SQLite ファイルが隔離されているか
ls ~/red-controller/sessions/<session-id>/sqlite3/
# 期待値: judge.db と crawler_test.db が演習開始後に生成される
```

---

## ファイル構成

```
~/red-controller/                        ← コントロールサーバーにデプロイされる場所
├── red_controller.py                    ← CLI エントリポイント（変更なし）
├── config.ini
├── requirements.txt                     ← fastapi・uvicorn を追加済み
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
└── web_controller/
    ├── main.py                          ← FastAPI エントリポイント
    ├── models.py                        ← Pydantic モデル定義
    ├── session_manager.py               ← セッション管理・ログストリーミング
    ├── db_reader.py                     ← SQLite 読み取り・スコア集計
    ├── config_editor.py                 ← シナリオ設定の読み書き
    └── static/
        └── index.html                   ← フロントエンド（4タブ SPA）
```

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| `http://<IP>:8888` に繋がらない | ファイアウォールでポートがブロックされている | `sudo ufw allow 8888/tcp` |
| サービスが起動しない | `fastapi`/`uvicorn` がインストールされていない | Ansible を再実行するか `pip install -r requirements.txt` を手動実行 |
| セッションを開始したがログが流れない | `red_controller.py` へのパスが誤っている | `session_manager.py` の `VENV_PYTHON` と `RED_CONTROLLER_PATH` を確認 |
| 演習終了後もスコアが `—` のまま | SQLite への書き込みが未完了 | 少し待ってから **↻ 更新** を押す。ジャッジはクロール+攻撃スレッドの終了後に実行される |
| 「実行中のセッションがあるため保存できません」 | 実行中のセッションがある | 実行中のセッションを全て停止してから保存する |
| `ModuleNotFoundError: web_controller` | uvicorn を間違ったディレクトリで起動している | systemd ユニットの `WorkingDirectory` が `/home/zansin/red-controller` になっているか確認 |
