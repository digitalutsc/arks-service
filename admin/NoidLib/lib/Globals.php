<?php
/**
 * Created by PhpStorm.
 * User: Hawk Johns
 * Date: 12/25/2018
 * Time: 05:52
 */

namespace Noid\Lib;

/**
 * Global variables container - GloVal
 * The word "Global" is a keyword in PHP.
 * So we cannot use it, rather could use "GloVal" instead.
 * "GloVal" stands Global Values and is rhyming with "Global".
 */
class Globals{
	const VERSION = '1.1.1-0.424-php';

	const NOLIMIT = -1;
	const SEQNUM_MIN = 1;
	const SEQNUM_MAX = 1000000;

	/**
	 * The database must hold nearly arbitrary user-level identifiers
	 * alongside various admin variables.  In order not to conflict, we
	 * require all admin variables to start with ":/", eg, ":/oacounter".
	 * We use "{_RR}/" frequently as our "reserved root" prefix.
	 *
	 * Prefix for global top level of admin db variables
	 *
	 * @internal This is a constant unavailable from outside.
	 * @const    string _RR standing "Reserved Root".
	 */
	const _RR = ':';

	/**
	 * @const array DB_TYPES database type array - global as constant
	 */
	const DB_TYPES = [
		'bdb' => 'Noid\Lib\Storage\BerkeleyDB',
		'mysql' => 'Noid\Lib\Storage\MysqlDB',
		'sqlite' => 'Noid\Lib\Storage\SqliteDB',
		'xml' => 'Noid\Lib\Storage\XmlDB',
	];

	/**
	 * @var string $db_type database type such as 'bdb', 'mysql' or 'xml'
	 */
	static public $db_type;

	/**
	 * References to opened resources and global messages.
	 *
	 * @internal In the Perl script:
	 * Global %opendbtab is a hash that maps a hashref (as key) to a database
	 * reference.  At a minimum, we need opendbtab so that we avoid passing a
	 * db reference to dbclose, which cannot do the final "untie" (see
	 * "untie gotcha" documentation) while the caller's db reference is
	 * still defined.
	 *
	 * @var array $open_tab
	 */
	static public $open_tab = array(
		// Reference to opened databases.
		'database' => array(
			'' => NULL,
		),
		'msg' => array(
			// Allow to save messages when a noid is not opened.
			'' => '',
		),
		// Reference to opened log files.
		'log' => array(
			'' => '',
		),
	);

	/**
	 * Primes:
	 *   2        3        5        7
	 *  11       13       17       19
	 *  23       29       31       37
	 *  41       43       47       53
	 *  59       61       67       71
	 *  73       79       83       89
	 *  97      101      103      107
	 * 109      113      127      131
	 * 137      139      149      151
	 * 157      163      167      173
	 * 179      181      191      193
	 * 197      199      211      223
	 * 227      229      233      239
	 * 241      251      257      263
	 * 269      271      277      281
	 * 283      293      307      311
	 * 313      317      331      337
	 * 347      349      353      359
	 * 367      373      379      383
	 * 389      397      401      409
	 * 419      421      431      433
	 * 439      443      449      457
	 * 461      463      467      479
	 * 487      491      499      503  …
	 */

	/**
	 * yyy other character subsets? eg, 0-9, a-z, and _  (37 chars, with 37 prime)
	 *     this could be mask character 'w' ?
	 * yyy there are 94 printable ASCII characters, with nearest lower prime = 89
	 *     a radix of 89 would result in a huge, compact space with check chars
	 *     mask character 'c' ?
	 */

	/**
	 * List of possible repertoires of characters.
	 *
	 * All alphabets have a prime number of characters, except "d" (digits).
	 *
	 * @var array $alphabets
	 */
	static public $alphabets = array(
		// Standard character repertoires.
		'd' => '0123456789',
		'e' => '0123456789bcdfghjkmnpqrstvwxz',
		// Proposed character repertoires.
		'i' => '0123456789x',
		'x' => '0123456789abcdef_',
		'v' => '0123456789abcdefghijklmnopqrstuvwxyz_',
		'E' => '123456789bcdfghjkmnpqrstvwxzBCDFGHJKMNPQRSTVWXZ',
		'w' => '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ#*+@_',
		// Proposed for the "c" mask, but not accepted for Ark.
		'c' => '!"#$&\'()*+,0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abcdefghijklmnopqrstuvwxyz{|}~',
		// Not proposed in the Perl script, but compatible with Ark and useful
		// because the longest with only alphanumeric characters:
		// { 0-9 a-z A-Z } - { l }     cardinality 61, mask char l
		'l' => '0123456789abcdefghijkmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
	);

	/**
	 * Helper to set the type of check characters according to the alphabets.
	 *
	 * The order is important, because the check character is the shortest
	 * alphabet with all the characters of the prefix and the mask.
	 *
	 * @var array $alphabetChecks
	 */
	static public $alphabetChecks = array(
		// For compatibility purpose with Perl script, the check character is
		// "e" for masks with "d" or "e", whatever the prefix (so vowels and "l"
		// are not allowed in the prefix when there is a check character).
		'd' => 'e',
		'i' => 'e',
		'x' => 'x',
		'e' => 'e',
		'v' => 'v',
		'E' => 'E',
		'l' => 'l',
		'w' => 'w',
		'c' => 'c',
	);

	/**
	 * Legal values of $how for the bind() function.
	 *
	 * @var array $valid_hows
	 */
	static public $valid_hows = array(
		'new', 'replace', 'set',
		'append', 'prepend', 'add', 'insert',
		'delete', 'purge', 'mint', 'peppermint',
	);

	/**
	 * Helper to check quickly the mask in various places.
	 *
	 * @var string $repertoires
	 */
	static public $repertoires = 'dixevElwc';
}
