<?php
$configFile = '../config/MysqlArkConf.php';
if (file_exists($configFile)) {
    require_once($configFile);
    header("Location: ./admin.php");
} else {
    // Handle the error, e.g., show a user-friendly message
    echo 'There is no database setup for the application. 
    Please setup the databse, visit 
    <a href="https://github.com/digitalutsc/arks-service/wiki#in-an-apache-server-for-productions-deployment">the setup documenation</a> for more information.';
}
?>