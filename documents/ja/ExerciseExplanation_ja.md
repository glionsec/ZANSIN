> [!IMPORTANT]
> ***このドキュメントはトレーニングマシンの脆弱性と演習で実施される攻撃を解説しているため、演習の答えを知りたくない場合はネタバレにご注意ください。***

# トレーニングマシンの脆弱性

以下に、このトレーニングマシンに存在する脆弱性と考えられる緩和策を説明します。

## 脆弱なパスワード

### 概要

トレーニングマシンのLinuxアカウントとMySQLの初期パスワードは推測しやすいものになっています。
この脆弱性により攻撃を受けやすくなっており、放置すると悪用される可能性があります。

| 種別 | 初期パスワード |
| ---- | ---- |
| Linuxアカウント | Passw0rd!23 |
| MySQL | password |
| redis | なし |

### 緩和策

* 強力なパスワードに変更する。
* パスワードクラッキングを防止または軽減する設定を行う。
    - SSHは公開鍵認証のみを有効にし、アカウントロックアウトを実装して不正アクセスを最小限に抑える。
    - 外部公開が不要なサービスにはアクセス制御を実装する。

## 不要なサービスの公開

### 概要

Dockerコンテナで実行されている各サービスにはアクセス制御がなく、一部のサービスのポートが外部ネットワークに公開されています。
この状況により、開いているポートへのアクセスを通じてサービスが悪用される可能性があります。

| 稼働中のサービス | ポート番号 |
| ---- | ---- |
| MySQL | 3306 |
| Redis | 6379 |
| phpMyAdmin | 5555 |
| APIデバッグコンテンツ | 3000 |

### 緩和策

* 各ポートにアクセス制御を実装する。
    - `docker-compose.yml` を変更する
    - クライアント側のファイアウォールで制御する
* サービス要件上不要なコンテナを停止する

## Docker設定の脆弱性

### 概要

ゲームサーバーでは、Docker APIが使用するポート2375/TCPが外部に公開されており、第三者がDockerの操作を操作できる危険な状況が生じています。この脆弱性は演習中に悪意のあるAlpine Linuxコンテナイメージを作成・起動して攻撃を行うために悪用されます。

### 緩和策

* ポートの設定変更とアクセス制御を実装する。

[設定変更の手順]
`/lib/systemd/system/docker.service` の以下の部分を変更します：
```
ExecStart=/usr/bin/dockerd -H fd:// -H=tcp://0.0.0.0:2375 --containerd=/run/containerd/containerd.sock
↓
ExecStart=/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
```
新しい設定を正しく適用するには、以下を入力します：
```
sudo systemctl daemon-reload
sudo systemctl restart docker
```

## SQLインジェクション

### 概要

ログイン処理（`login.php`）とユーザー登録処理（`new_user.php`）にSQLインジェクションの脆弱性があります。これらの脆弱性は、クライアントから渡された値を直接受け入れてSQLステートメントを動的に生成するために発生しています。

`login.php`
```php
$user_name = $request_json->user_name; //ユーザー入力
$password = $request_json->password; // ユーザー入力
$image = "default.png";

$pdo = connect_db();
$sql = "select * from player where user_name = '$user_name' and password = '$password'";
$login_stmt= $pdo->query($sql);
$row = $login_stmt->fetch(PDO::FETCH_ASSOC);
```

`new_user.php`
```php
$user_name = $request_json->user_name; //ユーザー入力
$password = $request_json->password; // ユーザー入力
$nick_name = $request_json->nick_name; // ユーザー入力
$image = "default.png";

$pdo = connect_db();

// 重複チェック

$dup_stmt = $pdo->query("select count(*) from player where user_name = '$user_name';");
$dup_count = $dup_stmt->fetchColumn();
```

### 緩和策

* プリペアドステートメントを使用してSQLステートメントを構築する。
* 入力文字列をエスケープする。

[PHPコード変更例]

`login.php`
```php
$user_name = $request_json->user_name; //ユーザー入力
$password = $request_json->password; // ユーザー入力
$image = "default.png";

$pdo = connect_db();
$sql = "SELECT * FROM player WHERE user_name = :user_name AND password = :password";
$login_stmt = $pdo->prepare($sql);
$login_stmt->bindParam(':user_name', $user_name, PDO::PARAM_STR);
$login_stmt->bindParam(':password', $password, PDO::PARAM_STR);
$login_stmt->execute();
$row = $login_stmt->fetch(PDO::FETCH_ASSOC);
```

`new_user.php`
```php
$user_name = $request_json->user_name; //ユーザー入力
$password = $request_json->password; // ユーザー入力
$nick_name = $request_json->nick_name; // ユーザー入力
$image = "default.png";

$pdo = connect_db();

// 重複チェック

$dup_stmt = $pdo->prepare("SELECT COUNT(*) FROM player WHERE user_name = :user_name");
$dup_stmt->bindParam(':user_name', $user_name, PDO::PARAM_STR);
$dup_stmt->execute();
$dup_count = $dup_stmt->fetchColumn();
```

## 画像アップロード処理の実装上の欠陥

### 概要

画像アップロード処理（`upload.php`）に脆弱性があります。
この脆弱性は、クライアントから受け取ったファイル名をもとに文字列の結合だけでファイルパスを生成しているため、パストラバーサル脆弱性が生じています。
また、アップロードされたファイルに対するチェック処理がなく、任意のファイルをアップロードすることが可能です。これにより、PHPファイルなどの任意のコードをアップロードして実行することが可能になります。

`upload.php`
```php
$target_file = "./images/players/" . $request_json->file_name;

. . .

try {
    ob_start();
    $file = file_put_contents($target_file, base64_decode($request_json->file_data));
    if ($file) {
        echo json_encode(array("result" => "ok"));
    } else {
        $warning = ob_get_contents();
        ob_end_clean();
        if ($warning) {
            throw new Exception($warning);
        }
        echo json_encode(array(
                "result" => "ng",
                "message" => "unknown error")
        );
    }
} catch (Exception $e) {
    echo json_encode(array(
        "result" => "ng",
        "message" => $e->getMessage()
    ));
}
```

### 緩和策

* アップロード処理に入力値検証を実装する（ファイル名と拡張子の両方）。

[PHPコード変更例]

`upload.php`
```php
//basename関数を使用した相対パス検証
$tmpname = basename($request_json->file_name);

//ファイル名の検証
if(preg_match('/^[0-9]*_[0-9]*.[a-z]*$/', $tmpname)){

    //拡張子の検証
    $allowed_extensions = ['jpg', 'jpeg' ,'png', 'gif'];
    $extension = strtolower(pathinfo($tmpname , PATHINFO_EXTENSION));

    if (!in_array($extension, $allowed_extensions)) {
        echo json_encode(array(
            "result" => "ng",
            "msg" => "サポートされていないファイル形式です。jpg、png、gifのみ使用できます。"));
        exit();
    }
}
else{
    echo json_encode(array(
        "result" => "ng",
        "msg" => "ファイル名の形式が無効です。"));
    exit();
}

$target_file = "./images/players/" . $tmpname;
```

## 認証のない管理パネル

### 概要

管理パネル（`user_list.php`）はユーザー削除などの管理者向け機能を持つページです。しかし、認証機能がないため誰でもアクセスできます。これにより、第三者が登録ユーザー情報にアクセスしたり、意図せずデータを削除したりするリスクがあります。

### 緩和策

* 管理パネルにアクセス制御を設ける。
    - 認証機能の追加（例：Basic認証）
    - IPアドレス制限の実装

## バトル処理の実装上の欠陥

### 概要

バトル処理（`course.php`）のコース情報取得のレスポンスに、ゲーム画面に表示されないデバッグ用モンスターがデータ内に存在することが確認できます。
これらのモンスターはデバッグ目的で存在するため、HPが低く設定されており、倒すと非常に多くの経験値とゴールドが得られます。そのため、これらのモンスターを選択してバトルすることで、簡単にレベルアップすることが可能です。

![デバッグ用モンスターの存在](../../images/courseget-response.png)

バトル処理（`battle.php`）で渡されるパラメータはHMACを使ったパラメータ改ざん検知の意図で実装されているようです。しかし実装に欠陥があり、パラメータ値を操作することで不正なレベルアップが可能です。

現在のコードは、HTTPリクエストで渡されたHMACパラメータの値を単純に比較しているだけで、実際には検証していないため、検証の意味をなしていません。また、プログラム内にHMAC値の比較の痕跡はありますが、`check_hmac` 関数を確認すると未実装のままで、値を正しく検証していないことがわかります。

`battle.php`
```php
//
// HMACの確認
//
// 戻り値:
// 汎用リターンコード
function check_hmac($hmac, $hmac_old) {
  $ret = 1; # 後で実装します...
  return $ret;
}
```

### 緩和策

* ゲーム画面に表示されるコースのみを選択できるよう入力値を制限する。

[PHPコード変更例]

`course.php`
```php
    //数値の範囲を検証
    if($request_json->{"id"} < 1 || $request_json->{"id"} > 5){
      $result["msg"] = "無効な番号です";
      echo json_encode($result);
      exit();
    }
```

* リクエストで受け取った各パラメータからHMAC値を生成して比較する。

[PHPコード変更例]

`battle.php`
```php
//追加コード開始

    unset($enemy_info_json->{"hmac"});
    $enemy_info_array = json_decode(json_encode($enemy_info_json), true);
    ksort($enemy_info_array);
    $einfo_json = json_encode($enemy_info_array);
    // 改ざん防止のためのHMAC追加
    $cksum = hash_hmac('sha1', $einfo_json, $hmac_secret);
    $enemy_info_json->{"hmac"} = $cksum;

    unset($player_info_json->{"hmac"});
    $player_info_array = json_decode(json_encode($player_info_json), true);
    ksort($player_info_array);
    $pinfo_json = json_encode($player_info_array);
    // 改ざん防止のためのHMAC追加
    $cksum = hash_hmac('sha1', $pinfo_json, $hmac_secret);
    $player_info_json->{"hmac"} = $cksum;

//追加コード終了

    // HMACを比較して正当性を確認
    if(
      ! check_hmac($player_info_json->{"hmac"}, $binfo_current_json->{"player"}->{"hmac"}) ||
      ! check_hmac($enemy_info_json->{"hmac"}, $binfo_current_json->{"enemy"}->{"hmac"})
    ){
      # 不正なHMAC
      $lock_flag = 0;
      set_lock_flag($redis, $redis_lock_name, $lock_flag, $max_lock_time, __LINE__);
      $result["msg"] = "HMACが正しくありませんでした; 行番号:" . __LINE__;
      echo json_encode($result);
      exit();
    }
```

* 引数として渡された値を比較し、値が等しい場合にTrueを返す `check_hmac` 関数を実装する。

[PHPコード変更例]

`battle.php`
```php
function check_hmac($hmac, $hmac_old) {
  if($hmac===$hmac_old){
    return 1;
  }else{
    return 0;
  }
}
```

## ガチャ処理の実装上の欠陥

### 概要

ガチャ処理では、支払い金額の検証がありません。そのため、HTTPリクエストのパラメータ値を改ざんすることで、指定された金額を支払わずにガチャを引くことが可能です。

`gacha.php`
```php
//現在のゴールドから支払い金額を差し引く
$result_gold = $current_gold - $post_gold;
```

### 緩和策

* 支払い金額パラメータ値の入力値検証を実装する。

[PHPコード変更例]

`gacha.php`
```php
//送信値を検証
if($post_gold !== 100 ) {
    echo json_encode(array(
        "result" => "ng",
        "msg" => "送信されたゴールドの値が無効です。"
    ));
    exit();
}
```

## プレイヤーデータ画面のBOLA（オブジェクトレベルの認可不備）

### 概要

ログイン処理（`login.php`）では、ユーザーに関連する `user_data` という値がCookieに設定されます。

`login.php`
```php
// ユーザーデータの取得
$user_cookie_data = $user_id;

setcookie('session_id', $session_id);
setcookie('user_data', $user_cookie_data);
```

プレイヤーデータ画面（`player.php`）はゲーム内のプレイヤー自身の情報を表示するために実装されています。
しかし実際には、このAPIには他のプレイヤーの情報を取得することを意図した `user_data` を使用するデバッグ機能が含まれています。

`player.php`
```php
// ログイン状態の確認
// "user_data" の確認はデバッグ専用です！
// "session_id" の確認は必須です！
if (isset($_COOKIE['user_data'])) {
    $user_id = $_COOKIE['user_data'];
} elseif (isset($_COOKIE['session_id'])) {
    $session_id = $_COOKIE['session_id'];
    $user_id = check_login($redis, $session_id);
} else {
    echo json_encode(array(
        "result" => "ng",
        "msg" => "セッションIDが必要です。"));
    exit();
}
```

`user_data` の値を操作することで、その値に紐付けられた他のゲームユーザーのプレイヤーデータ画面を閲覧することが可能です。

プレイヤーデータ画面のレスポンスデータは画面上に表示されませんが、パスワード値も出力するよう設計されています。この脆弱性を悪用してゲームユーザーのアカウントを乗っ取ることが可能です。

`player.php`
```php
// DBからプレイヤーデータを取得
$pdo = connect_db();
$stmt = $pdo->prepare("SELECT * FROM player where id =:id;");
$stmt->bindValue(':id', $user_id, PDO::PARAM_INT);
$stmt->execute();
$userData = array();
$rows_found = false;
while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
    $rows_found = true;
    $userData =[
        'id' => $row['id'],
        'user_name' => $row['user_name'],
        'password' => $row['password'],
        'nick_name' => $row['nick_name'],
        'image' => $row['image'],
        'level' => $row['level'],
        'stamina' => $row['stamina'],
        'weapon_id' => $row['weapon_id'],
        'armor_id' => $row['armor_id'],
        'gold' => $row['gold'],
        'exp' => $row['exp'],
        'created_at' => $row['created_at'],
        'staminaupdated_at' => $row['staminaupdated_at']
    ];
}
```

### 緩和策

* プレイヤーデータ画面が `session_id` Cookieの値のみに基づいてユーザーを識別するよう変更する。

[PHPコード変更例]

`player.php`
```php
if (isset($_COOKIE['session_id'])) {
    $session_id = $_COOKIE['session_id'];
    $user_id = check_login($redis, $session_id);
} else {
    echo json_encode(array(
        "result" => "ng",
        "msg" => "セッションIDが必要です。"));
    exit();
}
```

* プレイヤーデータ画面のレスポンスでパスワード文字列を出力しないよう変更する（根本的には、パスワードを平文で保存しないよう処理を見直すべきです）。

[PHPコード変更例]

`player.php`
```php
$userData =[
        'id' => $row['id'],
        'user_name' => $row['user_name'],
        'password' => "********",
        'nick_name' => $row['nick_name'],
        'image' => $row['image'],
        'level' => $row['level'],
        'stamina' => $row['stamina'],
        'weapon_id' => $row['weapon_id'],
        'armor_id' => $row['armor_id'],
        'gold' => $row['gold'],
        'exp' => $row['exp'],
        'created_at' => $row['created_at'],
        'staminaupdated_at' => $row['staminaupdated_at']
    ];
```

## デバッグコンテンツのOSコマンドインジェクション

### 概要

3000/TCPで動作するAPIデバッグコンテンツにはOSコマンドインジェクションの脆弱性があります。このコンテンツが公開されたままの場合、リモートコード実行のリスクがあります。さらに、`docker-compose.yml` を確認すると、APIデバッグコンテンツを実行しているコンテナ（`apidebug`）に `privileged` オプションが設定されていることがわかります。

この設定は重大なリスクをもたらします。コンテナ上でOSコマンドインジェクションを悪用することで、ホスト上でroot権限による任意のコマンドが実行される可能性があります。

### 緩和策

* このコンテナサービスはゲームサービスに不要なため、コンテナを停止するかポートへのアクセス制御を実装することでリスクを軽減することを検討してください。

## バックアップスクリプトの権限設定の不備

### 概要

サーバー内には `/usr/local/dbbackup` に `dbbackup.sh` という名前のMySQLバックアップスクリプトが存在し、cronを使用してrootユーザー権限で定期的に実行されるよう設定されています。
さらに、このシェルスクリプトのパーミッションが「777」に設定されています。
つまり、攻撃者がサーバーにアクセスして `dbbackup.sh` に任意のコマンドを書き込んだ場合、そのコマンドがrootユーザー権限で実行され、権限昇格につながる可能性があります。

![シェルスクリプトのパーミッション](../../images/backupsh.png)

### 緩和策

* パーミッションを変更する（「700」など適切なパーミッションに変更）。

適切なパーミッションを設定するには、以下を入力します：
```
sudo chmod 700 dbbackup.sh
```

# 演習での攻撃シナリオ

以下に、演習中に実施される攻撃の概要と、攻撃が発生した場合に想定される暫定対策を示します。

上記で説明した脆弱性を利用して、以下に説明する攻撃が演習で実行されます。各攻撃への根本的な解決策は、攻撃を引き起こす上記の脆弱性を修正することです。脆弱性が攻撃前に修正されていれば、当然ながら攻撃の影響はありません。

## バックドアのインストール

### 概要

脆弱性を利用してシステムにアクセスした後、さらなる攻撃を実行するために以下のバックドアが設置されます：

* Webシェルのインストール
* 不正ユーザー（wario）の作成
* cronを使用したリバースシェルの定期実行
* sudoers.dディレクトリへのファイル追加による権限昇格
* 強制SSHログイン用の公開鍵のインストール（root、www-data、nobody、sonic）

これらのバックドアを使用することで、攻撃者はゲームシステムをリモートから操作できます。

### 攻撃を受けた場合の対応例

* バックドアとして設定された各項目を削除する。
* リバースシェルなどの不審なプロセスを停止する。

## マルウェアのインストール

### 概要

脆弱性を利用してシステムにアクセスし、root権限が取得できた場合、DNSプロトコルを通じて攻撃者のC&Cサーバーと通信するマルウェアがサーバーにインストールされます。

```
/var/tmp/systemd-private-journal
/var/tmp/systemd-private-journal-zWuKif
/etc/systemd/system/systemd-journal.service
```

マルウェアはsystemdのサービス（`systemd-journal.service`）として動作し、DNSプロトコルを経由してC&Cサーバーに60秒ごとにポーリングを行います。このマルウェアを使用することで、攻撃者はroot権限でゲームサーバーにリモートアクセスできます。

### 攻撃を受けた場合の対応例

* マルウェアサービスを停止し、インストールされたマルウェアを削除する。

## ゲームチートの実行

### 概要

脆弱性を悪用して以下のようなチート行為を実施します：

* 不正なチートユーザーの大量登録。
* バグを悪用した違法なステータスブースト。

チートユーザーがゲームランキングに現れると、スコアリングメカニズムはクローラーの検知に基づいてアクセス間隔を延長し、最終スコアの低下につながります。

![チートユーザーに汚染されたランキングページ](../../images/cheat_ranking.png)

### 攻撃を受けた場合の対応

* 不審なユーザーを削除する。

## Webサイトの改ざん

### 概要

マルウェアの設定やバックドアのインストールに成功すると、Webサイトの改ざんが実行されます。
サイトが改ざんされると、クローラーがSLAを満たしていないと検知してアクセス間隔を延長し、最終スコアの低下につながります。

![改ざんされたWebサイト](../../images/Tampering.png)

### 攻撃を受けた場合の対応

* 改ざん前のコンテンツに戻す。

## 正規ユーザーの削除

### 概要

管理パネルの認証不備やプレイヤーデータ画面のBOLAなどの脆弱性が放置されると、これらの脆弱性を悪用して正規ユーザーを削除する攻撃が行われる可能性があります。

### 攻撃を受けた場合の対応

* この攻撃によって削除されたユーザーは復元できません。

## データベースの削除

SQLインジェクションが放置されると、SQLインジェクションを悪用してゲームデータベースを削除する攻撃のリスクがあります。
ゲームが正常に機能していない場合、クローラーが正常にアクセスできなくなり、最終スコアの低下につながります。

### 攻撃を受けた場合の対応

* バックアップされたデータベースファイルを使用して復元する（`/usr/local/dbbackup` ディレクトリ配下のファイルが役立つ場合があります）。
