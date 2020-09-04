<?php
/**
 * @author Daniel Berthereau
 * @package Noid
 */

use PHPUnit\Framework\TestCase;

/**
 * Common methods to test Noid
 */
class NoidTestCase extends TestCase
{
    public $dir;
    public $rm_cmd;
    public $noid_cmd;
    public $noid_dir;

    public function setUp()
    {
        $this->dir = getcwd();
        $this->rm_cmd = "/bin/rm -rf {$this->dir}/NOID > /dev/null 2>&1 ";
        $noid_bin = 'blib/script/noid';
        $cmd = is_executable($noid_bin) ? $noid_bin : $this->dir . DIRECTORY_SEPARATOR . 'noid';
        $this->noid_cmd = $cmd . ' -f ' . $this->dir . ' ';
        $this->noid_dir = $this->dir . DIRECTORY_SEPARATOR . 'NOID' . DIRECTORY_SEPARATOR;

        require_once dirname($cmd) . DIRECTORY_SEPARATOR . 'lib'. DIRECTORY_SEPARATOR . 'Noid.php';
    }

    public function tearDown()
    {
        $dbname = $this->noid_dir . 'noid.bdb';
        if (file_exists($dbname)) {
            Noid::dbclose($dbname);
        }
    }

    public function testReady()
    {
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

    /**
     * Subroutine to get the policy out of the README file.
     *
     * @param string $filename
     * @return string
     */
    protected function _get_policy($file_name)
    {
        $fh = fopen($file_name, 'r');
        $error = error_get_last();
        $this->assertTrue(is_resource($fh),
            sprintf('open of "%s" failed, %s', $file_name, $error['message']));
        if ($fh === false) {
            return;
        }

        $regex = '/^Policy:\s+\(:((G|-)(R|-)(A|-)(N|-)(I|-)(T|-)(E|-))\)\s*$/';
        while ($line = fgets($fh)) {
            $result = preg_match($regex, $line, $matches);
            if ($result) {
                fclose($fh);
                return $matches[1];
            }
        }
        fclose($fh);
    }

    /**
     * Subroutine to generate a random string of (sort of) random length.
     *
     * @return string
     */
    protected function _random_string()
    {
        $to_choose_from =
            'ABCDEFGHIJKLMNOPQRSTUVWXYZ' .
            'abcdefghijklmnopqrstuvwxyz' .
            '0123456789';
        $building_string = '';

        # Calculate the string length.  First, get a fractional number that's
        # between 0 and 1 but never 1.
        $string_length = (float) mt_rand() / (float) (mt_getrandmax() - 1);
        # Multiply it by 48, so that it's between 0 and 48, but never 48.
        $string_length *= 48;
        # Throw away the fractional part, leaving an integer between 0 and 47.
        $string_length = intval($string_length);
        # Add 3 to give us a number between 3 and 50.
        $string_length += 3;

        for ($i = 0; $i < $string_length; $i++) {
            # Calculate an integer between 0 and ((length of
            # $to_choose_from) - 1).
            # First, get a fractional number that's between 0 and 1,
            # but never 1.
            $to_choose_index = (float) mt_rand() / (float) (mt_getrandmax() - 1);
            # Multiply it by the length of $to_choose_from, to get
            # a number that's between 0 and (length of $to_choose_from),
            # but never (length of $choose_from);
            $to_choose_index *= strlen($to_choose_from);
            # Throw away the fractional part to get an integer that's
            # between 0 and ((length of $to_choose_from) - 1).
            $to_choose_index = intval($to_choose_index);

            # Fetch the character at that index into $to_choose_from,
            # and append it to the end of the string we're building.
            $building_string .= substr($to_choose_from, $to_choose_index, 1);
        }

        # Return our construction.
        return $building_string;
    }

    protected function _short($template, $return = 'erc')
    {
        $cmd = $this->rm_cmd;
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        $report = Noid::dbcreate('.', 'jak', $template, 'short');
        $errmsg = Noid::errmsg(null, 1);
        if ($return == 'stdout' || $return == 'stderr') {
            $this->assertEmpty($report, 'should output an error: ' . $errmsg);
            return $errmsg;
        }

        $this->assertNotEmpty($report, $errmsg);

        Noid::dbclose($this->noid_dir . 'noid.bdb');

        // Return the erc.
        $isReadable = is_readable($this->noid_dir . 'README');
        $error = error_get_last();
        $this->assertTrue($isReadable, "can't open README: " . $error['message']);

        $erc = file_get_contents($this->noid_dir . 'README');
        return $erc;
        #return `./noid dbcreate $template short 2>&1`;
    }
}
