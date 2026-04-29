<?php

require_once "../includes.php";

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

function init_system() {
    // set db type as mysql instead
    GlobalsArk::$db_type = 'ark_mysql';
    define("NAAN_UTSC", 61220);
    if (!Database::isInstalled()) {
        // redirect to install.php
        header("Location: install.php");
        exit;
    }
}

/**
 * Debug methods: print any thing to error.log
 * @param $thing
 */
function print_log($thing) {
    error_log(print_r($thing, true), 0);
}

/**
 * Debug method: print any thing with readable format to webpage
 * @param $thing
 */
function logging($thing) {
    echo '<pre>';
    print_r($thing);
    echo '</pre>';
}

/**
 * Official Encryption code for secure site
 *
 * https://www.geeksforgeeks.org/how-to-encrypt-and-decrypt-a-php-string/
 *
 * @param type $stringToEncrypt : string to encyrpt
 * @param type $encryption_key : module name
 * @param type $encryption_iv : timestamp of application
 */
function secureEncryption($stringToEncrypt, $encryption_key, $encryption_iv)
{
    // Store the cipher method
    $ciphering = "AES-128-CTR";

    // Use OpenSSl Encryption method
    $iv_length = openssl_cipher_iv_length($ciphering);
    $options = 0;

    // Use openssl_encrypt() function to encrypt the data
    return openssl_encrypt($stringToEncrypt, $ciphering,
        $encryption_key, $options, $encryption_iv);
}

/**
 * Official Decryption code for secure site
 *
 * https://www.geeksforgeeks.org/how-to-encrypt-and-decrypt-a-php-string/
 * @param type $stringToEncrypt : string to decrypt
 * @param type $decryption_key : module name
 * @param type $decryption_iv : timestamp of application
 * @return type
 */
function secureDecryption($stringToEncrypt, $decryption_key, $decryption_iv)
{
    $ciphering = "AES-128-CTR";

    // Use OpenSSl Encryption method
    $iv_length = openssl_cipher_iv_length($ciphering);
    $options = 0;
    // Use openssl_decrypt() function to decrypt the data
    return openssl_decrypt($stringToEncrypt, $ciphering,
        $decryption_key, $options, $decryption_iv);
}

/**
 * Call Rest API, with get method
 *
 * @param $req
 * @return bool|string
 */
function rest_get($req)
{
    $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
    print_log(CURLOPT_URL, $protocol . $_SERVER['HTTP_HOST'] . $req);
    try {
      $cURLConnection = curl_init();
      curl_setopt($cURLConnection, CURLOPT_URL, $protocol . $_SERVER['HTTP_HOST'] . $req);
      curl_setopt($cURLConnection, CURLOPT_RETURNTRANSFER, true);

      $result = curl_exec($cURLConnection);

      if ($result === false) {
        throw new Exception(curl_error($cURLConnection), curl_errno($cURLConnection));
        return null;
      }
      curl_close($cURLConnection);
      return $result;
    }catch(\Exception $e) {
      print_log($e->getMessage());
      return null;
    }
}


/**
 * for login
 * @param $txt
 * @return array|false
 */
function http_digest_parse($txt)
{
    // protect against missing data
    $needed_parts = array('nonce' => 1, 'nc' => 1, 'cnonce' => 1, 'qop' => 1, 'username' => 1, 'uri' => 1, 'response' => 1);
    $data = array();
    $keys = implode('|', array_keys($needed_parts));

    preg_match_all('@(' . $keys . ')=(?:([\'"])([^\2]+?)\2|([^\s,]+))@', $txt, $matches, PREG_SET_ORDER);

    foreach ($matches as $m) {
        $data[$m[1]] = $m[3] ? $m[3] : $m[4];
        unset($needed_parts[$m[1]]);
    }

    return $needed_parts ? false : $data;
}

function path(string $dbname = "")
{
    return getcwd() . "/db/" . $dbname;
}

function dbpath(string $dbname = "")
{
    return getcwd() . "/db/" . $dbname;
}

/**
 * authentication function
 */
function auth(){
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
        header('HTTP/1.1 401 Unauthorized');
        header('WWW-Authenticate: Digest realm="' . $realm .
            '",qop="auth",nonce="' . uniqid() . '",opaque="' . md5($realm) . '"');
        die('Wrong Credentials! <a href="logout.php">Please enter your login credentials to
                login.</a>');
    }
    
    
    // analyze the PHP_AUTH_DIGEST variable
    if (count($users) == 0 /*|| !isset($users[$data['username']])*/) {
        header('HTTP/1.1 401 Unauthorized');
        header('WWW-Authenticate: Digest realm="' . $realm .
            '",qop="auth",nonce="' . uniqid() . '",opaque="' . md5($realm) . '"');
    
        /*echo 'Access denied, your account is not found. <a href="logout.php">Please enter your login credentials to login.</a>';
        exit();*/
        return false;
    } else {
        $A1 = md5($data['username'] . ':' . $realm . ':' . $users[$data['username']]);
        $A2 = md5($_SERVER['REQUEST_METHOD'] . ':' . $data['uri']);
        $valid_response = md5($A1 . ':' . $data['nonce'] . ':' . $data['nc'] . ':' . $data['cnonce'] . ':' . $data['qop'] . ':' . $A2);
        if ($data['response'] != $valid_response) {
    
            /*echo 'Access denied ! Your login credential is matched. <a href="logout.php">Please enter your login credentials to
                login.</a>';
            exit();*/
            return false;
        }
        else {
            //header('Location: admin.php');
            return true;
        }
    
    }
}


/**
 * Get NAA
 * @return false|string
 */
function getNAA($db) {
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($db)) {
    die(json_encode('Database not found'));
  }
  $noid = Database::dbopen($db, getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $naa = Database::$engine->get(Globals::_RR . "/naa");
  Database::dbclose($noid);
  return json_encode($naa);
}

