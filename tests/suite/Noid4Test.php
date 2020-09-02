<?php
/**
 * @author Michael A. Russell
 * @author Daniel Berthereau (conversion to Php)
 * @package Noid
 */

require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'NoidTestCase.php';

/**
 * Tests for Noid (4).
 *
 * ------------------------------------
 *
 * Project: Noid
 *
 * Name:        noid4.t
 *
 * Function:    To test the noid command.
 *
 * What Is Tested:
 *      Create minter with template de, for 290 identifiers.
 *      Mint 10.
 *      Queue 3, hold 2, that would have been minted in the
 *          next 20.
 *      Mint 20 and check that they come out in the correct order.
 *
 * Command line parameters:  none.
 *
 * Author:  Michael A. Russell
 *
 * Revision History:
 *      7/19/2004 - MAR - Initial writing
 *
 * ------------------------------------
 */
class Noid4Test extends NoidTestCase
{
    public function testNoid4()
    {
        # Start off by doing a dbcreate.
        # First, though, make sure that the BerkeleyDB files do not exist.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate tst4.rde long 13030 cdlib.org noidTest >/dev/null";
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

        # Mint 10.
        $cmd = "{$this->noid_cmd} mint 10 > /dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Queue 3.
        $cmd = "{$this->noid_cmd} queue now 13030/tst43m 13030/tst47h 13030/tst44k >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Hold 2.
        $cmd = "{$this->noid_cmd} hold set 13030/tst412 13030/tst421 >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Mint 20, and check that they have come out in the correct order.
        $cmd = "{$this->noid_cmd} mint 20";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Remove trailing newlines, and delete the last line if it's empty.
        $noid_output = explode(PHP_EOL, $output);
        $noid_output = array_map('trim', $noid_output);
        # If the last one is the null string, delete it.
        $noid_output = array_filter($noid_output, 'strlen');
        $this->assertEquals(20, count($noid_output),
        # If we don't have exactly 20, something is probably very wrong.
            'wrong number of ids minted, stopped');
        # echo 'number of minted noids';

        $this->assertEquals('id: 13030/tst43m', $noid_output[0], 'Error in 1st minted noid');
        $this->assertEquals('id: 13030/tst47h', $noid_output[1], 'Error in 2nd minted noid');
        $this->assertEquals('id: 13030/tst44k', $noid_output[2], 'Error in 3rd minted noid');
        $this->assertEquals('id: 13030/tst48t', $noid_output[3], 'Error in 4th minted noid');
        $this->assertEquals('id: 13030/tst466', $noid_output[4], 'Error in 5th minted noid');
        $this->assertEquals('id: 13030/tst44x', $noid_output[5], 'Error in 6th minted noid');
        $this->assertEquals('id: 13030/tst42c', $noid_output[6], 'Error in 7th minted noid');
        $this->assertEquals('id: 13030/tst49s', $noid_output[7], 'Error in 8th minted noid');
        $this->assertEquals('id: 13030/tst48f', $noid_output[8], 'Error in 9th minted noid');
        $this->assertEquals('id: 13030/tst475', $noid_output[9], 'Error in 10th minted noid');
        $this->assertEquals('id: 13030/tst45v', $noid_output[10], 'Error in 11th minted noid');
        $this->assertEquals('id: 13030/tst439', $noid_output[11], 'Error in 12th minted noid');
        $this->assertEquals('id: 13030/tst40q', $noid_output[12], 'Error in 13th minted noid');
        $this->assertEquals('id: 13030/tst49f', $noid_output[13], 'Error in 14th minted noid');
        $this->assertEquals('id: 13030/tst484', $noid_output[14], 'Error in 15th minted noid');
        $this->assertEquals('id: 13030/tst46t', $noid_output[15], 'Error in 16th minted noid');
        $this->assertEquals('id: 13030/tst45h', $noid_output[16], 'Error in 17th minted noid');
        $this->assertEquals('id: 13030/tst447', $noid_output[17], 'Error in 18th minted noid');
        $this->assertEquals('id: 13030/tst42z', $noid_output[18], 'Error in 19th minted noid');
        $this->assertEquals('id: 13030/tst41n', $noid_output[19], 'Error in 20th minted noid');
    }
}
