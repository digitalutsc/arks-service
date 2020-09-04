<?php

class NoidUI
{
    public $dir;
    public $rm_cmd;
    public $noid_cmd;
    public $noid_dir;
    public $noid;

    public function __construct()
    {
        $this->dir = getcwd();
        $this->rm_cmd = "/bin/rm -rf {$this->dir}/NOID > /dev/null 2>&1 ";
        $noid_bin = 'blib/script/noid';
        $cmd = is_executable($noid_bin) ? $noid_bin : $this->dir . DIRECTORY_SEPARATOR . 'noid';
        $this->noid_cmd = $cmd . ' -f ' . $this->dir . ' ';
        $this->noid_dir = $this->dir . DIRECTORY_SEPARATOR . 'NOID' . DIRECTORY_SEPARATOR;
        $this->noid = dirname($cmd) . DIRECTORY_SEPARATOR . 'lib' . DIRECTORY_SEPARATOR . 'Noid.php';
    }

    public function dbcreate(String $name, String $template, $return = 'erc') {
        $db_path = getcwd()."/db/" .$name;
        //TODO: mkdir with $name (check exist first)
        if (!file_exists($db_path)) {
            mkdir($db_path, 0775);
            $cmd = $this->rm_cmd;
            $this->_executeCommand($cmd, $status, $output, $errors);

            $report = Noid::dbcreate($db_path, "dsu", $template, 'short');
            $errmsg = Noid::errmsg(null, 1);
            if ($return == 'stdout' || $return == 'stderr') {
                throw new Exception("Something went wrong");
                return $errmsg;
            }

            if (!isset($report))  {
                throw new Exception("Unable to create database");
            }

            Noid::dbclose($db_path . '/NOID/noid.bdb');

            // Return the erc.
            //$isReadable = is_readable($db_path . '/NOID/ . 'README');
            $isReadable = file_exists($db_path . '/NOID/README');
            if ($isReadable) {
                $result = <<<EOS
                    <div class="alert alert-success" role="alert">
                        New database <i>$name</i> created successfully.
                    </div>
                EOS;
                return $result;
            }
        }
        else {
            print("Database already existed");
        }


    }

    protected function _executeCommand($cmd, &$status, &$output, &$errors)
    {
        // Using proc_open() instead of exec() avoids an issue: current working
        // directory cannot be set properly via exec().  Note that exec() works
        // fine when executing in the web environment but fails in CLI.
        $descriptorSpec = array(
            0 => array('pipe', 'r'), //STDIN
            1 => array('pipe', 'w'), //STDOUT
            2 => array('pipe', 'w'), //STDERR
        );
        if ($proc = proc_open($cmd, $descriptorSpec, $pipes, getcwd())) {
            $output = stream_get_contents($pipes[1]);
            $errors = stream_get_contents($pipes[2]);
            foreach ($pipes as $pipe) {
                fclose($pipe);
            }
            $status = proc_close($proc);
        } else {
            throw new Exception("Failed to execute command: $cmd.");
        }
    }

    public function toString() {
        print "<pre>";
        print_r($this);
        print "</pre>";
    }

    public static function print_log($thing) {
        print "<pre>";
        print_r($thing);
        print "</pre>";
    }
}