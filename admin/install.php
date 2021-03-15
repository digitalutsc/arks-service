<?php

require_once "functions.php";

use Noid\Lib\Custom\Database;
use Noid\Lib\Custom\GlobalsArk;
use Noid\Config\MysqlArkConf;

ob_start();
GlobalsArk::$db_type = 'ark_mysql';

if (Database::isInstalled()) {
    // redirect to install.php
    header("Location: ../index.php");
    exit;
}
?>

<html>
<head>
    <title>Ark Services</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css"
          integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z"
          crossorigin="anonymous">
    <script type="text/javascript" language="javascript" src="https://code.jquery.com/jquery-3.5.1.js"></script>


    <!-- bootsrap -->
    <script src="https://cdn.jsdelivr.net/npm/popper.js@1.16.1/dist/umd/popper.min.js"
            integrity="sha384-9/reFTGAW83EW2RDu2S0VKaIzap3H66lZH81PoYlFhbGU+6BZp6G7niu735Sk7lN"
            crossorigin="anonymous"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"
            integrity="sha384-B4gt1jrGC7Jh4AgTPSdUtOBvfO8shuf57BaghqFfPlYxofvL8/KUEfYiJOMMV+rV"
            crossorigin="anonymous"></script>

    <!-- datatables -->
    <link rel="stylesheet"
          href="https://cdn.datatables.net/1.10.22/css/jquery.dataTables.min.css">
    <link rel="stylesheet"
          href="https://cdn.datatables.net/select/1.3.1/css/select.dataTables.min.css">

    <script type="text/javascript" language="javascript"
            src="https://cdn.datatables.net/1.10.22/js/jquery.dataTables.min.js"></script>
    <script type="text/javascript" language="javascript"
            src="https://cdn.datatables.net/buttons/1.6.4/js/dataTables.buttons.min.js"></script>
    <script type="text/javascript" language="javascript"
            src="https://cdn.datatables.net/buttons/1.6.4/js/buttons.html5.min.js"></script>
    <script type="text/javascript" language="javascript"
            src="https://cdn.datatables.net/select/1.3.1/js/dataTables.select.min.js"></script>

    <!-- bootstrap select-->
    <link rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/bootstrap-select@1.13.14/dist/css/bootstrap-select.min.css">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap-select@1.13.14/dist/js/bootstrap-select.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap-select/1.12.1/js/i18n/defaults-en_US.js"></script>
</head>
<body>
<div class="container">
    <div class="row">
        <div class="col-sm text-center">
            <h1 class="text-center">Ark Service Installation</h1>
        </div>
    </div>
    <div class="row">
        <?php
        if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['register-sys-admin-user']) && !isset($_GET['db'])) {
            if (strcmp($_POST["enterPassword"], $_POST["enterConfirmPassword"]) === 0) {
                // create database
                $conn = new mysqli(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd);

                if (!$conn) {
                    echo "Error: Unable to connect to MySQL." . PHP_EOL;
                    echo "Debugging errno: " . mysqli_connect_errno() . PHP_EOL;
                    echo "Debugging error: " . mysqli_connect_error() . PHP_EOL;
                }
                $sql = "CREATE DATABASE IF NOT EXISTS " . MysqlArkConf::$mysql_dbname;
                if ($conn->query($sql) === FALSE) {
                    echo '<div class="alert alert-danger" role="alert">Error creating table: ' . $conn->error . '</div>';
                }
                $conn->close();

                $conn = new mysqli(MysqlArkConf::$mysql_host, MysqlArkConf::$mysql_user, MysqlArkConf::$mysql_passwd, MysqlArkConf::$mysql_dbname);
                $sql = 'CREATE TABLE IF NOT EXISTS `system` (
                    `_key` VARCHAR(128) NOT NULL PRIMARY KEY,
                    `_value` VARCHAR(128) NOT NULL,
                    UNIQUE (_key)
                )';
                if ($conn->query($sql) === FALSE) {
                    echo '<div class="alert alert-danger" role="alert">Error creating table: ' . $conn->error . '</div>';
                }

                $sql = "CREATE TABLE IF NOT EXISTS `user` (
                        id INT(6) UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(50) NOT NULL UNIQUE,
                        firstname VARCHAR(30) NOT NULL,
                        lastname VARCHAR(30) NOT NULL,
                        pasword VARCHAR(128)  NOT NULL,
                        UNIQUE (username)
                )";
                if ($conn->query($sql) === FALSE) {
                    echo '<div class="alert alert-danger" role="alert">Error creating table: ' . $conn->error . '</div>';
                }
                $sql = 'INSERT INTO `system` VALUES ("Organization Name", "' . $_POST['enterOrgName'] . '")';
                if ($conn->query($sql) === FALSE) {
                    echo '<div class="alert alert-danger" role="alert">Error creating table: ' . $conn->error . '</div>';
                }
                $sql = 'INSERT INTO `system` VALUES ("Organization Website", "' . $_POST['enterOrgWebsite'] . '")';
                if ($conn->query($sql) === FALSE) {
                    echo '<div class="alert alert-danger" role="alert">Error creating table: ' . $conn->error . '</div>';
                }

                $sql = 'INSERT INTO `user`  VALUES (NULL, "' . $_POST["enterUsername"] . '", "' . $_POST["enterUserFirstname"] . '", "' . $_POST["enterUserLastname"] . '", "' . secureEncryption($_POST["enterPassword"], "VUQY%IdGWlBT!83YCM6TtY5X-uIYv)i1AEyk67VpusyCDXZW0", 2734025702752005) . '")';
                if ($conn->query($sql) === FALSE) {
                    echo '<div class="alert alert-danger" role="alert">Error creating table: ' . $conn->error . '</div>';
                }
            } else {
                echo '<div class="alert alert-danger" role="alert">Password are not matched</div>';
            }

            $conn->close();
            header("Location: admin.php");
        }
        ?>
    </div>
    <div class="row">
        <div class="col-sm">

            <form id="form-user-register" action="./install.php" method="post">
                <div class="form-group">
                    <h3 class="text-center">Organization</h3>
                </div>
                <div class="form-group">
                    <label for="enterFirstname">Organization's Name:</label>
                    <input required type="text" class="form-control" id="enterFirstname" name="enterOrgName" placeholder="Enter your organization's name">
                </div>
                <div class="form-group">
                    <label for="enterFirstname">Organization's URL:</label>
                    <input type="text" class="form-control" id="enterOrgWebsite" name="enterOrgWebsite" placeholder="Enter your organization's website">
                    <!--<p><strong>Note:</strong> If the Ark IDs resolver is located separatedly in a different site, please enter the domain name in this field. Otherwise your Ark URL will be: <br /> http://<?php //echo $_SERVER['HTTP_HOST']; ?> </p>-->
                </div>
                <div class="form-group">
                    <h3 class="text-center">System Admin User</h3>
                </div>
                <div class="form-group">
                    <label for="enterFirstname">First Name:</label>
                    <input required type="text" class="form-control" id="enterUserFirstname" name="enterUserFirstname">
                </div>
                <div class="form-group">
                    <label for="enterLastname">Last Name:</label>
                    <input required type="text" class="form-control" id="enterUserLastname" name="enterUserLastname"
                </div>
                <div class="form-group">
                    <label for="enterUsername">Username</label>
                    <input required type="text" class="form-control" id="enterUsername" name="enterUsername"
                           aria-describedby="emailHelp"
                           placeholder="Enter Username">
                </div>
                <div class="form-group">
                    <label for="exampleInputPassword1">Password</label>
                    <input required type="password" class="form-control" id="enterPassword" name="enterPassword"
                           placeholder="Password">
                </div>
                <div class="form-group">
                    <label for="exampleInputPassword2">Confirm Password</label>
                    <input required type="password" class="form-control" id="enterConfirmPassword"
                           name="enterConfirmPassword"
                           placeholder="Confirm Password">
                </div>

                <button type="submit" name="register-sys-admin-user" class="btn btn-primary">Install</button>
            </form>
        </div>
    </div>
    <?php
    ob_flush();
    ?>

</div>
</body>
</html>
