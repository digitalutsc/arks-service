<?php

include "lib/noid/Noid.php";
require_once('lib/resolver/URLResolver.php');
require_once "NoidUI.php";
?>

<html>
<head>
    <title>Test Ark URL</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css"
          integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
</head>
<body>
<div class="container">


    <div class="row">
        <div class="col-sm">
            <h1 class="text-center">Test Ark by URL Resolver</h1>
        </div>
    </div>

    <div class="card-body">
        <div id="row-dbcreate" class="row">
            <div class="col-sm-5">
                <form id="form-dbcreate" action="./resolver.php" method="post">
                <div class="form-group">
                    <label for="enterArkURL">Ark URL:</label>
                    <input type="text" class="form-control" id="enterArkURL" name="enterArkURL"
                           required/>
                </div>
                <input type="submit" name="submit" value="Submit" class="btn btn-primary"/>
                </form>
            </div>
            <div class="col-sm-7">

                <?php
                if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['submit'])) {
                    $url = $_POST['enterArkURL'];

                    $resolver = new mattwright\URLResolver();
                    print $resolver->resolveURL($url)->getURL();

                }
                ?>
            </div>
        </div>
    </div>
</div>
</body>

