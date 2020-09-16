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
        $this->noid = $cmd;
        $this->noid_cmd = $cmd . ' -f ' . $this->dir . ' ';
        $this->noid_dir = $this->dir . DIRECTORY_SEPARATOR . 'NOID' . DIRECTORY_SEPARATOR;
        //$this->noid = dirname($cmd) . DIRECTORY_SEPARATOR . 'lib' . DIRECTORY_SEPARATOR . 'Noid.php';
    }

    public function dbcreate(string $name, string $template, $return = 'erc')
    {
        //$db_path = getcwd()."/db/" .$name;
        $db_path = $this->path($name);
        //TODO: mkdir with $name (check exist first)
        if (!file_exists($db_path)) {
            mkdir($db_path, 0775);
            $cmd = $this->rm_cmd;
            $this->_executeCommand($cmd, $status, $output, $errors);

            Noid::dbcreate($db_path, "dsu", $template, 'short');
            Noid::errmsg(null, 1);

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
        } else {
            print("Database already existed");
        }
    }

    public function exec_command(string $command, string $db_path = null)
    {
        $cmd = "$this->noid -f $db_path $command";
        print("<p><strong><u>Linux Cmd</u>:</strong> " . $cmd . "</p>");
        $result = $this->_executeCommand($cmd, $status, $output, $errors);
        return $result;
    }

    public function mint(string $dbname, int $number)
    {
        //$db_path = getcwd()."/db/" .$dbname;
        $db_path = $this->path($dbname);
        if (!file_exists($db_path)) {
            throw new Exception("Database not found");
            exit;
        }
        $noid = Noid::dbopen($db_path . '/NOID/' . 'noid.bdb', 0);
        return Noid::mint($noid, "dsu", '');
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
            return $output;
        } else {
            throw new Exception("Failed to execute command: $cmd.");
        }
    }

    public function mintToCSV(string $path, array $data, string $filename)
    {

        if (!file_exists($path . '/mint/')) {
            mkdir($path . '/mint', 0775);
        }
        $out = fopen($path . '/mint/' . $filename . '.csv', 'w');
        $flag = false;
        fputcsv($out, ["Identifer", "pid"], ',', '"');
        foreach ($data as $row) {
            fputcsv($out, [preg_replace("/\r|\n/", "", $row)], ',', '"');
        }
        fclose($out);
    }

    public function importedToCSV(string $folder, string $path, array $collumns, array $data, string $filename)
    {
        if (!file_exists($path . '/' . $folder . '/')) {
            mkdir($path . '/' . $folder . '', 0775);
        }

        $out = fopen($path . '/' . $folder . '/' . $filename . '.csv', 'w');
        $flag = false;

        //write columns
        fputcsv($out, $collumns, ',', '"');

        // write other rows
        foreach ($data as $row) {
            if (!$flag) {
                // display field/column names as first row
                fputcsv($out, $row, ',', '"');
                $flag = true;
            }
            array_walk($row, __NAMESPACE__ . '\cleanData');
            fputcsv($out, $row, ',', '"');
        }

        fclose($out);
    }

    public function saveMetadataToCSV(string $path, string $dbname, array $json)
    {
        $file = fopen($path . '/' . $dbname . '.json', 'w');
        fwrite($file, json_encode($json));
        fclose($file);
    }
    public static function getDatabaseInfo(string $path, string $dbname) {
        if (file_exists($path. "/". $dbname. ".json")) {
            $metadata = file_get_contents($path. "/". $dbname. ".json");
            if ($metadata === false) {
                throw new Exception("Unable to get Database information from metadata file");
            }
            $databaseInfo = json_decode($metadata);
            return $databaseInfo;
        }
        return null;

    }

    public function path(string $dbname = "")
    {
        return getcwd() . "/db/" . $dbname;
    }

    public static function dbpath(string $dbname = "")
    {
        return getcwd() . "/db/" . $dbname;
    }

    public function toString()
    {
        print "<pre>";
        print_r($this);
        print "</pre>";
    }

    public static function print_log($thing)
    {
        print "<pre>";
        print_r($thing);
        print "</pre>";
    }
}