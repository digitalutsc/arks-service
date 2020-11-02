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
                // if ark ID found, look for URL fields first.
                $results = rest_get("/rest.php?db=$db&op=url&ark_id=$uid");
                $results = json_decode($results);

                if(count($results) <= 0 ) {
                    // if URL field is empty, go with the PID
                    $results = rest_get("/rest.php?db=$db&op=pid&ark_id=$uid");
                    $results = json_decode($results);
                    if (count($results) > 0) {
                        $dns = json_decode(rest_get("/rest.php?db=$db&op=naa"));
                        $url = "https://$dns/islandora/object/". $results[0]->{'_value'};
                        break;
                    }
                    else {
                        $url = "/404.php";
                    }
                }
                else {
                    $url = $results[0]->{'_value'};
                    break;
                }

            } catch (RequestException $e) {
                logging($e->getMessage());
                $url = "/404.php";
            }

        }
        header("Location: $url");
    }
}
else {
    print "invalid argument";
}

