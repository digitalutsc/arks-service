<?php

$realm = 'Restricted area';

//user => password
$users = array(
    'sysadmin' => '1q2w3e4r',
);
//$users = array('admin' => 'mypass', 'guest' => 'guest');


if (empty($_SERVER['PHP_AUTH_DIGEST'])) {
    header('HTTP/1.1 401 Unauthorized');
    header('WWW-Authenticate: Digest realm="' . $realm .
        '",qop="auth",nonce="' . uniqid() . '",opaque="' . md5($realm) . '"');
    ?>
    1Access denied, your entered login credentials are invalid. This site is restricted for University of Toronto Staff only. <a href="/">Please enter your login credentials to login.</a>
    <?php
    die();
}


// analyze the PHP_AUTH_DIGEST variable
if (!($data = http_digest_parse($_SERVER['PHP_AUTH_DIGEST'])) ||  !isset($users[$data['username']])) {
    header('HTTP/1.1 401 Unauthorized');
    header('WWW-Authenticate: Digest realm="' . $realm .
        '",qop="auth",nonce="' . uniqid() . '",opaque="' . md5($realm) . '"');
    ?>
    2Access denied, your entered login credentials are invalid. This site is restricted for University of Toronto Staff only. <a href="/">Please enter your login credentials to login.</a>
    <?php
    die();
}


// generate the valid response
$A1 = md5($data['username'] . ':' . $realm . ':' . $users[$data['username']]);
$A2 = md5($_SERVER['REQUEST_METHOD'] . ':' . $data['uri']);
$valid_response = md5($A1 . ':' . $data['nonce'] . ':' . $data['nc'] . ':' . $data['cnonce'] . ':' . $data['qop'] . ':' . $A2);

if ($data['response'] != $valid_response) {
    ?>
    3Access denied, your entered login credentials are invalid. This site is restricted for University of Toronto Staff only. <a href="/">Please enter your login credentials to login.</a>
    <?php
    die();
}

// ok, valid username & password
if ($_SERVER['REQUEST_URI'] === "index.php" || $_SERVER['REQUEST_URI'] === '/'){
    header('Location: admin.php');
}


// function to parse the http auth header
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
