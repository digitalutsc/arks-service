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

switch ($_GET['op']) {
    case "minted":
    {
        echo getMinted();
        break;
    }
    case "firstpart":
    {
        echo getfirstpart();
        break;
    }
    case 'select':
    {
        echo select();
        break;
    }
    case 'bound':
    {
        echo selectBound();
        break;
    }
    case "pid": {
        echo getPID($_GET['ark_id']);
        break;
    }
    case 'naa': {
        echo getNAA();
        break;
    }
    case 'prefix': {
        echo getPrefix();
        break;
    }
    case 'dbinfo': {
        echo getDbInfo();
        break;
    }
    default:
    {
        echo json_encode("Operation is mandatory");
        break;
    }
}

function getDbInfo() {
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);

    $result = [
        'prefix' => Database::$engine->get(Globals::_RR . "/prefix"),
        'generator_type' => Database::$engine->get(Globals::_RR . "/generator_type"),
        'naa' => Database::$engine->get(Globals::_RR . "/naa"),
        'naan' => Database::$engine->get(Globals::_RR . "/naan"),
        'template' => Database::$engine->get(Globals::_RR . "/template")
    ];
    Database::dbclose($noid);
    return json_encode($result);
}

function selectBound()
{
    $rows = json_decode(select());
    array_push($rows, (object)[]);
    $currentID = null;
    $result = array();
    $r = [];
    foreach ($rows as $row) {
        $row = (array)$row;
        $key_data = preg_split('/\s+/', $row['_key']);
        //print_r($row);
        if (!isset($currentID) || ($currentID !== $key_data[0])) {
            $currentID = $key_data[0];
            if (is_array($r) && count($r) > 0)
                array_push($result, $r);
            $r = [];
        }
        $r['id'] = $currentID;
        if ($key_data[1] == 'PID')
            $r['PID'] = $row['_value'];

        $r['metadata'] = (!empty($r['metadata']) ? $r['metadata'] . "|" : "") . $key_data[1] .':' .$row['_value'];

        // establish Ark URL
        $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
        $r['ark_url'] = $protocol . $_SERVER['HTTP_HOST'] . "/ark:/" . $currentID;
    }
    return json_encode($result);
}

function select($where = "")
{
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");

    $result = Database::$engine->select("_key REGEXP '^$firstpart' and _key NOT REGEXP ':/c$' and _key NOT REGEXP ':/h$' order by _key");
    //return json_encode($result);
    $json = array();
    foreach ($result as $row) {
        $urow = array();
        $urow['_key'] = $row['_key'];//trim(str_replace(":/c", "", $row['_key']));
        $urow['_value'] = $row['_value'];
        array_push($json, (object)$urow);
    }
    Database::dbclose($noid);
    return json_encode($json);
}

function getPID($arkID) {
    if (!isset($arkID))
        return "Ark ID is not valid";
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $result = Database::$engine->select("_key REGEXP '^$arkID' and _key REGEXP 'PID$'");
    Database::dbclose($noid);
    return json_encode($result);
}

function getNAA() {
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $naa = Database::$engine->get(Globals::_RR . "/naa");
    Database::dbclose($noid);
    return json_encode($naa);
}

function getMinted()
{
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
    $result = Database::$engine->select("_key REGEXP '^$firstpart' and _key REGEXP ':/c$'");
    //return json_encode($result);
    $json = array();
    foreach ($result as $row) {
        $urow = array();
        $urow['_key'] = trim(str_replace(":/c", "", $row['_key']));

        $metadata = explode('|', $row['_value']);
        $urow['_value'] = date("F j, Y, g:i a", $metadata[2]);
        array_push($json, (object)$urow);
    }
    Database::dbclose($noid);
    return json_encode($json);
}

function getfirstpart()
{
    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
    return json_encode($firstpart);
}

function getPrefix() {

    GlobalsArk::$db_type = 'ark_mysql';
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $prefix = Database::$engine->get(Globals::_RR . "/prefix");
    return json_encode($prefix);
}
