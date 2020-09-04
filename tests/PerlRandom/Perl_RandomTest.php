<?php
/**
 * @author Daniel Berthereau <daniel.github@berthereau.net>
 * @copyright Copyright (c) 2016 Daniel Berthereau
 * @license CeCILL-C v1.0 http://www.cecill.info/licences/Licence_CeCILL-C_V1-en.txt
 * @version 0.1.0
 * @package Perl_Random
 */

use PHPUnit\Framework\TestCase;

/**
 * Tests for Perl_Random.
 */
class Perl_RandomTest extends TestCase
{
    public function setUp()
    {
        // Check if perl is available.
        $cmd = 'perl -v';
        $result = shell_exec($cmd);
        if (empty($result)) {
            $this->markTestSkipped(
                'Perl is unavailable.'
            );
        }

        require_once dirname(dirname(__DIR__))
            . DIRECTORY_SEPARATOR . 'lib'
            . DIRECTORY_SEPARATOR . 'Perl_Random.php';
    }

    /**
     * Compare the perl int(rand()) and the Perl_Random->int_rand().
     */
    public function testIntRand()
    {
        $perlRandom = Perl_Random::init();
        $maxLength = pow(2, 32);
        $length = 1;
        $loop = 0;
        while ($length <= $maxLength) {
            $seed = rand(0, 4294967295);
            $perl = $this->_perlIntRandSeed($length, $seed);
            $perlRandom->srand($seed);
            $php = $perlRandom->int_rand($length);
            $this->assertEquals($perl, $php,
                sprintf('Perl rand() "%s" is not equal to Perl_Random "%s" [seed: %d, length: %d, loop: %d]',
                    $perl, $php, $seed, $length, $loop));
            ++$length;
            if ((++$loop % 1000) == 0) {
                fwrite(STDERR, sprintf('%s: Seed: %d - Length: %d - Loop: %d / 136000' . PHP_EOL, __FUNCTION__, $seed, $length, $loop));
                $length = intval($length * 1.1);
            }
        }
    }

    /**
     * Compare the perl rand(1) and the Perl_Random->rand(1).
     *
     * @internal The representation of the value may be different, but the real
     * internal value remains the same.
     */
    public function testRand1()
    {
        $this->_rand(1);
    }

    /**
     * Compare the perl rand(8192) and the Perl_Random->rand(8192).
     */
    public function testRand8192()
    {
        $this->_rand(8192);
    }

    /**
     * @internal The representation of the value may be different for the last
     * digital, but the php internal value remains the same.
     */
    protected function _rand($length)
    {
        $perlRandom = Perl_Random::init();
        $maxLength = pow(2, 32);
        $seed = 0;
        $loop = 0;
        while ($seed <= $maxLength) {
            $perl = $this->_perlRandSeed($length, $seed);
            $perlRandom->srand($seed);
            $php = $perlRandom->rand($length);
            $this->assertEquals($perl, $php,
                sprintf('Perl rand() "%s" is not equal to Perl_Random "%s" [seed: %d, length: %d, loop: %d]',
                    $perl, $php, $seed, $length, $loop));
            ++$seed;
            if ((++$loop % 1000) == 0) {
                fwrite(STDERR, sprintf('%s: Seed: %d - Length: %d - Loop: %d / 136000' . PHP_EOL, __FUNCTION__, $seed, $length, $loop));
                $seed = intval($seed * 1.1);
            }
        }
    }

    /**
     * Compare the perl rand() and the Perl_Random->rand().
     */
    public function testRand()
    {
        $perlRandom = Perl_Random::init();
        $maxLength = pow(2, 32);
        $length = 1;
        $loop = 0;
        while ($length <= $maxLength) {
            $seed = rand(0, 4294967295);
            $perl = $this->_perlRandSeed($length, $seed);
            $perlRandom->srand($seed);
            $php = $perlRandom->rand($length);
            $this->assertEquals($perl, $php,
                sprintf('Perl rand() "%s" is not equal to Perl_Random "%s" [seed: %d, length: %d, loop: %d]',
                    $perl, $php, $seed, $length, $loop));
            ++$length;
            if ((++$loop % 1000) == 0) {
                fwrite(STDERR, sprintf('%s: Seed: %d - Length: %d - Loop: %d / 136000' . PHP_EOL, __FUNCTION__, $seed, $length, $loop));
                $length = intval($length * 1.1);
            }
        }
    }

    /**
     * Compare the perl rand() and the Perl_Random->string_rand().
     */
    public function testStringRand()
    {
        $perlRandom = Perl_Random::init();
        $maxLength = pow(2, 32);
        $length = 1;
        $loop = 0;
        while ($length <= $maxLength) {
            $seed = rand(0, 4294967295);
            $perl = $this->_perlRandSeed($length, $seed);
            $perlRandom->srand($seed);
            $php = $perlRandom->string_rand($length);
            $this->assertEquals($perl, $php,
                sprintf('Perl rand() "%s" is not equal to Perl_Random "%s" [seed: %d, length: %d, loop: %d]',
                    $perl, $php, $seed, $length, $loop));
            ++$length;
            if ((++$loop % 1000) == 0) {
                fwrite(STDERR, sprintf('%s: Seed: %d - Length: %d - Loop: %d / 136000' . PHP_EOL, __FUNCTION__, $seed, $length, $loop));
                $length = intval($length * 1.1);
            }
        }
    }

    /**
     * Return a random float via the perl srand() and rand().
     *
     * This process uses perl via an external command.
     *
     * @param integer $length The max value returned, exclusive.
     * @param integer $seed
     * @return integer|null Null in case of error.
     */
    protected function _perlRandSeed($length, $seed)
    {
        $cmd = 'perl -e "srand(' . $seed . '); print rand(' . $length . ');"';
        $result = exec($cmd);
        return exec($cmd);
    }

    /**
     * Return a random integer via the perl srand() and rand().
     *
     * This process uses perl via an external command.
     *
     * @param integer $length The max value returned, exclusive.
     * @param integer $seed
     * @return integer|null Null in case of error.
     */
    protected function _perlIntRandSeed($length, $seed)
    {
        $cmd = 'perl -e "srand(' . $seed . '); print int(rand(' . $length . '));"';
        $result = exec($cmd);
        return $result;
    }
}
