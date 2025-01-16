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
if (auth()) { 
    header('Location: admin.php');
}
else {
    echo 'Access denied ! Your login credential is matched. <a href="logout.php">Please enter your login credentials to
                login.</a>';
    exit();
}
ob_flush();
