<?php

$realm = "Restricted area";
header('HTTP/1.1 401 Unauthorized');
header('WWW-Authenticate: Digest realm="' . $realm . '",qop="auth",nonce="' . $_SESSION['http_digest_nonce'] . '",opaque="' . md5($realm) . '"');

if (class_exists('SQLite3')) {
    $ver = SQLite3::version();

    print <<<EOS
        <div class="alert alert-success" role="alert"><p>SQLite3 plugin installed and enabled</p>
    EOS;
    print "<pre>";
    print_r($ver);
    print "</pre></div>";
} else {
    print <<<EOS
        <div class="alert alert-secondary" role="alert">Warning, this server doesn't have SQLite3 supported</div>
    EOS;
}
?>


<html>
<head>
    <title>Ark Services</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css"
          integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
</head>
<body>
<div class="container">
    <div class="row">
        <div class="col-sm text-center">
            <h1 class="text-center">Session End</h1>
        </div>
    </div>
    <div class="row">
        <div class="col-md-12">
            <div class="alert alert-secondary" role="alert">
                You have successfully logged out! <a href='/' class='icon-button star'>Login again</button></center></a>
            </div>

        </div>
    </div>

</div>
</body>
