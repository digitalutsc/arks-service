<?php
require_once "functions.php";

$realm = "Restricted area";
header('HTTP/1.1 401 Unauthorized');
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
                You have successfully logged out! <a href='auth.php' class='icon-button star'>Login again</button></center></a>
            </div>

        </div>
    </div>

</div>
</body>
