<?php
require_once "NoidUI.php";
require_once "index.php";
require_once "NoidLib/lib/Storage/MysqlDB.php";
require_once 'NoidLib/custom/GlobalsArk.php';
require_once 'NoidLib/lib/Db.php';
require_once 'NoidLib/custom/Database.php';
require_once 'NoidLib/custom/NoidArk.php';
require_once 'NoidLib/custom/MysqlArkConf.php';

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
use Noid\Lib\Custom\NoidArk;

// set db type as mysql instead
GlobalsArk::$db_type = 'ark_mysql';
define("NAAN_UTSC", 61220);
$arkdbs = Database::showdatabases();
?>

    <html>
    <head>
        <title>Ark Services</title>
        <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css"
              integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z"
              crossorigin="anonymous">
        <link rel="stylesheet" href="datatables/datatables.min.css">

        <script type="text/javascript" language="javascript" src="https://code.jquery.com/jquery-3.5.1.js"></script>
        <script type="text/javascript" language="javascript"
                src="https://cdn.datatables.net/1.10.22/js/jquery.dataTables.min.js"></script>

        <script src="https://cdn.jsdelivr.net/npm/popper.js@1.16.1/dist/umd/popper.min.js"
                integrity="sha384-9/reFTGAW83EW2RDu2S0VKaIzap3H66lZH81PoYlFhbGU+6BZp6G7niu735Sk7lN"
                crossorigin="anonymous"></script>
        <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"
                integrity="sha384-B4gt1jrGC7Jh4AgTPSdUtOBvfO8shuf57BaghqFfPlYxofvL8/KUEfYiJOMMV+rV"
                crossorigin="anonymous"></script>
        <script type="text/javascript" language="javascript" src="datatables/datatables.min.js"></script>

        <style>
            .form-group.required .control-label:after {
                content: "*";
                color: #ff0000;
            }
        </style>
        <script>
            var noidTemplates = {
                ".rddd": "to mint random 3-digit numbers, stopping after 1000th",
                ".sdddddd": "to mint sequential 6-digit numbers, stopping after millionth",
                ".zd": "sequential numbers without limit, adding new digits as needed",
                ".rdddd": "random 4-digit numbers with constant, prefix must be must be bc",
                ".sdd": "sequential 2-digit numbers with constant, prefix must be must be 8rf",
                ".se": "sequential extended-digits (from 0123456789bcdfghjkmnpqrstvwxz)",
                ".reee": "random 3-extended-digit numbers with constant, prefix must be must be h9",
                ".zeee": "unlimited sequential numbers with at least 3 extended-digits",
                ".rdedeedd": "random 7-char numbers, extended-digits at chars 2, 4, and 5",
                ".zededede": "unlimited mixed digits, adding new extended-digits as needed",
                ".sdede": "sequential 4-mixed-digit numbers with constant, prefix must be must be sdd",
                ".rdedk": "random 3 mixed digits plus final (4th) computed check character",
                ".sdeeedk": "5 sequential mixed digits plus final extended-digit check char",
                ".zdeek": "sequential digits plus check char, new digits added as needed",
                ".redek": "prefix plus random 4 mixed digits, one of them a check char",
                ".reedeedk": 'Minting order is random with limit 70,728,100 entry,, prefix must be must be must be "f5",'
            };
            <?php
            if (isset($_GET['db']) ) {
            ?>
            $(document).ready(function () {
                jQuery('#minted_table').DataTable({
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=minted" ?>",
                        "dataSrc": ""
                    },
                    columns: [
                        {data: '_key'},
                        {data: '_value'},
                    ],
                    dom: 'Bfrtip',
                    buttons: [
                        {
                            extend: 'csv',
                            exportOptions: {
                                columns: [0]
                            }
                        },
                    ]
                });

                jQuery('#bound_table').DataTable({
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=bound" ?>",
                        "dataSrc": ""
                    },
                    columns: [
                        {data: 'id'},
                        {data: 'PID'},
                        {data: 'metadata'},
                        {data: 'ark_url'},

                    ],
                    "columnDefs": [
                        {
                            "targets": 2,
                            "data": "metadata",
                            "render": function (data, type, row) {
                                if (data !== undefined && data.indexOf("|") != -1) {
                                    data = data.split("|").join("<br/>");
                                    data = data.split(":").join(": ");
                                }
                                return data;
                            }
                        },
                        {
                            "targets": 3,
                            "data": "ark_url",
                            "render": function (data, type, row) {
                                return '<a href="' + data + '">' + data + '</a>';
                            }
                        }
                    ]
                });
            });
            <?php
            }
            ?>


        </script>

    </head>
    <body>
    <div class="container">


        <div class="row">
            <div class="col-sm text-center">
                <h1 class="text-center">Ark Service</h1>
                <a href="/logout.php">Logout</a>
            </div>
        </div>


        <div class="card">
            <?php
            if (isset($_GET['db'])) {
                print '<h5 class="card-header">Database <i>' . $_GET['db'] . '</i> is selected.</h5>';
            } else {
                print <<<EOS
                    <h5 class="card-header">Create Database</h5>
                EOS;
            }
            ?>

            <div class="card-body">
                <div id="row-dbcreate" class="row">
                    <div class="col-sm-6">
                        <?php
                        if (!isset($_GET['db'])) {
                            print <<<EOS
                            <form id="form-dbcreate" action="./admin.php" method="post">
                                <div class="form-group">
                                    <label for="enterDatabaseName">Database Name:</label>
                                    <input type="text" class="form-control" id="enterDatabaseName" name="enterDatabaseName"
                                           required/>
                                </div>
                                <p><small id="noidHelp" class="form-text text-muted">For configuration detail, please visit <a target="_blank" href="https://metacpan.org/pod/distribution/Noid/noid">https://metacpan.org/pod/distribution/Noid/noid</a> </small></p>
                                
                               
                                  <script type="text/javascript">
                                    function onChangeTemplate(value)
                                    {
                                        // reset prefix
                                        document.getElementById("enterPrefix").value = "";
                                        document.getElementById('enterPrefix').readOnly = false;
                                        
                                        // swich detail explanation 
                                        document.getElementById("templateHelp").innerHTML = "<strong>Template definition: </strong> " + noidTemplates[value] + "</span>" ;
                                        switch (value) { 
                                            case ".rdddd": {
                                                // set, prefix must be must be to bc
                                                document.getElementById("enterPrefix").value = "bc";
                                                document.getElementById("enterPrefix").readOnly = true;
                                                break; 
                                            }
                                            case ".sdd": { 
                                                // set, prefix must be must be to 8rf
                                                document.getElementById("enterPrefix").value = "8rf";
                                                document.getElementById("enterPrefix").readOnly = true;
                                                break; 
                                            }
                                             case ".reee": { 
                                                // set, prefix must be must be to h9
                                                document.getElementById("enterPrefix").value = "h9";
                                                document.getElementById("enterPrefix").readOnly = true;
                                                break; 
                                            }case ".sdede": { 
                                                // set, prefix must be must be to ssd
                                                document.getElementById("enterPrefix").value = "ssd";
                                                document.getElementById("enterPrefix").readOnly = true;
                                                break; 
                                            }case ".redek": { 
                                                // set, prefix must be must be to 63q
                                                document.getElementById("enterPrefix").value = "63q";
                                                document.getElementById("enterPrefix").readOnly = true;
                                                break; 
                                            }case ".reedeedk": { 
                                                // set, prefix must be must be to 63q
                                                document.getElementById("enterPrefix").value = "f5";
                                                document.getElementById("enterPrefix").readOnly = true;
                                                break; 
                                            }
                                            default: 
                                                break;
                                        }
                                        
                                    }
                                </script>
                                <div class="form-group">
                                    <label for="templateHelp">Template:</label>
                                    
                                    <select class="form-control" id="selectTemplate" name="selectTemplate" onchange="onChangeTemplate(this.value);" required>
                                        <option selected disabled value="">Choose...</option>
                                        <option>.rddd</option>
                                        <option>.sdddddd</option>
                                        <option>.zd</option>
                                        <option>.rdddd</option>
                                        <option>.sdd</option>
                                        <option>.se</option>
                                        <option>.reee</option>
                                        <option>.rdedeedd</option>
                                        <option>.zededede</option>
                                        <option>.sdede</option>
                                        <option>.rdedk</option>
                                        <option>.sdeeedk</option>
                                        <option>.zdeek</option>
                                        <option>.redek</option>
                                        <option>.reedeedk</option>
                                    </select>
                                    <p id="templateHelp"></p>
                                    
                                </div>
                                
                                <div class="form-group">
                                    <label for="enterDatabaseName">Prefix (must be unique):</label>
                                    <input type="text" class="form-control" id="enterPrefix" name="enterPrefix" required/>
                                </div> 
                                
                                <script type="text/javascript">
                                    function onChangeTerms(value)
                                    {
                                        //alert(value);
                                        switch (value) { 
                                            case 'short': {
                                                break; 
                                            }
                                            case 'medium': {
                                                break; 
                                            }
                                            case 'long': {
                                                document.getElementById("enterNAAN").required = true;
                                                document.getElementById("enterInsitutionName").required = true;
                                                document.getElementById("enterRedirect").required = true;
                                                break; 
                                            }
                                            default: { 
                                                break;
                                            }
                                        }
                                    }
                                </script>
                                <div class="form-group">
                                    <label for="enterDatabaseName">Term:</label>
                                    <select class="form-control" id="identifier_minter" name="identifier_minter" onchange="onChangeTerms(this.value);" required>
                                        <option selected disabled value="">Choose...</option>
                                        <option>short</option>
                                        <option>medium</option>
                                        <option>long</option>
                                    </select>
                                </div>
                                
                                <div class="form-group">
                                    <label class="control-label" for="enterDatabaseName">Name Assigning Authority Number(NAAN):</label>
                                    <input type="text" class="form-control" id="enterNAAN" name="enterNAAN"/>
                                   <small id="emailHelp" class="form-text text-muted">Exclusive For UTSC: 61220</small>
                                </div>
                                 <div class="form-group">
                                    <label class="control-label" for="enterDatabaseName">Redirect URL(NAA):</label>
                                    <input type="text" class="form-control" id="enterRedirect" name="enterRedirect"
                                           />
                                   <small id="emailHelp" class="form-text text-muted">Exclusive For UTSC: digital.utsc.utoronto.ca</small>
                                </div>
                                
                                 <div class="form-group">
                                    <label class="control-label" for="enterDatabaseName">Insitution Name(SubNAA):</label>
                                    <input type="text" class="form-control" id="enterInsitutionName" name="enterInsitutionName"
                                           />
                                   <small id="emailHelp" class="form-text text-muted">Exclusive For UTSC: dsu/utsc-library</small>
                                </div>
                                
                                <input type="submit" name="dbcreate" value="Create" class="btn btn-primary"/>
                            </form>
                            EOS;

                        } else {
                            print <<<EOS
                            <a class="btn btn-secondary" href="./admin.php">Reset</a>
                        EOS;
                        }
                        ?>

                    </div>
                    <div class="col-sm-6">
                        <?php
                        if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['dbcreate']) && !isset($_GET['db'])) {
                            // Repace white space (if there is) with underscore
                            $database = str_replace(" ", "_", $_POST['enterDatabaseName']);

                            // add prefix to database.
                            $database = GlobalsArk::$db_prefix . $database;

                            // generate an ark service processing object
                            $noidUI = new NoidUI();

                            // create db directory if not exsit

                            if (!file_exists(getcwd() . "/db")) {
                                mkdir(getcwd() . "/db", 0775);
                            }
                            // TODO : CHECK entered prefix exist or not
                            $ePrefixflag = false;

                            foreach ($arkdbs as $db) {
                                $db = $db[0];
                                if (!in_array($db[0], ['.', '..', '.gitkeep', 'log'])) {
                                    $pf = json_decode(rest_get("/rest.php?db=$db[0]&op=prefix"));

                                    if ($pf === $_POST['enterPrefix']) {
                                        $ePrefixflag = true;
                                    }
                                }
                            }
                            if ($ePrefixflag === false) {
                                $dbpath = getcwd() . DIRECTORY_SEPARATOR . 'db';
                                $report = Database::dbcreate($database,
                                    $dbpath,
                                    'utsc',
                                    trim($_POST['enterPrefix']),
                                    $_POST['selectTemplate'],
                                    $_POST['identifier_minter'],
                                    trim($_POST['enterNAAN']),
                                    trim($_POST['enterRedirect']),
                                    trim($_POST['enterInsitutionName']),
                                );
                            } else {
                                print '
                                <div class="alert alert-danger" role="alert">
                                    The entered prefix has been used, please enter another prefix
                                </div>
                            ';
                            }

                            header("Location: admin.php");
                        }

                        // List all created databases in the table
                        if (count($arkdbs) > 0) {
                            ?>
                            <div class="row">
                                <table class="table table-bordered">
                                    <thead>
                                    <tr>
                                        <th scope="col">Databases</th>
                                        <th scope="col">Status</th>
                                        <th scope="col">Basic Info</th>
                                    </tr>
                                    </thead>
                                    <tbody>
                                    <?php
                                    foreach ($arkdbs as $db) {
                                        $highlight = "";
                                        $setActive = '<a href="./admin.php?db=' . $db . '">Select</a>';
                                        if ((isset($_GET['db']) && $_GET['db'] == $db)) {
                                            $setActive = "<strong>Selected</srong>";
                                            $highlight = 'class="table-success"';
                                        }
                                        $metadata = json_decode(rest_get("/rest.php?db=" . $db . "&op=dbinfo"));
                                        $detail = "<p>";
                                        foreach ((array)$metadata as $key => $value) {
                                            $detail .= "<strong>$key</strong>: $value <br />";
                                        }
                                        $detail .= "</p>";
                                        print <<<EOS
                                                    <tr $highlight>
                                                        <td scope="row">$db</td>
                                                        <td scope="row">$setActive</td>
                                                        <td scope="row">$detail</td>
                                                    </tr>
                                                EOS;
                                    }
                                    ?>
                                    </tbody>
                                </table>
                            </div>
                            <?php
                        }
                        ?>

                    </div>

                </div>
            </div>
        </div>

        <?php
        if (isset($_GET['db'])) { // if a database is selected (db name appears in the URL
            ?>
            <hr>
            <div class="card">
                <h5 class="card-header">Minting</h5>
                <div class="card-body">
                    <div id="row-mint" class="row">
                        <div class="col-sm-5">
                            <form id="form-mint" method="post" action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                <div class="form-group">
                                    <input type="hidden" name="db" value="<?php echo $_GET['db'] ?>">
                                    <label for="exampleInputEmail1">How many:</label>
                                    <input type="number" class="form-control" id="mint-number" name="mint-number">
                                </div>
                                <input type="submit" name="mint" value="Mint" class="btn btn-primary"/>
                            </form>
                        </div>
                        <div class="col-sm-7">
                            <?php
                            if ($_SERVER["REQUEST_METHOD"] == "POST" && !empty($_POST['mint-number'])) {

                                $noid = Database::dbopen($_GET["db"], NoidUI::dbpath(), DatabaseInterface::DB_WRITE);
                                $contact = time();
                                while ($_POST['mint-number']--) {
                                    $id = NoidArk::mint($noid, $contact);
                                };
                                print '
                                <div class="alert alert-success" role="alert">
                                    Ark IDs have been minted successfully.
                                </div>
                            ';
                                Database::dbclose($noid);
                                // redirect to the page.
                                header("Location: admin.php?db=" . $_GET["db"]);
                            }
                            ?>
                            <div class="row">
                                <div class="col-md-12">
                                    <table id="minted_table" class="display" style="width:100%">
                                        <thead>
                                        <tr>
                                            <th>Ark ID</th>
                                            <th>Minted Date</th>
                                        </tr>
                                        </thead>
                                    </table>
                                </div>

                            </div>

                        </div>
                    </div>
                </div>
            </div>

            <hr>
            <div class="card">
                <h5 class="card-header">Bind Set</h5>
                <div class="card-body">
                    <div id="row-bindset" class="row">
                        <div class="col-sm-12">
                            <button type="button" class="btn btn-primary" data-toggle="modal"
                                    data-target="#bindsetModal">
                                Bind Set
                            </button>
                            <div class="modal fade" id="bindsetModal" tabindex="-1" aria-labelledby="bindsetModalLabel"
                                 aria-hidden="true">
                                <div class="modal-dialog">
                                    <div class="modal-content">
                                        <div class="modal-header">
                                            <h5 class="modal-title" id="bindsetModalLabel">Bind Set</h5>
                                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                                <span aria-hidden="true">&times;</span>
                                            </button>
                                        </div>
                                        <div class="modal-body">
                                            <div class="col-sm-12">
                                                <form id="form-bindset" method="post"
                                                      action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                                    <div class="form-group">
                                                        <label for="enterIdentifier">Identifier:</label>
                                                        <input type="text" class="form-control" id="enterIdentifier"
                                                               name="enterIdentifier"
                                                               required>
                                                    </div>
                                                    <div class="form-group">
                                                        <label for="enterKey">Key:</label>
                                                        <input type="text" class="form-control" id="enterKey"
                                                               name="enterKey" required>
                                                    </div>
                                                    <div class="form-group">
                                                        <label for="enterValue">Value:</label>
                                                        <input type="text" class="form-control" id="enterValue"
                                                               name="enterValue" required>
                                                    </div>
                                                    <input type="submit" name="bindset" value="Bind"
                                                           class="btn btn-primary"/>
                                                    <button type="button" class="btn btn-secondary"
                                                            data-dismiss="modal">
                                                        Close
                                                </form>
                                            </div>
                                        </div>

                                    </div>
                                </div>
                            </div>

                            <!-- Bulk Bind Modal -->
                            <button type="button" class="btn btn-primary" data-toggle="modal"
                                    data-target="#bulkBindModal">
                                Bulk Bind
                            </button>
                            <div class="modal fade" id="bulkBindModal" tabindex="-1"
                                 aria-labelledby="bulkBindModalLabel"
                                 aria-hidden="true">
                                <div class="modal-dialog">
                                    <div class="modal-content">
                                        <div class="modal-header">
                                            <h5 class="modal-title" id="bulkBindModalLabel">Bulk Binding</h5>
                                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                                <span aria-hidden="true">&times;</span>
                                            </button>
                                        </div>
                                        <div class="modal-body">
                                            <div class="row" style="padding-bottom: 10px;">
                                                <div class="col-sm-12">
                                                    <form id="form-import" method="post" enctype="multipart/form-data"
                                                          action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                                        <div class="form-group">
                                                            <p><strong><u>Note:</u></strong> For this section, please
                                                                follow:</p>
                                                            <ul>
                                                                <li>Mint first</li>
                                                                <li>Download the CSV with minted identifiers above and
                                                                    add
                                                                    fields as columns to the
                                                                    CSV
                                                                </li>
                                                                <li>Export as a CSV file (only accept CSV) .</li>
                                                                <li>Import it below</li>
                                                            </ul>

                                                            <p><strong><label for="importCSV">Upload
                                                                        CSV: </label></strong>
                                                            </p>
                                                            <input type="file"
                                                                   id="importCSV" name="importCSV"
                                                                   accept=".csv">
                                                            <small id="emailHelp" class="form-text text-muted">Only
                                                                accept
                                                                CSV</small>

                                                        </div>
                                                        <input type="submit" name="import" value="Bulk Bind"
                                                               class="btn btn-primary"/>
                                                        <button type="button" class="btn btn-secondary"
                                                                data-dismiss="modal">Close
                                                        </button>
                                                    </form>
                                                </div>
                                            </div>
                                        </div>

                                    </div>
                                </div>
                            </div>


                        </div>
                    </div>
                    <div class="row">
                        <div class="col-sm-12">
                            <?php
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
                                            !in_array("mods_local_identifier", $columns)){
                                            exit ('<div class="alert alert-danger" role="alert" style="margin-top:10px;">
                                                        The imported CSV must have column name "PID", "URL", and "mods_local_identifier". Please <a href="/admin.php?db='. $_GET['db'] .'">Try again.</a>
                                                    </div>');
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
                                                        error_log(print_r("New minted: " . $identifier, true), 0);
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


                            ?>
                            <div class="row">
                                <div class="col-md-12">
                                    <table id="bound_table" class="display" style="width:100%">
                                        <thead>
                                        <tr>
                                            <th>Ark ID</th>
                                            <th>PID</th>
                                            <th>Other Bound Data</th>
                                            <th>Ark URL</th>
                                        </tr>
                                        </thead>
                                    </table>
                                </div>

                            </div>

                        </div>
                    </div>
                </div>
            </div>


            <!--<hr>
        <div class="card">
            <h5 class="card-header">Fetch</h5>
            <div class="card-body">

                <div id="row-fetch" class="row">
                    <div class="col-sm-3">
                        <form id="form-fetch" method="post" action="./admin.php?db=<?php echo $_GET['db'] ?>">
                            <div class="form-group">
                                <label for="exampleInputEmail1">Identifer:</label>
                                <input type="text" class="form-control" id="identifer" name="identifer">
                            </div>
                            <input type="submit" name="fetch" value="Fetch" class="btn btn-primary"/>
                        </form>
                    </div>
                    <div class="col-sm-9">

                        <p>
                            <?php

            if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['fetch'])) {
                // creat an ark service processor
                $noidUI = new NoidUI();

                // execute the command with entered params
                $result = $noidUI->exec_command("fetch " . $_POST['identifer'], $noidUI->path($_GET["db"]));

                // display the result
                print('<div class="alert alert-info">');
                print "<p><strong>Result:</strong></p>";
                print($result);
                print('</div>');

                // refresh the page to destroy post section
                header("Location: admin.php?db=" . $_GET["db"]);
            }
            ?>
                        </p>
                    </div>
                </div>
            </div>
        </div>


        <hr>
        <div class="card">
            <h5 class="card-header">Get</h5>
            <div class="card-body">

                <div id="row-fetch" class="row">
                    <div class="col-sm-3">
                        <form id="form-get" method="post" action="./admin.php?db=<?php echo $_GET['db'] ?>">
                            <div class="form-group">
                                <label for="exampleInputEmail1">Identifer:</label>
                                <input type="text" class="form-control" id="identifer" name="identifer">
                            </div>
                            <div class="form-group">
                                <label for="exampleInputEmail1">Key:</label>
                                <input type="text" class="form-control" id="key" name="enterkey">
                            </div>
                            <input type="submit" name="get" value="Get" class="btn btn-primary"/>
                        </form>
                    </div>
                    <div class="col-sm-9">

                        <p>
                            <?php
            if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['get'])) {
                // generate Ark service procession object
                $noidUI = new NoidUI();

                // execute with entered params
                $result = $noidUI->exec_command("get " . $_POST['identifer'] . ' ' . $_POST['enterKey'], $noidUI->path($_GET["db"]));

                // display the results
                print('<div class="alert alert-info">');
                print "<p></p><strong>Result</strong></p>";
                print($result);
                print('</div>');

                // refresh the page to destroy post session
                header("Location: admin.php?db=" . $_GET["db"]);
            }
            ?>
                        </p>
                    </div>
                </div>
            </div>
        </div>
        -->

            <hr>
            <div class="card">
                <h5 class="card-header">History of Bulk Bind</h5>
                <div class="card-body">
                    <div id="row-search" class="row">
                        <div class="col-sm-6">
                            <?php

                            if (file_exists(NoidUI::dbpath())) {
                                // List all minted identifer in csv which created each time execute mint
                                $dirs = scandir(NoidUI::dbpath() . $_GET['db'] . '/import_minted');
                                if (count($dirs) > 2) {
                                    ?>
                                    <div class="row">
                                        <table class="table table-bordered">
                                            <thead>
                                            <tr>
                                                <th scope="col">Past imported</th>
                                                <th scope="col">Date</th>
                                            </tr>
                                            </thead>
                                            <tbody>
                                            <?php
                                            foreach ($dirs as $dir) {
                                                if (!in_array($dir, ['.', '..', '.gitkeep'])) {
                                                    $csv = (isset($_GET['db']) && $_GET['db'] == $dir) ? 'Currently Active' : '<a href="' . 'db/' . $_GET['db'] . '/import_minted/' . $dir . '">' . $dir . '</a>';
                                                    $date = date("F j, Y, g:i a", explode('.', $dir)[0]);

                                                    print <<<EOS
                                        <tr>
                                            <td scope="row">$csv</td>
                                            <td scope="row">$date</td>
                                        </tr>
                                    EOS;
                                                }
                                            }
                                            ?>
                                            </tbody>
                                        </table>
                                    </div>
                                <?php }
                            }
                            ?>

                        </div>
                    </div>
                </div>
            </div>
            <hr>
        <?php }
        ?>
    </div>
    </body>
    </html>

<?php


function rest_get($req)
{
    $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
    $cURLConnection = curl_init();
    curl_setopt($cURLConnection, CURLOPT_URL, $protocol . $_SERVER['HTTP_HOST'] . $req);
    curl_setopt($cURLConnection, CURLOPT_RETURNTRANSFER, true);

    $result = curl_exec($cURLConnection);
    curl_close($cURLConnection);
    return $result;
}
