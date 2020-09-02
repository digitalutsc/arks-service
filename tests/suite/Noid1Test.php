<?php
/**
 * @author Michael A. Russell
 * @author Daniel Berthereau (conversion to Php)
 * @package Noid
 */

require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'NoidTestCase.php';

/**
 * Tests for Noid (1).
 *
 * ------------------------------------
 *
 * Project:	Noid
 *
 * Name:		noid1.t
 *
 * Function:	To test the noid command.
 *
 * What Is Tested:
 *		Create minter with template de, for 290 identifiers.
 *		Mint 288.
 *		Mint 1 and check that it was what was expected.
 *		Queue one of the 288 and check that it failed.
 *		Release hold on 3 of the 288.
 *		Queue those 3.
 *		Mint 3 and check that they are the ones that were queued.
 *		Mint 1 and check that it was what was expected.
 *		Mint 1 and check that it failed.
 *
 * Command line parameters:  none.
 *
 * Author:	Michael A. Russell
 *
 * Revision History:
 *		7/15/2004 - MAR - Initial writing
 *
 * ------------------------------------
 */
class Noid1Test extends NoidTestCase
{
    public function testNoid1()
    {
        # Start off by doing a dbcreate.
        # First, though, make sure that the BerkeleyDB files do not exist.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate tst1.rde long 13030 cdlib.org noidTest >/dev/null";
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

        # Mint all but the last two of 290.
        $cmd = "{$this->noid_cmd} mint 288";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Clean up each output line.
        $noid_output = explode(PHP_EOL, $output);
        foreach ($noid_output as &$no) {
            $no = trim($no);
            $no = preg_replace('/^\s*id:\s+/', '', $no);
        }
        # If the last one is the null string, delete it.
        $noid_output = array_filter($noid_output, 'strlen');
        # We expect to have 288 entries.
        $this->assertEquals(288, count($noid_output));
        # echo 'number of minted noids is 288';

        # Save number 20, number 55, and number 155.
        $save_noid[0] = $noid_output[20];
        $save_noid[1] = $noid_output[55];
        $save_noid[2] = $noid_output[155];
        unset($noid_output);

        # Mint the next to last one.
        $cmd = "{$this->noid_cmd} mint 1";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);
        # Remove leading "id: ".
        $noid = preg_replace('/^id:\s+/', '', $output);
        $this->assertNotEmpty($noid);
        # echo '"id: " precedes output of mint command for next to last noid';
        # Remove trailing white space.
        $noid = preg_replace('/\s+$/', '', $noid);
        $this->assertNotEmpty($noid);
        # echo "white space follows output of mint command for next to last noid");
        # This was the next to the last one on 7/16/2004.
        #is($noid, "13030/tst11q", "next to last noid was \"13030/tst11q\"");
        $this->assertEquals('13030/tst190', $noid);
        # echo 'next to last noid was "13030/tst190"';

        # Try to queue one of the 3.  It shouldn't let me, because the hold must
        # be released first.
        $cmd = "{$this->noid_cmd} queue now $save_noid[0] 2>&1";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Verify that it won't let me.
        $noidOutput0 = trim($output);
        $noidOutput0 = preg_match('/^error: a hold has been set for .* and must be released before the identifier can be queued for minting/', $noidOutput0);
        $this->assertNotEmpty($noidOutput0);
        # echo 'correctly disallowed queue before hold release';

        # Release the hold on the 3 minted noids.
        $cmd = "{$this->noid_cmd} hold release $save_noid[0] $save_noid[1] $save_noid[2] > /dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Queue those 3.
        $cmd = "{$this->noid_cmd} queue now $save_noid[0] $save_noid[1] $save_noid[2] > /dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Mint them.
        $cmd = "{$this->noid_cmd} mint 3";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Clean up each line.
        $noid_output = explode(PHP_EOL, $output);
        foreach ($noid_output as &$no) {
            $no = trim($no);
            $no = preg_replace('/^\s*id:\s+/', '', $no);
        }
        # If the last one is the null string, delete it.
        $noid_output = array_filter($noid_output, 'strlen');
        # We expect to have 3 entries.
        $this->assertEquals(3, count($noid_output));
        # echo '(minted 3 queued noids) number of minted noids is 3';

        # Check their values.
        $this->assertEquals($save_noid[0], $noid_output[0]);
        # echo 'first of three queued & reminted noids';
        $this->assertEquals($save_noid[1], $noid_output[1]);
        # echo 'second of three queued & reminted noids';
        $this->assertEquals($save_noid[2], $noid_output[2]);
        # echo 'third of three queued & reminted noids';
        unset($save_noid);
        unset($noid_output);

        # Mint the last one.
        $cmd = "{$this->noid_cmd} mint 1";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);
        # Remove leading "id: ".
        $noid = preg_replace('/^id:\s+/', '', $output);
        $this->assertNotEmpty($noid);
        # echo '"id: " precedes output of mint command for last noid';
        # Remove trailing white space.
        $noid = preg_replace('/\s+$/', '', $noid);
        $this->assertNotEmpty($noid);
        # echo "white space follows output of mint command for next to last noid");
        # This was the the last one on 7/16/2004.
        #is($noid, "13030/tst10f", "last noid was \"13030/tst10f\"");
        $this->assertEquals('13030/tst17p', $noid);
        # echo 'last noid was "13030/tst17p"';

        # Try to mint another, after they are exhausted.
        $cmd = "{$this->noid_cmd} mint 1 2>&1";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Clean up each line.
        $noidOutput0 = trim($output);
        $noidOutput0 = preg_match('/^error: identifiers exhausted/', $noidOutput0);
        $this->assertNotEmpty($noidOutput0);
        # echo 'correctly disallowed minting after identifiers were exhausted';
    }
}
