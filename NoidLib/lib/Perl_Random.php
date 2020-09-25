<?php
/**
 * @author    Daniel Berthereau <daniel.github@berthereau.net>
 * @copyright Copyright (c) 2016 Daniel Berthereau
 * @license   CeCILL-C v1.0 http://www.cecill.info/licences/Licence_CeCILL-C_V1-en.txt
 * @version   0.1.0
 * @package   Perl_Random
 */

/**
 * Port of the Perl function rand() in order to create the same sequence of
 * pseudo-random numbers.
 *
 * This class is designed for a 64-bit platform (or above) with a true
 * underlying 64-bit code (may not work with some 64-bit Windows).
 *
 * Currently, only the output of integers (via int(rand())) is managed without
 * difference between perl 5.20 and php 5.3.15 or greater, until 32 bits, the
 * perl limit. The function "int_rand()" is specially designed for this case: it
 * gets rand() as integer without useless internal rounding.
 *
 * For float numbers, the port works fine for rand(1) or a length below 13 bits
 * (8192), but results are incorrect for length larger (the last decimal may
 * differ of 1 to 10). Between perl and php, the main difficulty is to round the
 * float value. Furthermore, Perl uses 15 digits and Php 14 digits to represent
 * a float. A special method is provided to get the rand() float value with 15
 * digits: "string_rand()". Nevertheless, this part of the tool should be
 * corrected.
 *
 * This is a singleton so that the same sequence is available anywhere. Hence,
 * it should be initialized when needed:
 *     $perlRandom = Perl_Random::init();
 * Then, for example:
 *     $perlRandom->srand(1234567890);
 *     $random = $perlRandom->int_rand(293);
 *
 * Of course, the performance is bad because this is not a native function, but
 * this is not the main aim of this tool.
 *
 * Note:
 * On Php, rand() and mt_srand() create stable sequences since 5.3.15 and were
 * improved in php 7.1 (see @link https://secure.php.net/manual/en/migration71.incompatible.php#migration71.incompatible.fixes-to-mt_rand-algorithm).
 * On Perl, rand() creates stable sequences since 5.20.0.
 *
 * @todo     Manage float random numbers from 8193 until 32 bits (Perl limit).
 * @see      Perl_RandomTest
 *
 * @internal Require the BCMath extension (generally installed with php on main
 * distributions), because internal computations are greater than 64 bits.
 *
 * @link     http://pubs.opengroup.org/onlinepubs/007908799/xsh/drand48.html
 * @link     http://wellington.pm.org/archive/200704/randomness/
 * @link     https://rosettacode.org/wiki/Random_number_generator_%28included%29#Perl
 */

namespace Noid\Lib;

use \Exception;

class Perl_Random{
	/**
	 * The reference to the singleton instance of this class.
	 *
	 * @var Perl_Random
	 */
	private static $_instance;

	/**
	 * Store the seed as a 48-bit integer.
	 *
	 * @see self::srand48()
	 * @var integer
	 */
	private $_random_state_48 = NULL;

	/**
	 * Perl_Random constructor.
	 * @throws Exception
	 */
	private function __construct()
	{
		if(PHP_INT_SIZE < 8){
			throw new Exception('Perl_Random requires a true 64-bit platform.');
		}

		// Check if BCMath is installed.
		if(!extension_loaded('bcmath')){
			throw new Exception('Perl_Random requires the extension "BCMath".');
		}
	}

	/**
	 * This class is a singleton.
	 * @throws Exception
	 */
	static public function init()
	{
		if(is_null(self::$_instance)){
			self::$_instance = new Perl_Random();
		}
		return self::$_instance;
	}

	/**
	 * Store a seed to create 48-bit pseudo-random integers via a linear
	 * congruential generator.
	 *
	 * @param int $seed A 32-bit integer. If more than 32 bits, only
	 *                  the high-order 32 bits are kept internally.
	 *
	 * @return void
	 */
	public function srand48($seed = NULL)
	{
		// True pseudo-random initialization.
		if(is_null($seed)){
			$this->_random_state_48 = $this->_random48();
		}
		// Initialize with the specified seed.
		else{
			$seed = (int)$seed;
			// The input seed is a 32-bit integer: greater bits are discarded.
			$this->_random_state_48 = (($seed << 16) + 0x330E) & 0xFFFFFFFFFFFF;
		}
	}

	/**
	 * Alias of srand48().
	 *
	 * @uses self::srand48()
	 *
	 * @param int $seed
	 *
	 * @return void.
	 */
	public function srand($seed = NULL)
	{
		$this->srand48($seed);
	}

	/**
	 * Get a pseudo-random integer (48-bit).
	 *
	 * @uses self::srand48()
	 * @return int 48-bit pseudo-random integer.
	 */
	public function rand48()
	{
		// Initialize the random state if this is the first use.
		if(is_null($this->_random_state_48)){
			$this->srand48();
		}
		$this->_random_state_48 = (int)
		bcmod(bcadd(bcmul('25214903917', $this->_random_state_48, 0), '11', 0), '281474976710656');
		return $this->_random_state_48;
	}

	/**
	 * Get a pseudo-random float.
	 *
	 * This method doesn't cast to float as Perl (15 digits). If needed, rand(1)
	 * can be used.
	 *
	 * @uses self::rand48()
	 * @return float Pseudo-random float.
	 */
	public function drand48()
	{
		return (float)bcdiv($this->rand48(), '281474976710656', 32);
	}

	/**
	 * Get a pseudo-random float in order to emulate the perl function rand().
	 *
	 * This function has been checked until 8192 only.
	 *
	 * @uses self::_string_rand64()
	 *
	 * @param int $len Max exclusive returned value.
	 *
	 * @return float Pseudo-random float.
	 */
	public function rand($len = 1)
	{
		return (float)$this->_string_rand64($len);
	}

	/**
	 * Get a pseudo-random integer to emulate the perl function int(rand()).
	 *
	 * @uses self::_string_rand64()
	 *
	 * @param int $len Max exclusive returned value.
	 *
	 * @return int Pseudo-random integer.
	 */
	public function int_rand($len = 1)
	{
		return (int)$this->_string_rand64($len);
	}

	/**
	 * Get a pseudo-random float as a string representation with 15 digits max
	 * in order to emulate the perl function rand().
	 *
	 * @todo This function is under development and doesn't return the same
	 * string (last decimal may differ).
	 *
	 * @uses self::_string_rand64()
	 *
	 * @param int $len Max exclusive returned value.
	 *
	 * @return string Pseudo-random float as a string with 15 digits max.
	 */
	public function string_rand($len = 1)
	{
		$result = $this->_string_rand64($len);
		return $this->_significant15($result);
	}

	/**
	 * Get a pseudo-random float as string to emulate the perl function rand().
	 *
	 * @internal The Perl rand() tries libc drand48() first, then random(), then
	 * rand(). Here, the drand48() is emulated, so it is always used, like in Perl
	 * above 5.20.0 and like in standard implementations before.
	 *
	 * @uses     self::drand48()
	 *
	 * @param int $len Max exclusive returned value.
	 *
	 * @return string Pseudo-random float as a string with 64 digits.
	 */
	private function _string_rand64($len = 1)
	{
		$length = (int)$len;
		// Don't use drand48() in order to avoid a conversion to float.
		return bcdiv(bcmul($length ? : '1', $this->rand48(), 0), '281474976710656', 32);
	}

	/**
	 * Round a lloating value to 15 significant digits.
	 *
	 * The conversion to float between Perl and Php is slightly different (15 or
	 * 14 digits).
	 *
	 * @internal Mode is PHP_ROUND_HALF_UP (default).
	 *
	 * @param string $bcNumber A bc number.
	 *
	 * @return string
	 */
	private function _significant15($bcNumber)
	{
		$significant = 15;

		$point = strpos($bcNumber, '.');
		if($point === FALSE){
			return $this->_removeTrailingZeros($bcNumber);
		}

		// There is no exposant in a bc number.
		$decimal = substr($bcNumber, $point + 1);
		if(strlen($decimal) <= $significant){
			return $this->_removeTrailingZeros($bcNumber);
		}

		$integer = substr($bcNumber, 0, $point);

		// When the number is greater or equal to 1, the 15 significant digits
		// are always the first ones, minus the size of the integer part.
		if($integer !== '0'){
			$secondSignificant = $significant - strlen($integer);
			if($secondSignificant <= 0){
				return bccomp('0.' . $decimal, '0.5', 32) >= 0
					? bcadd($integer, '1', 0)
					: $integer;
			}

			$secondDecimal = '0.' . substr($decimal, $secondSignificant);
			$toRound = substr($decimal, 0, $secondSignificant);
			// Check if a round is required.
			if(bccomp($secondDecimal, '0.5', 64) < 0){
				$result = $integer . '.' . $toRound;
			}
			// Need to round.
			else{
				$toRound = bcadd($toRound, '1', 0);
				$result = strlen($toRound) > $significant
					? bcadd($integer, '1', 0) . '.' . substr($toRound, 1)
					: $integer . '.' . str_pad($toRound, $secondSignificant, '0', STR_PAD_LEFT);
			}
		}
		// Else, get the 15 significant digits with a negative exposant.
		else{
			$firstNonZero = strspn($decimal, '0');
			$toRound = bcmul('0.' . substr($decimal, $firstNonZero), str_pad('10', $significant + 1, '0'), 64);
			$secondDecimal = '0.' . substr($toRound, strpos($toRound, '.') + 1);
			if(bccomp($secondDecimal, '0.5', 32) >= 0){
				$toRound = bcadd($toRound, '1');
			}
			$toRound = substr($toRound, 0, $significant);
			$result = $integer . '.' . str_repeat('0', $firstNonZero) . $toRound;
		}

		return $this->_removeTrailingZeros($result);
	}

	/**
	 * Remove the trailing zeros.
	 *
	 * @param string $bcNumber A bc number.
	 *
	 * @return string
	 */
	private function _removeTrailingZeros($bcNumber)
	{
		if(strpos($bcNumber, '.') === FALSE){
			return $bcNumber;
		}
		$bcNumber = rtrim($bcNumber, '0');
		return strrpos($bcNumber, '.') === strlen($bcNumber) - 1
			? rtrim($bcNumber, '.')
			: $bcNumber;
	}

	/**
	 * Return a pseudo-random integer of 48 bits.
	 *
	 * This function doesn't use srand() or mt_rand() in order to avoid side
	 * effects.
	 *
	 * @return int 48-bit integer.
	 */
	private function _random48()
	{
		// The length is 48 bits, so 6 bytes.
		$length = 6;

		// Try /dev/urandom if exists.
		if(@is_readable('/dev/urandom')){
			$fh = fopen('/dev/urandom', 'r');
			$randomBytes = fread($fh, $length);
			fclose($fh);
			$hexa = '';
			for($i = 0; $i < $length; $i++){
				$byte = ord(substr($randomBytes, $i, 1));
				$hexa .= substr('0' . dechex($byte), -2);
			}
		}

		// No /dev/urandom, so use the time.
		else{
			$randomBytes = function_exists('microtime') ? sha1(microtime()) : sha1(time());
			$hexa = substr($randomBytes, 0, $length * 2);
		}

		$random = hexdec($hexa) & 0xFFFFFFFFFFFF;
		return (int)$random;
	}
}
