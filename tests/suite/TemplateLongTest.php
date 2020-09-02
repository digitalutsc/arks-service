<?php
/**
 * @author Daniel Berthereau (conversion to Php)
 * @package Noid
 */

require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'NoidTestCase.php';

/**
 * Tests for Noid: create a template with 3721 noids, and mint them all, until a
 * duplicate is found (none!).
 */
class TemplateLongTest extends NoidTestCase
{
    public function testLong()
    {
        $total = 3721;

        # Start off by doing a dbcreate.
        # First, though, make sure that the BerkeleyDB files do not exist.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate b.rllk long 99999 example.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Check that the "NOID" subdirectory was created.
        $this->assertFileExists($this->noid_dir, 'no minter directory created, stopped');
        # echo 'NOID was created';

        # That "NOID" is a directory.
        $this->assertTrue(is_dir($this->noid_dir), 'NOID is not a directory, stopped');
        # echo 'NOID is a directory';

        # Check for the presence of the "README" file, then "log" file, then the
        # "logbdb" file within "NOID".
        $this->assertFileExists($this->noid_dir . 'README');
        # echo 'NOID/README was created';
        $this->assertFileExists($this->noid_dir . 'log');
        # echo 'NOID/log was created';
        $this->assertFileExists($this->noid_dir . 'logbdb');
        # echo 'NOID/logbdb was created';

        # Check for the presence of the BerkeleyDB file within "NOID".
        $this->assertFileExists($this->noid_dir . 'noid.bdb', 'minter initialization failed, stopped');
        # echo 'NOID/noid.bdb was created';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $ids = array();
        fwrite(STDERR, PHP_EOL);
        for ($i = 1; $i <= $total; $i++) {
            $id = Noid::mint($noid, $contact, '');
            // The assertion is called separately to process it quickly.
            if (isset($ids[$id])) {
                $this->assertArrayHasKey($id, $ids,
                    sprintf('The noid "%s" is already set (order %d, current %d).',
                        $id, $ids[$id], $i));
            }

            $ids[$id] = $i;

            if (($i % 100) == 0) {
                fwrite(STDERR, "Processed $i / $total (last: $id)" . PHP_EOL);
            }
        }

        # Try to mint another, after they are exhausted.
        $id = Noid::mint($noid, $contact, '');
        $this->assertEmpty($id);
    }
}
