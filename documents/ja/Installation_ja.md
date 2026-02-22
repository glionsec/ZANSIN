# 必要要件

- **Ubuntu 20.04 Server** 以上
- プラットフォームは問いません（物理環境、仮想環境、パブリッククラウドいずれも可）。ただし、演習を複数回実施する可能性を考慮すると、スナップショット作成が可能な **VirtualBox** の使用が推奨されます。
- 2台のLinuxマシンが**相互に通信できる**状態で、かつ**パスワード認証によるSSH接続**が可能である必要があります。
  - 演習開始時の初期状態において、2台のLinuxホスト間に**通信制限がない**状態にしてください。
- 2台のLinuxマシンが**インターネットにアクセスできる**必要があります。
- 両マシンに **`sudo` 権限を持つ `zansin`** という名前のユーザーアカウントが必要で、**両マシンのパスワードは同一**でなければなりません。
- 推奨スペック：各Linuxホストに2GB以上のRAMと1CPU以上。

> [!Caution]
> パブリッククラウドでZANSIN環境をデプロイする場合、ファイアウォールのインバウンドルールで送信元IPアドレスを制限するか、SSHのみを公開することを強く推奨します。そうしないと、脆弱なサーバーがインターネット上に公開されてしまいます。


# Linuxのインストール

以下の例は、VirtualBoxにUbuntu Server 22.04.4 LTSをインストールする場合を想定しています。
ZANSINは2台のLinuxホストを必要とするため、このインストール手順を2回繰り返す必要があります。

1. Ubuntuのインストール中に、以下の設定を行ってください：
   - インストールタイプとして `Ubuntu Server` を選択します。
   - ユーザー作成時に、ユーザー名を `zansin` に設定し、両マシンに同じパスワードを使用します。
   - SSHセットアップ画面で `Install OpenSSH Server` にチェックを入れます。
2. インストール後、仮想マシン間の接続とインターネットアクセスを容易にするため、ネットワークアダプターの設定で「ブリッジアダプター」を使用します。

Ubuntuのインストール中に `zansin` ユーザーの作成またはOpenSSHのインストールができなかった場合は、Ubuntuにログインした後に以下のコマンドを実行してください。

## ZANSINユーザーの作成

```bash
sudo useradd zansin
sudo usermod -aG sudo zansin
echo "zansin:YOUR_PASSWORD" | sudo chpasswd
```

## OpenSSHのインストール

```bash
sudo apt update
sudo apt install openssh-server
```

# ZANSINのデプロイ

ZANSINをインストールする前に、両マシンのIPアドレスを確認してください。

> [!Note]
> これらのアドレスはZANSINコントロールサーバーからZANSINトレーニングマシンへの接続に使用されるため、グローバルIPアドレスである必要はありません。

1. `zansin` ユーザーでZANSINコントロールサーバーにログインします。

2. GitHubリポジトリから `zansin.sh` をダウンロードします：

    ```bash
    wget https://raw.githubusercontent.com/ZANSIN-sec/ZANSIN/main/zansin.sh
    ```

3. `zansin.sh` に実行権限を付与して実行します：
    ```bash
    chmod +x zansin.sh
    ./zansin.sh
    ```
