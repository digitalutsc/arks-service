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


if (strpos($_SERVER['REQUEST_URI'], "/ark:/") === 0) {
    $uid = str_replace("ark:/", "", $_GET['q']);
    
    // get all database Ark related
    $arkdbs = Database::showdatabases();
    
    // only proceed if already have ark_core db
    if (is_array($arkdbs) && count($arkdbs) > 1) {
        
        $url  = "";
        GlobalsArk::$db_type = 'ark_mysql';

        // loop through database and find matching one with prefix
        foreach ($arkdbs as $db) {
            try {
                $result = rest_get("/rest.php?db=$db&op=firstpart");
                $firstpart = json_decode($result);
                if(strpos($uid, $firstpart) === 0) {
                    // look up into this database
                    // first url field
                    $results = rest_get("/rest.php?db=$db&op=url&ark_id=$uid");
                    $results = json_decode($results);
                    if (count($results) <= 0) {
                        // if url field is empty, go for the PID
                        $results = rest_get("/rest.php?db=$db&op=pid&ark_id=$uid");
                        $results = json_decode($results);
                        $dns = json_decode(rest_get("/rest.php?db=$db&op=naa"));
                        $url = "https://$dns/islandora/object/". $results[0]->{'_value'};
                    }
                    else {
                        $url = $results[0]->{'_value'};
                    }

                    break;
                }
            } catch (RequestException $e) {
                print_log($e->getMessage());
                return null;
            }

        }

        if (!empty($url)) {
            var_dump($url);
            //header("Location: $url");
        }
        else {
            print "Ark ID is not found.";
        }

    }
}
else {
    print "invalid argument";
}

