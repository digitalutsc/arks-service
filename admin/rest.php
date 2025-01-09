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
        echo getMinted(0);
        break;
    }
    case "mintedDrop":
      {
          echo getMinted(1);
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
    case 'unbound':
    {
        echo selectUnBound();
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
    case 'purge': {
      if (isset($_GET['stage']) && $_GET['stage'] == 'upload'){
        // return result status
        echo purging();
      }
      else {
          echo  json_encode("Invalid stage");
      }
      break;
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

function handle_hierachy_variants() {

}

/**
 * Handle ajax call for each row of CSV during purging existing metadata
 */
function purging() {
  $status = true;
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
    die(json_encode(['success' => 0, 'message' => 'Database not found']));
  }
  if (empty($_POST['security'])  ||  (Database::isAuth($_POST['security']) === false) ) {
    die(json_encode(['success' => 401, 'message' => 'Security Credentials is invalid, Please verify it again.']));
  }

  $result = null;
  $purged = 0;
  if (is_array($_POST) && isset($_POST['data'])) {
    $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);

    $parts = explode("/", $_POST['data'][strtoupper('Ark_ID')]);
    $parts_count = count($parts);
    $identifier = $parts[0]. "/" .$parts[1];

    $where = "_key REGEXP '^" . $identifier ."\t' and _key NOT REGEXP ':/c$' and _key NOT REGEXP ':/h$' order by _key";
    $status = Database::$engine->purge($where);
  }
  return json_encode(['success' => $status]);
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
  $purged = 0;
  if (is_array($_POST) && isset($_POST['data'])) {
    $purged = $_POST['purged'];
    // capture identifier (strictly recommend first column)
    $contact = time();

    if (!empty($_POST['data'][strtoupper('Ark_ID')])) { // any pending data must has Ark_ID column
        $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
        
        $parts = explode("/", $_POST['data'][strtoupper('Ark_ID')]);
        $parts_count = count($parts);
        $identifier = $parts[0]. "/" .$parts[1];

        // TODO: check if the column Ark_ID has "/" ==> handle with hierarchical
        if (substr_count($_POST['data'][strtoupper('Ark_ID')], '/') > 1) { 
          // this arks ID is hierarchical
          $hierarchy = "/";
          for ($i = 2; $i < $parts_count; $i++) {
            if (strpos($parts[$i], ".") !== false) {
              $hierarchy .= explode(".", $parts[$i])[0]; 
            }
            else {
              $hierarchy .= $parts[$i]; 
            }
            if ($i < $parts_count-1)
              $hierarchy .= "/";
          }
        }
        
        if (substr_count($_POST['data'][strtoupper('Ark_ID')], '.') > 0) { 
          // this ark ID has variants
          $parts_variants = explode(".", $parts[$parts_count-1]);
          array_shift($parts_variants);
          $variants = "." . implode(".", $parts_variants); 
        }
       
        // Binding the new metadata
        foreach ($_POST['data'] as $key => $pair) {
          if ($key !== strtoupper('Ark_ID')) {
            
            // if there is hierachy, ie 61220/utsc0	/page1 WHO
            $key_field = "";
            if ((isset($hierarchy) && $hierarchy !== "/")) {
              $key_field = $hierarchy . "	";  
            }
            // if there is hierachy, ie 61220/utsc0	/page1.image.png
            if (isset($variants)) { 
              $key_field .= $variants . "	";
            }
            $key_field .= strtoupper($key);  

            NoidArk::bind($noid, $contact, 1, 'set', $identifier, $key_field, $pair);
          }
        }
        Database::dbclose($noid);
        return json_encode(['success' => true]);
    }
    else {
      // todo: flag error of missing Ark ID column
      return json_encode(['success' => false]);
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
function selectUnBound()
{
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
    die(json_encode('Database not found'));
  }

  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
  Database::dbclose($noid);

  $columnIdx = $_GET['order'][0]['column'];
  $sortCol = $_GET['columns'][$columnIdx];
  $sortDir = $_GET['order'][0]['dir'] === 'asc' ? 'ASC' : 'DESC';
  $offset = $_GET['start'] ?? 0;
  $limit = $_GET['length'] ?? 50;
  if ($_GET['length'] == -1) {
    $limit = NULL;
  }
  $search = $_GET['search']['value'];
  
  // sql which gets the arks without any metadata bound
  $sql_unboundarks = "SELECT id, REPLACE (id, '$firstpart', '') as _id
  from (
      SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id 
      FROM `<table-name>`
      WHERE _key LIKE '$firstpart%' AND (_key LIKE '%$search%' OR _value LIKE '%$search%')
      EXCEPT
        SELECT DISTINCT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id 
        FROM `<table-name>`
        WHERE _key LIKE '$firstpart%' AND (_key NOT LIKE '%:\\\\/c' AND _key NOT LIKE '%:\\\\/h')
  ) as list_ids
  ORDER BY cast(_id as unsigned) $sortDir";

// sql gets all unbound arks
  $sql = "$sql_unboundarks LIMIT $limit OFFSET $offset";
  $sql_count = "SELECT COUNT(*) as num_filtered
     FROM (
       $sql_unboundarks
     ) AS filtered_ids
  ";

  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $rows = Database::$engine->query($sql);
  $num_filtered = Database::$engine->query($sql_count)[0]['num_filtered'] ?? 0;
  Database::dbclose($noid);

  $currentID = null;
  $result = array();
  $r = [];

  foreach ($rows as $row) {
    $row = (array)$row;

    $r['id'] = $row['id'];
      
    if (empty($_SERVER['HTTPS'])) {
      $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
    }
    else {
      $protocol = "https://";
    }
    
    // establish Ark URL
    $arkURL = $protocol . $_SERVER['HTTP_HOST'];
    $ark_url = rtrim($arkURL,"/") . "/ark:" . $row['id'];
    $r['select'] = ' ';

    // New: Link to ? or ?? 
    $r['metadata'] = $ark_url . "?";
    $r['policy'] = $ark_url . "??";
    $r['ark_url'] = (array_key_exists("ark_url", $r) && is_array($r['ark_url']) && count($r['ark_url']) > 1) ? $r['ark_url'] : [$ark_url];

    array_push($result, $r);
  }

  return json_encode(array(
    "data" => $result,
    "draw" => isset ( $_GET['draw'] ) ? intval( $_GET['draw'] ) : 0,
    "recordsTotal" => countTotalArks(),
    "recordsFiltered" => $num_filtered,
  ));
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
  Database::dbclose($noid);

  $columnIdx = $_GET['order'][0]['column'];
  $sortCol = $_GET['columns'][$columnIdx];
  $sortDir = $_GET['order'][0]['dir'] === 'asc' ? 'ASC' : 'DESC';
  $offset = $_GET['start'] ?? 0;
  $limit = $_GET['length'] ?? 50;
  $search = $_GET['search']['value'];
  
  // sql which gets all bound arks 
  $sql_boundarks = "SELECT id, REPLACE (id, '$firstpart', '') as _id
      from (
          SELECT DISTINCT REGEXP_SUBSTR(_key, '".$firstpart."[[:digit:]]+(\\t[/.]*.*\\t)*') AS id
              FROM `<table-name>`
              WHERE _key LIKE '$firstpart%' 
              AND (_key NOT REGEXP '\\\\s:\\/c' AND _key NOT REGEXP '\\\\s:\\/h') 
              AND (_key LIKE '%$search%' OR _value LIKE '%$search%')
      ) as list_ids
      ORDER BY cast(_id as unsigned) $sortDir";

  $sql = "$sql_boundarks LIMIT $limit OFFSET $offset";
  $sql_count = "SELECT COUNT(*) as num_filtered
  FROM (
    $sql_boundarks
  ) AS filtered_ids
  ";

  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $rows = Database::$engine->query($sql);
  $num_filtered = Database::$engine->query($sql_count)[0]['num_filtered'] ?? 0;
  Database::dbclose($noid);

  $currentID = null;
  $result = array();
  $r = [];

  foreach ($rows as $row) {
    $row = (array)$row;

    $r['id'] = preg_replace('/\s+/', '', $row['id']);
    if (empty($_SERVER['HTTPS'])) {
      $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
    }
    else {
      $protocol = "https://";
    }
    
    // establish Ark URL
    $arkURL = $protocol . $_SERVER['HTTP_HOST'];
    $ark_url = rtrim($arkURL,"/") . "/ark:" . $row['id'];
    $ark_url = preg_replace('/\s+/', '', $ark_url);
    $r['select'] = ' ';
    
    /*if ($limit != 2147483647) {
      $redirect = getRedirects($row['id']);
      $r['redirect'] = (!empty($redirect)) ? $redirect : 0;
    }
    else {
      $r['redirect'] = " ";
    }*/
    
    // New: Link to ? or ?? 
    $r['metadata'] = $ark_url . "?";
    $r['policy'] = $ark_url . "??";
    $r['ark_url'] = (array_key_exists("ark_url", $r) && is_array($r['ark_url']) && count($r['ark_url']) > 1) ? $r['ark_url'] : [$ark_url];

    array_push($result, $r);
  }

  return json_encode(array(
    "data" => $result,
    "draw" => isset ( $_GET['draw'] ) ? intval( $_GET['draw'] ) : 0,
    "recordsTotal" => countTotalArks(),
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
 * Get Ark PID for ark ID
 * @param $arkID
 * @return false|string
 */
function getRedirects($arkID) {
  if (!isset($arkID))
      return "Ark ID is not valid";
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
      die(json_encode('Database not found'));
  }
  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  return NoidArk::fetch($noid, 0, $arkID, ['REDIRECT']);
  Database::dbclose($noid);

  //$result = Database::$engine->select("_key = '$arkID REDIRECT'");
  
  
  return (is_array($result) && count($result)> 0) ? $result[0]['_value'] : '';
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
function getMinted($mode)
{
  $totalArks = countTotalArks();
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
    die(json_encode('Database not found'));
  }
  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
  Database::dbclose($noid);

  if (isset($_GET['order'][0]['dir'])) {
    $sortDir = $_GET['order'][0]['dir'] === 'asc' ? 'ASC' : 'DESC';
  } else {
    $sortDir = 'DESC';
  }
  if($mode === 1){
    $limit = $totalArks;
  }else{
    $limit = $_GET['length'] ?? 50;
  }
  $offset = $_GET['start'] ?? 0;
  $search = $_GET['search']['value'];

  $sql = "SELECT REGEXP_SUBSTR(_key, '^([^\\\\s]+)') AS id, _value, SUBSTRING_INDEX(SUBSTRING_INDEX(_value,'|',4), '|', -1) AS seq
    FROM `<table-name>`
    WHERE _key LIKE '$firstpart%' AND _key REGEXP '\\\\s:\/c$' AND (_key LIKE '%$search%' OR _value LIKE '%$search%')
    ORDER BY  cast(seq as unsigned) $sortDir
    LIMIT $limit
    OFFSET $offset;
  ";
  
  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
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

  return json_encode(array(
    "data" => $json,
    "draw" => isset ( $_GET['draw'] ) ? intval( $_GET['draw'] ) : 0,
    "recordsTotal" => $totalArks,
    "recordsFiltered" => $totalArks,
  ));
}

/**
 * Count total Ark 
 */
function countTotalArks() {
  GlobalsArk::$db_type = 'ark_mysql';
  if (!Database::exist($_GET['db'])) {
      die(json_encode('Database not found'));
  }
  $noid = Database::dbopen($_GET["db"], getcwd() . "/db/", DatabaseInterface::DB_WRITE);
  $total = Database::$engine->get(Globals::_RR . "/oacounter");
  Database::dbclose($noid);
  return $total;
}

/**
 * Count arks IDs that are bound with metadata
 */
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
    WHERE _key LIKE '$firstpart%' AND _key REGEXP '(\\\\s:\\/c|\\\\s:\\/h)$';
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
    Database::dbclose($noid);
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
    Database::dbclose($noid);
    return json_encode($prefix);
}
