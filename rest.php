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

switch($_GET['op']) {
    case "minted": {
        echo getMinted();
        break;
    }
    case "prefix": {
        echo getPrefix();
        break;
    }
    default: {
        echo json_encode("Operation is mandatory");
        break;
    }
}

function getMinted() {
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $prefix = Database::$engine->get(Globals::_RR . "/firstpart");
    $result = Database::$engine->select("_key REGEXP '^$prefix' and _key REGEXP ':/c$'");
    return json_encode($result);
}

function getPrefix(){
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $prefix = Database::$engine->get(Globals::_RR . "/firstpart");
    return json_encode($prefix);
}
