<?php
require_once "NoidUI.php";
require_once "NoidLib/lib/Storage/MysqlDB.php";
require_once 'NoidLib/custom/GlobalsArk.php';
require_once 'NoidLib/lib/Db.php';
require_once 'NoidLib/custom/Database.php';
require_once 'NoidLib/custom/MysqlArkConf.php';
require_once 'NoidLib/custom/NoidArk.php';

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
            echo bulkbind_upload();
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

function bulkbind_upload(){
    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode(['success' => 0, 'message' => 'Database not found']));
    }
    $result = null;
    if (is_array($_POST) && isset($_POST['data'])) {
        $noid = Database::dbopen($_GET["db"], NoidUI::dbpath(), DatabaseInterface::DB_WRITE);
        // capture identifier (strictly recommend first column)
        $contact = time();

        if (!empty($_POST['data'][strtoupper('mods_local_identifier')])) {

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
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
    return json_encode($firstpart);
}

function getPrefix() {

    GlobalsArk::$db_type = 'ark_mysql';
    if (!Database::exist($_GET['db'])) {
        die(json_encode('Database not found'));
    }
    $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
    $prefix = Database::$engine->get(Globals::_RR . "/prefix");
    return json_encode($prefix);
}








function bulkbind_import() {
    if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['bindset']) && !empty($_POST['enterIdentifier'])) {
        $noid = Database::dbopen($_GET["db"], NoidUI::dbpath(), DatabaseInterface::DB_WRITE);
        $contact = time();

        // check if ark ID exist
        $checkExisted = Database::$engine->select("_key REGEXP '^" . $_POST['enterIdentifier'] . "' and _key REGEXP ':/c$'");
        if (count($checkExisted) > 0) {
            $result = NoidArk::bind($noid, $contact, 1, 'set', $_POST['enterIdentifier'], strtoupper($_POST['enterKey']), $_POST['enterValue']);
            print '
                                    <div class="alert alert-success" role="alert">
                                        Ark IDs have been bound successfully.
                                    </div>
                                ';
        } else {
            print '
                                    <div class="alert alert-warning" role="alert">
                                        Ark IDs does not exist to be bound.
                                    </div>
                                ';
        }
        Database::dbclose($noid);
        // refresh the page to clear Post method.
        header("Location: admin.php?db=" . $_GET["db"]);
    }

    //handle bulk bind set
    if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['import'])) {

        // read csv and start processing.
        if (is_uploaded_file($_FILES['importCSV']['tmp_name'])) {
            // generate Ark service procession object
            $noidUI = new NoidUI();

            //Read and scan through imported csv
            if (($handle = fopen($_FILES['importCSV']['tmp_name'], "r")) !== FALSE) {
                // read the first row as columns
                $columns = fgetcsv($handle, 0, ",");

                // check if CSV has 3 mandatory fields, otherwise, it won't proceed with bulk bind
                if (!in_array("PID", $columns) ||
                    !in_array("URL", $columns) ||
                    !in_array("mods_local_identifier", $columns)) {
                    exit ('<div class="alert alert-danger" role="alert" style="margin-top:10px;">
                                                        The imported CSV must have column name "PID", "URL", and "mods_local_identifier". Please <a href="/admin.php?db=' . $_GET['db'] . '">Try again.</a>
                                                    </div>');
                } else {
                    print '<div class="progress">
                                                  <div class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" style="width: 0%"></div>
                                                </div>';
                }


                array_push($columns, "Ark Link");

                // add columns to import data array
                $importedData = array_merge([], $columns);

                // loop through the rest of rows
                $flag = true;
                while (($data = fgetcsv($handle, 1000, ",")) !== FALSE) {
                    // avoid the 1st row since it's header
                    if ($flag) {
                        $flag = false;
                        continue;
                    }
                    $num = count($data);
                    $row++;


                    $identifier = null;
                    for ($c = 0; $c < $num; $c++) {

                        // capture identifier (strictly recommend first column)
                        if ($columns[$c] === 'Ark ID') {
                            $noid = Database::dbopen($_GET["db"], NoidUI::dbpath(), DatabaseInterface::DB_WRITE);

                            if (empty($data[$c])) {
                                // mint a new ark id
                                $identifier = NoidArk::mint($noid, $contact);
                            } else {
                                $identifier = $data[$c];
                            }

                        }
                        if ($columns[$c] == "mods_local_identifier") {
                            // TOOD: check if Local exist
                            $checkExistedLocalID = Database::$engine->select("_value = '$data[$c]'");
                            if (is_array($checkExistedLocalID) && count($checkExistedLocalID) > 0) {
                                $identifier = preg_split('/\s+/', $checkExistedLocalID['_key'])[0];
                            }
                        }
                        if ($c > 0) { // avoid bindset identifier column

                            $noid = Database::dbopen($_GET["db"], NoidUI::dbpath(), DatabaseInterface::DB_WRITE);
                            $contact = time();

                            // check if ark ID exist
                            $checkExisted = Database::$engine->select("_key REGEXP '^" . $identifier . "' and _key REGEXP ':/c$'");
                            if (is_array($checkExisted) && count($checkExisted) > 0) {
                                $result = NoidArk::bind($noid, $contact, 1, 'set', $identifier, strtoupper($columns[$c]), $data[$c]);
                            }
                        }
                        if ($c == $num - 1) {
                            $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
                            $data[$num] = $protocol . $_SERVER['HTTP_HOST'] . "/ark:/" . $identifier;
                        }
                        Database::dbclose($noid);
                    }
                    // add columns to import data array
                    array_push($importedData, $data);
                }
                //TODO: write each row to new csv

                $noidUI->importedToCSV("import_minted", $noidUI->path($_GET["db"]), $columns, $importedData, time());
                fclose($handle);
            }
        }
        header("Location: admin.php?db=" . $_GET["db"]);
    }
}
