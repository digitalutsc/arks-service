<?php

require_once "NoidLib/lib/Storage/MysqlDB.php";
require_once 'NoidLib/custom/GlobalsArk.php';
require_once 'NoidLib/lib/Db.php';
require_once 'NoidLib/custom/Database.php';

use Noid\Lib\Helper;
use Noid\Lib\Noid;
use Noid\Lib\Storage\DatabaseInterface;
use Noid\Lib\Storage\MysqlDB;
use Noid\Lib\Globals;
use Noid\Lib\Db;
use Noid\Lib\Log;

use Noid\Lib\Custom\Database;
use Noid\Lib\Custom\GlobalsArk;


epxeriment();

function epxeriment() {
    GlobalsArk::$db_type = 'ark_mysql';
    $dbpath = getcwd() . DIRECTORY_SEPARATOR . 'db';
    $report = Database::dbcreate($dbpath, 'jak', ".zd", 'short');

    /*$noid = Db::dbopen(getcwd() . DIRECTORY_SEPARATOR . 'db', DatabaseInterface::DB_WRITE);
    $contact = time();

    $n = 10;
    while($n--){
        $id = Noid::mint($noid, $contact);
    };
    $result = Noid::bind($noid, $contact, 1, 'set', "7 :/c", 'myelem', 'myvalue');
    $result = Noid::fetch($noid, 1, "7 :/c", 'myelem');
    print_r($result);
    */
}