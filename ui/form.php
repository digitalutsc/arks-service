<?php
include "lib/Noid.php";
require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'ui/NoidUI.php';

?>

<html>
<head>
    <title>Test Noid</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css"
          integrity="sha384-JcKb8q3iqJ61gNV9KGb8thSsNjpSL0n8PARn9HuZOnIxN0hoP+VmmDGMN5t9UJ0Z" crossorigin="anonymous">
</head>
<body>
<div class="container">
    <div class="row">
        <div class="col-sm">
            <h1 class="text-center">Ark Service</h1>
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
                <div class="col-sm-5">
                    <?php
                    if (!isset($_GET['db'])) {
                        print <<<EOS
                            <form id="form-dbcreate" action="./form.php" method="post">
                                <div class="form-group">
                                    <label for="enterDatabaseName">Database Name:</label>
                                    <input type="text" class="form-control" id="enterDatabaseName" name="enterDatabaseName"
                                           required/>
                                </div>
                                <div class="form-group">
                                    <label for="exampleFormControlSelect1">Template:</label>
                                    <select class="form-control" id="selectTemplate" name="selectTemplate" required>
                                        <option selected disabled value="">Choose...</option>
                                        <option>.rddd</option>
                                        <option>.sdddddd</option>
                                        <option>.zd</option>
                                        <option>.bc.rdddd</option>
                                        <option>.8rf.sdd</option>
                                        <option>.se</option>
                                        <option>.h9.reee</option>
                                        <option>.bc.rdedeedd</option>
                                        <option>.zededede</option>
                                        <option>.dd.sdede</option>
                                        <option>.rdedk</option>
                                        <option>.sdeeedk</option>
                                        <option>.zdeek</option>
                                        <option>.63q.redek</option>
                                    </select>
                                </div>
                                <button type="submit" class="btn btn-primary">Create</button>
                            </form>
                            EOS;

                    } else {
                        print <<<EOS
                            <a class="btn btn-secondary" href="./form.php">Reset</a>
                        EOS;
                    }
                    ?>

                </div>
                <div class="col-sm-7">
                    <?php
                    if ($_SERVER["REQUEST_METHOD"] == "POST" && !isset($_GET['db'])) {
                        $database = str_replace(" ", "_", $_POST['enterDatabaseName']);
                        $noidUI = new NoidUI();
                        $result = $noidUI->dbcreate($database, $_POST['selectTemplate']);
                        print $result;
                    }
                    $dirs = scandir(getcwd() . '/db/');
                    if (count($dirs) > 2) {
                        ?>
                        <div class="row">
                            <table class="table table-bordered">
                                <thead>
                                <tr>
                                    <th scope="col">Past database</th>
                                    <th scope="col">Set Active</th>
                                </tr>
                                </thead>
                                <tbody>
                                <?php


                                foreach ($dirs as $dir) {
                                    if (!in_array($dir, ['.', '..'])) {
                                        $setActive = (isset($_GET['db']) && $_GET['db'] == $dir) ? 'Currently Active' : '<a href="./form.php?db=' . $dir . '">Set Active</a>';
                                        print <<<EOS
                                        <tr>
                                            <td scope="row">$dir</td>
                                            <td scope="row">$setActive</td>
                                        </tr>
                                    EOS;
                                    }
                                }
                                ?>
                                </tbody>
                            </table>
                        </div>
                    <?php } ?>

                </div>

            </div>
        </div>
    </div>

    <?php
    if (isset($_GET['db'])) {
        ?>
        <hr>
        <div class="card">
            <h5 class="card-header">Minting</h5>
            <div class="card-body">
                <div id="row-mint" class="row">
                    <div class="col-sm-5">
                        <form id="form-mint" method="post" action="./form.php?db=<?php echo $_GET['db'] ?>">
                            <div class="form-group">
                                <input type="hidden" name="db" value="<?php echo $_GET['db'] ?>">
                                <label for="exampleInputEmail1">How many:</label>
                                <input type="number" class="form-control" id="mint-number" name="mint-number">
                            </div>
                            <input type="submit" name="action" value="Mint" class="btn btn-primary" />
                        </form>
                    </div>
                    <div class="col-sm-7">
                        <?php
                        if ($_SERVER["REQUEST_METHOD"] == "POST") {
                            $noidUI = new NoidUI();
                            //$noidUI->mint($_POST['db'], $_POST['mint-number']);
                            $result = $noidUI->exec_command("mint " . $_POST['mint-number'], $noidUI->path().$_GET["db"]);
                            $newIDs = array_filter(explode("id: ", $result));
                            $noidUI::print_log($newIDs);
                            $noidUI->toCSV($newIDs, "mint-".time());

                        }
                        ?>
                    </div>
                </div>
            </div>
        </div>
        <!--
        <hr>
        <div class="card">
            <h5 class="card-header">Bind Set</h5>
            <div class="card-body">
                <div id="row-bindset" class="row">
                    <div class="col-sm">
                        <form id="form-mint">
                            <div class="form-group">
                                <label for="exampleInputEmail1">Bind Set:</label>
                                <input type="email" class="form-control" id="exampleInputEmail1"
                                       aria-describedby="emailHelp">
                                <small id="emailHelp" class="form-text text-muted">No space, if there is, it will be convert
                                    to
                                    "_"</small>
                            </div>
                            <button type="submit" class="btn btn-primary">Submit</button>
                        </form>
                    </div>
                    <div class="col-sm">
                        Output
                    </div>
                </div>
            </div>
        </div>

        <hr>

        <div class="card">
            <h5 class="card-header">Fetch</h5>
            <div class="card-body">

                <div id="row-fetch" class="row">
                    <div class="col-sm">
                        <form id="form-mint">
                            <div class="form-group">
                                <label for="exampleInputEmail1">Bind Set:</label>
                                <input type="email" class="form-control" id="exampleInputEmail1"
                                       aria-describedby="emailHelp">
                                <small id="emailHelp" class="form-text text-muted">No space, if there is, it will be convert
                                    to
                                    "_"</small>
                            </div>
                            <button type="submit" class="btn btn-primary">Submit</button>
                        </form>
                    </div>
                    <div class="col-sm">
                        Output
                    </div>
                </div>
            </div>
        </div>

        <hr>
        <div class="card">
            <h5 class="card-header">Search</h5>
            <div class="card-body">
                <div id="row-search" class="row">
                    <div class="col-sm">
                        <form id="form-mint">
                            <div class="form-group">
                                <label for="exampleInputEmail1">Bind Set:</label>
                                <input type="email" class="form-control" id="exampleInputEmail1"
                                       aria-describedby="emailHelp">
                                <small id="emailHelp" class="form-text text-muted">No space, if there is, it will be convert
                                    to
                                    "_"</small>
                            </div>
                            <button type="submit" class="btn btn-primary">Submit</button>
                        </form>
                    </div>
                    <div class="col-sm">
                        Output
                    </div>
                </div>
            </div>
        </div>

        <hr>
        <div class="card">
            <h5 class="card-header">Import</h5>
            <div class="card-body">
                <div id="row-import" class="row">
                    <div class="col-sm">
                        <form id="form-mint">
                            <div class="form-group">
                                <label for="exampleInputEmail1">Bind Set:</label>
                                <input type="email" class="form-control" id="exampleInputEmail1"
                                       aria-describedby="emailHelp">
                                <small id="emailHelp" class="form-text text-muted">No space, if there is, it will be convert
                                    to
                                    "_"</small>
                            </div>
                            <button type="submit" class="btn btn-primary">Submit</button>
                        </form>
                    </div>
                    <div class="col-sm">
                        Output
                    </div>
                </div>
            </div>
        </div>
    -->
    <?php } ?>
</div>
</body>
</html>
