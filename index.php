<?php
include "lib/noid/Noid.php";
require_once "NoidUI.php";

if (isset($_GET['q'])) {
    $uid = str_replace("ark:/", "", $_GET['q']);
    print $uid;

    $dirs = scandir(NoidUI::dbpath());
    if (is_array($dirs) && count($dirs) > 2) {
        $noidUI = new NoidUI();
        foreach ($dirs as $dir) {
            if (!in_array($dir, ['.', '..'])) {

                // execute the command with entered params
                $result = $noidUI->exec_command("get " . $uid . ' ' . "Website", $noidUI->path($dir));

                $url = trim(preg_replace('/\s\s+/', ' ', $result));

                // refresh the page to destroy post section
                header("Location: " . $url);
            }

        }
    }


}
else {
    print "invalid argument";
}
