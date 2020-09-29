<?php
include "lib/noid/Noid.php";
require_once "NoidUI.php";
require_once "index.php";


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

// set db type as mysql instead
GlobalsArk::$db_type = 'ark_mysql';
define("NAAN_UTSC", 61220);

function olddbcreate()
{

    // check parent database folder created yet, if not, create it.
    if (!file_exists($noidUI->path($database))) {
        mkdir($noidUI->path($database), 0775);
    }
    // Execute dbcomment with entered parameters.
    $result = $noidUI->exec_command("dbcreate " . $_POST['enterPrefix'] . $_POST['selectTemplate'] . " " . $_POST['identifier_minter'] . " 61220 " . $_POST['enterRedirect'] . " " . $_POST['enterInsitutionName'], $noidUI->path($database));

    // check new database directory created yet. if yes, display success message, if not display error message.
    $isReadable = file_exists($noidUI->path($database) . '/NOID/README');
    if ($isReadable) {
        $result = <<<EOS
                                <div class="alert alert-success" role="alert">
                                    New database <i>$database</i> created successfully.
                                </div>
                            EOS;
        print $result;

        //TODO: create a database's metadata file
        $metadata = array(
            "enterPrefix" => $_POST['enterPrefix'],
            "selectTemplate" => $_POST['selectTemplate'],
            "identifier_minter" => $_POST['identifier_minter'],
            "enterRedirect" => $_POST['enterRedirect'],
            "enterInsitutionName" => $_POST['enterInsitutionName'],
        );
        $noidUI->saveMetadataToCSV($noidUI->path($database), $database, $metadata);
    } else {
        $result = <<<EOS
                                <div class="alert alert-danger" role="alert">
                                    Sorry, failed to create <i>$database</i>.
                                </div>
                            EOS;
        print $result;
    }
}

?>

<html>
<head>
    <title>Ark Services</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css"
          integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
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
                                    <label for="enterDatabaseName">Prefix:</label>
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
                                    <small id="termHelp" class="form-text text-muted">For more infomration  </small>
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

                        // generate an ark service processing object
                        $noidUI = new NoidUI();

                        // create db directory if not exsit

                        if (!file_exists(getcwd() . "/db")) {
                            var_dump(getcwd() . "/db");
                            mkdir(getcwd() . "/db", 0775);
                        }

                        $dbpath = getcwd() . DIRECTORY_SEPARATOR . 'db/' . $database;
                        $report = Database::custom_dbcreate( $database,
                            $dbpath,
                            'utsc',
                            trim($_POST['enterPrefix']),
                            $_POST['selectTemplate'],
                            $_POST['identifier_minter'],
                            trim($_POST['enterNAAN']),
                            trim($_POST['enterRedirect']),
                            trim($_POST['enterInsitutionName']),
                        );


                        header("Location: admin.php");
                    }
                    if (file_exists(NoidUI::dbpath())) {
                        // List all created databases in the table
                        $dirs = scandir(NoidUI::dbpath());
                        if (is_array($dirs) && count($dirs) > 3) {
                            ?>
                            <div class="row">
                                <table class="table table-bordered">
                                    <thead>
                                    <tr>
                                        <th scope="col">Past database</th>
                                        <th scope="col">Select</th>
                                        <th scope="col">Basic Info</th>
                                    </tr>
                                    </thead>
                                    <tbody>
                                    <?php


                                    foreach ($dirs as $dir) {
                                        $highlight = "";
                                        $setActive = '<a href="./admin.php?db=' . $dir . '">Select</a>';
                                        if (!in_array($dir, ['.', '..', '.gitkeep'])) {
                                            if ((isset($_GET['db']) && $_GET['db'] == $dir)) {
                                                $setActive = "<strong>Selected</srong>";
                                                $highlight = 'class="table-success"';
                                            }
                                            $metadata = NoidUI::getDatabaseInfo(NoidUI::dbpath($dir), $dir);
                                            $detail = "<p>";
                                            foreach ((array)$metadata as $key => $value) {
                                                $detail .= "<strong>$key</strong>: $value <br />";
                                            }
                                            $detail .= "</p>";
                                            print <<<EOS
                                        <tr $highlight>
                                            <td scope="row">$dir</td>
                                            <td scope="row">$setActive</td>
                                            <td scope="row">$detail</td>
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
                            // create Ark service procession object
                            $noidUI = new NoidUI();

                            // execute command with entered params
                            $result = $noidUI->exec_command("mint " . $_POST['mint-number'], $noidUI->path($_GET["db"]));

                            // remove any empty identifer happen to be in the result array
                            $newIDs = array_filter(explode("id: ", $result));

                            // Create an CSV and write minted identifiers to that new CSV
                            $noidUI->mintToCSV($noidUI->path($_GET["db"]), $newIDs, time());

                            // redirect to the page.
                            header("Location: admin.php?db=" . $_GET["db"]);
                        }

                        // List all minted identifer in csv which created each time execute mint
                        if (file_exists(NoidUI::dbpath())) {
                            $dirs = scandir(NoidUI::dbpath() . $_GET['db'] . '/mint');
                            if (count($dirs) > 2) {
                                ?>
                                <div class="row">
                                    <table class="table table-bordered">
                                        <thead>
                                        <tr>
                                            <th scope="col">Past minting</th>
                                            <th scope="col">Date</th>
                                        </tr>
                                        </thead>
                                        <tbody>
                                        <?php
                                        foreach ($dirs as $dir) {
                                            if (!in_array($dir, ['.', '..', '.gitkeep'])) {
                                                $csv = (isset($_GET['db']) && $_GET['db'] == $dir) ? 'Currently Active' : '<a href="' . 'db/' . $_GET['db'] . '/mint/' . $dir . '">' . $dir . '</a>';
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
        <div class="card">
            <h5 class="card-header">Bind Set</h5>
            <div class="card-body">
                <div id="row-bindset" class="row">
                    <div class="col-sm-4">
                        <form id="form-bindset" method="post" action="./admin.php?db=<?php echo $_GET['db'] ?>">
                            <div class="form-group">
                                <label for="enterIdentifier">Identifier:</label>
                                <input type="text" class="form-control" id="enterIdentifier" name="enterIdentifier"
                                       required>
                            </div>
                            <div class="form-group">
                                <label for="enterKey">Key:</label>
                                <input type="text" class="form-control" id="enterKey" name="enterKey" required>
                            </div>
                            <div class="form-group">
                                <label for="enterValue">Value:</label>
                                <input type="text" class="form-control" id="enterValue" name="enterValue" required>
                            </div>
                            <input type="submit" name="bindset" value="Bind" class="btn btn-primary"/>
                        </form>
                    </div>
                    <div class="col-sm-8">
                        <?php
                        if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['bindset']) && !empty($_POST['enterIdentifier'])) {
                            // create Ark service procession object
                            $noidUI = new NoidUI();

                            // Execute command with entered params
                            $result = $noidUI->exec_command(" bind set " . $_POST['enterIdentifier'] . " " . $_POST['enterKey'] . " '" . $_POST['enterValue'] . "'", $noidUI->path($_GET["db"]));

                            // display the rsults
                            print('<div class="alert alert-info">');
                            print("<p><strong>Result:</strong></p>");
                            print($result);
                            print("</div>");
                            // refresh the page to clear Post method.
                            header("Location: admin.php?db=" . $_GET["db"]);
                        }
                        ?>
                    </div>
                </div>
            </div>
        </div>


        <hr>
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


        <hr>
        <div class="card">
            <h5 class="card-header">Bulk Binding with minted identifiers(For Update)</h5>
            <div class="card-body">
                <div id="row-search" class="row">
                    <div class="col-sm-6">
                        <form id="form-import" method="post" enctype="multipart/form-data"
                              action="./admin.php?db=<?php echo $_GET['db'] ?>">
                            <div class="form-group">
                                <p><strong><u>Note:</u></strong> For this section, please follow:</p>
                                <ul>
                                    <li>Mint first</li>
                                    <li>Download the CSV with minted identifiers above and add fields as columns to the
                                        CSV
                                    </li>
                                    <li>Export as a CSV file (only accept CSV) .</li>
                                    <li>Import it below</li>
                                </ul>

                                <p><strong><label for="importCSV">Upload CSV: </label></strong></p>
                                <input type="file"
                                       id="importCSV" name="importCSV"
                                       accept=".csv">
                                <small id="emailHelp" class="form-text text-muted">Only accept CSV</small>

                            </div>
                            <input type="submit" name="import" value="Bulk Bind" class="btn btn-primary"/>
                        </form>
                    </div>
                    <div class="col-sm-6">
                        <?php
                        if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['import'])) {

                            if (is_uploaded_file($_FILES['importCSV']['tmp_name'])) {
                                // generate Ark service procession object
                                $noidUI = new NoidUI();

                                //Read and scan through imported csv
                                if (($handle = fopen($_FILES['importCSV']['tmp_name'], "r")) !== FALSE) {
                                    // read the first row as columns
                                    $columns = fgetcsv($handle, 0, ",");
                                    if (in_array("pid", $columns)) {
                                        $pidi = array_search("pid", $columns);
                                        if ($pidi !== FALSE) {
                                            $columns[$pidi] = "PID";
                                        }
                                    } else {
                                        die ("The imported CSV must have column name 'pid' or 'PID'");
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
                                            if ($columns[$c] === 'Identifer') {
                                                $identifier = $data[$c];
                                            }
                                            if ($c > 0) { // avoid bindset identifier column
                                                // mapping each column as params
                                                $bindset_cmd = " bind set " . $identifier;
                                                $bindset_cmd .= " " . $columns[$c] . " '" . $data[$c] . "'";;
                                                $result = $noidUI->exec_command($bindset_cmd, $noidUI->path($_GET["db"]));

                                                // display result of each bindset
                                                print('<div class="alert alert-info">');
                                                print "<p></p><strong>Result</strong></p>";
                                                print($result);
                                                print('</div>');
                                            }
                                            if ($c == $num - 1) {
                                                $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
                                                $data[$num] = $protocol . $_SERVER['HTTP_HOST'] . "/ark:/" . $identifier;
                                            }
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
        <div class="card">
            <h5 class="card-header">Bulk Binding <u>without</u> minted identifiers (For New)</h5>
            <div class="card-body">
                <div id="row-search" class="row">
                    <div class="col-sm-6">
                        <form id="form-importnoid" method="post" enctype="multipart/form-data"
                              action="./admin.php?db=<?php echo $_GET['db'] ?>">
                            <div class="form-group">
                                <p><strong><u>Note:</u></strong> For this section, please follow:</p>
                                <ul>
                                    <li>Download this initial CSV template by <a href="template.csv" download>this
                                            link.</a></li>
                                    <li>Mandatory: Leave the first column with the header as "Identifier".</li>
                                    <li>Add other needed fields as columns to the CSV.</li>
                                    <li>Export as a CSV file (only accept CSV) .</li>
                                    <li>Import it below</li>
                                </ul>
                                <p><strong><label for="importCSV_noID">Upload CSV: </label></strong></p>
                                <input type="file"
                                       id="importCSV_noID" name="importCSV_noID"
                                       accept=".csv">
                                <small id="emailHelp" class="form-text text-muted">Only accept CSV</small>

                            </div>
                            <input type="submit" name="import_noID" value="Bulk Bind" class="btn btn-primary"/>
                        </form>
                    </div>
                    <div class="col-sm-6">
                        <?php
                        if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['import_noID'])) {

                            if (is_uploaded_file($_FILES['importCSV_noID']['tmp_name'])) {
                                // generate Ark service procession object
                                $noidUI = new NoidUI();

                                //Read and scan through imported csv
                                if (($handle = fopen($_FILES['importCSV_noID']['tmp_name'], "r")) !== FALSE) {
                                    // read the first row as columns
                                    $columns = fgetcsv($handle, 0, ",");
                                    array_push($columns, "Ark Link");

                                    if (in_array("pid", $columns)) {
                                        $pidi = array_search("pid", $columns);
                                        if ($pidi !== FALSE) {
                                            $columns[$pidi] = "PID";
                                        }
                                    } else {
                                        die ("The imported CSV must have column name 'pid' or 'PID'");
                                    }
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
                                            if ($columns[$c] === 'Identifer') {
                                                $identifier = $data[$c];
                                                if (!isset($identifier) || empty($identifier)) {
                                                    // TODO : look up PID to make sure no duplicates
                                                    // if exist, update, put status as 'update'

                                                    // if not exist, insert, put status as 'created'

                                                    // execute command with entered params
                                                    $identifier = $noidUI->exec_command("mint 1", $noidUI->path($_GET["db"]));
                                                    $identifier = trim($identifier);
                                                    $identifier = str_replace("id: ", "", $identifier);
                                                    $data[0] = $identifier;
                                                }
                                            }
                                            if ($c > 0) { // avoid bindset identifier column
                                                // mapping each column as params
                                                $bindset_cmd = " bind set " . $identifier;
                                                $bindset_cmd .= " " . $columns[$c] . " '" . $data[$c] . "'";;
                                                $result = $noidUI->exec_command($bindset_cmd, $noidUI->path($_GET["db"]));

                                                // display result of each bindset
                                                print('<div class="alert alert-info">');
                                                print "<p></p><strong>Result</strong></p>";
                                                print($result);
                                                print('</div>');
                                            }
                                            if ($c == $num - 1) {
                                                $protocol = strtolower(substr($_SERVER["SERVER_PROTOCOL"], 0, strpos($_SERVER["SERVER_PROTOCOL"], '/'))) . '://';
                                                $data[$num] = $protocol . $_SERVER['HTTP_HOST'] . "/ark:/" . $identifier;
                                            }
                                        }
                                        // add columns to import data array
                                        array_push($importedData, $data);
                                    }
                                    //TODO: write each row to new csv

                                    $noidUI->importedToCSV("import_new", $noidUI->path($_GET["db"]), $columns, $importedData, time());
                                    fclose($handle);
                                }
                            }
                            header("Location: admin.php?db=" . $_GET["db"]);
                        }
                        if (file_exists(NoidUI::dbpath())) {
                            // List all minted identifer in csv which created each time execute mint
                            $dirs = scandir(NoidUI::dbpath() . $_GET['db'] . '/import_new');
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
                                                $csv = (isset($_GET['db']) && $_GET['db'] == $dir) ? 'Currently Active' : '<a href="' . 'db/' . $_GET['db'] . '/import_new/' . $dir . '">' . $dir . '</a>';
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
    <?php }
    ?>
</div>
</body>
</html>
