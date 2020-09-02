<?php
/**
 * @author Michael A. Russell
 * @author Daniel Berthereau (conversion to Php)
 * @package Noid
 */

require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'NoidTestCase.php';

/**
 * Tests for Noid (8).
 *
 * ------------------------------------
 *
 * Project: Noid
 *
 * Name:        noid8.t
 *
 * Function:    To test the noid command.
 *
 * What Is Tested:
 *      Do a "dbcreate" using a variety of options to
 *      test that the various options in the policy can
 *      be turned on and off.
 *
 * Command line parameters:  none.
 *
 * Author:  Michael A. Russell
 *
 * Revision History:
 *      7/21/2004 - MAR - Initial writing
 *
 * ------------------------------------
 */
class Noid8Test extends NoidTestCase
{
    public function testNoid8()
    {
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate .rde long 13030 cdlib.org noidTest";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate .rddk long 13030 cdlib.org noidTest";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('GRANITE', $policy);
        # echo 'policy "GRANITE"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate .rddk long 00000 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('-RANITE', $policy);
        # echo 'policy "-RANITE"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate .sddk long 13030 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('G-ANITE', $policy);
        # echo 'policy "G-ANITE"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate tst8.rdek long 13030 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('GR-NITE', $policy);
        # echo 'policy "GR-NITE"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate .rddk medium 13030 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('GRA-ITE', $policy);
        # echo 'policy "GRA-ITE"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate r-r.rdd long 13030 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('GRAN--E', $policy);
        # echo 'policy "GRAN--E"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate .rdd long 13030 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('GRANI-E', $policy);
        # echo 'policy "GRANI-E"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate a.rdd long 13030 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('GRANI--', $policy);
        # echo 'policy "GRANI--"';

        # Do dbcreate.
        $cmd = "{$this->rm_cmd} ; " .
            "{$this->noid_cmd} dbcreate a-a.seeeeee medium 00000 cdlib.org noidTest >/dev/null";
        $this->_executeCommand($cmd, $status, $output, $errors);
        $this->assertEquals(0, $status);

        # Get and check the policy.
        $policy = $this->_get_policy($this->noid_dir . 'README');
        $this->assertNotEmpty($policy, 'unable to get policy');
        $this->assertEquals('-------', $policy);
        # echo 'policy "-------"';
    }
}
