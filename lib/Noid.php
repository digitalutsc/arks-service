<?php
/**
 * Noid - Nice opaque identifiers (Php library).
 *
 * Strict conversion of the Perl module Noid-0.424 (21 April 2006) into php.
 *
 * @author Daniel Berthereau (port to php)
 * @license CeCILL-B v1.0 http://www.cecill.info/licences/Licence_CeCILL-B_V1-en.txt
 * @link https://metacpan.org/pod/distribution/Noid/noid
 * @link http://search.cpan.org/~jak/Noid/
 * @link https://github.com/Daniel-KM/Noid4Php
 * @package Noid
 * @version 1.1.1-0.424-php
 */

/**
 * Noid - Nice opaque identifiers (Perl module)
 *
 * Author:  John A. Kunze, jak@ucop.edu, California Digital Library
 *  Originally created, UCSF/CKM, November 2002
 *
 * ---------
 * Copyright (c) 2002-2006 UC Regents
 *
 * Permission to use, copy, modify, distribute, and sell this software and
 * its documentation for any purpose is hereby granted without fee, provided
 * that (i) the above copyright notices and this permission notice appear in
 * all copies of the software and related documentation, and (ii) the names
 * of the UC Regents and the University of California are not used in any
 * advertising or publicity relating to the software without the specific,
 * prior written permission of the University of California.
 *
 * THE SOFTWARE IS PROVIDED "AS-IS" AND WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS, IMPLIED OR OTHERWISE, INCLUDING WITHOUT LIMITATION, ANY
 * WARRANTY OF MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE.
 *
 * IN NO EVENT SHALL THE UNIVERSITY OF CALIFORNIA BE LIABLE FOR ANY
 * SPECIAL, INCIDENTAL, INDIRECT OR CONSEQUENTIAL DAMAGES OF ANY KIND,
 * OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
 * WHETHER OR NOT ADVISED OF THE POSSIBILITY OF DAMAGE, AND ON ANY
 * THEORY OF LIABILITY, ARISING OUT OF OR IN CONNECTION WITH THE USE
 * OR PERFORMANCE OF THIS SOFTWARE.
 * ---------
 */

# yyy many comment blocks are very out of date -- need thorough review
# yyy make it so that http://uclibs.org/PID/foo maps to
#     ark.cdlib.org/ark:/13030/xzfoo  [ requirement from SCP meeting May 2004]
# yyy use "wantarray" function to return either number or message
#     when bailing out.
# yyy add cdlpid doc to pod ?
# yyy write about comparison with PURLs
# yyy check chars, authentication, ordinal stored in metadata
# yyy implement mod 4/8/16 distribution within large counter regions?
# yyy implement count-down counters as well as count-up?
# yyy make a shadow DB

# yyy upgrade ark-service and ERC.pm (which still use PDB.pm)

# yyy bindallow(), binddeny() ????

/**
 * Create and manage noids.
 */
class Noid
{
    const VERSION = '1.1.1-0.424-php';

    const NOLIMIT = -1;
    const SEQNUM_MIN = 1;
    const SEQNUM_MAX = 1000000;

    const DB_CREATE = 'c';
    const DB_RDONLY = 'r';
    const DB_WRITE = 'w';

    // To be able to fetch by range, unavailable via the extension "dba".
    const DB_RANGE_PARTIAL = 'partial';
    const DB_RANGE_REGEX = 'regex';

    // For compatibility purpose with the perl script.  All other constants are
    // internal. They are used only with dbopen().
    const BDB_CREATE = 1;
    const BDB_RDONLY = 1024;
    const BDB_RDWR = 0;
    // Initialization of the Berkeley database.
    const BDB_INIT_LOCK = 256;
    const BDB_INIT_TXN = 8192;
    const BDB_INIT_MPOOL = 1024;
    const BDB_INIT_CDB = 128;
    // To be able to fetch by range, unavailable via the extension "dba".
    const BDB_SET_RANGE = 27;

    /**
     * The database must hold nearly arbitrary user-level identifiers
     * alongside various admin variables.  In order not to conflict, we
     * require all admin variables to start with ":/", eg, ":/oacounter".
     * We use "$R/" frequently as our "reserved root" prefix.
     *
     * Prefix for global top level of admin db variables
     *
     * @internal This is a constant unavailable from outside.
     * @var string
     */
    static protected $_R = ':';

    /**
     * For full compatibility with the perl script, the sequence must use the
     * same pseudo-random generator. The perl script uses int(rand()), that is
     * platform dependent. So, to make the sequence of a random-based template
     * predictable, that is required for long term maintenance, the same
     * generator should be used.
     *
     * @internal This value is used only for genid(), not for samples.
     *
     * Note: If the Suhosin patch is installed in php, srand() and mt_srand()
     * are disabled for encryption security reasons, so the noid can only be
     * sequential when this generator is set.
     *
     * @todo Add this information inside the database.
     *
     * @var string Can be "Perl_Random" (default), "perl rand()"; "php rand()"
     * or "php mt_rand()" (recommended but incompatible with the default Perl
     * script).
     */
    static public $random_generator = 'Perl_Random';

    /**
     * Contains the randomizer when the id generator is "Perl_Random".
     *
     * @var Perl_Random
     */
    static private $_perlRandom;

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
     * @var array
     */
    static protected $_opendbtab = array(
        // Reference to opened databases.
        'bdb' => array(
            '' => null,
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
     * To iterate over all Noids in the database, use
     *
     * each %hash
     * return $db or null
     * $flags one of O_RDONLY, O_RDWR, O_CREAT
     */

    /**
     * Allows to test the locking mechanism.
     *
     * @var integer
     */
    static public $locktest = 0;

    /**
     * Locking can be "l" (a .lck file is created) or "d" (the db file itself is
     * locked). Default is "d" and "l" has not been checked.
     *
     * @var string
     */
    static protected $_dbaLock = 'd';

    /**
     * Legal values of $how for the bind() function.
     *
     * @var array
     */
    static protected $_valid_hows = array(
        'new', 'replace', 'set',
        'append', 'prepend', 'add', 'insert',
        'delete', 'purge', 'mint', 'peppermint',
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
     * @var array
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
     * @var array
     */
    static protected $_alphabetChecks = array(
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
     * Helper to check quickly the mask in various places.
     *
     * @var string
     */
    static protected $_repertoires = 'dixevElwc';

    public function __construct()
    {
        self::init();
    }

    static public function init()
    {
        static $init = false;

        if ($init) {
            return;
        }
        $init = true;

        // Check if dba is installed.
        if (!extension_loaded('dba')) {
            throw new Exception('Noid requires the extension "Database (dbm-style) Abstraction Layer" (dba).');
        }

        // Check if BerkeleyDB is installed.
        if (!in_array('db4', dba_handlers())) {
            throw new Exception('Noid requires BerkeleyDB: not installed.');
        }

        /**
         * Workaround to get an array of all keys matching a simple pattern.
         *
         * @internal The default extension "dba" doesn't allow to get range of keys.
         * This workaround may be slow on big bases and may need a lot of memory.
         * @todo Build a partial temporary base to avoid memory out for big bases.
         *
         * @param string $pattern The pattern of the keys to retrieve (no regex).
         * @param resource $db
         * @return array Ordered associative array of matching keys and values.
         */
        function _dba_fetch_range($pattern, $db)
        {
            if (is_null($pattern) || !is_resource($db)) {
                return;
            }
            $results = array();
            $key = dba_firstkey($db);

            // Normalize and manage empty pattern.
            $pattern = (string) $pattern;
            if (strlen($pattern) == 0) {
                while ($key !== false) {
                    $results[$key] = dba_fetch($key, $db);
                    $key = dba_nextkey($db);
                }
            }
            // Manage partial pattern.
            else {
                while ($key !== false) {
                    if (strpos($key, $pattern) === 0) {
                        $results[$key] = dba_fetch($key, $db);
                    }
                    $key = dba_nextkey($db);
                }
            }
            // @internal Ordered by default with Berkeley database.
            ksort($results);
            return $results;
        }
    }

    /**
     * Adds an error message for a database pointer/object.  If the message
     * pertains to a failed open, the pointer is null, in which case the
     * message gets saved to what essentially acts like a global (possible
     * threading conflict).
     *
     * @param string $noid
     * @param string $message
     * @return int 1
     */
    static public function addmsg($noid, $message)
    {
        self::init();

        $noid = $noid ?: ''; # act like a global in case $noid undefined
        if (isset(self::$_opendbtab['msg'][$noid])) {
            self::$_opendbtab['msg'][$noid] .= $message . PHP_EOL;
        }
        else {
            self::$_opendbtab['msg'][$noid] = $message . PHP_EOL;
        }
        return 1;
    }

    /**
     * Returns accumulated messages for a database pointer/object.  If the
     * second argument is non-zero, also reset the message to the empty string.
     *
     * @param string $noid
     * @param string $reset
     * @return string
     */
    static public function errmsg($noid = null, $reset = 0)
    {
        self::init();

        $noid = $noid ?: ''; # act like a global in case $noid undefined
        $s = isset(self::$_opendbtab['msg'][$noid])
            ? self::$_opendbtab['msg'][$noid]
            : '';
        if ($reset) {
            self::$_opendbtab['msg'][$noid] = '';
        }
        return $s;
    }

    /**
     * Logs a message.
     *
     * @param string $noid
     * @param string $message
     * @return int 1
     */
    static public function logmsg($noid, $message)
    {
        self::init();

        $noid = $noid ?: ''; # act like a global in case $noid undefined
        if (!empty(self::$_opendbtab['log'][$noid])) {
            $logfhandle = self::$_opendbtab['log'][$noid];
            fwrite($logfhandle, $message . PHP_EOL);
        }
        # yyy file was opened for append -- hopefully that means always
        #     append even if others have appended to it since our last append;
        #     possible sync problems…
        return 1;
    }

    /**
     * Store a string in a file.
     *
     * @param string $fname
     * @param string $contents
     * @return int 0 (error) or 1 (success)
     */
    static protected function _storefile($filename, $contents)
    {
        $result = file_put_contents($filename, $contents);
        return $result === false ? 0 : 1;
    }

    /**
     * Return the database handle for the specified noid.
     *
     * @param string $noid Full path to the database file.
     * @return resource|null Handle to the database resource, else null.
     */
    static protected function _getDb($noid)
    {
        if (!isset(self::$_opendbtab['bdb'][$noid])) {
            self::addmsg($noid, sprintf('error: Database "%s" is not opened.', $noid));
            return;
        }
        $db = self::$_opendbtab['bdb'][$noid];
        if (!is_resource($db)) {
            self::addmsg($noid, sprintf('error: Access to database "%s" failed .', $noid));
            return;
        }
        return $db;
    }

    /**
     * Returns the status, the output and the errors of an external command.
     *
     * @param string $cmd
     * @param int $status
     * @param string $output
     * @param string $errors
     * @return void
     */
    static protected function _executeCommand($cmd, &$status, &$output, &$errors)
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

    //=======================================================================
    // --- begin alphabetic listing (with a few exceptions) of functions ---
    //=======================================================================

    /**
     * Returns ANVL message on success, null on error.
     *
     * @param string $noid
     * @param string $contact
     * @param string $validate
     * @param string $how
     * @param string $id
     * @param string $elem
     * @param string $value
     * @return array|null
     */
     static public function bind($noid, $contact, $validate, $how, $id, $elem, $value)
     {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        # yyy to add: incr, decr for $how;  possibly other ops (* + - / **)

        # Validate identifier and element if necessary.
        #
        # yyy to do: check $elem against controlled vocab
        #     (for errors more than for security)
        # yyy should this genonly setting be so capable of contradicting
        #     the $validate arg?
        if (dba_fetch("$R/genonly", $db)
                && $validate
                && !self::validate($noid, '-', $id)
            ) {
            return;
        }
        elseif (strlen($id) == 0) {
            self::addmsg($noid, 'error: bind needs an identifier specified.');
            return;
        }
        if (empty($elem)) {
            self::addmsg($noid, sprintf('error: "bind %s" requires an element name.', $how));
            return;
        }

        # Transform and place a "hold" (if "long" term and we're not deleting)
        # on a special identifier.  Right now that means a user-entrered Id
        # of the form :idmap/Idpattern.  In this case, change it to a database
        # Id of the form "$R/idmap/$elem", and change $elem to hold Idpattern;
        # this makes lookup faster and easier.
        #
        # First save original id and element names in $oid and $oelem to
        # use for all user messages; we use whatever is in $id and $elem
        # for actual database operations.
        #
        $oid = $id;
        $oelem = $elem;
        $hold = 0;
        if (substr($id, 0, 1) === ':') {
            if (!preg_match('|^:idmap/(.+)|', $id, $matches)) {
                self::addmsg($noid, sprintf('error: %s: id cannot begin with ":" unless of the form ":idmap/Idpattern".', $oid));
                return;
            }
            $id = "$R/idmap/$oelem";
            $elem = $matches[1];
            if (dba_fetch("$R/longterm", $db)) {
                $hold = 1;
            }
        }
        # yyy transform other ids beginning with ":"?

        # Check circulation status.  Error if term is "long" and the id
        # hasn't been issued unless a hold was placed on it.
        #
        # If no circ record and no hold…
        if (empty(dba_fetch("$id\t$R/c", $db)) && !dba_exists("$id\t$R/h", $db)) {
            if (dba_fetch("$R/longterm", $db)) {
                self::addmsg($noid, sprintf('error: %s: "long" term disallows binding an unissued identifier unless a hold is first placed on it.', $oid));
                return;
            }
            self::logmsg($noid, sprintf('warning: %s: binding an unissued identifier that has no hold placed on it.', $oid));
        }
        elseif (!in_array($how, self::$_valid_hows)) {
            self::addmsg($noid, sprintf('error: bind how?  What does %s mean?', $how));
            return;
        }

        $peppermint = $how === 'peppermint';
        if ($peppermint) {
            # yyy to do
            self::addmsg($noid, 'error: bind "peppermint" not implemented.');
            return;
        }

        # YYY bind mint file Elem Value     -- put into FILE by itself
        # YYY bind mint stuff_into_big_file Elem Value -- cat into file
        if ($how === 'mint' || $how === 'peppermint') {
            if ($id !== 'new') {
                self::addmsg($noid, 'error: bind "mint" requires id to be given as "new".');
                return;
            }
            $id = $oid = self::mint($noid, $contact, $peppermint);
            if (!$id) {
                return;
            }
        }

        if ($how === 'delete' || $how === 'purge') {
            if (!empty($value)) {
                self::addmsg($noid, sprintf('error: why does "bind %s" have a supplied value (%s)?"', $how, $value));
                return;
            }
            $value = '';
        }
        elseif (empty($value)) {
            self::addmsg($noid,
                sprintf('error: "bind %s %s" requires a value to bind.', $how, $elem));
            return;
        }
        # If we get here, $value is defined and we can use with impunity.

        self::_dblock();
        if (empty(dba_fetch("$id\t$elem", $db))) {      # currently unbound
            if (in_array($how, array('replace', 'append', 'prepend', 'delete'))) {
                self::addmsg($noid, sprintf('error: for "bind %s", "%s %s" must already be bound.', $how, $oid, $oelem));
                self::_dbunlock();
                return;
            }
            dba_replace("$id\t$elem", '', $db);  # can concatenate with impunity
        }
        else {                      # currently bound
            if (in_array($how, array('new', 'mint', 'peppermint'))) {
                self::addmsg($noid, sprintf('error: for "bind %s", "%s %s" cannot already be bound.', $how, $oid, $oelem));
                self::_dbunlock();
                return;
            }
        }
        # We don't care about bound/unbound for:  set, add, insert, purge

        $oldlen = strlen(dba_fetch("$id\t$elem", $db));
        $newlen = strlen($value);
        $statmsg = sprintf('%s bytes written', $newlen);

        if ($how === 'delete' || $how === 'purge') {
            dba_delete("$id\t$elem", $db);
            $statmsg = "$oldlen bytes removed";
        }
        elseif ($how === 'add' || $how === 'append') {
            dba_replace("$id\t$elem", dba_fetch("$id\t$elem", $db) . $value, $db);
            $statmsg .= " to the end of $oldlen bytes";
        }
        elseif ($how === 'insert' || $how === 'prepend') {
            dba_replace("$id\t$elem", $value . dba_fetch("$id\t$elem", $db), $db);
            $statmsg .= " to the beginning of $oldlen bytes";
        }
        // Else $how is "replace" or "set".
        else {
            dba_replace("$id\t$elem", $value, $db);
            $statmsg .= ", replacing $oldlen bytes";
        }

        if ($hold && dba_exists("$id\t$elem", $db) && !self::hold_set($noid, $id)) {
            $hold = -1; # don't just bail out -- we need to unlock
        }

        # yyy $contact info ?  mainly for "long" term identifiers?
        self::_dbunlock();

        return
            # yyy should this $id be or not be $oid???
            # yyy should labels for Id and Element be lowercased???
            "Id:      $id" . PHP_EOL
            . "Element: $elem" . PHP_EOL
            . "Bind:    $how" . PHP_EOL
            . "Status:  " . ($hold == -1 ? self::errmsg($noid) : 'ok, ' . $statmsg) . PHP_EOL;
    }

    /**
     * Compute check character for given identifier.  If identifier ends in '+'
     * (plus), replace it with a check character computed from the preceding chars,
     * and return the modified identifier.  If not, isolate the last char and
     * compute a check character using the preceding chars; return the original
     * identifier if the computed char matches the isolated char, or null if not.
     *
     * User explanation:  check digits help systems to catch transcription
     * errors that users might not be aware of upon retrieval; while users
     * often have other knowledge with which to determine that the wrong
     * retrieval occurred, this error is sometimes not readily apparent.
     * Check digits reduce the chances of this kind of error.
     *
     * @todo ask Steve Silberstein (of III) about check digits?
     *
     * @param string $id
     * @param string $alphabet The label used for the alphabet to check against.
     * The alphabet must contain all characters of all repertoires used. The
     * argument can be the repertoire itself (more than one letter, like in
     * scope()). Default to "e" for compatibility with the Perl script, that
     * uses only the mask "[de]+".
     * @return string|null
     */
    static public function checkchar($id, $alphabet = 'e')
    {
        self::init();

        if (strlen($id) == 0) {
            return;
        }

        if (empty($alphabet)) {
            return;
        }

        // Check if the argument is the repertoire.
        if (strlen($alphabet) == 1) {
            if (!isset(self::$alphabets[$alphabet])) {
                return;
            }
            $repertoire = $alphabet;
            $alphabet = self::$alphabets[$repertoire];
        }
        // The argument is the alphabet itself.
        else {
            $repertoire = array_search($alphabet, self::$alphabets);
            if (empty($repertoire)) {
                return;
            }
        }

        $lastchar = substr($id, -1);
        $id = substr($id, 0, -1);
        $pos = 1;
        $sum = 0;
        foreach (str_split($id) as $c) {
            # if character is null, it's ordinal value is zero
            if (strlen($c) > 0) {
                $sum += $pos * strpos($alphabet, $c);
            }
            $pos++;
        }
        $checkchar = substr($alphabet, $sum % strlen($alphabet), 1);
        # print 'RADIX=' . strlen($alphabet) . ', mod=' . $sum % strlen($alphabet) . PHP_EOL;
        if ($lastchar === '+' || $lastchar === $checkchar) {
            return $id . $checkchar;
        }
        # must be request to check, but failed match
        # xxx test if check char changes on permutations
        # XXX include test of length to make sure < than 29 (R) chars long
        # yyy will this work for doi/handles?
    }

    /**
     * Returns an array of cleared ids and byte counts if $verbose is set,
     * otherwise returns an empty array.  Set $verbose when we want to report what
     * was cleared.  Admin bindings aren't touched; they must be cleared manually.
     *
     * We always check for bindings before issuing, because even a previously
     * unissued id may have been bound (unusual for many minter situations).
     *
     * Use dblock() before and dbunlock() after calling this routine.
     *
     * @param string $noid
     * @param string $id
     * @param string $verbose
     * @return array
     */
    static protected function _clear_bindings($noid, $id, $verbose)
    {
        $R = &self::$_R;

        $retvals = array();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        # yyy right now "$id\t" defines how we bind stuff to an id, but in the
        #     future that could change.  in particular we don't bind (now)
        #     anything to just "$id" (without a tab after it)
        $first = "$id\t";
        $values = _dba_fetch_range($first, $db);
        if ($values) {
            foreach ($values as $key => $value) {
                $skip = preg_match('|^' . preg_quote("$first$R/", '|') . '|', $key);
                if (!$skip && $verbose) {
                    # if $verbose (ie, fetch), include label and
                    # remember to strip "Id\t" from front of $key
                    $key = preg_match('/^[^\t]*\t(.*)/', $key, $matches) ? $matches[1] : $key;
                    $retvals[] = $key . ': ' . sprintf('clearing %d bytes', strlen($value));
                    dba_delete($key, $db);
                }
            }
        }
        return $verbose ? $retvals : array();
    }

    /**
     * Returns a short printable message on success, null on error.
     *
     * @param string $dbdir
     * @param string $contact
     * @param string $template
     * @param string $term
     * @param string $naan
     * @param string $naa
     * @param string $subnaa
     * @return string|null
     */
    static public function dbcreate($dbdir, $contact, $template = null, $term = '-', $naan = '', $naa = '', $subnaa = '')
    {
        self::init();

        $R = &self::$_R;

        $total = null;
        $noid = null;
        $dir = ($dbdir == '.' ? getcwd() : $dbdir) . DIRECTORY_SEPARATOR . 'NOID';
        $dbname = $dir . DIRECTORY_SEPARATOR . 'noid.bdb';
        # yyy try to use "die" to communicate to caller (graceful?)
        # yyy how come tie doesn't complain if it exists already?

        if (file_exists($dbname)) {
            self::addmsg(null, sprintf('error: a NOID database already exists in %s.',
                    ($dbdir === '.' ? 'the current directory' : '"' . $dbdir . '"')). PHP_EOL
                . "\t" . 'To permit creation of a new minter, rename' . PHP_EOL
                . "\t" . 'or remove the entire NOID subdirectory.');
            return;
        }

        if (!is_dir($dir) && !mkdir($dir, 0755, true)) {
            $error = error_get_last();
            self::addmsg(null, sprintf("error: couldn't create database directory %s: %s", $dir, $error['message']));
            return;
        }

        $prefix = null;
        $mask = null;
        $gen_type = null;
        $msg = null;
        $genonly = null;
        if (is_null($template)) {
            $genonly = 0;
            $template = '.zd';
        }
        else {
            $genonly = 1;           # not generated ids only
        }

        $total = self::parse_template($template, $prefix, $mask, $gen_type, $msg);
        if (!$total) {
            self::addmsg($noid, $msg);
            return;
        }
        $synonym = 'noid' . ($genonly ? '_' . $msg : 'any');

        # Type check various parameters.
        #
        if (empty($contact) || trim($contact) == '') {
            self::addmsg($noid, sprintf('error: contact (%s) must be non-empty.', $contact));
            return;
        }

        $term = $term ?: '-';
        if (!in_array($term, array('long', 'medium', 'short', '-'))) {
            self::addmsg($noid, sprintf('error: term (%s) must be either "long", "medium", "-", or "short".', $term));
            return;
        }

        $naa = (string) $naa;
        $naan = (string) $naan;
        $subnaa = (string) $subnaa;

        if ($term === 'long'
                && (!strlen(trim($naan)) || !strlen(trim($naa)) || !strlen(trim($subnaa)))
            ) {
            self::addmsg($noid, sprintf('error: longterm identifiers require an NAA Number, NAA, and SubNAA.'));
            return;
        }
        # xxx should be able to check naa and naan live against registry
        # yyy code should invite to apply for NAAN by email to ark@cdlib.org
        # yyy ARK only? why not DOI/handle?
        if ($term === 'long' && !preg_match('/\d\d\d\d\d/', $naan)) {
            self::addmsg($noid, sprintf('error: term of "long" requires a 5-digit NAAN (00000 if none), and non-empty string values for NAA and SubNAA.'));
            return;
        }

        # Create log and logbdb files from scratch and make them writable
        # before calling dbopen().
        #
        if (!self::_storefile("$dir/log", '') || !chmod("$dir/log", 0666)) {
            $error = error_get_last();
            self::addmsg(null, sprintf("Couldn't chmod log file: %s", $error['message']));
            return;
        }
        if (!self::_storefile("$dir/logbdb", '') || !chmod("$dir/logbdb", 0666)) {
            $error = error_get_last();
            self::addmsg(null, sprintf("Couldn't chmod logbdb file: %s", $error['message']));
            return;
        }

        $noid = self::dbopen($dbname, self::DB_CREATE);
        if (! $noid) {
            $error = error_get_last();
            self::addmsg(null, sprintf("can't create database file: %s", $error['message']));
            return;
        }

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        self::logmsg($noid, $template
            ? sprintf('Creating database for template "%s".', $template)
            : sprintf('Creating database for bind-only minter.'));

        # Database info
        # yyy should be using db-> ops directly (for efficiency and?)
        #     so we can use DB_DUP flag
        dba_replace("$R/naa", $naa, $db);
        dba_replace("$R/naan", $naan, $db);
        dba_replace("$R/subnaa", $subnaa ?: '', $db);

        dba_replace("$R/longterm", $term === 'long', $db);
        dba_replace("$R/wrap", $term === 'short', $db);     # yyy follow through

        dba_replace("$R/template", $template, $db);
        dba_replace("$R/prefix", $prefix, $db);
        dba_replace("$R/mask", $mask, $db);
        dba_replace("$R/firstpart", ($naan ? $naan . '/' : '') . $prefix, $db);

        $add_cc = (bool) preg_match('/k$/', $mask);    # boolean answer
        dba_replace("$R/addcheckchar", $add_cc, $db);
        if ($add_cc) {
            // The template is already checked, so no error is possible.
            $repertoire = self::get_alphabet($template);
            dba_replace("$R/checkrepertoire", $repertoire, $db);
            dba_replace("$R/checkalphabet", self::$alphabets[$repertoire], $db);
        }

        dba_replace("$R/generator_type", $gen_type, $db);
        dba_replace("$R/genonly", $genonly, $db);
        if ($gen_type == 'random') {
            dba_replace("$R/generator_random", self::$random_generator, $db);
        }

        dba_replace("$R/total", $total, $db);
        dba_replace("$R/padwidth", ($total == self::NOLIMIT ? 16 : 2) + strlen($mask), $db);
            # yyy kludge -- padwidth of 16 enough for most lvf sorting

        # Some variables:
        #   oacounter   overall counter's current value (last value minted)
        #   oatop   overall counter's greatest possible value of counter
        #   held    total with "hold" placed
        #   queued  total currently in the queue
        dba_replace("$R/oacounter", 0, $db);
        dba_replace("$R/oatop", $total, $db);
        dba_replace("$R/held", 0, $db);
        dba_replace("$R/queued", 0, $db);

        dba_replace("$R/fseqnum", self::SEQNUM_MIN, $db);  # see queue() and mint()
        dba_replace("$R/gseqnum", self::SEQNUM_MIN, $db);  # see queue()
        dba_replace("$R/gseqnum_date", 0, $db);      # see queue()

        dba_replace("$R/version", self::VERSION, $db);

        # yyy should verify that a given NAAN and NAA are registered,
        #     and should offer to register them if not… ?

        # Capture the properties of this minter.
        #
        # There are seven properties, represented by a string of seven
        # capital letters or a hyphen if the property does not apply.
        # The maximal string is GRANITE (we first had GRANT, then GARNET).
        # We don't allow 'l' as an extended digit (good for minimizing
        # visual transcriptions errors), but we don't get a chance to brag
        # about that here.
        #
        # Note that on the Mohs mineral hardness scale from 1 - 10,
        # the hardest is diamonds (which are forever), but granites
        # (combinations of feldspar and quartz) are 5.5 to 7 in hardness.
        # From http://geology.about.com/library/bl/blmohsscale.htm ; see also
        # http://www.mineraltown.com/infocoleccionar/mohs_scale_of_hardness.htm
        #
        # These are far from perfect measures of identifier durability,
        # and of course they are only from the assigner's point of view.
        # For example, an alphabetical restriction doesn't guarantee
        # opaqueness, but it indicates that semantics will be limited.
        #
        # yyy document that (I)mpressionable has to do with printing, does
        #     not apply to general URLs, but does apply to phone numbers and
        #     ISBNs and ISSNs
        # yyy document that the opaqueness test is English-centric -- these
        #     measures work to some extent in English, but not in Welsh(?)
        #     or "l33t"
        # yyy document that the properties are numerous enough to look for
        #     a compact acronym, that the choice of acronym is sort of
        #     arbitrary, so (GRANITE) was chosen since it's easy to remember
        #
        # $pre and $msk are in service of the letter "A" below.
        $pre = preg_replace('/[a-z]/i', 'e', $prefix);
        $msk = preg_replace('/k/', 'e', $mask);
        $msk = preg_replace('/^ze/', 'zeeee', $msk);       # initial 'e' can become many later on

        $properties = ($naan !== '' && $naan !== '00000' ? 'G' : '-')
            . ($gen_type === 'random' ? 'R' : '-')
            # yyy substr is supposed to cut off first char
            . ($genonly && !preg_match('/eee/', $pre . substr($msk, 1)) ? 'A' : '-')
            . ($term === 'long' ? 'N' : '-')
            . ($genonly && !preg_match('/-/', $prefix) ? 'I' : '-')
            . (dba_fetch("$R/addcheckchar", $db) ? 'T' : '-')
            // Currently, only alphabets "d", "e" and "i" are without vowels.
            . ($genonly && (preg_match('/[aeiouy]/i', $prefix) || preg_match('/[^rszdeik]/', $mask))
                ? '-' : 'E')        # Elided vowels or not
        ;
        dba_replace("$R/properties", $properties, $db);

        # Now figure out "where" element.
        #
        $host = gethostname();

        #   $child_process_id = null;
        #   if (!isset($child_process_id = open(CHILD, '-|'))) {
        #       $error = error_get_last();
        #       die "unable to start child process, $error['message'], stopped";
        #   }
        #   if ($child_process_id == 0) {
        #       # We are in the child.  Set the PATH environment variable.
        #       $ENV["PATH"] = "/bin:/usr/bin";
        #       # Run the command we want, with its STDOUT redirected
        #       # to the pipe that goes back to the parent.
        #       exec "/bin/hostname";
        #       $error = error_get_last();
        #       die "unable to execute \"/bin/hostname\", $error['message'], stopped";
        #   }
        #   else {
        #       # We are in the parent, and the CHILD file handle is
        #       # the read end of the pipe that has its write end as
        #       # STDOUT of the child.
        #       $host = <CHILD>;
        #       close(CHILD);
        #       chomp $host;
        #   }

        $cwd = $dbdir;   # by default, assuming $dbdir is absolute path
        if (substr($dbdir, 0, 1) !== '/') {
            $cwd = getcwd() . '/' . $dbdir;
        }

        # Adjust some empty values for short-term display purposes.
        #
        $naa = $naa ?: 'no Name Assigning Authority';
        $subnaa = $subnaa ?: 'no sub authority';
        $naan = $naan ?: 'no NAA Number';

        # Create a human- and machine-readable report.
        #
        $p = str_split($properties);         # split into letters
        $p = array_map(
            function ($v) { return $v == '-' ? '_ not' : '_____'; },
            $p);
        $random_sample = null;          # null on purpose
        if ($total == self::NOLIMIT) {
            $random_sample = rand(0, 9); # first sample less than 10
        }
        $sample1 = self::sample($noid, $random_sample);
        if ($total == self::NOLIMIT) {
            $random_sample = rand(0, 100000); # second sample bigger
        }
        $sample2 = self::sample($noid, $random_sample);

        $htotal = $total == self::NOLIMIT ? 'unlimited' : self::_human_num($total);
        $what = ($total == self::NOLIMIT ? 'unlimited' : $total)
            . ' ' . sprintf('%s identifiers of form %s', $gen_type, $template) . PHP_EOL
            . '       ' . 'A Noid minting and binding database has been created that will bind ' . PHP_EOL
            . '       ' . ($genonly ? '' : 'any identifier ') . 'and mint ' . ($total == self::NOLIMIT
                ? sprintf('an unbounded number of identifiers') . PHP_EOL
                    . '       '
                : sprintf('%s identifiers', $htotal) . ' ')
            . sprintf('with the template "%s".', $template) . PHP_EOL
            . '       ' . sprintf('Sample identifiers would be "%s" and "%s".', $sample1, $sample2) . PHP_EOL
            . '       ' . sprintf('Minting order is %s.', $gen_type);

        $erc =
"# Creation record for the identifier generator in NOID/noid.bdb.
#
erc:
who:       $contact
what:      $what
when:      " . self::_temper() . "
where:     $host:$cwd
Version:   Noid " . self::VERSION . "
Size:      " . ($total == self::NOLIMIT ? "unlimited" : $total) . "
Template:  " . (!$template
                 ? '(:none)'
                 : $template . "
       A suggested parent directory for this template is \"$synonym\".  Note:
       separate minters need separate directories, and templates can suggest
       short names; e.g., the template \"xz.redek\" suggests the parent directory
       \"noid_xz4\" since identifiers are \"xz\" followed by 4 characters.") . "
Policy:    (:$properties)
       This minter's durability summary is (maximum possible being \"GRANITE\")
         \"$properties\", which breaks down, property by property, as follows.
          ^^^^^^^
          |||||||_$p[6] (E)lided of vowels to avoid creating words by accident
          ||||||_$p[5] (T)ranscription safe due to a generated check character
          |||||_$p[4] (I)mpression safe from ignorable typesetter-added hyphens
          ||||_$p[3] (N)on-reassignable in life of Name Assigning Authority
          |||_$p[2] (A)lphabetic-run-limited to pairs to avoid acronyms
          ||_$p[1] (R)andomly sequenced to avoid series semantics
          |_$p[0] (G)lobally unique within a registered namespace (currently
                     tests only ARK namespaces; apply for one at ark@cdlib.org)
Authority: $naa | $subnaa
NAAN:      $naan
";
        dba_replace("$R/erc", $erc, $db);

        if (! self::_storefile("$dir/README", dba_fetch("$R/erc", $db))) {
            return;
        }
        # yyy useful for quick info on a minter from just doing 'ls NOID'??
        #          self::_storefile("$dir/T=$prefix.$mask", "foo\n");

        $report = sprintf('Created:   minter for %s', $what)
            . '  ' . sprintf('See %s/README for details.', $dir) . PHP_EOL;

        if (empty($template)) {
            self::dbclose($noid);
            return $report;
        }

        self::_init_counters($noid);
        self::dbclose($noid);
        return $report;
    }

    /**
     * Report values according to level.
     *
     * @param string $noid
     * @param string $level Possible values:
     * - "brief" (default): user vals and interesting admin vals
     * - "full": user vals and all admin vals
     * - "dump": all vals, including all identifier bindings
     * @return int 0 (error) or 1 (success)
     */
    static public function dbinfo($noid, $level = 'brief')
    {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return 0;
        }

        $values = _dba_fetch_range("$R/", $db);
        if (is_null($values)) {
            self::addmsg($noid, sprintf('No values returned by the database.'));
            return 0;
        }

        if ($level === 'dump') {
            // Re-fetch from the true first key: data are ordered alphabetically
            // and some identifier may be set before the root ":", like numbers.
            $values = _dba_fetch_range('', $db);
            foreach ($values as $key => $value) {
                print $key . ': ' . $value . PHP_EOL;
            }
            return 1;
        }

        $userValues = _dba_fetch_range("$R/$R/", $db);
        if ($userValues) {
            print 'User Assigned Values' . PHP_EOL;
            foreach ($userValues as $key => $value) {
                print '  ' . $key . ': ' . $value . PHP_EOL;
            }
            print PHP_EOL;
        }

        print 'Admin Values' . PHP_EOL;
        foreach ($values as $key => $value) {
            if ($level === 'full'
                    || !preg_match('|^' . preg_quote("$R/c", '|') . '\d|', $key)
                    && strpos($key, "$R/$R/") !== 0
                    && strpos($key, "$R/saclist") !== 0
                    && strpos($key, "$R/recycle/") !== 0
                ) {
                print '  ' . $key . ': ' . $value . PHP_EOL;
            }
        }
        print PHP_EOL;

        return 1;
    }

    /**
     * BerkeleyDB features.  For now, lock before tie(), unlock after untie().
     *
     * @todo eventually we would like to do fancy fine-grained locking with
     * @return int 1.
     */
    static protected function _dblock()
    {
        // Placeholder.
        return 1;
    }

    /**
     * BerkeleyDB features.  For now, lock before tie(), unlock after untie().
     *
     * @todo eventually we would like to do fancy fine-grained locking with
     * @return int 1.
     */
    static protected function _dbunlock()
    {
        // Placeholder.
        return 1;
    }

    /**
     * Open a database in the specified mode and returns its full name.
     *
     * @internal The Perl script returns noid: a listref.
     * @todo Berkeley specific environment flags are not supported.
     *
     * @param string $dbname
     * @param int $flags
     * Can be DB_RDONLY, DB_CREATE, or DB_WRITE (the default).
     * Support for perl script: DB_RDONLY, DB_CREAT and DB_RDWR, without bit
     * checking. Other flags are not managed.
     * @return string|null
     */
    static public function dbopen($dbname, $flags = self::DB_WRITE)
    {
        self::init();

        // For compatibility purpose between perl and php.
        switch ($flags) {
            case self::DB_WRITE:
            // Note: With switch, an empty flag matches with self::BDB_RDWR.
            case $flags === self::BDB_RDWR:
                $flags = self::DB_WRITE;
                break;
            case self::DB_RDONLY:
            case self::BDB_RDONLY:
                $flags = self::DB_RDONLY;
                break;
            case self::DB_CREATE:
            case self::BDB_CREATE:
                $flags = self::DB_CREATE;
                break;
            default:
                self::addmsg(null, sprintf('"%s" is not a regular flag', $flags));
                return;
        }

        # yyy to test: can we now open more than one noid at once?

        $env = null;
        $envhome = null;
        $envhome = preg_replace('|[^/]+$|', '', $dbname); # path ending in "NOID/"
        if (!is_dir($envhome)) {
            self::addmsg(null, sprintf('%s not a directory', $envhome));
            return;
        }

        # yyy probably these envflags are overkill right now
        $envflags = self::BDB_INIT_LOCK | self::BDB_INIT_TXN | self::BDB_INIT_MPOOL;
        #my $envflags = self::BDB_INIT_CDB | self::BDB_INIT_MPOOL;
        $envargs = array();
        if ($flags == self::DB_CREATE) {
            $envflags |= self::BDB_CREATE;
            $envargs = array(
                '-Home' => $envhome,
                '-Flags' => $envflags,
                '-Verbose' => 1,
            );
        }

        # If it exists and is writable, use log file to inscribe BDB errors.
        #
        $logfile = $envhome . 'log';
        $logfhandle = fopen($logfile, 'a');
        $log_opened = $logfhandle !== false;

        $logbdb = $envhome . 'logbdb';
        if (is_writable($logbdb)) {
            $envargs['-ErrFile'] = $logbdb;
        }
        # yyy should we complain if can't open log file?

        /*
        // TODO No management of Berkeley Environment on php.
        $env = BerkeleyDB::Env($envargs);
        if (empty($env)) {
            self::addmsg(null, sprintf('no "Env" object (%s)', $BerkeleyDB::Error));
            return;
        }
        */

        #=for deleting
        #
        #   print "OK so far\n"; exit(0);
        #   if ($flags && self::DB_CREATE) {
        #       # initialize environment files
        #       print sprintf('envhome=%s', $envhome) . PHP_EOL;
        #       $env = BerkeleyDB::Env($envargs);
        #       if (! isset($env)) {
        #           self::addmsg(null,
        #               sprintf('no "Env" object (%s)', $BerkeleyDB::Error)),
        #           return;
        #       }
        #   }
        #   else {
        #       print sprintf('flags=%s', $flags) . PHP_EOL;
        #   }
        #   print 'OK so far' . PHP_EOL; exit(0);
        #   $env = BerkeleyDB::Env($envargs);
        #   if (!isset($env)) {
        #       die sprintf('unable to get a "BerkeleyDB::Env" object (%s), stopped', $BerkeleyDB::Error);
        #   }
        #
        #=cut

        // $noid = array();      # eventual minter database handle

        /*
        // Database is locked automatically with php.
        // TODO No management of the alarm on php.

        # For now we use simple database-level file locking with a timeout.
        # Unlocking is implicit when the NOIDLOCK file handle is closed
        # either explicitly or upon process termination.
        #
        $lockfile = $envhome . "lock";
        $timeout = 5;    # max number of seconds to wait for lock
        $locktype = ($flags == self::DB_RDONLY) ? LOCK_SH : LOCK_EX;

        if (! sysopen(NOIDLOCK, $lockfile, O_RDWR | O_CREAT)) {
            $error = error_get_last();
            self::addmsg(null, sprintf('cannot open "%s": %s', $lockfile, $error['getmessage']));
            return;
        }

        eval {
            local $SIG[ALRM] = sub {
                 die(sprintf('lock timeout after %s seconds; consider removing "%s"', $timeout, $lockfile) . PHP_EOL);
            };
            alarm $timeout;     # alarm goes off in $timeout seconds
            eval {  # yyy if system has no flock, say in dbcreate profile?
                flock(NOIDLOCK, $locktype)  # blocking lock
                    or die(sprintf('cannot flock: %s'; $!));
            };
            alarm 0;        # cancel the alarm
            die $@ if $@;       # re-raise the exception
        }

        alarm 0;            # race condition protection
        if ($@) {           # re-raise the exception
            self::addmsg(null, sprintf('error: %s', $@));
            return;
        }

        $db = tie(%$noid, "BerkeleyDB::Btree", array(
                '-Filename' => "noid.bdb",    # env has path to it
                '-Flags' => $flags,
        ## yyy  '-Property' => DB_DUP,
                '-Env' => $env));
        if (empty($db)) {
            self::addmsg(null, sprintf('tie failed on %s: %s', $dbname, $BerkeleyDB::Error));
            return;
        }
        */

        $mode = $flags . self::$_dbaLock;

        $db = @dba_open($dbname, $mode, 'db4');
        if ($db === false) {
            $error = error_get_last();
            self::addmsg(null, sprintf('Failed to open database %s: %s', $dbname, $error['message']));
            return;
        }

        $noid = $dbname;

        # yyy how to set error code or return string?
        #   or die("Can't open database file: $!\n");
        # print "dbopen: returning hashref=$noid, db=$db\n";
        self::$_opendbtab['bdb'][$noid] = $db;
        self::$_opendbtab['msg'][$noid] = '';
        self::$_opendbtab['log'][$noid] = $log_opened ? $logfhandle : null;

        if (self::$locktest) {
            print sprintf('locktest: holding lock for %s seconds…', self::$locktest) . PHP_EOL;
            sleep(self::$locktest);
        }

        return $noid;
    }

    /**
     * Call with number of seconds to sleep at end of each open.
     * This exists only for the purpose of testing the locking mechanism.
     *
     * @param string $sleepvalue
     * @return int 1
     */
    static public function locktest($sleepvalue)
    {
        self::init();

        // Set global variable for locktest.
        self::$locktest = $sleepvalue;
        return 1;
    }

    /**
     * Close database.
     *
     * @param string $noid
     * @return void
     */
    static public function dbclose($noid)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        unset(self::$_opendbtab['msg'][$noid]);
        if (!empty(self::$_opendbtab['log'][$noid])) {
            fclose(self::$_opendbtab['log'][$noid]);
        }
        dba_close($db);
        /*
        // Let go of lock.
        close NOIDLOCK;
        */
    }

    /**
     * get next value and, if no error, change the 2nd and 3rd parameters and
     * return 1, else return 0.  To start at the beginning, the 2nd parameter,
     * key (key), should be set to zero by caller, who might do this:
     * $key = 0; while (each($noid, $key, $value)) { … }
     * The 3rd parameter will contain the corresponding value.
     *
     * @todo is this needed? in present form?
     * @param string $noid
     * @param string $key
     * @param string $value
     * @return int 0 (error) or 1 (success)
     */
    static protected function _eachnoid($noid, &$key, &$value)
    {
        # yyy check that $db is tied?  this is assumed for now
        # yyy need to get next non-admin key/value pair
        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }
        #was: $flag = ($key ? R_NEXT : R_FIRST);
        # fix from Jim Fullton:
        $key = empty($key) ? dba_firstkey($db) : dba_nextkey($db);
        if ($key == false) {
            $value = null;
            return 0;
        }
        $value = dba_fetch($key, $db);
        return 1;
    }

    /**
     * Fetch elements from the base.
     *
     * @todo do we need to be able to "get/fetch" with a discriminant,
     *       eg, for smart multiple resolution??
     *
     * @param string $noid
     * @param int $verbose is 1 if we want labels, 0 if we don't
     * @param string $id
     * @param array|string $elems
     * @return string List of elements separated by an end of line.
     */
    static public function fetch($noid, $verbose, $id, $elems)
    {
        self::init();

        $R = &self::$_R;

        if (strlen($id) == 0) {
            self::addmsg($noid, sprintf('error: %s requires that an identifier be specified.', $verbose ? 'fetch' : 'get'));
            return;
        }

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        if (!is_array($elems)) {
            $elems = strlen($elems) == 0 ? array() : array($elems);
        }

        $hdr = '';
        $retval = '';
        if ($verbose) {
            $hdr = "id:    $id"
                . (dba_exists("$id\t$R/h", $db) ? ' hold ': '') . PHP_EOL
                . (self::validate($noid, '-', $id) ? '' : self::errmsg($noid) . PHP_EOL)
                . 'Circ:  ' . (dba_fetch("$id\t$R/c", $db) ?: 'uncirculated') . PHP_EOL;
        }

        if (empty($elems)) {  # No elements were specified, so find them.
            $first = "$id\t";
            $values = _dba_fetch_range($first, $db);
            if ($values) {
                foreach ($values as $key => $value) {
                    $skip = preg_match('|^' . preg_quote("$first$R/", '|') . '|', $key);
                    if (!$skip) {
                        # if $verbose (ie, fetch), include label and
                        # remember to strip "Id\t" from front of $key
                        if ($verbose) {
                            $retval .= (preg_match('/^[^\t]*\t(.*)/', $key, $matches) ? $matches[1] : $key) . ': ';
                        }
                        $retval .= $value . PHP_EOL;
                    }
                }
            }

            if (empty($retval)) {
                self::addmsg($noid, $hdr
                    . "note: no elements bound under $id.");
                return;
            }
            return $hdr . $retval;
        }

        # yyy should this work for elem names with regexprs in them?
        # XXX idmap won't bind with longterm ???
        $idmapped = null;
        foreach ($elems as $elem) {
            if (dba_fetch("$id\t$elem", $db)) {
                if ($verbose) {
                    $retval .= "$elem: ";
                }
                $retval .= dba_fetch("$id\t$elem", $db) . PHP_EOL;
            }
            else {
                $idmapped = self::_id2elemval($noid, $verbose, $id, $elem);
                if ($verbose) {
                    $retval .= $idmapped
                            ? $idmapped . PHP_EOL . 'note: previous result produced by :idmap'
                            : sprintf('error: "%s %s" is not bound.', $id, $elem);
                    $retval .= PHP_EOL;
                }
                else {
                    $retval .= $idmapped . PHP_EOL;
                }
            }
        }

        return $hdr . $retval;
    }

    /**
     * Generate the actual next id to give out.  May be randomly or sequentially
     * selected.  This routine should not be called if there are ripe recyclable
     * identifiers to use.
     *
     * This routine and n2xdig comprise the real heart of the minter software.
     *
     * @param string $noid
     * @return string
     */
    static protected function _genid($noid)
    {
        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        self::_dblock();

        # Variables:
        #   oacounter   overall counter's current value (last value minted)
        #   oatop   overall counter's greatest possible value of counter
        #   saclist (sub) active counters list
        #   siclist (sub) inactive counters list
        #   c$n/value   subcounter name's ($scn) value

        $oacounter = dba_fetch("$R/oacounter", $db);

        // Internally, _genid() is used only by mint() and seeded just before
        // with the last counter, so it can be set here to simplify generation.
        $seed = $oacounter;

        # yyy what are we going to do with counters for held? queued?

        if (dba_fetch("$R/oatop", $db) != self::NOLIMIT && $oacounter >= dba_fetch("$R/oatop", $db)) {

            # Critical test of whether we're willing to re-use identifiers
            # by re-setting (wrapping) the counter to zero.  To be extra
            # careful we check both the longterm and wrap settings, even
            # though, in theory, wrap won't be set if longterm is set.
            #
            if (dba_fetch("$R/longterm", $db) || !dba_fetch("$R/wrap", $db)) {
                self::_dbunlock();
                $m = sprintf('error: identifiers exhausted (stopped at %s).', dba_fetch("$R/oatop", $db));
                self::addmsg($noid, $m);
                self::logmsg($noid, $m);
                return;
            }
            # If we get here, term is not "long".
            self::logmsg($noid, sprintf('%s: Resetting counter to zero; previously issued identifiers will be re-issued', self::_temper()));
            if (dba_fetch("$R/generator_type", $db) === 'sequential') {
                dba_replace("$R/oacounter", 0, $db);
            }
            else {
                self::_init_counters($noid);   # yyy calls dblock -- problem?
            }
            $oacounter = 0;
        }
        # If we get here, the counter may actually have just been reset.

        # Deal with the easy sequential generator case and exit early.
        #
        if (dba_fetch("$R/generator_type", $db) === 'sequential') {
            $id = self::n2xdig(dba_fetch("$R/oacounter", $db), dba_fetch("$R/mask", $db));
            dba_replace("$R/oacounter", dba_fetch("$R/oacounter", $db) + 1, $db);   # incr to reflect new total
            self::_dbunlock();
            return $id;
        }

        # If we get here, the generator must be of type "random".
        #
        $saclist = dba_fetch("$R/saclist", $db);
        $saclist = explode(' ', trim($saclist));

        $len = count($saclist);
        if ($len < 1) {
            self::_dbunlock();
            self::addmsg($noid, sprintf('error: no active counters panic, but %s identifiers left?', $oacounter));
            return;
        }

        switch (self::$random_generator) {    # pick a specific counter name
            case 'Perl_Random':
            default:
                self::$_perlRandom->srand($seed);
                $randn = self::$_perlRandom->int_rand($len);
                break;

            case 'perl rand()':
                $cmd = 'perl -e "srand(' . $seed . '); print int(rand(' . $len. '));"';
                self::_executeCommand($cmd, $status, $output, $errors);
                if ($status != 0) {
                    self::_dbunlock();
                    self::addmsg($noid, sprintf('error: perl rand() is not available: %s.', $errors));
                    return;
                }
                $randn = $output;
                break;

            case 'php mt_rand()':
                mt_srand($seed);
                $randn = mt_rand(0, $len - 1);
                break;

            case 'php rand()':
                srand($seed);
                $randn = rand(0, $len - 1);
                break;
        }

        $sctrn = $saclist[$randn];   # at random; then pull its $n
        $n = substr($sctrn, 1);  # numeric equivalent from the name
        #print "randn=$randn, sctrn=$sctrn, counter n=$n\t";
        $sctr = dba_fetch("$R/$sctrn/value", $db); # and get its value
        $sctr++;                # increment and
        dba_replace("$R/$sctrn/value", $sctr, $db);    # store new current value
        dba_replace("$R/oacounter", dba_fetch("$R/oacounter", $db) + 1, $db);       # incr overall counter - some
                            # redundancy for sanity's sake

        # deal with an exhausted subcounter
        if ($sctr >= dba_fetch("$R/$sctrn/top", $db)) {
            $c = '';
            $modsaclist ='';
            # remove from active counters list
            foreach ($saclist as $c) {     # drop $sctrn, but add it to
                if ($c === $sctrn) {     # inactive subcounters
                    continue;
                }
                $modsaclist .= $c . ' ';
            }
            dba_replace("$R/saclist", $modsaclist, $db);     # update saclist
            dba_replace("$R/siclist", dba_fetch("$R/siclist", $db) . ' ' . $sctrn, $db);      # and siclist
            #print "===> Exhausted counter $sctrn\n";
        }

        # $sctr holds counter value, $n holds ordinal of the counter itself
        $id = self::n2xdig(
                $sctr + ($n * dba_fetch("$R/percounter", $db)),
                dba_fetch("$R/mask", $db));
        self::_dbunlock();
        return $id;
    }

    /**
     * Identifier admin info is stored in three places:
     *
     *    id\t:/h    hold status: if exists = hold, else no hold
     *    id\t:/c    circulation record, if it exists, is
     *           circ_status_history_vector|when|contact(who)|oacounter
     *           where circ_status_history_vector is a string of [iqu]
     *           and oacounter is current overall counter value, FWIW;
     *           circ status goes first to make record easy to update
     *    id\t:/p    pepper
     *
     * @param string $noid
     * @param string $id
     * @return string
     * Returns a single letter circulation status, which must be one
     * of 'i', 'q', or 'u'.  Returns the empty string on error.
     */
    static protected function _get_circ_svec($noid, $id)
    {
        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $circ_rec = dba_fetch("$id\t$R/c", $db);
        if (empty($circ_rec)) {
            return '';
        }

        # Circulation status vector (string of letter codes) is the 1st
        # element, elements being separated by '|'.  We don't care about
        # the other elements for now because we can find everything we
        # need at the beginning of the string (without splitting it).
        # Let errors hit the log file rather than bothering the caller.
        #
        $circ_svec = explode('|', trim($circ_rec));
        $circ_svec = reset($circ_svec);

        if (empty($circ_svec)) {
            self::logmsg($noid, sprintf('error: id %s has no circ status vector -- circ record is %s', $id, $circ_rec));
            return '';
        }
        if (!preg_match('/^([iqu])[iqu]*$/', $circ_svec, $matches)) {
            self::logmsg($noid, sprintf('error: id %s has a circ status vector containing letters other than "i", "q", or "u" -- circ record is %s', $id, $circ_rec));
            return '';
        }
        return $matches[1];
    }

    /**
     * As a last step of issuing or queuing an identifier, adjust the circulation
     * status record.  We place a "hold" if we're both issuing an identifier and
     * the minter is for "long" term ids.  If we're issuing, we also purge any
     * element bindings that exist; this means that a queued identifier's bindings
     * will by default last until it is re-minted.
     *
     * The caller must know what they're doing because we don't check parameters
     * for errors; this routine is not externally visible anyway.  Returns the
     * input identifier on success, or null on error.
     *
     * @param string $noid
     * @param string $id
     * @param string $circ_svec
     * @param string $date
     * @param string $contact
     * @return string|null
     */
    static protected function _set_circ_rec($noid, $id, $circ_svec, $date, $contact)
    {
        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $status = 1;
        $circ_rec = "$circ_svec|$date|$contact|" . dba_fetch("$R/oacounter", $db);

        # yyy do we care what the previous circ record was?  since right now
        #     we just clobber without looking at it

        self::_dblock();

        # Check for and clear any bindings if we're issuing an identifier.
        # We ignore the return value from _clear_bindings().
        # Replace or clear admin bindings by hand, including pepper if any.
        #       yyy pepper not implemented yet
        # If issuing a longterm id, we automatically place a hold on it.
        #
        if (strpos($circ_svec, 'i') === 0) {
            self::_clear_bindings($noid, $id, 0);
            dba_delete("$id\t$R/p", $db);
            if (dba_fetch("$R/longterm", $db)) {
                $status = self::hold_set($noid, $id);
            }
        }
        dba_replace("$id\t$R/c", $circ_rec, $db);

        self::_dbunlock();

        # This next logmsg should account for the bulk of the log when
        # longterm identifiers are in effect.
        #
        if (dba_fetch("$R/longterm", $db)) {
            self::logmsg($noid, sprintf('m: %s%s', $circ_rec, $status ? '' : ' -- hold failed'));
        }

        if (empty($status)) {           # must be an error in hold_set()
            return;
        }
        return $id;
    }

    /**
     * Helper to determine the repertoire of the check character, that is the
     * shortest alphabet that contains all characters used in the template,
     * prefix included.
     *
     * For compatibility purpose with the Perl script, the templates where the
     * mask is "[de]+" are an exception and exclude the prefix, so the check
     * repertoire is "e". The prefix isn't checked here but in parse_template().
     *
     * @param $template
     * @return string|bool The label of the alphabet, or true if the template
     * doesn't require a check character, or false if error.
     */
    static public function get_alphabet($template)
    {
        # Confirm well-formedness of $mask before proceeding.
        if (!preg_match('/^([^\.]*)\.([rsz][' . self::$_repertoires . ']+k?)$/', $template, $matches)) {
            return false;
        }
        $prefix = isset($matches[1]) ? $matches[1] : '';
        $mask = isset($matches[2]) ? $matches[2] : '';
        if (substr($mask, -1) !== 'k') {
            return true;
        }

        // For compatibility purpose with Perl script, only "e" is allowed for
        // masks with "d" and "e" exclusively. The prefix is not checked here.
        if (preg_match('/^.[de]+k$/', $mask)) {
            return 'e';
        }

        // Get the shortest alphabet. There are some subtleties ("x" has no "x",
        // "E has no "0"…), so a full check is needed.
        $allCharacters = $prefix;
        foreach (str_split(substr($mask, 1, strlen($mask) - 2)) as $c) {
            $allCharacters .= self::$alphabets[self::$_alphabetChecks[$c]];
        }
        // Deduplicate characters.
        $allCharacters = count_chars($allCharacters, 3);

        // Get the smallest repertoire with all characters.
        foreach (array_unique(self::$_alphabetChecks) as $repertoire) {
            if (preg_match('/^[' . preg_quote(self::$alphabets[$repertoire], '/') . ']+$/', $allCharacters)) {
                return $repertoire;
            }
        }

        return false;
    }

    /**
     * Get the value of any named internal variable (prefaced by $R)
     * given an open database reference.
     *
     * @param string $noid
     * @param string $varname
     * @return string
     */
    static public function getnoid($noid, $varname)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $R = &self::$_R;

        return dba_fetch("$R/$varname", $db);
    }

    /**
     * Get a user note.
     *
     * @param string $noid
     * @param string $key
     * @return string The note.
     */
    static public function get_note($noid, $key)
    {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        return dba_fetch("$R/$R/$key", $db);
    }

    #=for deleting
    /**
     * Simple ancillary counter that we currently use to pair a sequence number
     * with each minted identifier.  However, these are independent actions.
     * The direction parameter is negative, zero, or positive to count down,
     * reset, or count up upon call.  Returns the current counter value.
     *
     * @internal should we make it do zero-padding on the left to a fixed width
     * determined by number of digits in the total?
     *
     * @param string $noid
     * @param string $direction
     * @return string
     */
    /*
    static protected function _count($noid, $direction)
    {
        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        if ($direction > 0) {
            return dba_replace("$R/seqnum", dba_fetch("$R/seqnum", $db) + 1, $db);
        }
        if ($direction < 0) {
            return dba_replace("$R/seqnum", dba_fetch("$R/seqnum", $db) - 1, $db);
        }
        # $direction must == 0
        return dba_replace("$R/seqnum", 0, $db);
    }
    */
    #=cut

    /**
     * A hold may be placed on an identifier to keep it from being minted/issued.
     *
     * @param string $noid
     * @param string $contact
     * @param string $on_off
     * @param array|string $ids
     * @return int 0 (error) or 1 (success)
     * Sets errmsg() in either case.
     */
    static public function hold($noid, $contact, $on_off, $ids)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $R = &self::$_R;

        if (!is_array($ids)) {
            $ids = strlen($ids) == 0 ? array() : array($ids);
        }

        # yyy what makes sense in this case?
        # if (! dba_fetch("$R/template", $db)) {
        #   self::addmsg($noid,
        #       'error: holding makes no sense in a bind-only minter.');
        #   return 0;
        # }
        if (empty($contact)) {
            self::addmsg($noid, "error: contact undefined");
            return 0;
        }
        if (empty($on_off)) {
            self::addmsg($noid, 'error: hold "set" or "release"?');
            return 0;
        }
        if (empty($ids)) {
            self::addmsg($noid, 'error: no Id(s) specified');
            return 0;
        }
        if ($on_off !== 'set' && $on_off !== 'release') {
            self::addmsg($noid, sprintf('error: unrecognized hold directive (%s)', $on_off));
            return 0;
        }

        $release = $on_off === 'release';
        # yyy what is sensible thing to do if no ids are present?
        $iderrors = array();
        if (dba_fetch("$R/genonly", $db)) {
            $iderrors = self::validate($noid, '-', $ids);
            if (array_filter($iderrors, function ($v) { return strpos($v, 'error:') !== 0; })) {
                $iderrors = array();
            }
        }
        if ($iderrors) {
            self::addmsg($noid, sprintf('error: hold operation not started -- one or more ids did not validate: %s',
                PHP_EOL . implode(PHP_EOL, $iderrors)));
            return 0;
        }

        $status = null;
        $n = 0;
        foreach ($ids as $id) {
            if ($release) {     # no hold means key doesn't exist
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid, sprintf('%s %s: releasing hold', self::_temper(), $id));
                }
                self::_dblock();
                $status = self::hold_release($noid, $id);
            }
            else {          # "hold" means key exists
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid, sprintf('%s %s: placing hold', self::_temper(), $id));
                }
                self::_dblock();
                $status = self::hold_set($noid, $id);
            }
            self::_dbunlock();
            if (! $status) {
                return 0;
            }
            $n++;           # xxx should report number

            # Incr/Decrement for each id rather than by count($ids);
            # if something goes wrong in the loop, we won't be way off.

            # XXX should we refuse to hold if "long" and issued?
            #     else we cannot use "hold" in the sense of either
            #     "reserved for future use" or "reserved, never issued"
            #
        }
        self::addmsg($noid, $n == 1 ? sprintf('ok: 1 hold placed') : sprintf('ok: %s holds placed', $n));
        return 1;
    }

    /**
     * Returns 1 on success, 0 on error.  Use dblock() before and dbunlock()
     * after calling this routine.
     *
     * @todo don't care if hold was in effect or not
     *
     * @param string $noid
     * @param string $id
     * @return int 0 (error) or 1 (success)
     */
    static public function hold_set($noid, $id)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $R = &self::$_R;

        dba_replace("$id\t$R/h", 1, $db);        # value doesn't matter
        dba_replace("$R/held", dba_fetch("$R/held", $db) + 1, $db);
        if (dba_fetch("$R/total", $db) != self::NOLIMIT   # ie, if total is non-zero
                && dba_fetch("$R/held", $db) > dba_fetch("$R/oatop", $db)
            ) {
            $m = sprintf('error: hold count (%s) exceeding total possible on id %s', dba_fetch("$R/held", $db), $id);
            self::addmsg($noid, $m);
            self::logmsg($noid, $m);
            return 0;
        }
        return 1;
    }

    /**
     * Returns 1 on success, 0 on error.  Use dblock() before and dbunlock()
     * after calling this routine.
     *
     * @todo don't care if hold was in effect or not
     *
     * @param string $noid
     * @param string $id
     * @return int 0 (error) or 1 (success)
     */
    static public function hold_release($noid, $id)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $R = &self::$_R;

        dba_delete("$id\t$R/h", $db);
        dba_replace("$R/held", dba_fetch("$R/held", $db) - 1, $db);
        if (dba_fetch("$R/held", $db) < 0) {
            $m = sprintf('error: hold count (%s) going negative on id %s', dba_fetch("$R/held", $db), $id);
            self::addmsg($noid, $m);
            self::logmsg($noid, $m);
            return 0;
        }
        return 1;
    }

    /**
     * Return printable form of an integer after adding commas to separate
     * groups of 3 digits.
     *
     * @param int $num
     * @return string
     */
    static protected function _human_num($num)
    {
        return number_format($num);
    }

    /**
     * Return $elem: $val or error string.
     *
     * @param string $noid
     * @param string $verbose
     * @param string id
     * @param string $elem
     * @return string
     */
    static protected function _id2elemval($noid, $verbose, $id, $elem)
    {
        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $first = "$R/idmap/$elem\t";
        $values = _dba_fetch_range($first, $db);
        if (is_null($values)) {
            return sprintf('error: id2elemval: access to database failed.');
        }
        if (empty($values)) {
            return '';
        }
        $key = key($values);
        if (strpos($key, $first) !== 0) {
            return '';
        }
        foreach ($values as $key => $value) {
            $pattern = preg_match('|' . preg_quote($first, '|') . '(.+)|', $key) ? $key : null;
            $newval = $id;
            if (!empty($pattern)) {
                try {
                    # yyy kludgy use of unlikely delimiters (ascii 05: Enquiry)
                    $newval = preg_replace(chr(5) . preg_quote($pattern, chr(5)) . chr(5), $value, $newval);
                } catch (Exception $e) {
                    return sprintf('error: id2elemval eval: %s', $e->getMessage());
                }
                # replaced, so return
                return ($verbose ? $elem . ': ' : '') . $newval;
            }
        }
        return '';
    }

    /**
     * Initialize counters.
     *
     * @param string $noid
     * @return void
     */
    static protected function _init_counters($noid)
    {
        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        # Variables:
        #   oacounter   overall counter's current value (last value minted)
        #   saclist (sub) active counters list
        #   siclist (sub) inactive counters list
        #   c$n/value   subcounter name's ($n) value
        #   c$n/top subcounter name's greatest possible value

        self::_dblock();

        dba_replace("$R/oacounter", 0, $db);
        $total = dba_fetch("$R/total", $db);

        $maxcounters = 293;      # prime, a little more than 29*10
        #
        # Using a prime under the theory (unverified) that it may help even
        # out distribution across the more significant digits of generated
        # identifiers.  In this way, for example, a method for mapping an
        # identifier to a pathname (eg, fk9tmb35x -> fk/9t/mb/35/x/, which
        # could be a directory holding all files related to the named
        # object), would result in a reasonably balanced filesystem tree
        # -- no subdirectories too unevenly loaded.  That's the hope anyway.

        dba_replace("$R/percounter",
            intval($total / $maxcounters + 1), # round up to be > 0
            $db);                              # max per counter, last has fewer

        $n = 0;
        $t = $total;
        $pctr = dba_fetch("$R/percounter", $db);
        $saclist = '';
        while ($t > 0) {
            dba_replace("$R/c$n/top", $t >= $pctr ? $pctr : $t, $db);
            dba_replace("$R/c$n/value", 0, $db);       # yyy or 1?
            $saclist .= "c$n ";
            $t -= $pctr;
            $n++;
        }
        dba_replace("$R/saclist", $saclist, $db);
        dba_replace("$R/siclist", '', $db);
        $n--;

        self::_dbunlock();

        # print 'saclist: ' . dba_fetch("$R/saclist", $db) . PHP_EOL
        #     . 'final top: ' . dba_fetch("$R/c$n/top", $db) . PHP_EOL
        #     . "percounter=$pctr" . PHP_EOL;
        # foreach ($saclist as $c) {
        #     print "$c, ";
        # }
        # print PHP_EOL;
    }

    /**
     * This routine produces a new identifier by taking a previously recycled
     * identifier from a queue (usually, a "used" identifier, but it might
     * have been pre-recycled) or by generating a brand new one.
     *
     * The $contact should be the initials or descriptive string to help
     * track who or what was happening at time of minting.
     *
     * Returns null on error.
     *
     * @param string $noid
     * @param string $contact
     * @param string $pepper
     * @return string|null
     */
    static public function mint($noid, $contact, $pepper = 0)
    {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        if (empty($contact)) {
            self::addmsg($noid, 'contact undefined');
            return;
        }

        $template = dba_fetch("$R/template", $db);
        if (!$template) {
            self::addmsg($noid, 'error: this minter does not generate identifiers (it does accept user-defined identifier and element bindings).');
            return;
        }

        # Check if the head of the queue is ripe.  See comments under queue()
        # for an explanation of how the queue works.
        #
        $currdate = self::_temper();        # fyi, 14 digits long
        $first = "$R/q/";

        # The following is not a proper loop.  Normally it should run once,
        # but several cycles may be needed to weed out anomalies with the id
        # at the head of the queue.  If all goes well and we found something
        # to mint from the queue, the last line in the loop exits the routine.
        # If we drop out of the loop, it's because the queue wasn't ripe.
        #
        $values = _dba_fetch_range($first, $db);
        foreach ($values as $key => $value) {
            $id = &$value;
            # The cursor, key and value are now set at the first item
            # whose key is greater than or equal to $first.  If the
            # queue was empty, there should be no items under "$R/q/".
            #
            $qdate = preg_match('|' . preg_quote("$R/q/", '|') . '(\d{14})|', $key, $matches) ? $matches[1] : null;
            if (empty($qdate)) {           # nothing in queue
                # this is our chance -- see queue() comments for why
                if (dba_fetch("$R/fseqnum", $db) > self::SEQNUM_MIN) {
                    dba_replace("$R/fseqnum", self::SEQNUM_MIN, $db);
                }
                break;               # so move on
            }
            # If the date of the earliest item to re-use hasn't arrived
            if ($currdate < $qdate) {
                break;               # move on
            }

            # If we get here, head of queue is ripe.  Remove from queue.
            # Any "next" statement from now on in this loop discards the
            # queue element.
            #
            dba_delete($key, $db);
            dba_replace("$R/queued", dba_fetch("$R/queued", $db) - 1, $db);
            if (dba_fetch("$R/queued", $db) < 0) {
                $m = sprintf('error: queued count (%s) going negative on id %s', dba_fetch("$R/queued", $db), $id);
                self::addmsg($noid, $m);
                self::logmsg($noid, $m);
                return;
            }

            # We perform a few checks first to see if we're actually
            # going to use this identifier.  First, if there's a hold,
            # remove it from the queue and check the queue again.
            #
            if (dba_exists("$id\t$R/h", $db)) {     # if there's a hold
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid,
                        sprintf('warning: id %s found in queue with a hold placed on it -- removed from queue.', $id));
                }
                continue;
            }
            # yyy this means id on "hold" can still have a 'q' circ status?

            $circ_svec = self::_get_circ_svec($noid, $id);

            if (substr($circ_svec, 0, 1) === 'i') {
                self::logmsg($noid,
                    sprintf('error: id %s appears to have been issued while still in the queue -- circ record is %s',
                        $id, dba_fetch("$id\t$R/c", $db)));
                continue;
            }
            if (substr($circ_svec, 0, 1) === 'u') {
                self::logmsg($noid, sprintf('note: id %s, marked as unqueued, is now being removed/skipped in the queue -- circ record is %s',
                    $id, dba_fetch("$id\t$R/c", $db)));
                continue;
            }
            if (preg_match('/^([^q])/', $circ_svec, $matches)) {
                self::logmsg($noid, sprintf('error: id %s found in queue has an unknown circ status (%s) -- circ record is %s',
                    $id, $matches[1], dba_fetch("$id\t$R/c", $db)));
                continue;
            }

            # Finally, if there's no circulation record, it means that
            # it was queued to get it minted earlier or later than it
            # would normally be minted.  Log if term is "long".
            #
            if ($circ_svec === '') {
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid,
                        sprintf('note: queued id %s coming out of queue on first minting (pre-cycled)', $id));
                }
            }

            # If we get here, our identifier has now passed its tests.
            # Do final identifier signoff and return.
            #
            return self::_set_circ_rec($noid, $id, 'i' . $circ_svec, $currdate, $contact);
        }

        # If we get here, we're not getting an id from the queue.
        # Instead we have to generate one.
        #

        // Prepare the id generator for Perl_Random: keep the specified one.
        if (dba_fetch("$R/generator_type", $db) == 'random') {
            self::$random_generator = dba_fetch("$R/generator_random", $db) ?: self::$random_generator;
            if (self::$random_generator == 'Perl_Random') {
                require_once 'Perl_Random.php';
                self::$_perlRandom = Perl_Random::init();
            }
        }

        $repertoire = dba_fetch("$R/addcheckchar", $db)
            ? (dba_fetch("$R/checkrepertoire", $db) ?: self::get_alphabet($template))
            : '';

        # As above, the following is not a proper loop.  Normally it should
        # run once, but several cycles may be needed to weed out anomalies
        # with the generated id (eg, there's a hold on the id, or it was
        # queued to delay issue).
        #
        while (true) {

            # Next is the important seeding of random number generator.
            # We need this so that we get the same exact series of
            # pseudo-random numbers, just in case we have to wipe out a
            # generator and start over.  That way, the n-th identifier
            # will be the same, no matter how often we have to start
            # over.  This step has no effect when $generator_type ==
            # "sequential".
            #
            srand(dba_fetch("$R/oacounter", $db));

            # The id returned in this next step may have a "+" character
            # that n2xdig() appended to it.  The checkchar() routine
            # will convert it to a check character.
            #
            $id = self::_genid($noid);
            if (is_null($id)) {
                return;
            }

            # Prepend NAAN and separator if there is a NAAN.
            #
            if (dba_fetch("$R/firstpart", $db)) {
                $id = dba_fetch("$R/firstpart", $db) . $id;
            }

            # Add check character if called for.
            #
            if (dba_fetch("$R/addcheckchar", $db)) {
                $id = self::checkchar($id, $repertoire);
            }

            # There may be a hold on an id, meaning that it is not to
            # be issued (or re-issued).
            #
            if (dba_exists("$id\t$R/h", $db)) {     # if there's a hold
                continue;               # do _genid() again
            }

            # It's usual to find no circulation record.  However,
            # there may be a circulation record if the generator term
            # is not "long" and we've wrapped (restarted) the counter,
            # of if it was queued before first minting.  If the term
            # is "long", the generated id automatically gets a hold.
            #
            $circ_svec = self::_get_circ_svec($noid, $id);

            # A little unusual is the case when something has a
            # circulation status of 'q', meaning it has been queued
            # before first issue, presumably to get it minted earlier or
            # later than it would normally be minted; if the id we just
            # generated is marked as being in the queue (clearly not at
            # the head of the queue, or we would have seen it in the
            # previous while loop), we go to generate another id.  If
            # term is "long", log that we skipped this one.
            #
            if (substr($circ_svec, 0, 1) === 'q') {
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid,
                        sprintf("note: will not issue genid()'d %s as its status is 'q', circ_rec is %s",
                            $id, dba_fetch("$id\t$R/c", $db)));
                }
                continue;
            }

            # If the circulation status is 'i' it means that the id is
            # being re-issued.  This shouldn't happen unless the counter
            # has wrapped around to the beginning.  If term is "long",
            # an id can be re-issued only if (a) its hold was released
            # and (b) it was placed in the queue (thus marked with 'q').
            #
            if (substr($circ_svec, 0, 1) === 'i'
                    && (dba_fetch("$R/longterm", $db) || !dba_fetch("$R/wrap", $db))
                ) {
                self::logmsg($noid, sprintf('error: id %s cannot be re-issued except by going through the queue, circ_rec %s',
                    $id, dba_fetch("$id\t$R/c", $db)));
                continue;
            }
            if (substr($circ_svec, 0, 1) === 'u') {
                self::logmsg($noid, sprintf('note: generating id %s, currently marked as unqueued, circ record is %s',
                    $id, dba_fetch("$id\t$R/c", $db)));
                continue;
            }
            if (preg_match('/^([^iqu])/', $circ_svec, $matches)) {
                self::logmsg($noid, sprintf('error: id %s has unknown circulation status (%s), circ_rec %s',
                    $id, $matches[1], dba_fetch("$id\\t$R/c", $db)));
                continue;
            }
            #
            # Note that it's OK/normal if $circ_svec was an empty string.

            # If we get here, our identifier has now passed its tests.
            # Do final identifier signoff and return.
            #
            return self::_set_circ_rec($noid, $id, 'i' . $circ_svec, $currdate, $contact);
        }
        # yyy
        # Note that we don't assign any value to the very important key=$id.
        # What should it be bound to?  Let's decide later.

        # yyy
        # Often we want to bind an id initially even if the object or record
        # it identifies is "in progress", as this gives way to begin tracking,
        # eg, back to the person responsible.
        #
    }

    /**
     * Record user (":/:/…") values in admin area.
     *
     * @param string $noid
     * @param string $contact
     * @param string $key
     * @param string $value
     * @return int 0 (error) or 1 (success)
     */
    static public function note($noid, $contact, $key, $value)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $R = &self::$_R;

        self::_dblock();
        $status = dba_replace("$R/$R/$key", $value, $db);
        self::_dbunlock();
        if (dba_fetch("$R/longterm", $db)) {
            self::logmsg($noid, sprintf('note: note attempt under %s by %s', $key, $contact)
                . ($status ? '' : ' -- note failed'));
        }
        if (!$status) {
            self::addmsg($noid, 'dba_replace() error unknown.');
            return 0;
        }
        return 1;
    }

    /**
     * Convert a number to an extended digit according to $mask and $generator_type
     * and return (without prefix or NAAN).  A $mask character of 'k' gets
     * converted to '+' in the returned string; post-processing will eventually
     * turn it into a computed check character.
     *
     * @param int $num
     * @param string $mask
     * @return string
     */
    static public function n2xdig($num, $mask)
    {
        self::init();

        $s = '';
        $div = null;
        $remainder = null;
        $c = null;

        # Confirm well-formedness of $mask before proceeding.
        #
        if (!preg_match('/^[rsz][' . self::$_repertoires . ']+k?$/', $mask)) {
            return;
        }

        $varwidth = 0;   # we start in fixed width part of the mask
        $rmask = array_reverse(str_split($mask));  # process each char in reverse
        while ($num != 0 || ! $varwidth) {
            if (! $varwidth) {
                $c = array_shift($rmask);  # check next mask character,
                // Avoid to str_split() an empty value.
                if (strlen($c) == 0
                        || $c === 'r'
                        || $c === 's'
                    ) { # terminate on r or s even if
                    break;   # $num is not all used up yet
                }
                if (isset(self::$alphabets[$c])) {
                    $alphabet = self::$alphabets[$c];
                    $div = strlen($alphabet);
                }
                elseif ($c === 'z') {
                    $varwidth = 1;   # re-uses last $div value
                    continue;
                }
                elseif ($c === 'k') {
                    continue;
                }
            }
            $remainder = $num % $div;
            $num = intval($num / $div);
            $s = substr($alphabet, $remainder, 1) . $s;
        }
        if (substr($mask, -1) === 'k') {       # if it ends in a check character
            $s .= '+';      # represent it with plus in new id
        }
        return $s;
    }

    /**
     * Reads template looking for errors and returns the total number of
     * identifiers that it is capable of generating, using NOLIMIT to mean
     * indefinite (unbounded).  Returns 0 on error.  Variables $prefix,
     * $mask, and $generator_type are output parameters.
     *
     * $message will always be set; 0 return with error, 1 return with synonym
     *
     * @todo templates should probably have names, eg, jk##.. could be jk4
     * or jk22, as in "./noid testdb/jk4 <command> … "
     *
     * @param string $template
     * @param string $prefix
     * @param string $mask
     * @param string $gen_type
     * @param string $message
     * @return int -1 for no limit, 0 for error, else the total.
     */
    static public function parse_template($template, &$prefix, &$mask, &$gen_type, &$message)
    {
        self::init();

        $msg = &$message;   # so we can modify $message argument easily

        $dirname = null;
        $msg = '';

        # Strip final spaces and slashes.  If there's a pathname,
        # save directory and final component separately.
        #
        $template = $template ?: '';
        $template = preg_replace('|[/\s]+$|', '', $template);       # strip final spaces or slashes
        preg_match('|^(.*/)?([^/]+)$|', $template, $matches);
        $dirname = isset($matches[1]) ? $matches[1] : '';            # make sure $dirname is defined
        $template = isset($matches[2]) ? $matches[2] : '';

        if (empty($template) || $template === '-') {
            $msg = 'parse_template: no minting possible.';
            $prefix = $mask = $gen_type = '';
            return self::NOLIMIT;
        }
        if (strpos($template, '.') === false) {
            $msg = 'parse_template: a template requires a "." to separate the prefix and the mask.'
                . " - can't generate identifiers.";
            return 0;
        }
        if (!preg_match('/^([^\.]*)\.(\w+)/', $template, $matches)) {
            $msg = "parse_template: no template mask - can't generate identifiers.";
            return 0;
        }
        $prefix = isset($matches[1]) ? $matches[1] : '';
        $mask = isset($matches[2]) ? $matches[2] : '';

        if (!preg_match('/^[rsz]/', $mask)) {
            $msg = 'parse_template: mask must begin with one of the letters' . PHP_EOL
                . '"r" (random), "s" (sequential), or "z" (sequential unlimited).';
            return 0;
        }

        if (!preg_match('/^.[^k]+k?$/', $mask)) {
            $msg = 'parse_template: exactly one check character (k) is allowed, and it may only appear at the end of a string of one or more mask characters.';
            return 0;
        }

        if (!preg_match('/^.[' . self::$_repertoires . ']+k?$/', $mask)) {
            $msg = sprintf('parse_template: a mask may contain only the letters "%s".',
                implode('", "', array_keys(self::$alphabets)));
            return 0;
        }

        # Check prefix for errors.
        #
        $has_cc = substr($mask, -1) === 'k';
        if ($has_cc) {
            $repertoire = self::get_alphabet($template);
            if (empty($repertoire)) {
                $msg = sprintf('parse_template: the check character cannot be determined.');
                return 0;
            }

            if ($repertoire !== true) {
                $alphabet = self::$alphabets[$repertoire];
                foreach (str_split($prefix) as $c) {
                    // strlen() avoid an issue with str_split() when there is no prefix.
                    if (strlen($c) && $c !== '/' && strpos($alphabet, $c) === false) {
                        // By construction, only "[de]+" templates can set an
                        // error here.
                        $msg = sprintf('parse_template: with a check character at the end, a mask of type "[de]+" may contain only characters from "%s".',
                            self::$alphabets['e']);
                        return 0;
                    }
                }
            }
        }

        # If we get here, the mask is well-formed.  Now try to come up with
        # a short synonym for the template; it should start with the
        # template's prefix and then an integer representing the number of
        # letters in identifiers generated by the template.  For example,
        # a template of "ft.rddeek" would be "ft5".
        #
        $masklen = strlen($mask) - 1;    # subtract one for [rsz]
        $msg = $prefix . $masklen;
        if (substr($mask, 0, 1) === 'z') {           # "+" indicates length can grow
            $msg .= '+';
        }

        # r means random;
        # s means sequential, limited;
        # z means sequential, no limit, and repeat most significant mask
        #   char as needed;

        $total = 1;
        foreach (str_split($mask) as $c) {
            // Avoid to str_split() an empty mask.
            if (strlen($c) == 0) {
                break;
            }
            # Mask chars it could be are: repertoires or k
            if (isset(self::$alphabets[$c])) {
                $total *= strlen(self::$alphabets[$c]);
            }
            elseif (preg_match('/[krsz]/', $c)) {
                continue;
            }
        }

        $gen_type = substr($mask, 0, 1) === 'r' ? 'random' : 'sequential';
        # $message was set to the synonym already
        return substr($mask, 0, 1) === 'z' ? self::NOLIMIT : $total;
    }

    /**
     * An identifier may be queued to be issued/minted.  Usually this is used
     * to recycle a previously issued identifier, but it may also be used to
     * delay or advance the birth of an identifier that would normally be
     * issued in its own good time.  The $when argument may be "first", "lvf",
     * "delete", or a number and a letter designating units of seconds ('s',
     * the default) or days ('d') which is a delay added to the current time;
     * a $when of "now" means use the current time with no delay.
     *
     * The queue is composed of keys of the form $R/q/$qdate/$seqnum/$paddedid,
     * with the correponding values being the actual queued identifiers.  The
     * Btree allows us to step sequentially through the queue in an ordering
     * that is a side-effect of our key structure.  Left-to-right, it is
     *
     *   :/q/        $R/q/, 4 characters wide
     *   $qdate      14 digits wide, or 14 zeroes if "first" or "lvf"
     *   $seqnum     6 digits wide, or 000000 if "lvf"
     *   $paddedid   id "value", zero-padded on left, for "lvf"
     *
     * The $seqnum is there to help ensure queue order for up to a million queue
     * requests in a second (the granularity of our clock).  [ yyy $seqnum would
     * probably be obviated if we were using DB_DUP, but there's much conversion
     * involved with that ]
     *
     * We base our $seqnum (min is 1) on one of two stored sources:  "fseqnum"
     * for queue "first" requests or "gseqnum" for queue with a real time stamp
     * ("now" or delayed).  To implement queue "first", we use an artificial
     * time stamp of all zeroes, just like for "lvf"; to keep all "lvf" sorted
     * before "first" requests, we reset fseqnum and gseqnum to 1 (not zero).
     * We reset gseqnum whenever we use it at a different time from last time
     * since sort order will be guaranteed by different values of $qdate.  We
     * don't have that guarantee with the all-zeroes time stamp and fseqnum,
     * so we put off resetting fseqnum until it is over 500,000 and the queue
     * is empty, so we do then when checking the queue in mint().
     *
     * This key structure should ensure that the queue is sorted first by date.
     * As long as fewer than a million queue requests come in within a second,
     * we can make sure queue ordering is fifo.  To support "lvf" (lowest value
     * first) recycling, the $date and $seqnum fields are all zero, so the
     * ordering is determined entirely by the numeric "value" of identifier
     * (really only makes sense for a sequential generator); to achieve the
     * numeric sorting in the lexical Btree ordering, we strip off any prefix,
     * right-justify the identifier, and zero-pad on the left to create a number
     * that is 16 digits wider than the Template mask [yyy kludge that doesn't
     * take any overflow into account, or bigints for that matter].
     *
     * Returns the array of corresponding strings (errors and "id:" strings)
     * or an empty array on error.
     *
     * @param string $noid
     * @param string $contact
     * @param string $when
     * @param array|string $ids
     * @return array
     */
    static public function queue($noid, $contact, $when, $ids)
    {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        if (!is_array($ids)) {
            $ids = strlen($ids) == 0 ? array() : array($ids);
        }

        if (!dba_fetch("$R/template", $db)) {
            self::addmsg($noid, 'error: queuing makes no sense in a bind-only minter.');
            return array();
        }
        if (empty($contact)) {
            self::addmsg($noid, 'error: contact undefined');
            return array();
        }
        if (empty($when) || trim($when) === '') {
            self::addmsg($noid, 'error: queue when? (eg, first, lvf, 30d, now)');
            return array();
        }
        # yyy what is sensible thing to do if no ids are present?
        if (empty($ids)) {
            self::addmsg($noid, 'error: must specify at least one id to queue.');
            return array();
        }
        $seqnum = 0;
        $delete = 0;
        # purposely null
        $fixsqn = null;
        $qdate = null;

        # You can express a delay in days (d) or seconds (s, default).
        #
        if (preg_match('/^(\d+)([ds]?)$/', $when, $matches)) {    # current time plus a delay
            # The number of seconds in one day is 86400.
            $multiplier = isset($matches[2]) && $matches[2] === 'd' ? 86400 : 1;
            $qdate = self::_temper(time() + $matches[1] * $multiplier);
        }
        elseif ($when === 'now') {    # a synonym for current time
            $qdate = self::_temper(time());
        }
        elseif ($when === 'first') {
            # Lowest value first (lvf) requires $qdate of all zeroes.
            # To achieve "first" semantics, we use a $qdate of all
            # zeroes (default above), which means this key will be
            # selected even earlier than a key that became ripe in the
            # queue 85 days ago but wasn't selected because no one
            # minted anything in the last 85 days.
            #
            $seqnum = dba_fetch("$R/fseqnum", $db);
            #
            # NOTE: fseqnum is reset only when queue is empty; see mint().
            # If queue never empties fseqnum will simply keep growing,
            # so we effectively truncate on the left to 6 digits with mod
            # arithmetic when we convert it to $fixsqn via sprintf().
        }
        elseif ($when=== 'delete') {
            $delete = 1;
        }
        elseif ($when !== 'lvf') {
            self::addmsg($noid, sprintf('error: unrecognized queue time: %s', $when));
            return array();
        }

        if (!empty($qdate)) {     # current time plus optional delay
            if ($qdate > dba_fetch("$R/gseqnum_date", $db)) {
                $seqnum = self::SEQNUM_MIN;
                dba_replace("$R/gseqnum", $seqnum, $db);
                dba_replace("$R/gseqnum_date", $qdate, $db);
            }
            else {
                $seqnum = dba_fetch("$R/gseqnum", $db);
            }
        }
        else {
            $qdate = '00000000000000';  # this needs to be 14 zeroes
        }

        $iderrors = array();
        if (dba_fetch("$R/genonly", $db)) {
            $iderrors = self::validate($noid, '-', $ids);
            if (array_filter($iderrors, function ($v) { return strpos($v, 'error:') !== 0; })) {
                $iderrors = array();
            }
        }
        if ($iderrors) {
            self::addmsg($noid, sprintf('error: queue operation not started -- one or more ids did not validate: %s',
                PHP_EOL . implode(PHP_EOL, $iderrors)));
            return array();
        }

        $firstpart = dba_fetch("$R/firstpart", $db);
        $padwidth = dba_fetch("$R/padwidth", $db);
        $currdate = self::_temper();
        $retvals = array();
        $idval = null;
        $paddedid = null;
        $circ_svec = null;
        foreach ($ids as $id) {
            if (dba_exists("$id\t$R/h", $db)) {     # if there's a hold
                $m = sprintf('error: a hold has been set for "%s" and must be released before the identifier can be queued for minting.', $id);
                self::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }

            # If there's no circulation record, it means that it was
            # queued to get it minted earlier or later than it would
            # normally be minted.  Log if term is "long".
            #
            $circ_svec = self::_get_circ_svec($noid, $id);

            if (substr($circ_svec, 0, 1) === 'q' && ! $delete) {
                $m = sprintf('error: id %s cannot be queued since it appears to be in the queue already -- circ record is %s',
                    $id, dba_fetch("$id\t$R/c", $db));
                self::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }
            if (substr($circ_svec, 0, 1) === 'u' && $delete) {
                $m = sprintf('error: id %s has been unqueued already -- circ record is %s',
                    $id, dba_fetch("$id\t$R/c", $db));
                self::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }
            if (substr($circ_svec, 0, 1) !== 'q' && $delete) {
                $m = sprintf('error: id %s cannot be unqueued since its circ record does not indicate its being queued, circ record is %s',
                    $id, dba_fetch("$id\t$R/c", $db));
                self::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }
            # If we get here and we're deleting, circ_svec must be 'q'.

            if ($circ_svec === '') {
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid,
                        sprintf('note: id %s being queued before first minting (to be pre-cycled)', $id));
                }
            }
            elseif (substr($circ_svec, 0, 1) === 'i') {
                if (dba_fetch("$R/longterm", $db)) {
                    self::logmsg($noid, sprintf('note: longterm id %s being queued for re-issue', $id));
                }
            }

            # yyy ignore return OK?
            self::_set_circ_rec($noid, $id,
                    ($delete ? 'u' : 'q') . $circ_svec,
                    $currdate, $contact);

            $idval = preg_replace('/^' . preg_quote("$firstpart", '/') . '/', '', $id);
            $paddedid = sprintf("%0$padwidth" . "s", $idval);
            $fixsqn = sprintf("%06d", $seqnum % self::SEQNUM_MAX);

            self::_dblock();

            dba_replace("$R/queued", dba_fetch("$R/queued", $db) + 1, $db);
            if (dba_fetch("$R/total", $db) != self::NOLIMIT   # if total is non-zero
                    && dba_fetch("$R/queued", $db) > dba_fetch("$R/oatop", $db)
                ) {

                self::_dbunlock();

                $m = sprintf('error: queue count (%s) exceeding total possible on id %s.  Queue operation aborted.',
                    dba_fetch("$R/queued", $db), $id);
                self::logmsg($noid, $m);
                $retvals[] = $m;
                break;
            }
            dba_replace("$R/q/$qdate/$fixsqn/$paddedid", $id, $db);

            self::_dbunlock();

            if (dba_fetch("$R/longterm", $db)) {
                self::logmsg($noid, sprintf('id: %s added to queue under %s',
                    dba_fetch("$R/q/$qdate/$fixsqn/$paddedid", $db), "$R/q/$qdate/$seqnum/$paddedid"));
            }
            $retvals[] = sprintf('id: %s', $id);
            if ($seqnum) {     # it's zero for "lvf" and "delete"
                $seqnum++;
            }
        }

        self::_dblock();
        if ($when === 'first') {
            dba_replace("$R/fseqnum", $seqnum, $db);
        }
        elseif ($qdate > 0) {
            dba_replace("$R/gseqnum", $seqnum, $db);
        }
        self::_dbunlock();

        return $retvals;
    }

    /**
     * Generate a sample id for testing purposes.
     *
     * @param string $noid
     * @param int $num
     * @return string
     */
    static public function sample($noid, $num = null)
    {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $upper = null;
        if (is_null($num)) {
            $upper = dba_fetch("$R/total", $db);
            if ($upper == self::NOLIMIT) {
                $upper = 100000;
            }
            $num = rand(0, $upper - 1);
        }
        $mask = dba_fetch("$R/mask", $db);
        $firstpart = dba_fetch("$R/firstpart", $db);
        $result = $firstpart . self::n2xdig($num, $mask);

        if (dba_fetch("$R/addcheckchar", $db)) {
            $template = dba_fetch("$R/template", $db);
            $repertoire = self::get_alphabet($template);
            return self::checkchar($result, $repertoire);
        }

        return $result;
    }

    /**
     * Scopes.
     *
     * @param string $noid
     * @return int 1
     */
    static public function scope($noid)
    {
        self::init();

        $R = &self::$_R;

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $template = dba_fetch("$R/template", $db);
        if (!$template) {
            print 'This minter does not generate identifiers, but it does accept user-defined identifier and element bindings.' . PHP_EOL;
        }
        $total = dba_fetch("$R/total", $db);
        $totalstr = self::_human_num($total);
        $naan = dba_fetch("$R/naan", $db) ?: '';
        if ($naan) {
            $naan .= '/';
        }

        $prefix = dba_fetch("$R/prefix", $db);
        $mask = dba_fetch("$R/mask", $db);
        $gen_type = dba_fetch("$R/generator_type", $db);

        print sprintf('Template %s will yield %s %s unique ids',
            $template, $total < 0 ? 'an unbounded number of' : $totalstr, $gen_type) . PHP_EOL;
        $tminus1 = $total < 0 ? 987654321 : $total - 1;

        # See if we need to compute a check character.
        $results = array(0 => null, 1 => null, 2 => null, $tminus1 => null);
        if (28 < $total - 1) {
            $results[28] = null;
        }
        if (29 < $total - 1) {
            $results[29] = null;
        }
        foreach ($results as $n => &$xdig) {
            $xdig = $naan . self::n2xdig($n, $mask);
            if (dba_fetch("$R/addcheckchar", $db)) {
                $xdig = self::checkchar($xdig, $prefix . '.' . $mask);
            }
        }
        unset($xdig);

        print 'in the range ' . $results[0] . ', ' . $results[1] . ', ' . $results[2];
        if (28 < $total - 1) {
            print ', …, ' . $results[28];
        }
        if (29 < $total - 1) {
            print ', ' . $results[29];
        }
        print ', … up to ' . $results[$tminus1]
            . ($total < 0 ? ' and beyond.' : '.')
            . PHP_EOL;
        if (substr($mask, 0, 1) !== 'r') {
            return 1;
        }
        print 'A sampling of random values (may already be in use): ';
        for ($i = 0; $i < 5; $i++) {
            print sample($noid) . ' ';
        }
        print PHP_EOL;
        return 1;
    }

    /**
     * Return local date/time stamp in TEMPER format.  Use supplied time (in seconds)
     * if any, or the current time.
     *
     * @param int $time
     * @return string
     */
    static protected function _temper($time = null)
    {
        return strftime('%Y%m%d%H%M%S', $time ?: time());
    }

    /**
     * Check that identifier matches a given template, where "-" means the
     * default template for this generator.  This is a complete check of all
     * characteristics _except_ whether the identifier is stored in the
     * database.
     *
     * Returns an array of strings that are messages corresponding to any ids
     * that were passed in.  Error strings # that pertain to identifiers
     * begin with "iderr: ".
     *
     * @param string $noid
     * @param string $template
     * @param array|string $ids
     * @return array
     */
    static public function validate($noid, $template, $ids)
    {
        self::init();

        $db = self::_getDb($noid);
        if (is_null($db)) {
            return;
        }

        $R = &self::$_R;

        if (!is_array($ids)) {
            $ids = strlen($ids) == 0 ? array() : array($ids);
        }

        $first = null;
        $prefix = null;
        $mask = null;
        $gen_type = null;
        $msg = null;

        $retvals = array();

        if (empty($ids)) {
            self::addmsg($noid, 'error: must specify a template and at least one identifier.');
            return array();
        }
        if (empty($template)) {
            # If $noid is null, the caller looks in self::errmsg(null).
            self::addmsg($noid, 'error: no template given to validate against.');
            return array();
        }

        $repertoire = null;

        if ($template === '-') {
            # $retvals[] = sprintf('template: %s', dba_fetch("$R/template", $db)));
            if (! dba_fetch("$R/template", $db)) {  # do blanket validation
                $nonulls = array_filter(preg_replace('/^(.)/', 'id: $1', $ids));
                if (empty($nonulls)) {
                    return array();
                }
                $retvals += $nonulls;
                return $retvals;
            }
            $prefix = dba_fetch("$R/prefix", $db);
            $mask = dba_fetch("$R/mask", $db);
            // Validate with the saved repertoire, if any.
            $repertoire = dba_fetch("$R/addcheckchar", $db)
                ? (dba_fetch("$R/checkrepertoire", $db) ?: self::get_alphabet($template))
                : '';
        }
        elseif (! self::parse_template($template, $prefix, $mask, $gen_type, $msg)) {
            self::addmsg($noid, sprintf('error: template %s bad: %s', $template, $msg));
            return array();
        }

        $m = preg_replace('/k$/', '', $mask);
        $should_have_checkchar = $m !== $mask;
        if (is_null($repertoire)) {
            $repertoire = $should_have_checkchar ? self::get_alphabet($prefix . '.' . $mask) : '';
        }

        $naan = dba_fetch("$R/naan", $db);
        foreach ($ids as $id) {
            if (is_null($id) || trim($id) == '') {
                $retvals[] = "iderr: can't validate an empty identifier";
                continue;
            }

            # Automatically reject ids starting with "$R/", unless it's an
            # "idmap", in which case automatically validate.  For an idmap,
            # the $id should be of the form $R/idmap/ElementName, with
            # element, Idpattern, and value, ReplacementPattern.
            #
            if (strpos("$R/", $id) === 0) {
                $retvals[] = preg_match('|^' . preg_quote("$R/idmap/", '|') . '.+|', $id)
                    ? sprintf('id: %s', $id)
                    : sprintf('iderr: identifiers must not start with "%s".', "$R/");
                continue;
            }

            $first = $naan;             # … if any
            if ($first) {
                $first .= '/';
            }
            $first .= $prefix;          # … if any
            $varpart = preg_replace('/^' . preg_quote($first, '/') . '/', '', $id);
            if (strlen($first) > 0 && strpos($id, $first) !== 0) {
            # yyy            ($varpart = $id) !~ s/^$prefix// and
                $retvals[] = sprintf('iderr: %s should begin with %s.', $id, $first);
                continue;
            }
            if ($should_have_checkchar && ! self::checkchar($id, $repertoire)) {
                $retvals[] = sprintf('iderr: %s has a check character error', $id);
                continue;
            }
            ## xxx fix so that a length problem is reported before (or
            # in addition to) a check char problem

            # yyy needed?
            # if (strlen($first) + strlen($mask) - 1 != strlen($id)) {
            #     $retvals[] = sprintf('error: %s has should have length %s',
            #         $id, (strlen($first) + strlen($mask) - 1));
            #     continue;
            # }

            # Maskchar-by-Idchar checking.
            #
            $maskchars = str_split($mask);
            $mode = array_shift($maskchars);       # toss 'r', 's', or 'z'
            $suppl = $mode == 'z' ? $maskchars[0] : null;
            $flagBreakContinue = false;
            foreach (str_split($varpart) as $c) {
                // Avoid to str_split() an empty varpart.
                if (strlen($c) == 0) {
                    break;
                }
                $m = array_shift($maskchars);
                if (is_null($m)) {
                    if ($mode != 'z') {
                        $retvals[] = sprintf('iderr: %s longer than specified template (%s)', $id, $template);
                        $flagBreakContinue = true;
                        break;
                    }
                    $m = $suppl;
                }
                if (isset(self::$alphabets[$m]) && strpos(self::$alphabets[$m], $c) === false) {
                    $retvals[] = sprintf('iderr: %s char "%s" conflicts with template (%s) char "%s"%s',
                        $id, $c, $template, $m, $m == 'e' ? ' (extended digit)' : ($m == 'd' ? ' (digit)' : ''));
                    $flagBreakContinue = true;
                    break;
                }       # or $m === 'k', in which case skip
            }
            if ($flagBreakContinue) {
                continue;
            }

            $m = array_shift($maskchars);
            if (!is_null($m)) {
                $retvals[] = sprintf('iderr: %s shorter than specified template (%s)', $id, $template);
                continue;
            }

            # If we get here, the identifier checks out.
            $retvals[] = sprintf('id: %s', $id);
        }
        return $retvals;
    }
}

/**
__END__

=head1 NAME

Noid - routines to mint and manage nice opaque identifiers

=head1 SYNOPSIS

 use Noid;			    # import routines into a Perl script

 $dbreport = Noid::dbcreate(	    # create minter database & printable
 		$dbdir, $contact,   # report on its properties; $contact
		$template, $term,   # is string identifying the operator
		$naan, $naa, 	    # (authentication information); the
		$subnaa );          # report is printable

 $noid = Noid::dbopen( $dbname, $flags );    # open a minter, optionally
 	$flags = 0 | DB_RDONLY;		     # in read only mode

 Noid::mint( $noid, $contact, $pepper );     # generate an identifier

 Noid::dbclose( $noid );		     # close minter when done

 Noid::checkchar( $id, $alphabet ); # if id ends in +, replace with new check
 			      # char and return full id, else return id
			      # if current check char valid, else return
			      # 'undef'
			      # The alphabet is the label of the character
			      # repertoire (or the repertoire itself) used
			      # for the check character.
			      # Default is "e" for legal extended digits.

 Noid::get_alphabet( $template ); # Return the mask of the alphabet
			# that matches all characters contained in the
			# template. For compatibility purpose, the check
			# character is "e" for masks with "d" or "e"
			# exclusively, whatever the prefix.

 Noid::validate( $noid,	      # check that ids conform to template ("-"
 		$template,    # means use minter's template); returns
		@ids );	      # array of corresponding strings, errors
			      # beginning with "iderr:"

 $n = Noid::bind( $noid, $contact,	# bind data to identifier; set
		$validate, $how,	# $validate to 0 if id. doesn't
		$id, $elem, $value );	# need to conform to a template

 Noid::note( $noid, $contact, $key, $value );	# add an internal note

 Noid::get_note( $noid, $key );  # get an internal user note

 Noid::fetch( $noid, $verbose,		# fetch bound data; set $verbose
 		$id, @elems );		# to 1 to return labels

 print Noid::dbinfo( $noid,		# get minter information; level
 		$level );		# brief (default), full, or dump
 Noid::getnoid( $noid, $varname );	# get arbitrary named internal
 					# variable

 Noid::hold( $noid, $contact,		# place or release hold; return
 		$on_off, @ids );	# 1 on success, 0 on error
 Noid::hold_set( $noid, $id );
 Noid::hold_release( $noid, $id );

 Noid::parse_template( $template,  # read template for errors, returning
 		$prefix, $mask,	   # namespace size (NOLIMIT=unbounded)
		$gen_type,	   # or 0 on error; $message, $gen_type,
		$message );	   # $prefix, & $mask are output params

 Noid::queue( $noid, $contact,	   # return strings for queue attempts
 		$when, @ids );	   # (failures start "error:")

 Noid::n2xdig( $num, $mask );	   # show identifier matching ord. $num

 Noid::sample( $noid, $num );	   # show random ident. less than $num

 Noid::scope( $noid );		   # show range of ids inside the minter

 print Noid::errmsg( $noid, $reset );   # print message from failed call
 	$reset = undef | 1;	   # use 1 to clear error message buffer

 Noid::addmsg( $noid, $message );  # add message to error message buffer

 Noid::logmsg( $noid, $message );  # write message to minter log

=head1 DESCRIPTION

This is very brief documentation for the B<Noid> Perl module subroutines.
For this early version of the software, it is indispensable to have the
documentation for the B<noid> utility (the primary user of these routines)
at hand.  Typically that can be viewed with

	perldoc noid

while the present document can be viewed with

	perldoc Noid

The B<noid> utility creates minters (identifier generators) and accepts
commands that operate them.  Once created, a minter can be used to produce
persistent, globally unique names for documents, databases, images,
vocabulary terms, etc.  Properly managed, these identifiers can be used as
long term durable information object references within naming schemes such
as ARK, PURL, URN, DOI, and LSID.  At the same time, alternative minters
can be set up to produce short-lived names for transaction identifiers,
compact web server session keys (cf. UUIDs), and other ephemera.

In general, a B<noid> minter efficiently generates, tracks, and binds
unique identifiers, which are produced without replacement in random or
sequential order, and with or without a check character that can be used
for detecting transcription errors.  A minter can bind identifiers to
arbitrary element names and element values that are either stored or
produced upon retrieval from rule-based transformations of requested
identifiers; the latter has application in identifier resolution.  Noid
minters are very fast, scalable, easy to create and tear down, and have a
relatively small footprint.  They use BerkeleyDB as the underlying database.

Identifiers generated by a B<noid> minter are also known as "noids" (nice
opaque identifiers).  While a minter can record and bind any identifiers
that you bring to its attention, often it is used to generate, bringing
to your attention, identifier strings that carry no widely recognizable
meaning.  This semantic opaqueness reduces their vulnerability to era-
and language-specific change, and helps persistence by making for
identifiers that can age and travel well.

=begin later

=head1 HISTORY

Since 2002 Sep 3:
- seeded (using srand) the generator so that the same exact sequence of
    identifiers would be minted if we started over from scratch (limited
    disaster recovery assistance)
- changed module name from PDB.pm to Noid.pm
- changed variable names from pdb… to noid…
- began adding support for sequentially generated numbers as part of
    generalization step (eg, for use as session ids)
- added version number
- added copyright to code
- slightly improved comments and error messages
- added extra internal (admin) symbols "$R/…" (":/…"),
    eg, "template" broken into "prefix", "mask", and "generator_type"
- changed the number of counters from 300 to 293 (a prime) on the
    theory that it will improve the impression of randomness
- added "scope" routine to print out sample identifiers upon db creation

Since 2004 Jan 18:
- changed var names from b -> noid throughout
- create /tmp/errs file public write
- add subnaa as arg to dbopen
- changed $R/authority to $R/subnaa
- added note feature
- added dbinfo
- added (to noid) short calling form: noi (plus NOID env var)
- changed dbcreate to take term, naan, and naa
- added DB_DUP flag to enable duplicate keys

Plus many, many more changes…

=end

=head1 BUGS

Probably.  Please report to jak at ucop dot edu.

=head1 COPYRIGHT AND LICENSE

Copyright 2002-2006 UC Regents.  BSD-type open source license.

=head1 SEE ALSO

L<dbopen(3)>, L<perl(1)>, L<http://www.cdlib.org/inside/diglib/ark/>

=head1 AUTHOR

John A. Kunze

=cut
*/
