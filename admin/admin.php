<?php
    if (!file_exists('../config/MysqlArkConf.php')) {
        header("Location: ./index.php");
        exit;
    } 
    require_once "functions.php";
    require_once "../services.php";
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
        <title>Arks Service</title>
        <link rel="stylesheet" href="includes/css/bootstrap.min.css">
        <script type="text/javascript" language="javascript" src="includes/js/jquery-3.6.0.min.js"></script>


        <!-- bootsrap -->
        <script src="includes/js/popper.min.js"></script>
        <script src="includes/js/bootstrap.min.js"></script>

        <!-- datatables -->
        <link rel="stylesheet"
              href="//cdn.datatables.net/1.13.7/css/jquery.dataTables.min.css">
        <link rel="stylesheet"
              href="https://cdn.datatables.net/select/1.3.1/css/select.dataTables.min.css">

        <script type="text/javascript" language="javascript"
                src="///cdn.datatables.net/1.13.7/js/jquery.dataTables.min.js"></script>
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

        <!-- Font Awesome -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css" integrity="sha256-eZrrJcwDc/3uDhsdt61sL2oOBY362qM3lon1gyExkL0=" crossorigin="anonymous" />
        
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

            .dropdown a.cus {
              padding-left: 0;
              color: #007bff;
            }
            a.cus1 {
              color: #007bff;
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
            if (isset($_GET['db']) && !isset($_GET['op'])) {
            ?>

            //
            // Pipelining function for DataTables. To be used to the `ajax` option of DataTables
            //
            $.fn.dataTable.pipeline = function ( opts ) {
            // Configuration options
            var conf = $.extend( {
                pages: 5,     // number of pages to cache
                url: '',      // script url
                data: null,   // function or object with parameters to send to the server
                            // matching how `ajax.data` works in DataTables
                method: 'GET' // Ajax HTTP method
            }, opts );

            // Private variables for storing the cache
            var cacheLower = -1;
            var cacheUpper = null;
            var cacheLastRequest = null;
            var cacheLastJson = null;

            return function ( request, drawCallback, settings ) {
                var ajax          = false;
                var requestStart  = request.start;
                var drawStart     = request.start;
                var requestLength = request.length;
                var requestEnd    = requestStart + requestLength;
                
                if ( settings.clearCache ) {
                    // API requested that the cache be cleared
                    ajax = true;
                    settings.clearCache = false;
                }
                else if ( cacheLower < 0 || requestStart < cacheLower || requestEnd > cacheUpper ) {
                    // outside cached data - need to make a request
                    ajax = true;
                }
                else if ( JSON.stringify( request.order )   !== JSON.stringify( cacheLastRequest.order ) ||
                        JSON.stringify( request.columns ) !== JSON.stringify( cacheLastRequest.columns ) ||
                        JSON.stringify( request.search )  !== JSON.stringify( cacheLastRequest.search )
                ) {
                    // properties changed (ordering, columns, searching)
                    ajax = true;
                }
                
                // Store the request for checking next time around
                cacheLastRequest = $.extend( true, {}, request );

                if ( ajax ) {
                    // Need data from the server
                    if ( requestStart < cacheLower ) {
                        requestStart = requestStart - (requestLength*(conf.pages-1));

                        if ( requestStart < 0 ) {
                            requestStart = 0;
                        }
                    }
                    
                    cacheLower = requestStart;
                    cacheUpper = requestStart + (requestLength * conf.pages);

                    request.start = requestStart;
                    request.length = requestLength*conf.pages;

                    // Provide the same `data` options as DataTables.
                    if ( typeof conf.data === 'function' ) {
                        // As a function it is executed with the data object as an arg
                        // for manipulation. If an object is returned, it is used as the
                        // data object to submit
                        var d = conf.data( request );
                        if ( d ) {
                            $.extend( request, d );
                        }
                    }
                    else if ( $.isPlainObject( conf.data ) ) {
                        // As an object, the data given extends the default
                        $.extend( request, conf.data );
                    }

                    return $.ajax( {
                        "type":     conf.method,
                        "url":      conf.url,
                        "data":     request,
                        "dataType": "json",
                        "cache":    false,
                        "success":  function ( json ) {
                            cacheLastJson = $.extend(true, {}, json);

                            if ( cacheLower != drawStart ) {
                                json.data.splice( 0, drawStart-cacheLower );
                            }
                            if ( requestLength >= -1 ) {
                                json.data.splice( requestLength, json.data.length );
                            }
                            
                            drawCallback( json );
                        }
                    } );
                }
                else {
                    json = $.extend( true, {}, cacheLastJson );
                    json.draw = request.draw; // Update the echo for each response
                    json.data.splice( 0, requestStart-cacheLower );
                    json.data.splice( requestLength, json.data.length );

                    drawCallback(json);
                }
            }
        };

        // Register an API method that will empty the pipelined data, forcing an Ajax
        // fetch on the next draw (i.e. `table.clearPipeline().draw()`)
        $.fn.dataTable.Api.register( 'clearPipeline()', function () {
            return this.iterator( 'table', function ( settings ) {
                settings.clearCache = true;
            } );
        } );


            $(document).ready(function () {

                $('#enterToClearIdentifier').focusout(function (e) {
                    var selected = this.value.trim();
                    $('#enterKeytoClear').empty();
                    jQuery.ajax({
                        url: "rest.php?db=<?php echo $_GET['db']; ?>&ark_id=" + selected + "&op=fields"
                    }).then(function (data) {
                        var objects = JSON.parse(data);
                        var options = '';
                        for (var i = 0; i < objects.length; i++) {
                            options += '<option value="' + objects[i] + '">' + objects[i] + '</option>';
                        }
                        $('#enterKeytoClear').html(options).selectpicker('refresh');
                    });

                });

                let mintedTable = jQuery('#minted_table').DataTable({
                    dom: 'lBfrtip',
                    /*"ajax": $.fn.dataTable.pipeline( {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=minted" ?>",
                        "pages": 5 // number of pages to cache
                    }),*/
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=minted" ?>",
                        error: function (xhr, error, code) {
                            mintedTable.ajax.reload();
                        }
                    },
                    processing: true,
                    "search": {
                        return: true
                    },
                	serverSide: true,
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
                    lengthMenu: [10, 50, 100, 200, 500, 1000, 2000],
                    "order": [[ 1, "asc" ]],
                    select: {
                        style: 'multi',
                        selector: 'td:first-child'
                    },
                    buttons: [
                        {
                            extend: 'csv',
                            text: 'Export',
                            exportOptions: {
                                columns: [1, 2]
                            },
                        },
                        {
                            extend: 'csv',
                            text: 'Export All',
                            exportOptions: {
                                columns: [1, 2]
                            },
                            "action": exportAllAction
                        },
                    ],
                    initComplete: function () {
                      this.api().columns().every(function () {
                        var column = this;
                      });
                    }
                });

                /**
                 * Export all rows (server prcessing) 
                 * https://stackoverflow.com/questions/41350206/export-all-from-datatables-with-server-side-processing
                 */
                function exportAllAction(e, dt, button, config) {
                    var self = this;
                    var oldStart = dt.settings()[0]._iDisplayStart;
                    
                    dt.one('preXhr', function (e, s, data) {
                        // Just this once, load all data from the server...
                        data.start = 0;
                        data.length = 2147483647;
                        dt.one('preDraw', function (e, settings) {
                            // Call the original action function
                            if (button[0].className.indexOf('buttons-copy') >= 0) {
                                $.fn.dataTable.ext.buttons.copyHtml5.action.call(self, e, dt, button, config);
                            } else if (button[0].className.indexOf('buttons-excel') >= 0) {
                                $.fn.dataTable.ext.buttons.excelHtml5.available(dt, config) ?
                                    $.fn.dataTable.ext.buttons.excelHtml5.action.call(self, e, dt, button, config) :
                                    $.fn.dataTable.ext.buttons.excelFlash.action.call(self, e, dt, button, config);
                            } else if (button[0].className.indexOf('buttons-csv') >= 0) {
                                $.fn.dataTable.ext.buttons.csvHtml5.available(dt, config) ?
                                    $.fn.dataTable.ext.buttons.csvHtml5.action.call(self, e, dt, button, config) :
                                    $.fn.dataTable.ext.buttons.csvFlash.action.call(self, e, dt, button, config);
                            } else if (button[0].className.indexOf('buttons-pdf') >= 0) {
                                $.fn.dataTable.ext.buttons.pdfHtml5.available(dt, config) ?
                                    $.fn.dataTable.ext.buttons.pdfHtml5.action.call(self, e, dt, button, config) :
                                    $.fn.dataTable.ext.buttons.pdfFlash.action.call(self, e, dt, button, config);
                            } else if (button[0].className.indexOf('buttons-print') >= 0) {
                                $.fn.dataTable.ext.buttons.print.action(e, dt, button, config);
                            }
                            dt.one('preXhr', function (e, s, data) {
                                // DataTables thinks the first item displayed is index 0, but we're not drawing that.
                                // Set the property to what it was before exporting.
                                settings._iDisplayStart = oldStart;
                                data.start = oldStart;
                            });
                            // Reload the grid with the original page. Otherwise, API functions like table.cell(this) don't work properly.
                            setTimeout(dt.ajax.reload, 0);
                            // Prevent rendering of the full data to the DOM
                            return false;
                        });
                    });
                    // Requery the server with the new one-time export settings
                    dt.ajax.reload();
                }
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
                    /*"ajax": $.fn.dataTable.pipeline( {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=bound" ?>",
                        "pages": 1, // number of pages to cache
                    }),*/
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=bound" ?>",
                        error: function (xhr, error, code) {
                            boundTable.ajax.reload();
                        }
                    },
                    processing: true,
                    search: {
                        return: true
                    },
                    aLengthMenu: [
                        [10, 25, 50, 100, 200, 1000, 2000],
                        [10, 25, 50, 100, 200, 1000, 2000]
                    ],
                    iDisplayLength: 10,
                	serverSide: true,
                    "initComplete": function (settings, json) {
                        $(".collapse").collapse({
                            toggle: false
                        });
                        // enable show/hide metadata button after ajax loaded
                        //enableShowHideMetadataColumn();
                    },
                    columns: [
                        {data: 'select'},
                        {data: 'id'},
                        /*{data: 'redirect'},*/
                        {data: 'ark_url'},
                        {data: 'metadata'},
                        /*{data: 'policy'},*/
                    ],
                    "fnDrawCallback": function (oSettings) {
                        //enableShowHideMetadataColumn();
                    },
                    select: {
                        style: 'multi',
                        selector: 'td:first-child'
                    },
                    buttons: [
                        {
                            extend: 'csv',
                            text: 'Export',
                            exportOptions: {
                                columns: [1, 2, 3]
                            },
                        },
                        {
                            extend: 'csv',
                            text: 'Export all',
                            exportOptions: {
                                columns: [1, 2, 3]
                            },
                            "action": exportAllAction
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
                        /*{
                            orderable: false,
                            targets: 4
                        },
                        {
                            "targets": 2,
                            "data": "redirect",
                            "render": function (data, type, row) {
                                if (data) {
                                    return data;
                                } else {
                                    return "0";
                                }

                            }
                        },*/
                        {
                            "targets": 3,
                            "data": "metadata",
                            orderable: false,
                            "render": function (data, type, row) {
                                data = '<a target="_blank" href="' + data + '">' + data + '</a>';
                                return data;
                            }
                        },
                        /*{
                            "targets": 4,
                            "data": "policy",
                            orderable: false,
                            "render": function (data, type, row) {
                                data = '<a target="_blank" href="' + data + '">' + data + '</a>';
                                return data;
                            }
                        },*/
                        {
                            "targets": 2,
                            "data": "ark_url",
                            orderable: false,
                            "render": function (data, type, row) {
                                if (data === undefined)
                                    return;
                                data.sort();
                                var count = data.length;
                                var ark_urls = '';
                                if (count >1) {
                                   <?php $dropdown = "derevatives-". time(); ?>
                                   ark_urls += '<div class="dropdown">' +
                                               '<a target="_blank" class="btn btn-default cus" href="'+ data[0] +'">'+ data[0] +'</a>'
                                  ark_urls += '<button type="button" class="btn btn-default dropdown-toggle dropdown-toggle-split" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"> <span class="sr-only">Arks </span> </button>';
                                  ark_urls += '<div class="dropdown-menu" aria-labelledby="<?php echo $dropdown; ?>">';
                                  ark_urls += '<h6 class="dropdown-header">With Qualifiers:</h6>';
                                  for (var i = 1; i < count; i ++){

                                    ark_urls += '<a class="dropdown-item cus1" target="_blank" href="' + data[i] + '">' + data[i] + '</a>';
                                  }
                                  ark_urls += "</div></div>";
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


                // Make a Ajax call to Rest api and render data to table
                let unboundTable = jQuery('#unbound_table').DataTable({
                    dom: 'lBfrtip',
                    "search": {
                        "return": true
                    },
                    /*"ajax": $.fn.dataTable.pipeline( {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=unbound" ?>",
                        "pages": 5 // number of pages to cache
                    }),*/
                    "ajax": {
                        "url": "rest.php?db=<?php echo $_GET['db'] . "&op=unbound" ?>",
                        error: function (xhr, error, code) {
                            unboundTable.ajax.reload();
                        }
                    },

                    processing: true,
                	serverSide: true,
                    aLengthMenu: [
                        [10, 25, 50, 100, 200, 1000, 2000],
                        [10, 25, 50, 100, 200, 1000, 2000]
                    ],
                    iDisplayLength: 10,
                    "initComplete": function (settings, json) {
                        $(".collapse").collapse({
                            toggle: false
                        });
                        // enable show/hide metadata button after ajax loaded
                        //enableShowHideMetadataColumn();
                    },
                    columns: [
                        {data: 'select'},
                        {data: 'id'},
                        {data: 'ark_url'},
                    ],
                    "fnDrawCallback": function (oSettings) {
                        //enableShowHideMetadataColumn();
                    },
                    select: {
                        style: 'multi',
                        selector: 'td:first-child'
                    },
                    buttons: [
                        {
                            extend: 'csv',
                            text: 'Export',
                            exportOptions: {
                                columns: [1, 2]
                            }
                        },
                        {
                            extend: 'csv',
                            text: 'Export all',
                            exportOptions: {
                                columns: [1, 2]
                            },
                            "action": exportAllAction
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
                            "targets": 2,
                            orderable: false,
                            "data": "ark_url",
                            "render": function (data, type, row) {
                                if (data === undefined)
                                    return;
                                data.sort();
                                var count = data.length;
                                var ark_urls = '';
                                if (count >1) {
                                   <?php $dropdown = "derevatives-". time(); ?>
                                   ark_urls += '<div class="dropdown">' +
                                               '<a target="_blank" class="btn btn-default cus" href="'+ data[0] +'">'+ data[0] +'</a>'
                                  ark_urls += '<button type="button" class="btn btn-default dropdown-toggle dropdown-toggle-split" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"> <span class="sr-only">Arks </span> </button>';
                                  ark_urls += '<div class="dropdown-menu" aria-labelledby="<?php echo $dropdown; ?>">';
                                  ark_urls += '<h6 class="dropdown-header">With Qualifiers:</h6>';
                                  for (var i = 1; i < count; i ++){

                                    ark_urls += '<a class="dropdown-item cus1" target="_blank" href="' + data[i] + '">' + data[i] + '</a>';
                                  }
                                  ark_urls += "</div></div>";
                                }
                                else {
                                  ark_urls = '<a target="_blank" href="' + data[0] + '">' + data[0] + '</a>';
                                }

                                return ark_urls;
                            }
                        }
                    ]
                });

                unboundTable.on("click", "th.select-checkbox", function () {
                    if ($("th.select-checkbox").hasClass("selected")) {
                        boununboundTabledTable.rows().deselect();
                        $("th.select-checkbox").removeClass("selected");
                    } else {
                        unboundTable.rows().select();
                        $("th.select-checkbox").addClass("selected");
                    }
                }).on("select deselect", function () {
                    ("Some selection or deselection going on")
                    if (unboundTable.rows({
                        selected: true
                    }).count() !== unboundTable.rows().count()) {
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
        <?php embedServices(); ?>
        <div class="container">
            <div class="row">
                <div class="col-sm text-center">
                    <h1>Arks Service</h1>
                    <a style="margin-bottom: 20px" class="btn btn-danger" href="/admin/logout.php">Logout</a>
                </div>
            </div> <!-- end of row -->
            <div id="arksdb" class="card">
                <?php
                if (isset($_GET['db']) && !isset($_GET['op'])) {
                    print '<h5 class="card-header">Database <i>' . $_GET['db'] . '</i> is selected.</h5>';
                } else {

                    if (isset($_GET['op']) && $_GET['op'] == "edit") { 
                        print <<<EOS
                            <h5 class="card-header">Update your existing collection</h5>
                        EOS;
                    }
                    else {
                        print <<<EOS
                            <h5 class="card-header">Create a new Ark collection, or select your existing collection</h5>
                        EOS;    
                    }
                }
                ?>

                <div id="arksdb-creation" class="card-body">
                    <div id="row-dbcreate" class="row">
                        <div id="arksdb-create-form" class="col-sm-6">
                            <?php
                            $back_btn = '<a class="btn btn-secondary" href="./admin.php">Back</a>';
                            if (!isset($_GET['db']) || (isset($_GET['db']) && isset($_GET['op']) && $_GET['op'] === "edit")) {
                                
                                // submit button to create db
                                $submit_btn = '<input type="submit" name="dbcreate" value="Create" class="btn btn-primary"/>';
                                $edit_dbname= "";
                                $edit_dbtemplate = "";
                                $edit_dbprefix = "";
                                $edit_dbtemplate_display = "";
                                $edit_dbnaan = "";
                                $edit_dbnaa = "";

                                if (isset($_GET['op']) && $_GET['op'] === "edit") { 
                                    // for Edit database mode
                                    $metadata = json_decode(rest_get("/admin/rest.php?db=" . $_GET['db'] . "&op=dbinfo"));
                                    $edit_dbname = "value='". $_GET['db'] . "' disabled";
                                
                                    if (isset($metadata->template)) {
                                        $edit_dbtemplate = '
                                            <script type="text/javascript">
                                                var dropdown = document.getElementById("selectTemplate");
                                                dropdown.value = "'. $metadata->template .'"; 
                                                document.getElementById("selectTemplate").disabled = true;
                                            </script>
                                        ';
                                    }
                                    if (isset($metadata->prefix)) { 
                                        $edit_dbprefix = "value='". $metadata->prefix . "' disabled";
                                    }
                                    if (!empty($metadata)) { 
                                        $edit_dbtemplate_display = "d-none";
                                        $edit_dbtemplate_disabled = "disabled";
                                    }
                                    if (isset($metadata->naan)) { 
                                        $edit_dbnaan = "value='". $metadata->naan . "' disabled";
                                    }
                                    if (isset($metadata->naa)) { 
                                        $edit_dbnaa = $metadata->naa;
                                    }

                                    if ((isset($_GET['db']) && $_GET['op'] === "edit")) { 
                                        $submit_btn  = '<input type="hidden" name="editDBname" id ="editDBname" value="'.$_GET['db'].'"/>';
                                        $submit_btn .= '<input type="submit" name="dbupdate" value="Update" class="btn btn-primary"/>';
                                        $submit_btn .= $back_btn;
                                    }
                                }
                                

                                print <<<EOS
                                <form id="form-dbcreate" action="./admin.php" method="post">
                                    <div class="form-group">
                                        <label for="enterDatabaseName">Database Name:</label>
                                        <input type="text" class="form-control" id="enterDatabaseName" name="enterDatabaseName" $edit_dbname
                                            required/>
                                    </div>
                                    <p><small id="noidHelp" class="form-text text-muted">Review Ark configuration documentation at <a target="_blank" href="https://metacpan.org/pod/distribution/Noid/noid">https://metacpan.org/pod/distribution/Noid/noid</a> </small></p>
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
                                        <label for="templateHelp">Template (for minter):</label>

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
                                    $edit_dbtemplate
                                    <div class="form-group">
                                        <label for="enterDatabaseName">Prefix or Shoulder(must be unique):</label>
                                        <input type="text" class="form-control" id="enterPrefix" name="enterPrefix" $edit_dbprefix required/>
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
                                                    document.getElementById("enterNAA").required = true;
                                                    break;
                                                }
                                                default: {
                                                    break;
                                                }
                                            }
                                        }
                                    </script>
                                    <div class="form-group $edit_dbtemplate_display">
                                        <label for="identifier_minter">Term:</label>
                                        <select class="form-control" id="identifier_minter" name="identifier_minter" onchange="onChangeTerms(this.value);" $edit_dbtemplate_disabled required>
                                            <option selected disabled value="">Choose...</option>
                                            <option>short</option>
                                            <option>medium</option>
                                            <option>long</option>
                                        </select>
                                    </div>

                                    <div class="form-group">
                                        <label class="control-label" for="enterNAAN">Name Assigning Authority Number(NAAN):</label>
                                        <input type="text" class="form-control" id="enterNAAN" name="enterNAAN" $edit_dbnaan/>
                                    <small id="naan_tips" class="form-text text-muted">Look up your NAAN <a href="https://cdlib.org/naan_registry" target="_blank">here</a></small>
                                    </div>
                                    
                                    <div class="form-group">
                                        <label class="control-label" for="enterNAA">Name Assigning Authority (NAA):</label>
                                        <textarea type="text" class="form-control" id="enterNAA" name="enterNAA"
                                            >$edit_dbnaa</textarea>
                                    <small id="naa_tip" class="form-text text-muted"></small>
                                    </div>

                                    <input type="hidden" class="form-control" id="enterInsitutionName" name="enterInsitutionName" value="dsu/utsc-library"/>
                                    $submit_btn
                                </form>
                                EOS;

                            } else {
                                print <<<EOS
                                $back_btn
                            EOS;
                            }
                            ?>
                        </div> <!-- end of arksdb-create-form-->

                        <div id="arksdbs-list" class="col-sm-6">
                            <?php
                            // create an new Ark database
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
                                        trim($_POST['enterNAA']),
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

                            // Update a existing database 
                            if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['dbupdate'])) {
                                // backup database before bulk binding
                                $dbpath = getcwd() . DIRECTORY_SEPARATOR . 'db';
                                Database::dbupdatesetting($_POST['editDBname'], $dbpath, "naa", $_POST['enterNAA']);;
                            }

                            // List all created databases in the table
                            if (count($arkdbs) > 2) {
                                ?>
                                <div class="row">
                                    <table class="table table-bordered">
                                        <thead>
                                        <tr>
                                            <th scope="col">Collection</th>
                                            <th scope="col">Configuration</th>
                                            <th scope="col"></th>

                                        </tr>
                                        </thead>
                                        <tbody>
                                        <?php
                                        foreach ($arkdbs as $db) {
                                            if (!in_array($db, ['system', 'user'])) {
                                                $highlight = "";
                                                $setActive = '<a class="btn btn-success" href="./admin.php?db=' . $db . '">Select</a>';
                                                $setEdit= '<a class="btn btn-warning" href="./admin.php?op=edit&db=' . $db . '">Edit</a>';
                                                if (isset($_GET['op']) && $_GET['op'] == "edit") {
                                                    $setEdit= '<a class="btn btn-warning disabled" href="#disable>Edit</a>';
                                                }
                                                if (!isset($_GET['op']) && (isset($_GET['db']) && $_GET['db'] == $db)) {
                                                    $setActive = "<strong>Selected</srong>";
                                                    $highlight = 'class="table-success"';
                                                }
                                                $metadata = json_decode(rest_get("/admin/rest.php?db=" . $db . "&op=dbinfo"));
                                                $detail = "<p>";
                                                foreach ((array)$metadata as $key => $value) {
                                                    if ($key !== "naa")
                                                        $detail .= "<strong>$key</strong>: $value <br />";
                                                }
                                                $detail .= "</p>";
                                                print <<<EOS
                                                        <tr $highlight>
                                                            <td scope="row">$db</td>
                                                            <td scope="row">$detail</td>
                                                            <td scope="row">
                                                                <p>$setActive</p>
                                                                <p>$setEdit</p>
                                                            </td>

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
                        </div><!-- end of arksdbs-list -->
                    </div> <!-- end of row-dbcreate -->
                </div> <!-- end of arksdb-creation -->
            </div> <!-- end of arksdb -->

            <?php
            if (isset($_GET['db']) && !isset($_GET['op'])) { // if a database is selected (db name appears in the URL
                ?>
                <hr>
                <div id="arksdb-mint" class="card">
                    <h5 class="card-header">Minting</h5>
                    <div class="card-body">
                        <div id="row-mint" class="row">
                            <div class="col-sm-5">
                                <form id="form-mint" method="post" action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                    <div class="form-group">
                                        <input type="hidden" name="db" value="<?php echo $_GET['db'] ?>">
                                        <label for="exampleInputEmail1">How many Arks would you like to mint ?</label>
                                        <input type="number" class="form-control" id="mint-number" name="mint-number">
                                    </div>
                                    <input type="submit" name="mint" value="Mint" class="btn btn-primary"/>
                                </form>
                                 <!-- Modal -->
                                <div class="modal fade" id="MtingProgressModal" tabindex="-1" aria-labelledby="MtingProgressModalLabel" aria-hidden="true">
                                    <div class="modal-dialog">
                                        <div class="modal-content">
                                            <div class="modal-header">
                                                <h5 class="modal-title" id="MtingProgressModalLabel">Minting...</h5>
                                            </div>
                                            <div class="modal-body">
                                                <div class="progress">
                                                    <div id="minting_progress_bar" class="progress-bar progress-bar-striped progress-bar-animated" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100" style="width: 0%"></div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <script>
                                    document.addEventListener('DOMContentLoaded', function() {
                                     // Get the form, modal, input field, and progress bar
                                    const mintForm = document.getElementById('form-mint');
                                    const mintingProgressModalElement = document.getElementById('MtingProgressModal');
                                    const mintingProgressModal = new bootstrap.Modal(mintingProgressModalElement, {
                                        backdrop: 'static',
                                        keyboard: false
                                    });
                                    const mintNumberInput = document.getElementById('mint-number');
                                    const progressBar = document.getElementById('minting_progress_bar');

                                    // Add event listener to the form submit event
                                    mintForm.addEventListener('submit', function(event) {
                                        // Show the modal
                                        mintingProgressModal.show();

                                        // Get the mint number value and convert it to milliseconds
                                        const mintDuration = parseInt(mintNumberInput.value) * 1000;

                                        // Reset the progress bar
                                        progressBar.style.width = '0%';
                                        progressBar.setAttribute('aria-valuenow', '0');

                                        // Update the progress bar over the specified duration
                                        let startTime = Date.now();
                                        let interval = setInterval(function() {
                                            let elapsedTime = Date.now() - startTime;
                                            let progress = Math.min((elapsedTime / mintDuration) * 100, 100);
                                            progressBar.style.width = progress + '%';
                                            progressBar.setAttribute('aria-valuenow', progress);

                                            if (progress >= 100) {
                                                clearInterval(interval);
                                                // Hide the modal after the timeout
                                                //mintingProgressModal.hide();
                                            }
                                        }, 100); // Update every 100ms
                                    });
                                });
                                </script>
                            </div>
                            <div class="col-sm-7">
                                <?php
                                if ($_SERVER["REQUEST_METHOD"] == "POST" && !empty($_POST['mint-number']) && $_POST['mint-number'] > 0) {

                                    // backup database before bulk binding
                                    Database::backupArkDatabase();

                                    $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
                                    $contact = time();
                                    $count = 0;
                                    while ($_POST['mint-number']--) {
                                        $id = NoidArk::mint($noid, $contact);
                                        $count++;
                                    };
                                    print '
                                    <div class="alert alert-success" role="alert">
                                        Ark IDs have been minted successfully.
                                    </div>
                                    <script>
                                        // Update progress bar
                                        progressBar.setAttribute("aria-valuenow", 100);
                                    </script>
                                    ';
                                    Database::dbclose($noid);
                                    // redirect to the page.
                                    header("Location: admin.php?db=" . $_GET["db"]);

                                }
                                else if ($_SERVER["REQUEST_METHOD"] == "POST" && (empty($_POST['mint-number']) || $_POST['mint-number'] <= 0)) {
                                    print '
                                    <div class="alert alert-warning" role="alert">
                                        Please enter a valid number to mint.
                                    </div>
                                    ';
                                }
                                ?>
                                <p><h5>Minted Arks </h5></p>
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
                </div> <!-- end of arksdb-mint -->

                <hr>
                <div id ="arksdb-bind" class="card">
                    <h5 class="card-header">Bound Arks </h5>
                    <div class="card-body">
                        <div id="a-bound-arks-msg" class="row">
                            <div class="col-sm-12">
                                <?php
                                // handle bind set
                                if ($_SERVER["REQUEST_METHOD"] == "POST" && isset($_POST['bindset']) && $_POST['enterIdentifier'] != -1) {

                                    // backup database before bulk binding
                                    Database::backupArkDatabase();

                                    $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
                                    $contact = time();

                                    // check if ark ID exist
                                    $result = NoidArk::bind($noid, $contact, 1, 'set', trim($_POST['enterIdentifier']), strtoupper($_POST['enterKey']), $_POST['enterValue']);
                                    if (isset($result)) {

                                        print '<div class="alert alert-success" role="alert">
                                                Ark IDs have been bound successfully.
                                            </div>';
                                    } else {
                                        print '<div class="alert alert-warning" role="alert">
                                            Ark IDs does not exist to be bound.
                                        </div>';
                                    }
                                    Database::dbclose($noid);

                                    // refresh the page to clear Post method.
                                    header("Location: admin.php?db=" . $_GET["db"]);
                                }
                                ?>
                            </div> <!-- end of col-sm-12 -->
                        </div> <!-- end of single-bound-arks-msg -->

                        <?php
                        // handle clear bind set
                        if ($_SERVER["REQUEST_METHOD"] == "POST" && !empty($_POST['clear-bindset'])) { ?>
                            <div id="clear-a-bound-arks-msg" class="row">
                                <div class="col-sm-12">
                                    <?php
                                        // todo: if "all field" is checked, delete all fields bound instead
                                        $noid = Database::dbopen($_GET["db"], dbpath(), DatabaseInterface::DB_WRITE);
                                        if (isset($_POST['AllFieldcheckbox']) && $_POST['AllFieldcheckbox'] === "all-fields") {
                                            $where = "_key REGEXP '^" . $_POST['enterToClearIdentifier'] ."\t' and _key NOT REGEXP ':/c$' and _key NOT REGEXP ':/h$' order by _key";
                                            $status = Database::$engine->purge($where);
                                        }
                                        else {
                                            $status = NoidArk::clearBind($noid, trim($_POST['enterToClearIdentifier']), $_POST['enterKeytoClear']);
                                        }

                                        if ($status !== false) {
                                            print '<div class="alert alert-success" role="alert">
                                                    Ark ID <i>' . trim($_POST['enterToClearIdentifier']) . '</i> - ' . $_POST['enterKeytoClear'] . ' has been cleared
                                                </div>';
                                        } else {
                                            print '<div class="alert alert-success" role="alert">
                                                    Ark ID <i>' . trim($_POST['enterToClearIdentifier']) . '</i> - ' . $_POST['enterKeytoClear'] . ' failed to be cleared
                                                </div>';
                                        }
                                        Database::dbclose($noid);

                                        // redirect to the page.
                                        header("Location: admin.php?db=" . $_GET["db"]);
                                    ?>
                                </div> <!-- end of col-sm-12 -->
                            </div> <!-- end of clear-a-bound-arks-msg -->
                        <?php } ?>
                        <div id="arksdb-bind-operations" class="row">
                            <div class="col-sm-12">
                                <div class="dropdown show">
                                    <a class="btn btn-primary dropdown-toggle" href="#" role="button" id="dropdownMenuLink" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
                                        --- Select ---
                                    </a>

                                    <div class="dropdown-menu" aria-labelledby="dropdownMenuLink">
                                        <button type="button" class="btn btn-link dropdown-item" data-toggle="modal"
                                                data-target="#bindsetModal">
                                            Binding an Arks
                                        </button>
                                        <button type="button" class="btn btn-link dropdown-item" data-toggle="modal"
                                                data-target="#clearbindsetModal">
                                                Unbinding an Arks
                                        </button>
                                        <div class="dropdown-divider"></div>
                                        <button id="btn-bulk-bind" type="button" class="btn btn-link dropdown-item" data-toggle="modal"
                                                data-target="#bulkBindModal">
                                            Bulk Binding Arks
                                        </button>
                                    </div> <!-- end of dropdown-menu -->
                                </div> <!-- end of dropdown, show-->
                            </div> <!-- end of col-sm-12 -->
                        </div> <!-- end of arksdb-bind-operations-->

                        <div id="row-bindset" class="row">
                            <div class="col-sm-12">
                                <div class="modal fade" id="bindsetModal" tabindex="-1" aria-labelledby="bindsetModalLabel"
                                    aria-hidden="true">
                                    <div class="modal-dialog">
                                        <div class="modal-content">
                                            <div class="modal-header">
                                                <h5 class="modal-title" id="bindsetModalLabel">Binding an Ark ID</h5>
                                                <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                                    <span aria-hidden="true">&times;</span>
                                                </button>
                                            </div> <!-- end of modal-header -->
                                            <div class="modal-body">
                                                <div class="col-sm-12">
                                                    <form id="form-bindset" method="post"
                                                        action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                                        <div class="form-group">
                                                            <label for="enterIdentifier">Ark ID:</label>
                                                            <input type="text" id="enterIdentifier" name="enterIdentifier" class="form-control">
                                                        </div>
                                                        <div class="form-group">
                                                            <label for="enterKey">Key:</label>
                                                            <input type="text" class="form-control" id="enterKey"
                                                                name="enterKey" aria-describedby="keyHelp" required>
                                                            <small id="keyHelp" class="form-text text-muted">Enter a metadata field or a qualifier.<br >
                                                            <strong>Note:</strong> the field <i>URL</i> must be valid for Ark URL to work.
                                                            </small>
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
                                                    </form> <!-- end of form-bindset -->
                                                </div> <!-- end of col-sm-12 -->
                                            </div> <!-- end of modal-body -->
                                        </div> <!-- end of modal-content -->
                                    </div> <!-- end of modal-dialog -->
                                </div> <!-- end of bindsetModal -->

                                <!-- Remove Metadata set -->
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
                                                                <input type="text" id="enterToClearIdentifier" name="enterToClearIdentifier" class="form-control">
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
                                                        </form> <!--end of form-clear-bindset -->
                                                    </div> <!-- end of col-sm-12 -->
                                                </div> <!-- end of row -->
                                            </div> <!-- end of modal-body -->
                                        </div> <!-- end of modal-content -->
                                    </div> <!-- end of modal-diaglog -->
                                </div> <!-- end of clearbindsetModal -->

                                <!-- Bulk Bind Modal -->
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
                                            </div> <!-- end of modal-header -->
                                            
                                            <div class="modal-body">
                                                <div class="row" style="padding-bottom: 10px;">
                                                    <div class="col-sm-12">
                                                        <form id="form-import" method="post" enctype="multipart/form-data"
                                                            action="./admin.php?db=<?php echo $_GET['db'] ?>">
                                                            <div class="form-group">
                                                                <p><strong><u>Note:</u></strong> For this section, please
                                                                    follow:</p>
                                                                <ol>
                                                                <li>Mint your Arks </li>
                                                                <li>Download <a href="template.csv" download>template.csv</a>, place the above minted Arks into the ARK_ID column.</li>
                                                                <li>There is no limitation on the data fields you bind with your ARK. Add additional columns.
                                                                    <ul>
                                                                    <li><u><strong>Ark_ID</strong></u>: MANDATORY field for binding.</li>
                                                                    <li><u><strong>URL</strong></u>: MANDATORY field, the Resolver looks for this field to redirection.</li>
                                                                    <li><u>LOCAL_ID</u>: Object's unique ID in the repository. Any local identifier that is not ARK</li>
                                                                    <li><u>PID</u>: persistent Identifiers, Any persistent identifier that is not ARK</li>
                                                                    <li><u>COLLECTION</u>(Optional): Indicating the collection can help you discover.</li>
                                                                    </ul>
                                                                </li>
                                                                <li><strong>Upload the CSV to start the process.</strong></li>
                                                                </ol>
                                                            </div>
                                                            <hr/>
                                                            <div class="container">
                                                                <div class="form-group">
                                                                    <input class="form-check-input" type="checkbox" id="unbindAllFieldcheckbox" name="unbindAllFieldcheckbox">
                                                                    <label class="form-check-label" for="unbindAllFieldcheckbox">
                                                                        Replace existing metadata for each Arks
                                                                    </label>
                                                                </div>
                                                            </div>
                                                            <hr/>
                                                            <div class="container">
                                                                <div class="form-group">
                                                                    <label for="enterPasswordPostBulkBind"><strong>Please enter admin password before bulk binding: </strong></label>
                                                                    <input required type="password" class="form-control" id="enterPasswordPostBulkBind" name="enterPasswordPostBulkBind"
                                                                        placeholder="Password">
                                                                </div>
                                                                <div class="form-group">
                                                                    <p><strong><label for="importCSV">Upload
                                                                                CSV: </label></strong>
                                                                    </p>
                                                                    <input type="file" id="importCSV"  name="importCSV" accept=".csv, .tsv, text/csv, text/tab-separated-values">
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
                                                                        <div id="progress-status-message">
                                                                            <span id="progress_operation"></span> <span id="process_data"></span> of <span
                                                                                id="total_data"></span> Arks.
                                                                        </div>
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
                                                        </form> <!-- end of form-import -->
                                                    </div> <!-- end of col-sm-12 -->
                                                </div> <!-- end of row -->
                                            </div> <!-- end of modal-body -->

                                            <script>
                                                // at beginning, hide and disable process button
                                                $('#btn-process').hide();
                                                $('#btn-process').prop('disabled', true);
                                                $('#progress-status-message').hide();

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
                                                    $('#unbindAllFieldcheckbox').prop('disabled', true);
                                                    
                                                    //capture if Replace existing metadata checkbox is checked
                                                    localStorage.setItem("unbindAllFields", ($('#unbindAllFieldcheckbox').prop('checked') ? 1 : 0 ));

                                                    // read and process CSV file
                                                    var csv = $('#importCSV');
                                                    var csvFile = csv[0].files[0];
                                                    var ext = csv.val().split(".").pop().toLowerCase();

                                                    // verify if uploaded file is CSV file.
                                                    if ($.inArray(ext, ["csv", "tsv"]) === -1) {
                                                        $('#message').html('<div class="alert alert-danger">Only accept CSV or TSV file</div>');
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
                                                            var csvResult = e.target.result.split(/\n/).filter(function(line) {
                                                                return $.trim(line) !== ""; // Alternative: return line.trim()
                                                            });

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

                                                                // Hide the progress status message 
                                                                $('#progress_operation').hide();

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
                                                                if ($('#importCSV').val().split(".").pop().toLowerCase() === "tsv") { 
                                                                    var keys = csvResult[0].split('\t').map(function (x) {
                                                                        return x.toUpperCase().trim().replace(/ /g, "_");
                                                                    });
                                                                }
                                                                else {
                                                                    var keys = csvResult[0].split(',').map(function (x) {
                                                                        return x.toUpperCase().trim().replace(/ /g, "_");
                                                                    });
                                                                }
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
                                                                    $('#unbindAllFieldcheckbox').prop('disabled', false);

                                                                    return false;
                                                                } else {
                                                                    // loop through row 2 till end of CSV file
                                                                    var index = 1; // start from 2nd line because 1st one is header/columns

                                                                    // TODO: send post request to backup database, if success, proceed with the post request below:
                                                                    var password = JSON.parse(localStorage.getItem("syspasswd"));
                                                                    // send POST request for each line of read CSV file
                                                                    $.post("rest.php?db=<?php echo $_GET['db']; ?>&op=backupdb", {security: password})
                                                                        .done(function (data) {
                                                                            // disable input fields
                                                                            $('#importCSV').attr('disabled', true);
                                                                            $("#enterPasswordPostBulkBind").attr('disabled', true);
                                                                            
                                                                            // Show progress status message.
                                                                            $('#progress_operation').show();
                                                                            // send Post request
                                                                            var purged = localStorage.getItem("unbindAllFields");
                                                                            
                                                                            // if the checkbox Replace existing metadata is checked
                                                                            if (purged == 1) {
                                                                                // Doing the purging metadata first
                                                                                doPostPurging(index, total_data, csvResult);
                                                                            }
                                                                            else {
                                                                                // othersise, procceed with bulk binding
                                                                                index = 1;
                                                                                doPostBulkbind(index, total_data, csvResult);
                                                                            }
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

                                                /**
                                                 * Post Requests to remove existing metadata from imported Arks
                                                 */
                                                function doPostPurging(index, total_data, csvResult) {
                                                    // Update UI while processing data
                                                    $('.progress-bar').addClass("bg-danger");
                                                    $('#message').html('<div class="alert alert-warning">' +
                                                                                    'Removing existing metadata from the imported Arks.'
                                                                                    + '</div>');
                                                     // pulll preserve read data from CSV from local storage
                                                    var csvResult = JSON.parse(localStorage.getItem("importCSV"));
                                                    var password = JSON.parse(localStorage.getItem("syspasswd"));
                                                    var purged = localStorage.getItem("unbindAllFields");

                                                    if (Array.isArray(csvResult)) {
                                                        if ($('#importCSV').val().split(".").pop().toLowerCase() === "tsv") { 
                                                            var keys = csvResult[0].split('\t').map(function (x) {
                                                                return x.toUpperCase();
                                                            });
                                                        }
                                                        else {
                                                            var keys = csvResult[0].split(',').map(function (x) {
                                                                return x.toUpperCase();
                                                            });
                                                        }
                                                    }
                                                    else {
                                                        return;
                                                    }

                                                    // start binding each line of CSV file
                                                    var item = csvResult[index];
                                                    if ($('#importCSV').val().split(".").pop().toLowerCase() === "tsv") { 
                                                        var values = item.split('\t');
                                                    }
                                                    else {
                                                        var values = item.split(',');
                                                    }

                                                    var pdata = {};
                                                    for (var i = 0; i < values.length; i++) {
                                                        // enforce csv must follow sequence LocalID, PID, URL,
                                                        if (keys[i] !== undefined) {
                                                            pdata[keys[i].toUpperCase().replace(/(\r\n|\n|\r)/gm,"")] = values[i].trim().replace(/ /g, "_");
                                                        }
                                                    }

                                                    // send POST request for each line of read CSV file
                                                    $.post("rest.php?db=<?php echo $_GET['db']; ?>&op=purge&stage=upload", {data: pdata, security: password, purged: purged})
                                                        .done(function (data) {
                                                            var result =  JSON.parse(data);
                                                            if (result.success == 401) {

                                                                // display unauthrize message
                                                                $('#message').html('<div class="alert alert-danger">'+result.message+'</div>');

                                                                // re-enable operation button
                                                                $('#process').css('display', 'none');
                                                                $('#btn-process').prop('disabled', false);
                                                                $('#bulk-binding-dismiss-button').prop('disabled', false);
                                                                $('#unbindAllFieldcheckbox').prop('disabled', false);
                                                                return;
                                                            }
                                                            else {
                                                                // process result of each process
                                                                processPostSuccess(index, csvResult, data, "Removing existing metadata from", "Existing Metadata has been removed.");

                                                                // recursive call post request till end of file
                                                                index++;
                                                                if (index < csvResult.length)
                                                                    doPostPurging(index, keys, csvResult);
                                                                else {
                                                                    index = 1;
                                                                    doPostBulkbind(index, total_data, csvResult);
                                                                }
                                                            }
                                                        })
                                                        .fail(function () {
                                                            $('#message').html('<div class="alert alert-danger">Fail to read the CSV file.</div>');
                                                            $('#importCSV').attr('disabled', false);
                                                            $('#importCSV').val('Import');
                                                        });
                                                }

                                                /**
                                                 * Post Requests to bulk bind metdata to import Arks
                                                 */
                                                function doPostBulkbind(index, total_data, csvResult) {
                                                    // dismiss the progress bar
                                                    $('#process').css('display', 'block');
                                                    $('.progress-bar').removeClass("bg-danger");
                                                    $('.progress-bar').addClass("bg-success");
                                                    // display the message of ongoing binding process.
                                                    $('#message').html('<div class="alert alert-warning">' +
                                                                    'The Binding process has started. Please do not close this page until the process is completed.'
                                                                    + '</div>');
                                                    // pulll preserve read data from CSV from local storage
                                                    
                                                    var csvResult = JSON.parse(localStorage.getItem("importCSV"));
                                                    var password = JSON.parse(localStorage.getItem("syspasswd"));
                                                    var purged = localStorage.getItem("unbindAllFields");
                                                    
                                                    if (Array.isArray(csvResult)) {
                                                        if ($('#importCSV').val().split(".").pop().toLowerCase() === "tsv") { 
                                                            var keys = csvResult[0].split('\t').map(function (x) {
                                                                return x.toUpperCase();
                                                            });
                                                        }
                                                        else {
                                                            var keys = csvResult[0].split(',').map(function (x) {
                                                                return x.toUpperCase();
                                                            });
                                                        }
                                                    }
                                                    else {
                                                        return;
                                                    }

                                                    // start binding each line of CSV file
                                                    var item = csvResult[index];
                                                    if ($('#importCSV').val().split(".").pop().toLowerCase() === "tsv") { 
                                                        var values = item.split('\t');
                                                    }
                                                    else {
                                                        var values = item.split(',');
                                                    }
                                                    
                                                    var pdata = {};
                                                    for (var i = 0; i < values.length; i++) {
                                                        // enforce csv must follow sequence LocalID, PID, URL,
                                                        if (keys[i] !== undefined) {
                                                            pdata[keys[i].toUpperCase().replace(/(\r\n|\n|\r)/gm,"")] = values[i].trim().replace(/ /g, "_");
                                                        }
                                                    }

                                                    // send POST request for each line of read CSV file
                                                    $.post("rest.php?db=<?php echo $_GET['db']; ?>&op=bulkbind&stage=upload", {data: pdata, security: password, purged: purged})
                                                        .done(function (data) {
                                                            
                                                        var result =  JSON.parse(data);
                                                            if (result.success == 401) {

                                                                // display unauthrize message
                                                                $('#message').html('<div class="alert alert-danger">'+result.message+'</div>');

                                                                // re-enable operation button
                                                                $('#process').css('display', 'none');
                                                                $('#btn-process').prop('disabled', false);
                                                                $('#bulk-binding-dismiss-button').prop('disabled', false);
                                                                $('#unbindAllFieldcheckbox').prop('disabled', false);
                                                                return;
                                                            }
                                                            else {
                                                                // process result of each process
                                                                processPostSuccess(index, csvResult, data, "Binding", "Bulk Bind successfully completed.");

                                                                // recursive call post request till end of file
                                                                index++;
                                                                if (index < csvResult.length)
                                                                    doPostBulkbind(index, keys, csvResult);
                                                            }


                                                        })
                                                        .fail(function () {
                                                            $('#message').html('<div class="alert alert-danger">Fail to read the CSV file.</div>');
                                                            $('#importCSV').attr('disabled', false);
                                                            $('#importCSV').val('Import');
                                                        });
                                                }

                                                /**
                                                 * Handler for Post request success runnin, mainly update UIs
                                                 */
                                                function processPostSuccess(index, csvResult, data, operation, message) {
                                                    // get total objects to bind
                                                    var total_data = csvResult.length;
                                                    // get result form POST request from REST api
                                                    var result = JSON.parse(data);

                                                    // if success
                                                    if (result.success === true) {

                                                        // display total lines have to import
                                                        $('#total_data').text(total_data);

                                                        // calculate percentage of ongoing process.
                                                        var width = ((index + 1) / total_data) * 100;

                                                        // update the progress bar.
                                                        $('#progress_operation').text(operation);
                                                        $('#process_data').text(index);
                                                        $('.progress-bar').css('width', width + '%');
                                                        $('#progress-status-message').show();

                                                        // if the process reaches 100%
                                                        if (width >= 100) {

                                                            // disable all buttons during processing
                                                            // dismiss the progress bar
                                                            $('#process').css('display', 'none');

                                                            // reset the input type file
                                                            //$('#importCSV').val('');
                                                            $('#importCSV').attr('disabled', true);

                                                            // re-enable all buttons
                                                            $('#import').attr('disabled', false);
                                                            $('#import').val('Import');
                                                            $('#btn-close-bulkbind').prop('disabled', false);
                                                            $('#bulk-binding-dismiss-button').prop('disabled', false);
                                                            $('#unbindAllFieldcheckbox').prop('disabled', false);
                                                            $('#btn-process').hide();

                                                            // display completed message
                                                            $('#message').html('<div class="alert alert-success">'+message+'</div>');
                                                            
                                                            // clear read data from CSV from localstorage
                                                            if (operation === "Binding") {
                                                                localStorage.removeItem("importCSV");
                                                                localStorage.removeItem("syspasswd");
                                                            }

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
                                            </script> <!-- end of javascript handle bulk bind -->
                                        </div> <!-- end of modal-content -->
                                    </div> <!-- end of bulk-binding-modal -->
                                </div> <!-- end of bulkBindModal -->
                            </div> <!-- end of col-sm-12 -->
                        </div> <!-- end of row-bindset -->

                        <div id="arksdb-bound-table" class="row" style="margin-top:20px;">
                            <div class="col-sm-12">
                                <div class="row">
                                    <div class="col-md-12">
                                        <table id="bound_table" class="display" style="width:100%">
                                            <thead>
                                            <tr>
                                                <th></th>
                                                <th>Ark ID</th>
                                                <!--<th>Number <br />of Redirects</th>-->
                                                <th>Ark URL</th>
                                                <th>Metadata</th>
                                            </tr>
                                            </thead>
                                        </table> <!-- end of bound_table -->
                                    </div> <!-- end of col-md-12 -->
                                </div> <!-- end of row -->
                            </div> <!-- end of col-sm-12 -->
                        </div> <!-- end of arksdb-bound-table -->
                    </div> <!-- end of arksdb-bind card-body -->
                </div> <!-- end of arksdb-bind -->
                <hr>
                <!-- Unbound Arks -->
                <div id ="arksdb-unbound-arks" class="card">
                    <h5 class="card-header">Unbound Arks </h5>
                    <div class="card-body">
                        <div class="row" style="margin-top:20px;">
                            <div class="col-sm-12">
                                <div class="row">
                                    <div class="col-md-12">
                                        <table id="unbound_table" class="display" style="width:100%">
                                            <thead>
                                            <tr>
                                                <th></th>
                                                <th>Ark ID</th>
                                                <th>Ark URL</th>
                                            </tr>
                                            </thead>
                                        </table> <!-- end of unbound_table -->
                                    </div> <!-- end of col-md-12 -->
                                </div> <!-- end of row -->
                            </div> <!-- end of col-sm-12 -->
                        </div> <!-- end of row -->
                    </div> <!-- end of card-header -->
                </div> <!-- end of arksdb-unbound-arks -->
            <?php }
            ?>
        </div> <!-- end of Container -->
    </body>
</html>

<?php
ob_flush();
