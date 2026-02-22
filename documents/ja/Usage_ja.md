# 使い方

## 演習開始前

繰り返し演習を行えるよう、可能であれば現在のマシンのスナップショットを取得しておきましょう。

## 演習の開始

ZANSINコントロールサーバーとZANSINトレーニングマシンの準備が整ったら、**ZANSINコントロールサーバー**と**ZANSINトレーニングマシン**の両方にSSHでログインする必要があります。

> [!NOTE]
> **ZANSINコントロールサーバー**は、ZANSINコントロールサーバーからZANSINトレーニングマシンへのクローリング（ゲームプレイ）と攻撃を担います。
>
> **ZANSINトレーニングマシン**は、脆弱性の修正とインシデント対応を行う場所です。

### ZANSINコントロールサーバー

事前に設定した `zansin` ユーザーとパスワードで**ZANSINコントロールサーバー**にログインし、**Red Controller**を実行して演習を開始します。

#### 仮想環境の有効化

**Red Controller**は、Pythonの仮想環境 `red_controller_venv` を使用して実行されます。次のコマンドで**Red Controller**の仮想環境を有効化してください。

```bash
zansin@hostname:~$ source red-controller/red_controller_venv/bin/activate
(red_controller_venv) zansin@hostname:~$
```

> [!NOTE]
> 演習が終了したら、次のコマンドで仮想環境を無効化してください。
> ```bash
> (red_controller_venv) zansin@hostname:~$ deactivate
> ```

#### Red Controllerの実行

**Red Controller**は以下のコマンドオプションで実行できます。

```bash
(red_controller_venv) zansin@hostname:~$ cd red-controller/
(red_controller_venv) zansin@hostname:~/red-controller$ python3 red_controller.py -h
usage:
    red_controller.py -n <name> -t <training-server-ip> -c <control-server-ip> -a <attack-scenario>
    red_controller.py -h | --help
options:
    -n <name>                 : 学習者名（例：Taro Zansin）
    -t <training-server-ip>   : ZANSINトレーニングマシンのIPアドレス（例：192.168.0.5）
    -c <control-server-ip>    : ZANSINコントロールサーバーのIPアドレス（例：192.168.0.6）
    -a <attack-scenario>      : 攻撃シナリオ番号（例：1）
    -h --help                 : このヘルプメッセージを表示して終了
```

**Red Controller**の実行例を以下に示します。

```bash
(red_controller_venv) zansin@hostname:~/red-controller$ python3 red_controller.py -n first_learner -t 192.168.0.5 -c 192.168.0.6 -a 1
```

オプション `-a`（攻撃シナリオ）は、演習で使用する攻撃シナリオ番号を指定します。
現在のバージョンのZANSINでは以下の攻撃シナリオが提供されています。お好みのシナリオを選んでお楽しみください！

#### 攻撃シナリオ

| No. | 説明 |
| ---- | ---- |
| 0 | 開発用。通常は使用しません。 |
| 1 | 状況に応じてすべての攻撃パターンを試みます。最も難易度が高いモードです。 |
| 2 | 攻撃の約半数を試みます。各攻撃の間隔もシナリオ1より長めです。 |

#### スコアの確認

演習が終了すると、画面に以下のスコアが表示されます。

```bash
+----------------------------------+----------------------------------+
| Technical Point (Max 100 point)  | Operation Ratio (Max 100 %)      |
|----------------------------------+----------------------------------+
| Your Score : 70 point            | Your Operation Ratio : 60 %      |
+----------------------------------+----------------------------------+
```

左側の `Technical Point` は、攻撃に適切に対処できたかどうかを評価する技術点です。右側の `Operation Ratio` は、演習全体を通じてクローラーがゲームを正常に実行できた割合（稼働率）です。

### ZANSINトレーニングマシン

演習のため、認証情報 `vendor`/`Passw0rd!23` を使用してSSHで**ZANSINトレーニングマシン**にログインしてください（`zansin` アカウントではありません！）。

サイバー攻撃やゲーム内チート行為が広がる前に、ゲームAPIだけでなくZANSINトレーニングマシン全体の環境を確認し、脆弱性を修正しましょう。

サイバー攻撃やゲームチートと思われる不審な動作に気づいたら、できる限り迅速に対応してください。

ZANSINトレーニングマシンの環境の詳細については、[シナリオ - MINI QUEST](./MINIQUEST_ja.md) ページをご参照ください。



**Technical Point** と **Operation Ratio** の両方でパーフェクトスコアを目指してがんばってください！
