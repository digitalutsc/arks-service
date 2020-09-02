<?php
/**
 * @author Michael A. Russell
 * @author Daniel Berthereau (conversion to Php)
 * @package Noid
 */

require_once dirname(__DIR__) . DIRECTORY_SEPARATOR . 'NoidTestCase.php';

/**
 * Tests for Noid (DBCreate).
 *
 * Note on Perl script.
 * Before `make install' is performed this script should be runnable with
 * `make test'. After `make install' it should work as `perl dbcreate.t'
 */
class NoidDbCreateTest extends NoidTestCase
{
    /**
     * Size tests
     */
    public function testSize()
    {
        $result = $this->_short('.sd');
        $regex = '/Size:\s*10\n/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo 'single digit sequential template';

        $result = $this->_short('.sdd');
        $regex = '/Size:\s*100\n/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo '2-digit sequential template';

        $result = $this->_short('.zded');
        $regex = '/Size:\s*unlimited\n/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo '3-digit unbounded sequential';

        $result = $this->_short('fr.reedde');
        $regex = '/Size:\s*2438900\n/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo '6-digit random template';
    }

    /**
     * Some template error tests
     */
    public function testTemplateError()
    {
        $result = $this->_short('ab.rddd');
        $regex = '/Size:\s*1000\n/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo 'prefix vowels ok in general';

        $result = $this->_short('ab.rdXdk', 'stdout');
        $regex = '/parse_template: a mask may contain only the letters/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo 'bad mask char';

        $result = $this->_short('ab.rdddk', 'stdout');
        $regex = '/' . preg_quote('a mask of type "[de]+" may contain only characters from', '/') . '/';
        $this->assertNotEmpty(preg_match($regex, $result));
        # echo 'prefix vowels not ok with check char';
    }

    /**
     * Set up a generator that we will test
     */
    public function testGenerator()
    {
        $erc = $this->_short('8r9.sdd');
        $regex = '/Size:\s*100\n/';
        $this->assertNotEmpty(preg_match($regex, $erc));
        # echo '2-digit sequential';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $n = 1;
        while ($n--) {
            $id = Noid::mint($noid, $contact, '');
        };
        $this->assertEquals('8r900', $id);
        # echo 'sequential mint test first';

        $n = 99;
        while ($n--) {
            $id = Noid::mint($noid, $contact, '');
        };
        $this->assertEquals('8r999', $id);
        # echo 'sequential mint test last';

        $n = 1;
        while ($n--) {
            $id = Noid::mint($noid, $contact, '');
        };
        $this->assertEquals('8r900', $id);
        # echo 'sequential mint test wrap to first';

        Noid::dbclose($noid);
    }

    /**
     * Test a user note.
     */
    public function testNote()
    {
        $erc = $this->_short('8r9.sdd');
        $regex = '/Size:\s*100\n/';
        $this->assertNotEmpty(preg_match($regex, $erc));
        # echo '2-digit sequential';

        $noid = Noid::dbopen($this->noid_dir . 'noid.bdb', 0);
        $contact = 'Fester Bestertester';

        $result = Noid::note($noid, $contact, 'keynote', 'Value of the note');
        $this->assertNotEmpty($result);

        $result = Noid::note($noid, $contact, 'keynote', 'Replacement value');
        $this->assertNotEmpty($result);

        $value = Noid::get_note($noid, 'keynote');
        $this->assertEquals('Replacement value', $value);

        $value = Noid::get_note($noid, 'otherkey');
        $this->assertEmpty($value);

        Noid::dbclose($noid);
    }
}
