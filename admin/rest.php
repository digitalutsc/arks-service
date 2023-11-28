<?php
require_once "functions.php";

use Noid\Lib\Custom\NoidArk;
use Noid\Lib\Storage\DatabaseInterface;
use Noid\Lib\Globals;

use Noid\Lib\Custom\Database;
use Noid\Lib\Custom\GlobalsArk;

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
        echo getNAA($_GET['db']);
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
    case 'backupdb': {
        if (empty($_POST['security'])  ||  (Database::isAuth($_POST['security']) === false) ) {
            die(json_encode(['success' => 401, 'message' => 'Security Credentials is invalid, Please verify it again.']));
        }

        // backup database before bulk binding
        Database::backupArkDatabase();
        return json_encode(['success' => 1]);
    }
    case 'bulkbind': {

        if (isset($_GET['stage']) && $_GET['stage'] == 'upload'){
            // return result status
            echo bulkbind();
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
 *  Handle ajax call for each row of CSV during bulk binding import
 *
 * @return false|string
 */
function bulkbind(){
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
    die(json_encode(['success' => 0, 'message' => 'Database not found']));
  }
  if (empty($_POST['security'])  ||  (Database::isAuth($_POST['security']) === false) ) {
    die(json_encode(['success' => 401, 'message' => 'Security Credentials is invalid, Please verify it again.']));
  }

  $result = null;
  if (is_array($_POST) && isset($_POST['data'])) {
    $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
    // capture identifier (strictly recommend first column)
    $contact = time();

    if (!empty($_POST['data'][strtoupper('Ark_ID')])) { // any pending data must has Ark_ID column
        // check if the ARK ID has been bound before
        foreach ($_POST['data'] as $key => $pair) {
          if ($key !== strtoupper('Ark_ID')) {
            // check if ark ID exist
            $identifier = $_POST['data'][strtoupper('Ark_ID')];
            NoidArk::bind($noid, $contact, 1, 'set', $identifier, strtoupper($key), $pair);
          }
        }
        Database::dbclose($noid);
        return json_encode(['success' => 1]);
    }
    else {
      // todo: flag error of missing Ark ID column
      return json_encode(['success' => 0]);
    }
  }
}

/**
 * (Old, unused) This function can handle bulk bind without mint first
 * But disabled because the duplication check with unique Local ID not valid anymore
 *
 * @return false|string
 */
function free_bulkbind(){
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
    die(json_encode(['success' => 0, 'message' => 'Database not found']));
  }
  if (empty($_POST['security'])  ||  (Database::isAuth($_POST['security']) === false) ) {
    die(json_encode(['success' => 401, 'message' => 'Security Credentials is invalid, Please verify it again.']));
  }

  $result = null;
  if (is_array($_POST) && isset($_POST['data'])) {
    $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
    // capture identifier (strictly recommend first column)
    $contact = time();

    if (!empty($_POST['data'][strtoupper('LOCAL_ID')])) {
      // if Local_ID valid, check if Local_ID existed.
      $checkExistedLocalID = Database::$engine->select("_value = '".$_POST['data']['LOCAL_ID']."'");

      // if Local_id existed, get Ark ID from LocalID
      if (is_array($checkExistedLocalID) && count($checkExistedLocalID) > 0) {
        $identifier = preg_split('/\s+/', $checkExistedLocalID[0]['_key'])[0];
      }
      else { // if Local_ID is not existed, Look for Ark ID, this is for ingesting to update existing Ark

        // if Ark ID not in CSV, minting new Ark ID
        if (empty($_POST['data'][strtoupper('Ark_ID')] )) {
          // mint a new ark id
          $identifier = NoidArk::mint($noid, $contact);
        }
        else {
          // obtain Ark ID to do update
          $identifier = $_POST['data'][strtoupper('Ark_ID')];
        }
      }
    }
    else {
      // TODO: if Local ID is empty, go for PID as unique check
      if (!empty($_POST['data'][strtoupper('PID')])) {
        $checkExistedPID = Database::$engine->select("_value = '".$_POST['data']['PID']."'");

        // if Local_id existed, get Ark ID from LocalID
        if (is_array($checkExistedPID) && count($checkExistedPID) > 0) {
          $identifier = preg_split('/\s+/', $checkExistedPID[0]['_key'])[0];
        }else {
          // if Ark ID not in CSV, minting new Ark ID
          if (empty($_POST['data'][strtoupper('Ark_ID')] )) {
            // mint a new ark id
            $identifier = NoidArk::mint($noid, $contact);
          }
          else {
            // obtain Ark ID to do update
            $identifier = $_POST['data'][strtoupper('Ark_ID')];
          }
        }
      }
      else {
        // from PID not find the Ark ID, mint it
        if (empty($_POST['data'][strtoupper('Ark_ID')] )) {
          // mint a new ark id
          $identifier = NoidArk::mint($noid, $contact);
        }
        else {
          $identifier = $_POST['data'][strtoupper('Ark_ID')];
        }
      }

    }

    foreach ($_POST['data'] as $key => $pair) {
      if ($key !== strtoupper('Ark_ID')) {
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

  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");

  $columnIdx = $_GET['order'][0]['column'];
  $sortCol = $_GET['columns'][$columnIdx];
  $sortDir = $_GET['order'][0]['dir'] === 'asc' ? 'ASC' : 'DESC';
  $offset = $_GET['start'] ?? 0;
  $limit = $_GET['length'] ?? 50;
  $search = $_GET['search']['value'];
  
  if ($sortCol['data'] === 'redirect') {
    $sql = "SELECT arks.* 
      FROM `<table-name>`
      AS arks 
      JOIN ( 
        SELECT bound.id, 
        COALESCE(redirected._value, 0) 
        AS _value 
        FROM ( 
          SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id 
          FROM <table-name> 
          WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '(\\\\s:\\/c|\\\\sREDIRECT|\\\\sPID|\\\\sLOCAL_ID|\\\\sCOLLECTION)$' AND (_key LIKE '%$search%' OR _value LIKE '%$search%')
        ) AS bound 
        LEFT JOIN ( 
          SELECT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id, _value 
          FROM <table-name> 
          WHERE _key LIKE '$firstpart%' AND _key REGEXP '\\\\sREDIRECT$'
        ) AS redirected ON bound.id = redirected.id 
        ORDER BY _value $sortDir 
        LIMIT $limit 
        OFFSET $offset 
      ) AS subquery 
      ON arks._key LIKE CONCAT(subquery.id, '%')
      AND arks._key NOT LIKE '%:\\/c'
      ORDER BY arks._key ASC;
    ";
    $sql_count = "SELECT COUNT(*) as num_filtered
      FROM (
        SELECT bound.id, 
        COALESCE(redirected._value, 0) 
        AS _value 
        FROM ( 
          SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id 
          FROM <table-name> 
          WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '(\\\\s:\\/c|\\\\sREDIRECT|\\\\sPID|\\\\sLOCAL_ID|\\\\sCOLLECTION)$'
        ) AS bound 
        LEFT JOIN ( 
          SELECT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id, _value 
          FROM <table-name> 
          WHERE _key LIKE '$firstpart%' AND _key REGEXP '\\\\sREDIRECT$'
        ) AS redirected ON bound.id = redirected.id 
      ) AS filtered_ids;
    ";
  }
  else { // Sort on Ark IDs
    $sql = "SELECT arks.* 
      FROM `<table-name>`
      AS arks 
      JOIN ( 
        SELECT * FROM (
          SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id
          FROM `<table-name>`
          WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '(\\\\s:\\/c|\\\\sREDIRECT|\\\\sPID|\\\\sLOCAL_ID|\\\\sCOLLECTION)$' 
          INTERSECT
          SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id
          FROM `<table-name>`
          WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '\\\\s:\\/c' AND (_key LIKE '%$search%' OR _value LIKE '%$search%')
        ) AS target
        ORDER BY id $sortDir 
        LIMIT $limit
        OFFSET $offset
      ) AS subquery 
      ON arks._key LIKE CONCAT(subquery.id, '%') 
      AND arks._key NOT LIKE '%:\\/c' 
      ORDER BY arks._key $sortDir;
    ";
    $sql_count = "SELECT COUNT(*) as num_filtered
      FROM (
        SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id
        FROM `<table-name>`
        WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '(\\\\s:\\/c|\\\\sREDIRECT|\\\\sPID|\\\\sLOCAL_ID|\\\\sCOLLECTION)$' 
        INTERSECT
        SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id
        FROM `<table-name>`
        WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '\\\\s:\\/c' AND (_key LIKE '%$search%' OR _value LIKE '%$search%')
      ) AS filtered_ids;
    ";
  }

  $rows = Database::$engine->query($sql);
  $num_filtered = Database::$engine->query($sql_count)[0]['num_filtered'] ?? 0;
  Database::dbclose($noid);

  $currentID = null;
  $result = array();
  $r = [];

  foreach ($rows as $row) {
    $row = (array)$row;

    if (isset($row['_key'])) {
      $key_data = preg_split('/\s+/', $row['_key']);
      if (!isset($currentID) || ($currentID !== $key_data[0])) {
        $currentID = $key_data[0];
        if (is_array($r) && count($r) > 0) {
          array_push($result, $r);
        }

        $r = [
          'select' => ' ',
          'id' => $currentID,
          'PID' => ' ',
          'LOCAL_ID' => ' ',
          'redirect' => 0,
        ];
      }

      if ($key_data[1] == 'PID')
        $r['PID'] = (!empty($row['_value'])) ? $row['_value'] : ' ';
      if ($key_data[1] == "LOCAL_ID")
        $r['LOCAL_ID'] = (!empty($row['_value'])) ? $row['_value'] : ' ';
      if ($key_data[1] == "REDIRECT")
        $r['redirect'] = (!empty($row['_value'])) ? $row['_value'] : ' ';
      $r['metadata'] = (!empty($r['metadata']) ? $r['metadata'] . "|" : "") . $key_data[1] .':' .$row['_value'];

      // check if server have https://, if not, go with http://
      if (empty($_SERVER['HTTPS'])) {
        $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
      }
      else {
        $protocol = "https://";
      }

      $arkURL = $protocol . $_SERVER['HTTP_HOST'];
      // establish Ark URL
      // old format
      //$ark_url = rtrim($arkURL,"/") . "/ark:/" . $currentID;
      // new format
      $ark_url = rtrim($arkURL,"/") . "/ark:" . $currentID;
      $r['ark_url'] = (array_key_exists("ark_url", $r) && is_array($r['ark_url']) && count($r['ark_url']) > 1) ? $r['ark_url'] : [$ark_url];

      // if there is qualifier bound to an Ark ID, establish the link the link
      if ($key_data[1] !== "URL" && filter_var($row['_value'], FILTER_VALIDATE_URL)) {
        array_push($r['ark_url'], strtolower($ark_url. "/". $key_data[1]));
      }
    }
  }
  
  if (!empty($r)) {
    array_push($result, $r);
  }

  if ($sortCol['data'] === 'redirect') {
    $redirect = array_column($result, "redirect");
    array_multisort($redirect, $sortDir === 'ASC' ? SORT_ASC : SORT_DESC, $result);
  }
  else {
    $id = array_column($result, "id");
    array_multisort($id, $sortDir === 'ASC' ? SORT_ASC : SORT_DESC, $result);
  }

  return json_encode(array(
    "data" => $result,
    "draw" => isset ( $_GET['draw'] ) ? intval( $_GET['draw'] ) : 0,
    "recordsTotal" => countBoundedArks(),
    "recordsFiltered" => $num_filtered,
  ));
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

    $result = Database::$engine->select("_key REGEXP '^$firstpart' and _key NOT REGEXP ':/c$' and _key NOT REGEXP ':/h$' order by _key desc");
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
    $result = Database::$engine->select("_key = '$arkID\tURL'");
    Database::dbclose($noid);
    return json_encode($result);
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

  if (isset($_GET['order'][0]['dir'])) {
    $sortDir = $_GET['order'][0]['dir'] === 'asc' ? 'ASC' : 'DESC';
  } else {
    $sortDir = 'ASC';
  }
  $offset = $_GET['start'] ?? 0;
  $limit = $_GET['length'] ?? 50;

  $sql = "SELECT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id, _value
    FROM `<table-name>`
    WHERE _key LIKE '$firstpart%' AND _key REGEXP '\\\\s:\/c$' 
    ORDER BY _key $sortDir
    LIMIT $limit
    OFFSET $offset;
  ";

  $result = Database::$engine->query($sql);
  Database::dbclose($noid);

  $json = array();
  foreach ($result as $row) {
    $urow = array();
    $urow['select'] = ' ';
    $urow['_key'] = $row['id'];

    $metadata = explode('|', $row['_value']);
    //$urow['_value'] = date("F j, Y, g:i a", $metadata[2]);
    $urow['_value'] = date("F j, Y", $metadata[2]);
    array_push($json, (object)$urow);
  }

  $totalArks = countTotalArks();
  return json_encode(array(
    "data" => $json,
    "draw" => isset ( $_GET['draw'] ) ? intval( $_GET['draw'] ) : 0,
    "recordsTotal" => $totalArks,
    "recordsFiltered" => $totalArks,
  ));
}

function countTotalArks() {
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
      die(json_encode('Database not found'));
  }
  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
  $result = Database::$engine->query("SELECT COUNT(DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)')) AS total FROM `<table-name>` WHERE _key LIKE '$firstpart%' and _key REGEXP '\\\\s:\\/c$';");
  Database::dbclose($noid);
  return $result[0]['total'] ?? 0;
}

function countBoundedArks() {
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
      die(json_encode('Database not found'));
  }
  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
  $result = Database::$engine->query("SELECT COUNT(
    DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)')) AS total 
    FROM `<table-name>` 
    WHERE _key LIKE '$firstpart%' AND _key NOT REGEXP '(\\\\s:\\/c|\\\\sREDIRECT|\\\\sPID|\\\\sLOCAL_ID|\\\\sCOLLECTION)$';
  ");
  Database::dbclose($noid);
  return $result[0]['total'] ?? 0;
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
