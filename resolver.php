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
use Noid\Lib\Custom\NoidArk;
GlobalsArk::$db_type = 'ark_mysql';

if (strpos($_SERVER['REQUEST_URI'], "/ark:/") === 0) {
    $uid = str_replace("ark:/", "", $_GET['q']);

    // get all database Ark related
    $arkdbs = Database::showArkDatabases();
    // only proceed if already have ark_core db
    if (is_array($arkdbs) && count($arkdbs) > 0) {
        $url  = "";
        GlobalsArk::$db_type = 'ark_mysql';

        // loop through database and find matching one with prefix
        foreach ($arkdbs as $db) {
            try {
                $noid = Database::dbopen($db, getcwd() . "/db/", DatabaseInterface::DB_WRITE);
                $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");

                if(strpos($uid, $firstpart) === 0) {
                    // look up into this database
                    $url = Database::$engine->get($uid .'\t'. "URL");
                    if (empty($url)) {
                        // if URL field is empty, use PID to establish the URL
                        $pid =  Database::$engine->get($uid .'\t'. "PID");
                        $dns = Database::$engine->get(Globals::_RR . "/naa");
                        $url = "https://$dns/islandora/object/". $pid;
                    }
                    break;
                }
            } catch (RequestException $e) {
                logging($e->getMessage());
                return null;
            }
        }
        if (!empty($url)) {
            //var_dump($url);
            header("Location: $url");
        }
        else {
            print "Ark ID is not found.";
        }
    }
}
else {
    print "invalid argument";
}

