<?php
/**
 * @author Michael A. Russell
 * @author Daniel Berthereau (conversion to Php)
 * @package Noid
 */

require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'NoidTestCase.php';

/**
 * Tests for Noid (Bind).
 */
class NoidBindTest extends NoidTestCase
{
    /**
     * Bind tests -- short
     */
    public function testBind()
    {
        $erc = $this->_short('.sdd');
        $regex = '/Size:\s*100\n/';
        $this->assertNotEmpty(preg_match($regex, $erc));
        # echo '2-digit sequential';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $id = Noid::mint($noid, $contact, '');
        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('01', $id);
        # echo 'sequential mint verify';

        $result = Noid::bind($noid, $contact, 1, 'set', $id, 'myelem', 'myvalue');
        $this->assertNotEmpty(preg_match('/Status:  ok, 7/', $result));
        # echo 'simple bind';

        $result = Noid::fetch($noid, 1, $id, 'myelem');
        $this->assertNotEmpty(preg_match('/myelem: myvalue/', $result));
        # echo 'simple fetch';

        $result = Noid::fetch($noid, 0, $id, 'myelem');
        $this->assertNotEmpty(preg_match('/^myvalue$/', $result));
        # echo 'simple non-verbose (get) fetch';

        Noid::dbclose($noid);
    }

    /**
     * Queue/hold tests -- short
     */
    public function testQueueHold()
    {
        $erc = $this->_short('.sdd');
        $regex = '/Size:\s*100\n/';
        $this->assertNotEmpty(preg_match($regex, $erc));
        # echo '2-digit sequential';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('00', $id);
        # echo 'mint first';

        $result = Noid::hold($noid, $contact, 'set', '01');
        $this->assertEquals(1, $result);
        # echo 'hold next';

        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('02', $id);
        # echo 'mint next skips id held';

        # Shouldn't have to release hold to queue it
        $result = Noid::queue($noid, $contact, 'now', $id);
        $regex = "/id: " . preg_quote($id, '/') . '/';
        $this->assertNotEmpty(preg_match($regex, $result[0]));
        # echo 'queue previously held';

        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('02', $id);
        # echo 'mint next gets from queue';

        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('03', $id);
        # echo 'mint next back to normal';

        Noid::dbclose($noid);
    }

    # XXX
    # To do: set up a "long" minter and test the various things that
    # it should reject, eg, queue a minted Id without first doing a
    # "hold release Id"

    /**
     * Validate tests -- short
     */
    public function testValidate()
    {
        $erc = $this->_short('fk.redek');
        $regex = '/Size:\s*8410\n/';
        $this->assertNotEmpty(preg_match($regex, $erc));
        # echo '4-digit random';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('fk491f', $id);
        # echo 'mint first';

        $result = Noid::validate($noid, '-', 'fk491f');
        $regex = '/error: /';
        $this->assertEquals(0, preg_match($regex, $result[0]));
        # echo 'validate just minted';

        $result = Noid::validate($noid, '-', 'fk492f');
        $regex = '/iderr: /';
        $this->assertEquals(1, preg_match($regex, $result[0]));
        # echo 'detect one digit off';

        $result = Noid::validate($noid, '-', 'fk419f');
        $regex = '/iderr: /';
        $this->assertEquals(1, preg_match($regex, $result[0]));
        # echo 'detect transposition';

        Noid::dbclose($noid);
    }

    /**
     * Validate tests for unlimited sequences -- short
     */
    public function testValidateUnlimited()
    {
        $erc = $this->_short('fk.zde');
        $regex = '/Size:\s*unlimited\n/';
        $this->assertNotEmpty(preg_match($regex, $erc));
        # echo '4-digit random';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $id = Noid::mint($noid, $contact, '');
        $this->assertEquals('fk00', $id);
        # echo 'mint first';

        $result = Noid::validate($noid, '-', 'fk9w');
        $regex = '/error: /';
        $this->assertEquals(0, preg_match($regex, $result[0]));
        # echo 'validate just minted';

        $result = Noid::validate($noid, '-', 'fkw9');
        $regex = '/iderr: /';
        $this->assertEquals(1, preg_match($regex, $result[0]));
        # echo 'validate just minted';

        $result = Noid::validate($noid, '-', 'fk9w5');
        $regex = '/iderr: /';
        $this->assertEquals(0, preg_match($regex, $result[0]));
        # echo 'detect one digit off';

        $result = Noid::validate($noid, '-', 'fk9wh');
        $regex = '/iderr: /';
        $this->assertEquals(1, preg_match($regex, $result[0]));
        # echo 'detect transposition';

        Noid::dbclose($noid);
    }

    /**
     * Validate tests for unlimited sequences -- short
     */
    public function testGetAlphabets()
    {
        $tests = array(
            'fk.zdep' => false,
            'fk.zde' => true,
            'fk.zdeedk' => 'e',
            'fk.rdeik' => 'e',
            'fa.rdeik' => 'v',
            'fk.slwk' => 'w',
            'fk.rdewk' => 'w',
            'fk.zixxik' => 'v',
            'fk.zeixEwk' => 'w',
            'fk.zlwk' => 'w',
            'fk.zdcexviEk' => 'c',
            'fk.rllllk' => 'l',
        );

        foreach ($tests as $template => $repertoire) {
            $alphabet = Noid::get_alphabet($template);
            $this->assertEquals($repertoire, $alphabet,
                sprintf('Thte template "%s" should have the character repertoire "%s", not "%s".',
                    $template, $repertoire, $alphabet));
        }
    }

    /**
     * Validate tests for various unlimited alphabets -- short
     */
    public function testValidateUnlimitedAlphabets()
    {
        $tests = array(
            'fk.zdek' => 'fk00m',
            'fa.zdewk' => 'fa000z',
            'fa.zxik' => 'fa00z',
            'f5.zeixwk' => 'f50000p',
        );

        foreach ($tests as $template => $first) {
            $erc = $this->_short($template);
            $regex = '/Size:\s*unlimited\n/';
            $this->assertNotEmpty(preg_match($regex, $erc),
                sprintf('Template "%s" is not unlimited.', $template));
            # echo '4-digit random';

            $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
            $contact = 'Fester Bestertester';

            $id = Noid::mint($noid, $contact, '');
            $this->assertEquals($first, $id, sprintf('First is not "%s" for template "%s".', $first, $template));
            # echo 'mint first';

            Noid::dbclose($noid);
        }
    }
}
