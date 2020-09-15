<?php
include "lib/noid/Noid.php";
require_once "NoidUI.php";

if (isset($_GET['q'])) {
    $uid = str_replace("ark:/", "", $_GET['q']);
    $dirs = scandir(NoidUI::dbpath());
    if (is_array($dirs) && count($dirs) > 2) {
        $noidUI = new NoidUI();
        foreach ($dirs as $dir) {
            if (!in_array($dir, ['.', '..'])) {

                // execute the command with entered params
                $result = $noidUI->exec_command("get " . $uid . ' ' . "PID", $noidUI->path($dir));
                $pid = trim(preg_replace('/\s\s+/', ' ', $result));

                // get current databaase
                $metadata = NoidUI::getDatabaseInfo(NoidUI::dbpath($dir), $dir);

                // refresh the page to destroy post section
                header("Location: http://$metadata->enterRedirect/islandora/object/$pid");
            }
        }
    }
}
else {
    print "invalid argument";
}
