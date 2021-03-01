<?php
require_once "functions.php";

use Noid\Lib\Helper;
use Noid\Lib\Noid;
use Noid\Lib\Storage\DatabaseInterface;
use Noid\Lib\Storage\MysqlDB;
use Noid\Lib\Globals;
use Noid\Lib\Db;
use Noid\Lib\Log;

use Noid\Lib\Custom\Database;
use Noid\Lib\Custom\GlobalsArk;
use Noid\Config\MysqlArkConf;
use Noid\Lib\Custom\NoidArk;

ob_start();
init_system();

$realm = "Restricted area";

if (empty($_SERVER['PHP_AUTH_DIGEST'])) {

    header('HTTP/1.1 401 Unauthorized');
    header('WWW-Authenticate: Digest realm="' . $realm .
        '",qop="auth",nonce="' . uniqid() . '",opaque="' . md5($realm) . '"');
    echo 'Access denied, you must have account to proceed. This site is restricted for University of Toronto Staff only. <a href="logout.php">Please enter your login credentials to login.</a>';
    //die('Text to send if user hits Cancel button');
    die();
}

$data = http_digest_parse($_SERVER['PHP_AUTH_DIGEST']);
$conn = new mysqli(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);
if (!$conn) {
    echo "Error: Unable to connect to MySQL." . PHP_EOL;
    echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
    echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
}
$sql = "Select `username`, `pasword` from user where username = '" . $data['username'] . "'";
$result = $conn->query($sql)->fetch_all();
$users = array();

foreach ($result as $row) {
    $users[$row[0]] = secureDecryption($row[1], "VUQY%IdGWlBT!83YCM6TtY5X-uIYv)i1AEyk67VpusyCDXZW0", 2734025702752005);
}
$conn->close();

if (!isset($data) || !isset($users[$data['username']])) {
    die('Wrong Credentials! <a href="logout.php">Please enter your login credentials to
            login.</a>');
}


// analyze the PHP_AUTH_DIGEST variable
if (count($users) == 0 /*|| !isset($users[$data['username']])*/) {
    header('HTTP/1.1 401 Unauthorized');
    header('WWW-Authenticate: Digest realm="' . $realm .
        '",qop="auth",nonce="' . uniqid() . '",opaque="' . md5($realm) . '"');

    echo 'Access denied, your account is not found. <a href="logout.php">Please enter your login credentials to login.</a>';
    exit();
} else {
    $A1 = md5($data['username'] . ':' . $realm . ':' . $users[$data['username']]);
    $A2 = md5($_SERVER['REQUEST_METHOD'] . ':' . $data['uri']);
    $valid_response = md5($A1 . ':' . $data['nonce'] . ':' . $data['nc'] . ':' . $data['cnonce'] . ':' . $data['qop'] . ':' . $A2);
    if ($data['response'] != $valid_response) {

        echo 'Access denied ! Your login credential is matched. <a href="logout.php">Please enter your login credentials to
            login.</a>';
        exit();
    }
    else {
        header('Location: admin.php');
    }

}


ob_flush();
