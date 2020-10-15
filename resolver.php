<?php
require_once "NoidUI.php";
require_once "NoidLib/lib/Storage/MysqlDB.php";
require_once 'NoidLib/custom/GlobalsArk.php';
require_once 'NoidLib/custom/NoidArk.php';
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
use Noid\Lib\Custom\NoidArk;


if (strpos($_SERVER['REQUEST_URI'], "/ark:/") === 0) {
    $uid = str_replace("ark:/", "", $_GET['q']);
    $dirs = scandir(NoidUI::dbpath());
    if (is_array($dirs) && count($dirs) > 2) {
        $noidUI = new NoidUI();
        $url  = "";
        GlobalsArk::$db_type = 'ark_mysql';
        foreach ($dirs as $dir) {
            if (!in_array($dir, ['.', '..', '.gitkeep'])) {
                try {
                    $result = rest_get("/rest.php?db=$dir&op=firstpart");
                    $firstpart = json_decode($result);
                    if(strpos($uid, $firstpart) === 0) {
                        // look up into this database
                        // first url field
                        $results = rest_get("/rest.php?db=$dir&op=url&ark_id=$uid");
                        $results = json_decode($results);
                        if (count($results) <= 0) {
                            // if url field is empty, go for the PID
                            $results = rest_get("/rest.php?db=$dir&op=pid&ark_id=$uid");
                            $results = json_decode($results);
                        }
                        $dns = json_decode(rest_get("/rest.php?db=$dir&op=naa"));
                        $url = "https://$dns/islandora/object/". $results[0]->{'_value'};
                        break;
                    }
                } catch (RequestException $e) {
                    print_log($e->getMessage());
                    return null;
                }

            }
        }
        if (!empty($url)) {
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

function rest_get($req) {
    $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
    $cURLConnection = curl_init();
    curl_setopt($cURLConnection, CURLOPT_URL, $protocol . $_SERVER['HTTP_HOST'].$req);
    curl_setopt($cURLConnection, CURLOPT_RETURNTRANSFER, true);

    $result = curl_exec($cURLConnection);
    curl_close($cURLConnection);
    return $result;
}
