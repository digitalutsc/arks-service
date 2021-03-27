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
use Noid\Lib\Custom\MysqlArkConf;
use Noid\Lib\Custom\NoidArk;

// check if user logging yet
auth();

// start buffer for all input for the forms
ob_start();

// set db type as mysql instead
GlobalsArk::$db_type = 'ark_mysql';

// check if system installed. If not, rediret to installation page.
 init_system();

// get created database
$arkdbs = Database::showDatabases();

// display registered Org info in header.
$orgdata = Database::getOrganization();
$subheader = "<p>";
foreach($orgdata as $pair) {
    if ($pair[0] == "Organization Name") {
        $subheader .= '<h4>'. $pair[1] . '</h4>';
    }
    else if ($pair[0] == "Organization Website") {
        $subheader .= '<a href="'.$pair[1].'" target="_blank">'. $pair[1] . '</a>';
    }
}
$subheader .= "</p>";

?>

    <html>
    <head>
        <title>Ark Services</title>
        <link rel="stylesheet" href="includes/css/bootstrap.min.css">
        <script type="text/javascript" language="javascript" src="includes/js/jquery-3.6.0.min.js"></script>


        <!-- bootsrap -->
        <script src="includes/js/popper.min.js"></script>
        <script src="includes/js/bootstrap.min.js"></script>

        <!-- datatables -->
        <link rel="stylesheet"
              href="https://cdn.datatables.net/1.10.22/css/jquery.dataTables.min.css">
        <link rel="stylesheet"
              href="https://cdn.datatables.net/select/1.3.1/css/select.dataTables.min.css">

        <script type="text/javascript" language="javascript"
                src="includes/js/jquery.dataTables.min.js"></script>
        <script type="text/javascript" language="javascript"
                src="includes/js/dataTables.buttons.min.js"></script>
        <script type="text/javascript" language="javascript"
                src="includes/js/buttons.html5.min.js"></script>
        <script type="text/javascript" language="javascript"
                src="includes/js/dataTables.select.min.js"></script>
        <script type="text/javascript" language="javascript"
                src="includes/js/natural.js"></script>

        <!-- bootstrap select-->
        <link rel="stylesheet"
              href="includes/css/bootstrap-select.min.css">
        <script src="includes/js/bootstrap-select.min.js"></script>
        <script src="includes/js/defaults-en_US.js"></script>

        <style>
            .form-group.required .control-label:after {
                content: "*";
                color: #ff0000;
            }

            .dropdown-menu {
                max-height: 350px !important;
            }

            table.dataTable tr th.select-checkbox.selected::after {
                content: "✔";
                margin-top: -11px;
                margin-left: -4px;
                text-shadow: rgb(176, 190, 217) 1px 1px, rgb(176, 190, 217) -1px -1px, rgb(176, 190, 217) 1px -1px, rgb(176, 190, 217) -1px 1px;
            }

            table.dataTable thead th.select-checkbox:before, table.dataTable tbody th.select-checkbox:before {
              content: "\00a0 \00a0 \00a0\00a0\00a0";
              border: 1px solid black;
              border-radius: 3px;
              font-size: xx-small;
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

                // To style only selects with the select-ark-id class
                // ajax load data to dropdown list
                jQuery.ajax({
                    url: "rest.php?db=<?php echo $_GET['db']; ?>&op=minted"
                }).then(function (data) {
                    $objects = JSON.parse(data);
                    var options = '<option value="-1" selected disabled>-- Select --</option>';
                    for (var i = 0; i < $objects.length; i++) {
                        options += '<option value="' + $objects[i]._key + '">' + $objects[i]._key + '</option>';
                    }
                    $('#enterIdentifier').html(options).selectpicker();
                    $('#enterToClearIdentifier').html(options).selectpicker();
                });


                $('#enterToClearIdentifier').on('change', function (e) {

                    var selected = this.value;
                    $('#enterKeytoClear').empty();

                    jQuery.ajax({
                        url: "rest.php?db=<?php echo $_GET['db']; ?>&ark_id=" + selected + "&op=fields"
                    }).then(function (data) {
                        var objects = JSON.parse(data);
                        //console.log(objects);
                        var options = '';
                        for (var i = 0; i < objects.length; i++) {
                            options += '<option value="' + objects[i] + '">' + objects[i] + '</option>';
                        }
                        //console.log(options);


                        $('#enterKeytoClear').html(options).selectpicker('refresh');
                    });

                });


                let mintedTable = jQuery('#minted_table').DataTable({
                    dom: 'lBfrtip',
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=minted" ?>",
                        "dataSrc": ""
                    },
                    columns: [
                        {data: 'select'},
                        {data: '_key'},
                        {data: '_value'},
                    ],
                    columnDefs: [
                        { type: 'natural', targets: "_all" },
                        {
                            orderable: false,
                            className: 'select-checkbox',
                            targets: 0
                        },
                        {
                          orderable: false,
                          targets: 2
                        }
                    ],
                    "order": [[ 1, "asc" ]],
                    select: {
                        style: 'multi',
                        selector: 'td:first-child'
                    },
                    buttons: [
                        {
                            extend: 'csv',
                            text: 'Export to CSV',
                            exportOptions: {
                                columns: [1]
                            }
                        },
                    ],
                    initComplete: function () {
                      this.api().columns().every(function () {
                        var column = this;
                        if ($(column.header()).text() == 'Minted Date') {

                          var select = $('<select><option value="0">Filter by ' + $(column.header()).text() + '</option></select>')
                            .appendTo($(column.header()).empty())
                            .on('change', function () {
                              var val = $.fn.dataTable.util.escapeRegex(
                                $(this).val()
                              );

                              if (val == 0) {
                                column.search('').draw();
                              } else {
                                column.search(val ? '^' + val + '$' : '', true, false).draw();
                              }

                            });

                          column.data().unique().sort().each(function (d, j) {
                            if (d !== '') {
                              select.append('<option value="' + d + '">' + d + '</option>')
                            }

                          });
                        }

                      });
                    }
                });

                mintedTable.on("click", "th.select-checkbox", function () {
                    if ($("th.select-checkbox").hasClass("selected")) {
                        mintedTable.rows().deselect();
                        $("th.select-checkbox").removeClass("selected");
                    } else {
                        mintedTable.rows().select();
                        $("th.select-checkbox").addClass("selected");
                    }
                }).on("select deselect", function () {
                    ("Some selection or deselection going on")
                    if (mintedTable.rows({
                        selected: true
                    }).count() !== mintedTable.rows().count()) {
                        $("th.select-checkbox").removeClass("selected");
                    } else {
                        $("th.select-checkbox").addClass("selected");
                    }
                });


                // Make a Ajax call to Rest api and render data to table
                let boundTable = jQuery('#bound_table').DataTable({
                    dom: 'lBfrtip',
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=bound" ?>",
                        "dataSrc": ""
                    },
                    "initComplete": function (settings, json) {
                        $(".collapse").collapse({
                            toggle: false
                        });
                        // enable show/hide metadata button after ajax loaded
                        enableShowHideMetadataColumn();

                    },
                    columns: [
                        {data: 'select'},
                        {data: 'id'},
                        {data: 'PID'},
                        //{data: 'LOCAL_ID'},
                        {data: 'ark_url'},
                        {data: 'metadata'},
                    ],
                    "fnDrawCallback": function (oSettings) {
                        //console.log( 'DataTables has redrawn the table' );
                        enableShowHideMetadataColumn();
                    },
                    select: {
                        style: 'multi',
                        selector: 'td:first-child'
                    },
                    buttons: [
                        {
                            extend: 'csv',
                            text: 'Export to CSV',
                            exportOptions: {
                                columns: [1, 2, 3, 4, 5]
                            }
                        },
                    ],
                    "order": [[ 1, "asc" ]],
                    "columnDefs": [
                        { type: 'natural', targets: "_all" },
                        {
                            orderable: false,
                            className: 'select-checkbox',
                            targets: 0
                        },
                        {
                            orderable: false,
                            targets: 4
                        },
                        /*{
                            "targets": 3,
                            "data": "LOCAL_ID",
                            "render": function (data, type, row) {
                                if (data) {
                                    return data;
                                } else {
                                    return " ";
                                }

                            }
                        },*/

                        {
                            "targets": 4,
                            "data": "metadata",
                            "render": function (data, type, row) {
                                if (data !== undefined && data.indexOf("|") != -1) {
                                    var now = row.id;
                                    if (now !== undefined) {
                                        now = now.replace(/[&\/\\#,+()$~%.'":*?<>{}]/g, '');
                                    }
                                    data = data.split("|").join("<br/>");
                                    data = data.split(":").join(": ");
                                    data = ' <button type="button" class="btn btn-link metadata-btn" data-toggle="collapse"  aria-expanded="false" aria-controls="' + now + '" data-target="#' + now + '">' +
                                        '<span>Show</span>' +
                                        '  </button>' +
                                        '<div class="collapse" id="' + now + '">' +
                                        '  <div class="card card-body">' + data + '</div>' +
                                        '</div>';
                                }
                                return data;
                            }
                        },
                        {
                            "targets": 3,
                            "data": "ark_url",
                            "render": function (data, type, row) {
                                var count = data.length;
                                var ark_urls = '<p><a target="_blank" href="' + data[0] + '">' + data[0] + '</a></p>';
                                if (count >1) {
                                   ark_urls += "<p>Derivatives:</p>";
                                   ark_urls += "<ul>";
                                  for (var i = 1; i < count; i ++){
                                    ark_urls += "<li>"+'<a target="_blank" href="' + data[i] + '">' + data[i] + '</a>'+"</li>"
                                  }
                                  ark_urls += "<ul>";
                                }
                                else {
                                  ark_urls = '<a target="_blank" href="' + data[0] + '">' + data[0] + '</a>';
                                }

                                return ark_urls;
                            }
                        }
                    ]
                });

                boundTable.on("click", "th.select-checkbox", function () {
                    if ($("th.select-checkbox").hasClass("selected")) {
                        boundTable.rows().deselect();
                        $("th.select-checkbox").removeClass("selected");
                    } else {
                        boundTable.rows().select();
                        $("th.select-checkbox").addClass("selected");
                    }
                }).on("select deselect", function () {
                    ("Some selection or deselection going on")
                    if (boundTable.rows({
                        selected: true
                    }).count() !== boundTable.rows().count()) {
                        $("th.select-checkbox").removeClass("selected");
                    } else {
                        $("th.select-checkbox").addClass("selected");
                    }
                });


                function enableShowHideMetadataColumn() {
                    // enable show/hide metadata button after ajax loaded
                    $('[data-toggle="collapse"]').click(function (e) {
                        e.preventDefault();
                        var button = $(this);
                        var target_element = button.attr("data-target");
                        //console.log(target_element);
                        //console.log($(target_element));
                        $(target_element).collapse('toggle');
                        $(target_element).on('shown.bs.collapse', function () {
                            $("span", button).text('Hide');
                        })
                        $(target_element).on('hidden.bs.collapse', function () {
                            $("span", button).text('Show');
                        })
                    });
                }

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
                <?php echo $subheader; ?>
                <a style="margin-bottom: 20px" class="btn btn-danger" href="/admin/logout.php">Logout</a>

            </div>
        </div>


        <div class="card">
            <?php
            if (isset($_GET['db'])) {
                print '<h5 class="card-header">Database <i>' . $_GET['db'] . '</i> is selected.</h5>';
            } else {
                print <<<EOS
                    <h5 class="card-header">Create a collection of Arks</h5>
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
                                    <label for="enterDatabaseName">Collection Name:</label>
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
                                    <label class="control-label" for="enterDatabaseName">Name Assigning Authority (NAA):</label>
                                    <input type="text" class="form-control" id="enterRedirect" name="enterRedirect"
                                           />
                                   <small id="emailHelp" class="form-text text-muted">Exclusive For UTSC: collections.digital.utsc.utoronto.ca</small>
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

                            // create db directory if not exsit
                            if (!file_exists(getcwd() . "/db")) {
                                mkdir(getcwd() . "/db", 0775);
                            }

                            // TODO : CHECK entered prefix exist or not
                            $ePrefixflag = false;

                            foreach ($arkdbs as $db) {
                                $pf = json_decode(rest_get("/rest.php?db=$db&op=prefix"));

                                if ($pf === $_POST['enterPrefix']) {
                                    $ePrefixflag = true;
                                    break;
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
                                header("Location: admin.php");
                            } else {
                                print '
                                <div class="alert alert-danger" role="alert">
                                    The entered prefix has been used, please enter another prefix
                                </div>
                            ';
                            }
                        }

                        // List all created databases in the table
                        if (count($arkdbs) > 2) {
                            ?>
                            <div class="row">
                                <table class="table table-bordered">
                                    <thead>
                                    <tr>
                                        <th scope="col">Collections</th>
                                        <th scope="col">Basic Info</th>
                                        <th scope="col">Status</th>

                                    </tr>
                                    </thead>
                                    <tbody>
                                    <?php
                                    foreach ($arkdbs as $db) {
                                        if (!in_array($db, ['system', 'user'])) {
                                            $highlight = "";
                                            $setActive = '<a class="btn btn-success" href="./admin.php?db=' . $db . '">Select</a>';
                                            if ((isset($_GET['db']) && $_GET['db'] == $db)) {
                                                $setActive = "<strong>Selected</srong>";
                                                $highlight = 'class="table-success"';
                                            }
                                            $metadata = json_decode(rest_get("/admin/rest.php?db=" . $db . "&op=dbinfo"));
                                            $detail = "<p>";
                                            foreach ((array)$metadata as $key => $value) {
                                                $detail .= "<strong>$key</strong>: $value <br />";
                                            }
                                            $detail .= "</p>";
                                            print <<<EOS
                                                    <tr $highlight>
                                                        <td scope="row">$db</td>
                                                        <td scope="row">$detail</td>
                                                        <td scope="row">$setActive</td>

                                                    </tr>
                                                EOS;
                                        }

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

                                // backup database before bulk binding
                                Database::backupArkDatabase();

                                $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
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
                                            <th></th>
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
                <h5 class="card-header">Established Ark IDs</h5>
                <div class="card-body">
                    <div class="row">
                        <div class="col-sm-12">
                            <?php
                            // handle bind set
                            if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['bindset']) && $_POST['enterIdentifier'] != -1) {

                                // backup database before bulk binding
                                Database::backupArkDatabase();

                                $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
                                $contact = time();

                                // check if ark ID exist
                                $result = NoidArk::bind($noid, $contact, 1, 'set', $_POST['enterIdentifier'], strtoupper($_POST['enterKey']), $_POST['enterValue']);
                                if (isset($result)) {

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
                            ?>
                        </div>
                    </div>

                    <?php
                    // handle clear bind set
                    if ($_SERVER["REQUEST_METHOD"] == "POST" && !empty($_POST['clear-bindset'])) { ?>
                        <div class="row">
                            <div class="col-sm-12">
                                <?php
                                // todo: if "all field" is checked, delete all fields bound instead
                                $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
                                if (isset($_POST['AllFieldcheckbox']) && $_POST['AllFieldcheckbox'] === "all-fields") {
                                  $where = "_key REGEXP '^" . $_POST['enterToClearIdentifier'] ."\t' and _key NOT REGEXP ':/c$' and _key NOT REGEXP ':/h$' order by _key";
                                  $result = Database::$engine->select($where);

                                  $json = array();
                                  foreach ($result as $row) {
                                    $status = NoidArk::clearBind($noid, $_POST['enterToClearIdentifier'], trim(str_replace($_POST['enterToClearIdentifier'],"", $row['_key'])));
                                  }
                                }
                                else {
                                  $status = NoidArk::clearBind($noid, $_POST['enterToClearIdentifier'], $_POST['enterKeytoClear']);
                                }

                                if ($status !== false) {
                                    print '
                                                                <div class="alert alert-success" role="alert">
                                                                    Ark ID <i>' . $_POST['enterToClearIdentifier'] . '</i> - ' . $_POST['enterKeytoClear'] . ' has been cleared
                                                                </div>
                                                            ';
                                } else {
                                    print '
                                                                <div class="alert alert-success" role="alert">
                                                                    Ark ID <i>' . $_POST['enterToClearIdentifier'] . '</i> - ' . $_POST['enterKeytoClear'] . ' failed to be cleared
                                                                </div>
                                                            ';
                                }

                                Database::dbclose($noid);

                                // redirect to the page.
                                header("Location: admin.php?db=" . $_GET["db"]);
                                ?>
                            </div>
                        </div>
                    <?php } ?>

                    <div id="row-bindset" class="row">
                        <div class="col-sm-12">
                            <button type="button" class="btn btn-primary" data-toggle="modal"
                                    data-target="#bindsetModal">
                                Binding
                            </button>
                            <div class="modal fade" id="bindsetModal" tabindex="-1" aria-labelledby="bindsetModalLabel"
                                 aria-hidden="true">
                                <div class="modal-dialog">
                                    <div class="modal-content">
                                        <div class="modal-header">
                                            <h5 class="modal-title" id="bindsetModalLabel">Binding an Ark ID</h5>
                                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                                <span aria-hidden="true">&times;</span>
                                            </button>
                                        </div>
                                        <div class="modal-body">
                                            <div class="col-sm-12">
                                                <form id="form-bindset" method="post"
                                                      action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                                    <div class="form-group">
                                                        <label for="enterIdentifier">Ark ID:</label>
                                                        <select id="enterIdentifier" name="enterIdentifier"
                                                                class="form-control" data-live-search="true">
                                                        </select>
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


                            <!-- Remove Metadata set -->
                            <button type="button" class="btn btn-secondary" data-toggle="modal"
                                    data-target="#clearbindsetModal">
                                Unbinding
                            </button>
                            <div class="modal fade" id="clearbindsetModal" tabindex="-1"
                                 aria-labelledby="clearbindsetModalLabel"
                                 aria-hidden="true">
                                <div class="modal-dialog">
                                    <div class="modal-content">
                                        <div class="modal-header">
                                            <h5 class="modal-title" id="clearbindsetModalLabel">Unbinding an Ark ID</h5>
                                            <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                                <span aria-hidden="true">&times;</span>
                                            </button>
                                        </div>
                                        <div class="modal-body">
                                            <div class="row">
                                                <div class="col-sm-12">
                                                    <form id="form-clear-bindset" method="post"
                                                          action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                                        <div class="form-group">
                                                            <label for="enterToClearIdentifier">Ark ID:</label>
                                                            <select id="enterToClearIdentifier"
                                                                    name="enterToClearIdentifier" class="form-control"
                                                                    data-live-search="true">
                                                                <option value="-1" selected disabled>-- Select --
                                                                </option>
                                                            </select>
                                                        </div>

                                                        <div class="form-group" id="group-unbind-fields">
                                                            <label for="enterKeytoClear">Field:</label>
                                                            <select id="enterKeytoClear"
                                                                    name="enterKeytoClear" class="form-control">
                                                                <option value="-1" selected disabled>-- Select --
                                                                </option>
                                                            </select>
                                                        </div>

                                                        <div class="form-check" style="padding-bottom: 25px;">
                                                          <input class="form-check-input" type="checkbox" value="all-fields" id="AllFieldcheckbox" name="AllFieldcheckbox">
                                                          <label class="form-check-label" for="AllFieldcheckbox">
                                                            All fields
                                                          </label>
                                                        </div>

                                                        <div class="modal-footer">
                                                          <input type="submit" name="clear-bindset" value="Unbind"
                                                                 class="btn btn-primary"/>

                                                          <button type="button" class="btn btn-secondary"
                                                                  data-dismiss="modal">
                                                              Close
                                                          </button>
                                                        </div>
                                                    </form>
                                                </div>
                                            </div>

                                        </div>

                                    </div>
                                </div>
                            </div>
                            <!-- Bulk Bind Modal -->
                            <button id="btn-bulk-bind" type="button" class="btn btn-success" data-toggle="modal"
                                    data-target="#bulkBindModal">
                                Bulk Bind
                            </button>
                            <div class="modal fade" id="bulkBindModal" tabindex="-1"
                                 aria-labelledby="bulkBindModalLabel"
                                 aria-hidden="true" data-backdrop="static" data-keyboard="false">
                                <div id="bulk-binding-modal" class="modal-dialog modal-lg">
                                    <div class="modal-content">
                                        <div class="modal-header">
                                            <h5 class="modal-title" id="bulkBindModalLabel">Bulk Binding</h5>
                                            <button id="bulk-binding-dismiss-button" type="button" class="close"
                                                    data-dismiss="modal" aria-label="Close">
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
                                                            <ol>
                                                              <li>Mint Ark ID(s)</li>
                                                              <li>Download <a href="template.csv" download>template.csv</a>, place the above minted Ark IDs into the ARK_ID column.</li>
                                                              <li><strong>There no limitation of data field(s) to be bound with an Ark ID. For UTSC only, highly recommend to have the below essential columns which are already included in the template CSVs above</strong> and add more column(s) if needed for other metadata.
                                                                <ul>
                                                                  <li><u><strong>Ark_ID</strong></u>: MANDATORY field for binding.</li>
                                                                  <li><u><strong>URL</strong></u>: MANDATORY field, the Resolver looks for this field to redirection.</li>
                                                                  <li><u>LOCAL_ID</u>: Object's unique ID in the repository.</li>
                                                                  <li><u>PID</u>: persistent Identifiers</li>
                                                                  <li><u>COLLECTION</u>(Optional): to assist on searching in the table.</li>
                                                                </ul>
                                                              </li>
                                                              <li><strong>Upload the CSV to start the process.</strong></li>
                                                            </ol>
                                                        </div>
                                                        <hr/>
                                                        <div class="container">
                                                            <div class="form-group">
                                                                <label for="enterPasswordPostBulkBind"><strong>For security measure, please enter admin password before bulk binding: </strong></label>
                                                                <input required type="password" class="form-control" id="enterPasswordPostBulkBind" name="enterPasswordPostBulkBind"
                                                                       placeholder="Password">
                                                            </div>
                                                            <div class="form-group">
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
                                                        </div>
                                                        <div class="row">
                                                            <div class="col-sm-12">
                                                                <span id="message"></span>
                                                                <div class="form-group" id="process"
                                                                     style="display:none;">
                                                                    <div class="progress">
                                                                        <div class="progress-bar progress-bar-striped progress-bar-animated"
                                                                             role="progressbar" aria-valuemin="0"
                                                                             aria-valuemax="100">
                                                                        </div>
                                                                    </div>
                                                                    Binding <span id="process_data">0</span> of <span
                                                                            id="total_data">0</span> objects.
                                                                </div>

                                                            </div>
                                                        </div>

                                                        <div class="row">
                                                            <div class="col-sm-12">
                                                                <input type="submit" id="btn-upload" name="import" value="Upload"
                                                                       class="btn btn-primary"/>
                                                                <input type="submit" name="btn-process" id="btn-process" value="Start Binding"
                                                                       class="btn btn-primary"/>
                                                                <button type="button" id="btn-close-bulkbind"
                                                                        class="btn btn-secondary"
                                                                        data-dismiss="modal">Close
                                                                </button>
                                                            </div>
                                                        </div>

                                                    </form>
                                                </div>
                                            </div>
                                        </div>
                                        <script>
                                            // at beginning, hide and disable process button
                                            $('#btn-process').hide();
                                            $('#btn-process').prop('disabled', true);

                                            $("#AllFieldcheckbox").click(function(){
                                              if($(this).prop("checked") == true){
                                                $("#group-unbind-fields").hide();
                                              }
                                              else if($(this).prop("checked") == false){
                                                $("#group-unbind-fields").show();
                                              }
                                            });

                                            // handle form submission
                                            $('#form-import').on('submit', function (event) {
                                                event.preventDefault();

                                                // check password not empty before bulk binding
                                                if($.trim($('#enterPasswordPostBulkBind').val()) == ''){
                                                    $('#message').html('<div class="alert alert-danger">Please enter the administrator password before bulk binding</div>');
                                                    return false;
                                                }

                                                // reset message
                                                $('#message').html('');

                                                // disable close button in bulk bind popup to keep it in focus
                                                $('#btn-close-bulkbind').prop('disabled', true);
                                                $('#bulk-binding-dismiss-button').prop('disabled', true);

                                                // read and process CSV file
                                                var csv = $('#importCSV');
                                                var csvFile = csv[0].files[0];
                                                var ext = csv.val().split(".").pop().toLowerCase();

                                                // verify if uploaded file is CSV file.
                                                if ($.inArray(ext, ["csv"]) === -1) {
                                                    $('#message').html('<div class="alert alert-danger">Only accept CSV file</div>');
                                                    return false;
                                                }

                                                // If uploaded file is CSV, read the file.
                                                if (csvFile != undefined) {

                                                    // init file reader
                                                    reader = new FileReader();

                                                    // Important: reading the CSV file.
                                                    reader.readAsText(csvFile);

                                                    // handle when reading file completed.
                                                    reader.onload = function (e) {
                                                        // split all lines
                                                        var csvResult = e.target.result.split(/\n/);

                                                        // store all read data from CSV in Local storage.
                                                        localStorage.setItem("importCSV", JSON.stringify(csvResult));

                                                        //hide upload button
                                                        $('#btn-upload').hide();

                                                        // display upload complete message
                                                        $('#message').html('<div class="alert alert-info">' +
                                                            'Your CSV file has been uploaded successfully. Please click <i>Start Binding</i> button to start the process.'
                                                            + '</div>');

                                                        // show and enable process button
                                                        $('#btn-process').show();
                                                        $('#btn-process').prop('disabled', false);

                                                        // handle process button clicked
                                                        $('#btn-process').click(function() {

                                                            // store password to caches
                                                            localStorage.setItem("syspasswd", JSON.stringify($("#enterPasswordPostBulkBind").val()));

                                                            // display the message of ongoing binding process.
                                                            $('#message').html('<div class="alert alert-warning">' +
                                                                'The Binding process has been ongoing. Please do not close this page until the process is completed.'
                                                                + '</div>');

                                                            // get total number of lines in CSV
                                                            var total_data = csvResult.length;

                                                            // if the CSV file has data, adjust UI
                                                            if (total_data > 1) {
                                                                //show progress bar
                                                                $('#process').css('display', 'block');

                                                                // disable process button.
                                                                $('#btn-process').prop('disabled', true);
                                                            }

                                                            // get headers
                                                            var keys = csvResult[0].split(',').map(function (x) {
                                                                return x.toUpperCase().trim().replace(/ /g, "_");
                                                            });
                                                            // check if the CSV must have 3 mandatory columns
                                                            if ($.inArray("ARK_ID", keys) === -1) {
                                                                // show message.
                                                                $('#message').html('<div class="alert alert-danger">' +
                                                                    ' <p>Make sure your CSV has the mandatory columns: Ark_ID </p>'
                                                                    + '</div>');

                                                                // disable message shown
                                                                $('#process').css('display', 'none');
                                                                $('#btn-close-bulkbind').prop('disabled', false);
                                                                $('#bulk-binding-dismiss-button').prop('disabled', false);

                                                                return false;
                                                            } else {
                                                                // loop through row 2 till end of CSV file
                                                                var index = 1; // start from 2nd line because 1st one is header/columns

                                                                // TODO: send post request to backup database, if success, proceed with the post request below:
                                                                var password = JSON.parse(localStorage.getItem("syspasswd"));
                                                                // send POST request for each line of read CSV file
                                                                $.post("rest.php?db=<?php echo $_GET['db']; ?>&op=backupdb", {security: password})
                                                                    .done(function (data) {
                                                                        // send Post request
                                                                        doPost(index, total_data, csvResult);
                                                                    })
                                                                    .fail(function () {
                                                                        $('#message').html('<div class="alert alert-danger">Fail to run backup the database before bulk binding.</div>');
                                                                        $('#importCSV').attr('disabled', false);
                                                                        $('#importCSV').val('Import');
                                                                    });



                                                            }
                                                        });
                                                    }
                                                }
                                            });

                                            function doPost(index, total_data, csvResult) {
                                                // pulll preserve read data from CSV from local storage
                                                var csvResult = JSON.parse(localStorage.getItem("importCSV"));
                                                var password = JSON.parse(localStorage.getItem("syspasswd"));
                                                if (Array.isArray(csvResult)) {
                                                  var keys = csvResult[0].split(',').map(function (x) {
                                                    return x.toUpperCase();
                                                  });
                                                }
                                                else {
                                                  return;
                                                }


                                                // start binding each line of CSV file
                                                var item = csvResult[index];
                                                var values = item.split(',');

                                                var pdata = {};
                                                for (var i = 0; i < values.length; i++) {
                                                    // enforce csv must follow sequence LocalID, PID, URL,
                                                    if (keys[i] !== undefined) {
                                                        pdata[keys[i].toUpperCase().replace(/(\r\n|\n|\r)/gm,"")] = values[i].trim().replace(/ /g, "_");
                                                    }
                                                }

                                                // send POST request for each line of read CSV file
                                                $.post("rest.php?db=<?php echo $_GET['db']; ?>&op=bulkbind&stage=upload", {data: pdata, security: password})
                                                    .done(function (data) {
                                                      console.log(data);

                                                      var result =  JSON.parse(data);
                                                        if (result.success == 401) {

                                                            // display unauthrize message
                                                            $('#message').html('<div class="alert alert-danger">'+result.message+'</div>');

                                                            // re-enable operation button
                                                            $('#process').css('display', 'none');
                                                            $('#btn-process').prop('disabled', false);
                                                            $('#bulk-binding-dismiss-button').prop('disabled', false);
                                                            return;
                                                        }
                                                        else {
                                                            // process result of each process
                                                            processPostSuccess(index, csvResult, data);

                                                            // recursive call post request till end of file
                                                            index++;
                                                            if (index < csvResult.length)
                                                                doPost(index, keys, csvResult);
                                                        }


                                                    })
                                                    .fail(function () {
                                                        $('#message').html('<div class="alert alert-danger">Fail to read the CSV file.</div>');
                                                        $('#importCSV').attr('disabled', false);
                                                        $('#importCSV').val('Import');
                                                    });
                                            }

                                            function processPostSuccess(index, csvResult, data) {
                                                // get total objects to bind
                                                var total_data = csvResult.length;
                                                // get result form POST request from REST api
                                                var result = JSON.parse(data);

                                                // if success
                                                if (result.success === 1) {

                                                    // display total lines have to import
                                                    $('#total_data').text(total_data);

                                                    // calculate percentage of ongoing process.
                                                    var width = ((index + 1) / total_data) * 100;

                                                    // update the progress bar.
                                                    $('#process_data').text(index);
                                                    $('.progress-bar').css('width', width + '%');

                                                    // if the process reaches 100%
                                                    if (width >= 100) {

                                                        // dismiss the progress bar
                                                        $('#process').css('display', 'none');

                                                        // reset the input type file
                                                        $('#importCSV').val('');

                                                        // display completed message
                                                        $('#message').html('<div class="alert alert-success">Bulk Bind successfully completed.</div>');

                                                        // re-enable all buttons
                                                        $('#import').attr('disabled', false);
                                                        $('#import').val('Import');
                                                        $('#btn-close-bulkbind').prop('disabled', false);
                                                        $('#bulk-binding-dismiss-button').prop('disabled', false);
                                                        $('#btn-process').hide();

                                                        // clear read data from CSV from localstorage
                                                        localStorage.removeItem("importCSV");
                                                        localStorage.removeItem("syspasswd");

                                                        // if click on close button, page will be refresh to update the tables.
                                                        $('#btn-close-bulkbind').click(function () {
                                                            location.reload();
                                                        });
                                                    }
                                                } else if (result.success == 0) {
                                                    // if fail to read a row, display.
                                                    $('#message').html('<div class="alert alert-danger">' + result.message + '</div>');
                                                    $('#importCSV').attr('disabled', false);
                                                    $('#importCSV').val('Import');
                                                }
                                            }
                                        </script>

                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="row" style="margin-top:20px;">
                        <div class="col-sm-12">

                            <div class="row">
                                <div class="col-md-12">
                                    <table id="bound_table" class="display" style="width:100%">
                                        <thead>
                                        <tr>
                                            <th></th>
                                            <th>Ark ID</th>
                                            <th>PID</th>
<!--                                            <th>LOCAL_ID</th>-->
                                            <th>Ark URL</th>
                                            <th>Metadata</th>
                                        </tr>
                                        </thead>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        <?php }
        ?>
    </div>
    </body>
    </html>

<?php
ob_flush();
