<?php
require_once "functions.php";

use Noid\Lib\Custom\NoidArk;
use Noid\Lib\Helper;
use Noid\Lib\Noid;
use Noid\Lib\Storage\DatabaseInterface;
use Noid\Lib\Storage\MysqlDB;
use Noid\Lib\Globals;
use Noid\Lib\Db;
use Noid\Lib\Log;

use Noid\Lib\Custom\Database;
use Noid\Lib\Custom\GlobalsArk;
use Noid\Lib\Custom\MysqlArkConf;

/**
 * Must pass database when call each request
 */
if (!isset($_GET['db'])) {
    die(json_encode("No database selected"));
}

switch ($_GET['op']) {
    case "minted":
    {
        echo getMinted();
        break;
    }
    case "fields": {
        if (isset($_GET['ark_id']) ) {
            echo getFields($_GET['ark_id']);
        }
        else {
            echo  json_encode("Invalid Ark ID");
        }
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
    case "url": {
        echo getURL($_GET['ark_id']);
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
    case 'bulkbind': {
        if (isset($_GET['stage']) && $_GET['stage'] == 'upload'){
            echo bulkbind();
        }
        else if (isset($_GET['stage']) && $_GET['stage'] == 'import'){
            echo bulkbind_import();
        }
        else if (isset($_GET['stage']) && $_GET['stage'] == 'processing') {
            echo bulkbind_processing();
        }
        else {
            echo  json_encode("Invalid stage");
        }
        break;
    }
    default:
    {
        echo json_encode("Operation is mandatory");
        break;
    }
}

/**
 * Get fields of given Ark ID
 *
 * @param $ark_id
 * @return false|string
 */
function getFields($ark_id) {
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $where = "_key REGEXP '^" .$ark_id ."\t' and _key NOT REGEXP ':/c$' and _key NOT REGEXP ':/h$' order by _key";
    $result = Database::$engine->select($where);

    $json = array();
    foreach ($result as $row) {
        array_push($json, trim(str_replace($ark_id,"", $row['_key'])));
    }
    Database::dbclose($noid);
    return json_encode($json);
}

/**
 * Handle ajax call for each row of CSV during bulk binding import
 *
 * @return false|string
 */
function bulkbind(){
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode(['success' => 0, 'message' => 'Database not found']));
    }
    $result = null;
    if (is_array($_POST) && isset($_POST['data'])) {
        $noid = Database::dbopen($_GET["db"], NoidUI::dbpath(), DatabaseInterface::DB_WRITE);
        // capture identifier (strictly recommend first column)
        $contact = time();

        if (!empty($_POST['data'][strtoupper('LOCAL_ID')])) {

            // TOOD: check if decided unique field exist, to avoid duplication
            $checkExistedLocalID = Database::$engine->select("_value = '".$_POST['data']['PID']."'");
            if (is_array($checkExistedLocalID) && count($checkExistedLocalID) > 0) {
                $identifier = preg_split('/\s+/', $checkExistedLocalID[0]['_key'])[0];
            }
            else {
                if (empty($_POST['data'][strtoupper('Ark ID')] )) {
                    // mint a new ark id
                    $identifier = NoidArk::mint($noid, $contact);
                }
                else {
                    $identifier = $_POST['data'][strtoupper('Ark ID')];
                }
            }
        }
        else {
            if (empty($_POST['data'][strtoupper('Ark ID')] )) {
                // mint a new ark id
                $identifier = NoidArk::mint($noid, $contact);
            }
            else {
                $identifier = $_POST['data'][strtoupper('Ark ID')];
            }
        }

        foreach ($_POST['data'] as $key => $pair) {
            if ($key !== strtoupper('Ark ID')) {
                // check if ark ID exist
                NoidArk::bind($noid, $contact, 1, 'set', $identifier, strtoupper($key), $pair);
            }
        }
        Database::dbclose($noid);
        return json_encode(['success' => 1]);
    }
    return json_encode(['success' => 0, 'message' => 'Invalid data imported']);


}

/**
 * Return basic information of database
 *
 * @return false|string
 */
function getDbInfo() {
    GlobalsArk::$db_type = 'ark_mysql';

    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }

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

/**
 * Return bound objects in database
 * @return false|string
 */
function selectBound()
{
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
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
        $r['select'] = " ";
        $r['id'] = $currentID;
        if ($key_data[1] == 'PID')
            $r['PID'] = $row['_value'];
        if ($key_data[1] == "LOCAL_ID")
            $r['LOCAL_ID'] = $row['_value'];
        $r['metadata'] = (!empty($r['metadata']) ? $r['metadata'] . "|" : "") . $key_data[1] .':' .$row['_value'];


        // establish Ark URL
        $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
        $r['ark_url'] = $protocol . $_SERVER['HTTP_HOST'] . "/ark:/" . $currentID;
    }
    return json_encode($result);
}

/**
 * Run query from given databae and refined key and value
 * @param string $where
 * @return false|string
 */
function select($where = "")
{
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
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

/**
 * Get Ark PID for ark ID
 * @param $arkID
 * @return false|string
 */
function getPID($arkID) {
    if (!isset($arkID))
        return "Ark ID is not valid";
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $result = Database::$engine->select("_key REGEXP '^$arkID' and _key REGEXP 'PID$'");
    Database::dbclose($noid);
    return json_encode($result);
}

/**
 * @param $arkID
 * @return false|string
 */
function getURL($arkID) {
    if (!isset($arkID))
        return "Ark ID is not valid";
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $result = Database::$engine->select("_key REGEXP '^$arkID' and _key REGEXP 'URL$'");
    Database::dbclose($noid);
    return json_encode($result);
}

/**
 * Get NAA
 * @return false|string
 */
function getNAA() {
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $naa = Database::$engine->get(Globals::_RR . "/naa");
    Database::dbclose($noid);
    return json_encode($naa);
}

/**
 * Get minted Ark IDs
 * @return false|string
 */
function getMinted()
{
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
    $result = Database::$engine->select("_key REGEXP '^$firstpart' and _key REGEXP ':/c$'");
    //return json_encode($result);
    $json = array();
    foreach ($result as $row) {
        $urow = array();
        $urow['select']= ' ';
        $urow['_key'] = trim(str_replace(":/c", "", $row['_key']));

        $metadata = explode('|', $row['_value']);
        $urow['_value'] = date("F j, Y, g:i a", $metadata[2]);
        array_push($json, (object)$urow);
    }
    Database::dbclose($noid);
    return json_encode($json);
}

/**
 * Get first part for Ark URL
 * @return false|string
 */
function getfirstpart()
{
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
    return json_encode($firstpart);
}

/**
 * Get prefix
 * @return false|string
 */
function getPrefix() {

    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $prefix = Database::$engine->get(Globals::_RR . "/prefix");
    return json_encode($prefix);
}
