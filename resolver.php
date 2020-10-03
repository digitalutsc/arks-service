<?php
include "lib/noid/Noid.php";
require_once "NoidUI.php";
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


if (strpos($_SERVER['REQUEST_URI'], "/ark:/") === 0) {
    $uid = str_replace("ark:/", "", $_GET['q']);
    $dirs = scandir(NoidUI::dbpath());
    if (is_array($dirs) && count($dirs) > 2) {
        $noidUI = new NoidUI();
        $url  = "";
        GlobalsArk::$db_type = 'ark_mysql';
        foreach ($dirs as $dir) {
            if (!in_array($dir, ['.', '..', '.gitkeep'])) {
                // TODO: Switch database within loop not working, need fixed
                $noid = Database::dbopen($dir, getcwd() . "/db/", DatabaseInterface::DB_WRITE);
                $prefix = Database::$engine->get(Globals::_RR . "/firstpart");

                if(strpos($uid, $prefix) === 0) {
                    // look up into this database
                    $results = Database::$engine->select("_key REGEXP '^$uid' and _key  REGEXP 'PID$'");
                    $dns = Database::$engine->get(Globals::_RR . "/naa");
                    $url = "http://$dns/islandora/object/". $results[0]['_value'];
                    break;
                }
            }
        }
        header("Location: $url");
    }
}
else {
    print "invalid argument";
}
