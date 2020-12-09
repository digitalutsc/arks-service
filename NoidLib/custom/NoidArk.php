<?php

namespace Noid\Lib\Custom;
require_once "NoidLib/custom/GlobalsArk.php";
require_once "NoidLib/custom/GeneratorArk.php";
require_once 'NoidLib/lib/Globals.php';
require_once 'NoidLib/lib/Helper.php';
require_once 'NoidLib/lib/Generator.php';
require_once 'NoidLib/lib/Log.php';
require_once 'NoidLib/lib/Noid.php';
require_once 'NoidLib/lib/Perl_Random.php';

use Noid\Lib\Noid;
use Noid\Lib\Globals;
use Noid\Lib\Helper;
use Noid\Lib\Perl_Random;
use Noid\Lib\Log;

class NoidArk extends Noid {

    public static $random_generator = 'Perl_Random';

    /**
     * Contains the randomizer when the id generator is "Perl_Random".
     *
     * @var Perl_Random $_perlRandom
     */
    public static $_perlRandom;

    /**
     * DbEngine constructor.
     * @throws Exception
     */
    public function __construct()
    {
        self::init();
    }

    /**
     * * Initialization.
     * * set the default time zone.
     * * create database interface entity.
     *
     * @throws Exception
     * @param String $dbname
     */
    static public function init(String $dbname = "NOID")
    {
        // Make sure that this function is called only one time.
        static $init = FALSE;
        if($init){
            return;
        }
        $init = TRUE;

        // create database interface according to database option. added by xQ, 2018-12-24 06:30
        if(is_null(Database::$engine)){
            $db_class = GlobalsArk::DB_TYPES[GlobalsArk::$db_type];
            $db_class_file = preg_replace('/(^.*\\\\)/', '', $db_class);
            require_once 'NoidLib/custom' . DIRECTORY_SEPARATOR . $db_class_file . '.php';
            Database::$engine = new $db_class($dbname);
        }
        // function _dba_fetch_range() went as named "get_range()" to DatabaseInterface(BerkeleyDB and MysqlDB)
    }

    /**
     * @param $noid
     * @param $id
     * @return int|null
     */
    static public function clearBind($noid, $id, $elem = null) {
        self::init();
        $status = false;
        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }
        $first = "$id\t";
        $values = Database::$engine->get_range($first);
        if($values){
            foreach($values as $key => $value){
                if (isset($elem) && !empty($elem) && strpos($key, $elem) !== FALSE) {
                    $status = Database::$engine->delete($key);
                    break;
                }
            }
        }
        return $status;
    }


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
     *
     * @return string
     * @throws Exception
     */
    static public function bind($noid, $contact, $validate, $how, $id, $elem, $value)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        # yyy to add: incr, decr for $how;  possibly other ops (* + - / **)

        # Validate identifier and element if necessary.
        #
        # yyy to do: check $elem against controlled vocab
        #     (for errors more than for security)
        # yyy should this genonly setting be so capable of contradicting
        #     the $validate arg?
        if(Database::$engine->get(Globals::_RR . "/genonly")
            && $validate
            && !self::validate($noid, '-', $id)
        ){
            return NULL;
        }
        else if(strlen($id) == 0){
            Log::addmsg($noid, 'error: bind needs an identifier specified.');
            return NULL;
        }
        if(empty($elem)){
            Log::addmsg($noid, sprintf('error: "bind %s" requires an element name.', $how));
            return NULL;
        }

        # Transform and place a "hold" (if "long" term and we're not deleting)
        # on a special identifier.  Right now that means a user-entrered Id
        # of the form :idmap/Idpattern.  In this case, change it to a database
        # Id of the form GloVal::_RR."/idmap/$elem", and change $elem to hold Idpattern;
        # this makes lookup faster and easier.
        #
        # First save original id and element names in $oid and $oelem to
        # use for all user messages; we use whatever is in $id and $elem
        # for actual database operations.
        $oid = $id;
        $oelem = $elem;
        $hold = 0;
        if(substr($id, 0, 1) === ':'){
            if(!preg_match('|^:idmap/(.+)|', $id, $matches)){
                Log::addmsg($noid, sprintf('error: %s: id cannot begin with ":" unless of the form ":idmap/Idpattern".', $oid));
                return NULL;
            }
            $id = Globals::_RR . "/idmap/$oelem";
            $elem = $matches[1];
            if(Database::$engine->get(Globals::_RR . "/longterm")){
                $hold = 1;
            }
        }
        # yyy transform other ids beginning with ":"?

        # Check circulation status.  Error if term is "long" and the id
        # hasn't been issued unless a hold was placed on it.
        #
        # If no circ record and no hold…
        $ret_val = Database::$engine->get("$id\t" . Globals::_RR . "/c");
        if(empty($ret_val) && !Database::$engine->exists("$id\t" . Globals::_RR . "/h")){
            if(Database::$engine->get(Globals::_RR . "/longterm")){
                Log::addmsg($noid, sprintf('error: %s: "long" term disallows binding an unissued identifier unless a hold is first placed on it.', $oid));
                return NULL;
            }
            Log::logmsg($noid, sprintf('warning: %s: binding an unissued identifier that has no hold placed on it.', $oid));
        }
        else if(!in_array($how, Globals::$valid_hows)){
            Log::addmsg($noid, sprintf('error: bind how?  What does %s mean?', $how));
            return NULL;
        }

        $peppermint = ($how === 'peppermint');
        if($peppermint){
            # yyy to do
            Log::addmsg($noid, 'error: bind "peppermint" not implemented.');
            return NULL;
        }

        # YYY bind mint file Elem Value     -- put into FILE by itself
        # YYY bind mint stuff_into_big_file Elem Value -- cat into file
        if($how === 'mint' || $how === 'peppermint'){
            if($id !== 'new'){
                Log::addmsg($noid, 'error: bind "mint" requires id to be given as "new".');
                return NULL;
            }
            $id = $oid = self::mint($noid, $contact, $peppermint);
            if(!$id){
                return NULL;
            }
        }

        if($how === 'delete' || $how === 'purge'){
            if(!empty($value)){
                Log::addmsg($noid, sprintf('error: why does "bind %s" have a supplied value (%s)?"', $how, $value));
                return NULL;
            }
            $value = '';
        }
        else if(empty($value)){
            Log::addmsg($noid,
                sprintf('error: "bind %s %s" requires a value to bind.', $how, $elem));
            return NULL;
        }
        # If we get here, $value is defined and we can use with impunity.

        Database::_dblock();
        $ret_val = Database::$engine->get("$id\t$elem");
        if(empty($ret_val)){      # currently unbound
            if(in_array($how, array('replace', 'append', 'prepend', 'delete'))){
                Log::addmsg($noid, sprintf('error: for "bind %s", "%s %s" must already be bound.', $how, $oid, $oelem));
                Database::_dbunlock();
                return NULL;
            }
            Database::$engine->set("$id\t$elem", '');  # can concatenate with impunity
        }
        else{                      # currently bound
            if(in_array($how, array('new', 'mint', 'peppermint'))){
                Log::addmsg($noid, sprintf('error: for "bind %s", "%s %s" cannot already be bound.', $how, $oid, $oelem));
                Database::_dbunlock();
                return NULL;
            }
        }
        # We don't care about bound/unbound for:  set, add, insert, purge

        $oldlen = strlen(Database::$engine->get("$id\t$elem"));
        $newlen = strlen($value);
        $statmsg = sprintf('%s bytes written', $newlen);

        if($how === 'delete' || $how === 'purge'){
            Database::$engine->delete("$id\t$elem");
            $statmsg = "$oldlen bytes removed";
        }
        else if($how === 'add' || $how === 'append'){
            Database::$engine->set("$id\t$elem", Database::$engine->get("$id\t$elem") . $value);
            $statmsg .= " to the end of $oldlen bytes";
        }
        else if($how === 'insert' || $how === 'prepend'){
            Database::$engine->set("$id\t$elem", $value . Database::$engine->get("$id\t$elem"));
            $statmsg .= " to the beginning of $oldlen bytes";
        }
        // Else $how is "replace" or "set".
        else{
            Database::$engine->set("$id\t$elem", $value);
            $statmsg .= ", replacing $oldlen bytes";
        }

        if($hold && Database::$engine->exists("$id\t$elem") && !self::hold_set($noid, $id)){
            $hold = -1; # don't just bail out -- we need to unlock
        }

        # yyy $contact info ?  mainly for "long" term identifiers?
        Database::_dbunlock();

        return
            # yyy should this $id be or not be $oid???
            # yyy should labels for Id and Element be lowercased???
            "Id:      $id" . PHP_EOL
            . "Element: $elem" . PHP_EOL
            . "Bind:    $how" . PHP_EOL
            . "Status:  " . ($hold == -1 ? Log::errmsg($noid) : 'ok, ' . $statmsg) . PHP_EOL;
    }

    /**
     * Fetch elements from the base.
     *
     * @todo do we need to be able to "get/fetch" with a discriminant,
     *       eg, for smart multiple resolution??
     *
     * @param string       $noid
     * @param int          $verbose is 1 if we want labels, 0 if we don't
     * @param string       $id
     * @param array|string $elems
     *
     * @return string List of elements separated by an end of line.
     * @throws Exception
     */
    static public function fetch($noid, $verbose, $id, $elems)
    {
        self::init();

        if(strlen($id) == 0){
            Log::addmsg($noid, sprintf('error: %s requires that an identifier be specified.', $verbose ? 'fetch' : 'get'));
            return NULL;
        }

        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        if(!is_array($elems)){
            $elems = strlen($elems) == 0 ? array() : array($elems);
        }

        $hdr = '';
        $retval = '';
        if($verbose){
            $hdr = "id:    $id"
                . (Database::$engine->exists("$id\t" . Globals::_RR . "/h") ? ' hold ' : '') . PHP_EOL
                . (self::validate($noid, '-', $id) ? '' : Log::errmsg($noid) . PHP_EOL)
                . 'Circ:  ' . (Database::$engine->get("$id\t" . Globals::_RR . "/c") ? : 'uncirculated') . PHP_EOL;
        }

        if(empty($elems)){  # No elements were specified, so find them.
            $first = "$id\t";
            $values = Database::$engine->get_range($first);
            if($values){
                foreach($values as $key => $value){
                    $skip = preg_match('|^' . preg_quote("$first" . Globals::_RR . "/", '|') . '|', $key);
                    if(!$skip){
                        # if $verbose (ie, fetch), require_once label and
                        # remember to strip "Id\t" from front of $key
                        if($verbose){
                            $retval .= (preg_match('/^[^\t]*\t(.*)/', $key, $matches) ? $matches[1] : $key) . ': ';
                        }
                        $retval .= $value . PHP_EOL;
                    }
                }
            }

            if(empty($retval)){
                Log::addmsg($noid, $hdr
                    . "note: no elements bound under $id.");
                return NULL;
            }
            return $hdr . $retval;
        }

        # yyy should this work for elem names with regexprs in them?
        # XXX idmap won't bind with longterm ???
        $idmapped = NULL;
        foreach($elems as $elem){
            if(Database::$engine->get("$id\t$elem")){
                if($verbose){
                    $retval .= "$elem: ";
                }
                $retval .= Database::$engine->get("$id\t$elem") . PHP_EOL;
            }
            else{
                $idmapped = self::_id2elemval($noid, $verbose, $id, $elem);
                if($verbose){
                    $retval .= $idmapped
                        ? $idmapped . PHP_EOL . 'note: previous result produced by :idmap'
                        : sprintf('error: "%s %s" is not bound.', $id, $elem);
                    $retval .= PHP_EOL;
                }
                else{
                    $retval .= $idmapped . PHP_EOL;
                }
            }
        }

        return $hdr . $retval;
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
     * @param int    $pepper
     *
     * @return string
     * @throws Exception
     */
    static public function mint($noid, $contact, $pepper = 0)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        if(empty($contact)){
            Log::addmsg($noid, 'contact undefined');
            return NULL;
        }

        $template = Database::$engine->get(Globals::_RR . "/template");
        if(!$template){
            Log::addmsg($noid, 'error: this minter does not generate identifiers (it does accept user-defined identifier and element bindings).');
            return NULL;
        }

        # Check if the head of the queue is ripe.  See comments under queue()
        # for an explanation of how the queue works.
        #
        $currdate = Helper::getTemper();        # fyi, 14 digits long
        $first = Globals::_RR . "/q/";

        # The following is not a proper loop.  Normally it should run once,
        # but several cycles may be needed to weed out anomalies with the id
        # at the head of the queue.  If all goes well and we found something
        # to mint from the queue, the last line in the loop exits the routine.
        # If we drop out of the loop, it's because the queue wasn't ripe.
        $values = Database::$engine->get_range($first);
        foreach($values as $key => $value){
            $id = &$value;
            # The cursor, key and value are now set at the first item
            # whose key is greater than or equal to $first.  If the
            # queue was empty, there should be no items under GloVal::_RR."/q/".
            #
            $qdate = preg_match('|' . preg_quote(Globals::_RR . "/q/", '|') . '(\d{14})|', $key, $matches) ? $matches[1] : NULL;
            if(empty($qdate)){           # nothing in queue
                # this is our chance -- see queue() comments for why
                if(Database::$engine->get(Globals::_RR . "/fseqnum") > Globals::SEQNUM_MIN){
                    Database::$engine->set(Globals::_RR . "/fseqnum", Globals::SEQNUM_MIN);
                }
                break;               # so move on
            }
            # If the date of the earliest item to re-use hasn't arrived
            if($currdate < $qdate){
                break;               # move on
            }

            # If we get here, head of queue is ripe.  Remove from queue.
            # Any "next" statement from now on in this loop discards the
            # queue element.
            #
            Database::$engine->delete($key);
            Database::$engine->set(Globals::_RR . "/queued", Database::$engine->get(Globals::_RR . "/queued") - 1);
            if(Database::$engine->get(Globals::_RR . "/queued") < 0){
                $m = sprintf('error: queued count (%s) going negative on id %s', Database::$engine->get(Globals::_RR . "/queued"), $id);
                Log::addmsg($noid, $m);
                Log::logmsg($noid, $m);
                return NULL;
            }

            # We perform a few checks first to see if we're actually
            # going to use this identifier.  First, if there's a hold,
            # remove it from the queue and check the queue again.
            #
            if(Database::$engine->exists("$id\t" . Globals::_RR . "/h")){     # if there's a hold
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid,
                        sprintf('warning: id %s found in queue with a hold placed on it -- removed from queue.', $id));
                }
                continue;
            }
            # yyy this means id on "hold" can still have a 'q' circ status?

            $circ_svec = self::_get_circ_svec($noid, $id);

            if(substr($circ_svec, 0, 1) === 'i'){
                Log::logmsg($noid,
                    sprintf('error: id %s appears to have been issued while still in the queue -- circ record is %s',
                        $id, Database::$engine->get("$id\t" . Globals::_RR . "/c")));
                continue;
            }
            if(substr($circ_svec, 0, 1) === 'u'){
                Log::logmsg($noid, sprintf('note: id %s, marked as unqueued, is now being removed/skipped in the queue -- circ record is %s',
                    $id, Database::$engine->get("$id\t" . Globals::_RR . "/c")));
                continue;
            }
            if(preg_match('/^([^q])/', $circ_svec, $matches)){
                Log::logmsg($noid, sprintf('error: id %s found in queue has an unknown circ status (%s) -- circ record is %s',
                    $id, $matches[1], Database::$engine->get("$id\t" . Globals::_RR . "/c")));
                continue;
            }

            # Finally, if there's no circulation record, it means that
            # it was queued to get it minted earlier or later than it
            # would normally be minted.  Log if term is "long".
            #
            if($circ_svec === ''){
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid,
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
        if(Database::$engine->get(Globals::_RR . "/generator_type") == 'random'){
            self::$random_generator = Database::$engine->get(Globals::_RR . "/generator_random") ? : self::$random_generator;
            if(self::$random_generator == 'Perl_Random'){
                self::$_perlRandom = Perl_Random::init();
            }
        }

        $repertoire = Database::$engine->get(Globals::_RR . "/addcheckchar")
            ? (Database::$engine->get(Globals::_RR . "/checkrepertoire") ? : Helper::getAlphabet($template))
            : '';

        # As above, the following is not a proper loop.  Normally it should
        # run once, but several cycles may be needed to weed out anomalies
        # with the generated id (eg, there's a hold on the id, or it was
        # queued to delay issue).
        #
        while(TRUE){
            # Next is the important seeding of random number generator.
            # We need this so that we get the same exact series of
            # pseudo-random numbers, just in case we have to wipe out a
            # generator and start over.  That way, the n-th identifier
            # will be the same, no matter how often we have to start
            # over.  This step has no effect when $generator_type ==
            # "sequential".
            #
            srand(Database::$engine->get(Globals::_RR . "/oacounter"));

            # The id returned in this next step may have a "+" character
            # that n2xdig() appended to it.  The checkchar() routine
            # will convert it to a check character.
            #
            $id = GeneratorArk::_genid($noid);
            if(is_null($id)){
                return NULL;
            }

            # Prepend NAAN and separator if there is a NAAN.
            #
            if(Database::$engine->get(Globals::_RR . "/firstpart")){
                $id = Database::$engine->get(Globals::_RR . "/firstpart") . $id;
            }

            # Add check character if called for.
            #
            if(Database::$engine->get(Globals::_RR . "/addcheckchar")){
                $id = Helper::checkChar($id, $repertoire);
            }

            # There may be a hold on an id, meaning that it is not to
            # be issued (or re-issued).
            #
            if(Database::$engine->exists("$id\t" . Globals::_RR . "/h")){     # if there's a hold
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
            if(substr($circ_svec, 0, 1) === 'q'){
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid,
                        sprintf("note: will not issue genid()'d %s as its status is 'q', circ_rec is %s",
                            $id, Database::$engine->get("$id\t" . Globals::_RR . "/c")));
                }
                continue;
            }

            # If the circulation status is 'i' it means that the id is
            # being re-issued.  This shouldn't happen unless the counter
            # has wrapped around to the beginning.  If term is "long",
            # an id can be re-issued only if (a) its hold was released
            # and (b) it was placed in the queue (thus marked with 'q').
            #
            if(substr($circ_svec, 0, 1) === 'i'
                && (Database::$engine->get(Globals::_RR . "/longterm") || !Database::$engine->get(Globals::_RR . "/wrap"))
            ){
                Log::logmsg($noid, sprintf('error: id %s cannot be re-issued except by going through the queue, circ_rec %s',
                    $id, Database::$engine->get("$id\t" . Globals::_RR . "/c")));
                continue;
            }
            if(substr($circ_svec, 0, 1) === 'u'){
                Log::logmsg($noid, sprintf('note: generating id %s, currently marked as unqueued, circ record is %s',
                    $id, Database::$engine->get("$id\t" . Globals::_RR . "/c")));
                continue;
            }
            if(preg_match('/^([^iqu])/', $circ_svec, $matches)){
                Log::logmsg($noid, sprintf('error: id %s has unknown circulation status (%s), circ_rec %s',
                    $id, $matches[1], Database::$engine->get("$id\\t" . Globals::_RR . "/c")));
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
        return NULL;
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
     * The queue is composed of keys of the form ".GloVal::_RR."/q/$qdate/$seqnum/$paddedid,
     * with the correponding values being the actual queued identifiers.  The
     * Btree allows us to step sequentially through the queue in an ordering
     * that is a side-effect of our key structure.  Left-to-right, it is
     *
     *   :/q/        ".GloVal::_RR."/q/, 4 characters wide
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
     * @param string       $noid
     * @param string       $contact
     * @param string       $when
     * @param array|string $ids
     *
     * @return array
     * @throws Exception
     */
    static public function queue($noid, $contact, $when, $ids)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        if(!is_array($ids)){
            $ids = strlen($ids) == 0 ? array() : array($ids);
        }

        if(!Database::$engine->get(Globals::_RR . "/template")){
            Log::addmsg($noid, 'error: queuing makes no sense in a bind-only minter.');
            return array();
        }
        if(empty($contact)){
            Log::addmsg($noid, 'error: contact undefined');
            return array();
        }
        if(empty($when) || trim($when) === ''){
            Log::addmsg($noid, 'error: queue when? (eg, first, lvf, 30d, now)');
            return array();
        }
        # yyy what is sensible thing to do if no ids are present?
        if(empty($ids)){
            Log::addmsg($noid, 'error: must specify at least one id to queue.');
            return array();
        }
        $seqnum = 0;
        $delete = 0;
        # purposely null
        $fixsqn = NULL;
        $qdate = NULL;

        # You can express a delay in days (d) or seconds (s, default).
        #
        if(preg_match('/^(\d+)([ds]?)$/', $when, $matches)){    # current time plus a delay
            # The number of seconds in one day is 86400.
            $multiplier = isset($matches[2]) && $matches[2] === 'd' ? 86400 : 1;
            $qdate = Helper::getTemper(time() + $matches[1] * $multiplier);
        }
        else if($when === 'now'){    # a synonym for current time
            $qdate = Helper::getTemper(time());
        }
        else if($when === 'first'){
            # Lowest value first (lvf) requires $qdate of all zeroes.
            # To achieve "first" semantics, we use a $qdate of all
            # zeroes (default above), which means this key will be
            # selected even earlier than a key that became ripe in the
            # queue 85 days ago but wasn't selected because no one
            # minted anything in the last 85 days.
            #
            $seqnum = Database::$engine->get(Globals::_RR . "/fseqnum");
            #
            # NOTE: fseqnum is reset only when queue is empty; see mint().
            # If queue never empties fseqnum will simply keep growing,
            # so we effectively truncate on the left to 6 digits with mod
            # arithmetic when we convert it to $fixsqn via sprintf().
        }
        else if($when === 'delete'){
            $delete = 1;
        }
        else if($when !== 'lvf'){
            Log::addmsg($noid, sprintf('error: unrecognized queue time: %s', $when));
            return array();
        }

        if(!empty($qdate)){     # current time plus optional delay
            if($qdate > Database::$engine->get(Globals::_RR . "/gseqnum_date")){
                $seqnum = Globals::SEQNUM_MIN;
                Database::$engine->set(Globals::_RR . "/gseqnum", $seqnum);
                Database::$engine->set(Globals::_RR . "/gseqnum_date", $qdate);
            }
            else{
                $seqnum = Database::$engine->get(Globals::_RR . "/gseqnum");
            }
        }
        else{
            $qdate = '00000000000000';  # this needs to be 14 zeroes
        }

        $iderrors = array();
        if(Database::$engine->get(Globals::_RR . "/genonly")){
            $iderrors = self::validate($noid, '-', $ids);
            if(array_filter($iderrors, function($v){
                return strpos($v, 'error:') !== 0;
            })){
                $iderrors = array();
            }
        }
        if($iderrors){
            Log::addmsg($noid, sprintf('error: queue operation not started -- one or more ids did not validate: %s',
                PHP_EOL . implode(PHP_EOL, $iderrors)));
            return array();
        }

        $firstpart = Database::$engine->get(Globals::_RR . "/firstpart");
        $padwidth = Database::$engine->get(Globals::_RR . "/padwidth");
        $currdate = Helper::getTemper();
        $retvals = array();
        $idval = NULL;
        $paddedid = NULL;
        $circ_svec = NULL;
        foreach($ids as $id){
            if(Database::$engine->exists("$id\t" . Globals::_RR . "/h")){     # if there's a hold
                $m = sprintf('error: a hold has been set for "%s" and must be released before the identifier can be queued for minting.', $id);
                Log::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }

            # If there's no circulation record, it means that it was
            # queued to get it minted earlier or later than it would
            # normally be minted.  Log if term is "long".
            #
            $circ_svec = self::_get_circ_svec($noid, $id);

            if(substr($circ_svec, 0, 1) === 'q' && !$delete){
                $m = sprintf('error: id %s cannot be queued since it appears to be in the queue already -- circ record is %s',
                    $id, Database::$engine->get("$id\t" . Globals::_RR . "/c"));
                Log::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }
            if(substr($circ_svec, 0, 1) === 'u' && $delete){
                $m = sprintf('error: id %s has been unqueued already -- circ record is %s',
                    $id, Database::$engine->get("$id\t" . Globals::_RR . "/c"));
                Log::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }
            if(substr($circ_svec, 0, 1) !== 'q' && $delete){
                $m = sprintf('error: id %s cannot be unqueued since its circ record does not indicate its being queued, circ record is %s',
                    $id, Database::$engine->get("$id\t" . Globals::_RR . "/c"));
                Log::logmsg($noid, $m);
                $retvals[] = $m;
                continue;
            }
            # If we get here and we're deleting, circ_svec must be 'q'.

            if($circ_svec === ''){
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid,
                        sprintf('note: id %s being queued before first minting (to be pre-cycled)', $id));
                }
            }
            else if(substr($circ_svec, 0, 1) === 'i'){
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid, sprintf('note: longterm id %s being queued for re-issue', $id));
                }
            }

            # yyy ignore return OK?
            self::_set_circ_rec($noid, $id, ($delete ? 'u' : 'q') . $circ_svec, $currdate, $contact);

            $idval = preg_replace('/^' . preg_quote("$firstpart", '/') . '/', '', $id);
            $paddedid = sprintf("%0$padwidth" . "s", $idval);
            $fixsqn = sprintf("%06d", $seqnum % Globals::SEQNUM_MAX);

            Database::_dblock();

            Database::$engine->set(Globals::_RR . "/queued", Database::$engine->get(Globals::_RR . "/queued") + 1);
            if(Database::$engine->get(Globals::_RR . "/total") != Globals::NOLIMIT   # if total is non-zero
                && Database::$engine->get(Globals::_RR . "/queued") > Database::$engine->get(Globals::_RR . "/oatop")
            ){
                Database::_dbunlock();

                $m = sprintf('error: queue count (%s) exceeding total possible on id %s.  Queue operation aborted.',
                    Database::$engine->get(Globals::_RR . "/queued"), $id);
                Log::logmsg($noid, $m);
                $retvals[] = $m;
                break;
            }
            Database::$engine->set(Globals::_RR . "/q/$qdate/$fixsqn/$paddedid", $id);

            Database::_dbunlock();

            if(Database::$engine->get(Globals::_RR . "/longterm")){
                Log::logmsg($noid, sprintf('id: %s added to queue under %s',
                    Database::$engine->get(Globals::_RR . "/q/$qdate/$fixsqn/$paddedid"), Globals::_RR . "/q/$qdate/$seqnum/$paddedid"));
            }
            $retvals[] = sprintf('id: %s', $id);
            if($seqnum){     # it's zero for "lvf" and "delete"
                $seqnum++;
            }
        }

        Database::_dblock();
        if($when === 'first'){
            Database::$engine->set(Globals::_RR . "/fseqnum", $seqnum);
        }
        else if($qdate > 0){
            Database::$engine->set(Globals::_RR . "/gseqnum", $seqnum);
        }
        Database::_dbunlock();

        return $retvals;
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
     * @param string       $noid
     * @param string       $template
     * @param array|string $ids
     *
     * @return array
     * @throws Exception
     */
    static public function validate($noid, $template, $ids)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        if(!is_array($ids)){
            $ids = strlen($ids) == 0 ? array() : array($ids);
        }

        $first = NULL;
        $prefix = NULL;
        $mask = NULL;
        $gen_type = NULL;
        $msg = NULL;

        $retvals = array();

        if(empty($ids)){
            Log::addmsg($noid, 'error: must specify a template and at least one identifier.');
            return array();
        }
        if(empty($template)){
            # If $noid is null, the caller looks in Log::errmsg(null).
            Log::addmsg($noid, 'error: no template given to validate against.');
            return array();
        }

        $repertoire = NULL;

        if(!strcmp($template, '-')){
            # $retvals[] = sprintf('template: %s', GloVal::$db_engine->get(GloVal::_RR."/template")));
            if(!Database::$engine->get(Globals::_RR . "/template")){  # do blanket validation
                $nonulls = array_filter(preg_replace('/^(.)/', 'id: $1', $ids));
                if(empty($nonulls)){
                    return array();
                }
                $retvals += $nonulls;
                return $retvals;
            }
            $prefix = Database::$engine->get(Globals::_RR . "/prefix");
            $mask = Database::$engine->get(Globals::_RR . "/mask");
            // Validate with the saved repertoire, if any.
            $repertoire = Database::$engine->get(Globals::_RR . "/addcheckchar")
                ? (Database::$engine->get(Globals::_RR . "/checkrepertoire") ? : Helper::getAlphabet($template))
                : '';
        }
        else if(!Helper::parseTemplate($template, $prefix, $mask, $gen_type, $msg)){
            Log::addmsg($noid, sprintf('error: template %s bad: %s', $template, $msg));
            return array();
        }

        $m = preg_replace('/k$/', '', $mask);
        $should_have_checkchar = $m !== $mask;
        if(is_null($repertoire)){
            $repertoire = $should_have_checkchar ? Helper::getAlphabet($prefix . '.' . $mask) : '';
        }

        $naan = Database::$engine->get(Globals::_RR . "/naan");
        foreach($ids as $id){
            if(is_null($id) || trim($id) == ''){
                $retvals[] = "iderr: can't validate an empty identifier";
                continue;
            }

            # Automatically reject ids starting with GloVal::_RR."/", unless it's an
            # "idmap", in which case automatically validate.  For an idmap,
            # the $id should be of the form ".GloVal::_RR."/idmap/ElementName, with
            # element, Idpattern, and value, ReplacementPattern.
            #
            if(strpos(Globals::_RR . "/", $id) === 0){
                $retvals[] = preg_match('|^' . preg_quote(Globals::_RR . "/idmap/", '|') . '.+|', $id)
                    ? sprintf('id: %s', $id)
                    : sprintf('iderr: identifiers must not start with "%s".', Globals::_RR . "/");
                continue;
            }

            $first = $naan;             # … if any
            if($first){
                $first .= '/';
            }
            $first .= $prefix;          # … if any
            $varpart = preg_replace('/^' . preg_quote($first, '/') . '/', '', $id);
            if(strlen($first) > 0 && strpos($id, $first) !== 0){
                # yyy            ($varpart = $id) !~ s/^$prefix// and
                $retvals[] = sprintf('iderr: %s should begin with %s.', $id, $first);
                continue;
            }
            if($should_have_checkchar && !Helper::checkChar($id, $repertoire)){
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
            $suppl = $mode == 'z' ? $maskchars[0] : NULL;
            $flagBreakContinue = FALSE;
            foreach(str_split($varpart) as $c){
                // Avoid to str_split() an empty varpart.
                if(strlen($c) == 0){
                    break;
                }
                $m = array_shift($maskchars);
                if(is_null($m)){
                    if($mode != 'z'){
                        $retvals[] = sprintf('iderr: %s longer than specified template (%s)', $id, $template);
                        $flagBreakContinue = TRUE;
                        break;
                    }
                    $m = $suppl;
                }
                if(isset(Globals::$alphabets[$m]) && strpos(Globals::$alphabets[$m], $c) === FALSE){
                    $retvals[] = sprintf('iderr: %s char "%s" conflicts with template (%s) char "%s"%s',
                        $id, $c, $template, $m, $m == 'e' ? ' (extended digit)' : ($m == 'd' ? ' (digit)' : ''));
                    $flagBreakContinue = TRUE;
                    break;
                }       # or $m === 'k', in which case skip
            }
            if($flagBreakContinue){
                continue;
            }

            $m = array_shift($maskchars);
            if(!is_null($m)){
                $retvals[] = sprintf('iderr: %s shorter than specified template (%s)', $id, $template);
                continue;
            }

            # If we get here, the identifier checks out.
            $retvals[] = sprintf('id: %s', $id);
        }
        return $retvals;
    }

    /**
     * A hold may be placed on an identifier to keep it from being minted/issued.
     *
     * @param string       $noid
     * @param string       $contact
     * @param string       $on_off
     * @param array|string $ids
     *
     * @return int 0 (error) or 1 (success)
     * Sets errmsg() in either case.
     * @throws Exception
     */
    static public function hold($noid, $contact, $on_off, $ids)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return 0;
        }

        if(!is_array($ids)){
            $ids = strlen($ids) == 0 ? array() : array($ids);
        }

        # yyy what makes sense in this case?
        # if (! GloVal::$db_engine->get(GloVal::_RR."/template")) {
        #   Log::addmsg($noid,
        #       'error: holding makes no sense in a bind-only minter.');
        #   return 0;
        # }
        if(empty($contact)){
            Log::addmsg($noid, "error: contact undefined");
            return 0;
        }
        if(empty($on_off)){
            Log::addmsg($noid, 'error: hold "set" or "release"?');
            return 0;
        }
        if(empty($ids)){
            Log::addmsg($noid, 'error: no Id(s) specified');
            return 0;
        }
        if($on_off !== 'set' && $on_off !== 'release'){
            Log::addmsg($noid, sprintf('error: unrecognized hold directive (%s)', $on_off));
            return 0;
        }

        $release = $on_off === 'release';
        # yyy what is sensible thing to do if no ids are present?
        $iderrors = array();
        if(Database::$engine->get(Globals::_RR . "/genonly")){
            $iderrors = self::validate($noid, '-', $ids);
            if(array_filter($iderrors, function($v){
                return strpos($v, 'error:') !== 0;
            })){
                $iderrors = array();
            }
        }
        if($iderrors){
            Log::addmsg($noid, sprintf('error: hold operation not started -- one or more ids did not validate: %s',
                PHP_EOL . implode(PHP_EOL, $iderrors)));
            return 0;
        }

        $status = NULL;
        $n = 0;
        foreach($ids as $id){
            if($release){     # no hold means key doesn't exist
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid, sprintf('%s %s: releasing hold', Helper::getTemper(), $id));
                }
                Database::_dblock();
                $status = self::hold_release($noid, $id);
            }
            else{          # "hold" means key exists
                if(Database::$engine->get(Globals::_RR . "/longterm")){
                    Log::logmsg($noid, sprintf('%s %s: placing hold', Helper::getTemper(), $id));
                }
                Database::_dblock();
                $status = self::hold_set($noid, $id);
            }
            Database::_dbunlock();
            if(!$status){
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
        Log::addmsg($noid, $n == 1 ? sprintf('ok: 1 hold placed') : sprintf('ok: %s holds placed', $n));
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
     *
     * @return int 0 (error) or 1 (success)
     * @throws Exception
     */
    static public function hold_set($noid, $id)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return 0;
        }

        Database::$engine->set("$id\t" . Globals::_RR . "/h", 1);        # value doesn't matter
        Database::$engine->set(Globals::_RR . "/held", Database::$engine->get(Globals::_RR . "/held") + 1);
        if(Database::$engine->get(Globals::_RR . "/total") != Globals::NOLIMIT   # ie, if total is non-zero
            && Database::$engine->get(Globals::_RR . "/held") > Database::$engine->get(Globals::_RR . "/oatop")
        ){
            $m = sprintf('error: hold count (%s) exceeding total possible on id %s', Database::$engine->get(Globals::_RR . "/held"), $id);
            Log::addmsg($noid, $m);
            Log::logmsg($noid, $m);
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
     *
     * @return int 0 (error) or 1 (success)
     * @throws Exception
     */
    static public function hold_release($noid, $id)
    {
        self::init();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return 0;
        }

        Database::$engine->delete("$id\t" . Globals::_RR . "/h");
        Database::$engine->set(Globals::_RR . "/held", Database::$engine->get(Globals::_RR . "/held") - 1);
        if(Database::$engine->get(Globals::_RR . "/held") < 0){
            $m = sprintf('error: hold count (%s) going negative on id %s', Database::$engine->get(Globals::_RR . "/held"), $id);
            Log::addmsg($noid, $m);
            Log::logmsg($noid, $m);
            return 0;
        }
        return 1;
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
     *
     * @return string
     * Returns a single letter circulation status, which must be one
     * of 'i', 'q', or 'u'.  Returns the empty string on error.
     * @throws Exception
     */
    static protected function _get_circ_svec($noid, $id)
    {
        $db = Database::getDb($noid);
        if(is_null($db)){
            return '';
        }

        $circ_rec = Database::$engine->get("$id\t" . Globals::_RR . "/c");
        if(empty($circ_rec)){
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

        if(empty($circ_svec)){
            Log::logmsg($noid, sprintf('error: id %s has no circ status vector -- circ record is %s', $id, $circ_rec));
            return '';
        }
        if(!preg_match('/^([iqu])[iqu]*$/', $circ_svec, $matches)){
            Log::logmsg($noid, sprintf('error: id %s has a circ status vector containing letters other than "i", "q", or "u" -- circ record is %s', $id, $circ_rec));
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
     *
     * @return string|null
     * @throws Exception
     */
    static protected function _set_circ_rec($noid, $id, $circ_svec, $date, $contact)
    {
        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        $status = 1;
        $circ_rec = "$circ_svec|$date|$contact|" . Database::$engine->get(Globals::_RR . "/oacounter");

        # yyy do we care what the previous circ record was?  since right now
        #     we just clobber without looking at it

        Database::_dblock();

        # Check for and clear any bindings if we're issuing an identifier.
        # We ignore the return value from _clear_bindings().
        # Replace or clear admin bindings by hand, including pepper if any.
        #       yyy pepper not implemented yet
        # If issuing a longterm id, we automatically place a hold on it.
        #
        if(strpos($circ_svec, 'i') === 0){
            self::_clear_bindings($noid, $id, 0);
            Database::$engine->delete("$id\t" . Globals::_RR . "/p");
            if(Database::$engine->get(Globals::_RR . "/longterm")){
                $status = NoidArk::hold_set($noid, $id);
            }
        }
        Database::$engine->set("$id\t" . Globals::_RR . "/c", $circ_rec);

        Database::_dbunlock();

        # This next logmsg should account for the bulk of the log when
        # longterm identifiers are in effect.
        #
        if(Database::$engine->get(Globals::_RR . "/longterm")){
            Log::logmsg($noid, sprintf('m: %s%s', $circ_rec, $status ? '' : ' -- hold failed'));
        }

        if(empty($status)){           # must be an error in hold_set()
            return NULL;
        }
        return $id;
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
     *
     * @return array|NULL
     * @throws Exception
     */
    static protected function _clear_bindings($noid, $id, $verbose)
    {
        $retvals = array();

        $db = Database::getDb($noid);
        if(is_null($db)){
            return NULL;
        }

        # yyy right now "$id\t" defines how we bind stuff to an id, but in the
        #     future that could change.  in particular we don't bind (now)
        #     anything to just "$id" (without a tab after it)
        $first = "$id\t";
        $values = Database::$engine->get_range($first);
        if($values){
            foreach($values as $key => $value){
                $skip = preg_match('|^' . preg_quote("$first" . Globals::_RR . "/", '|') . '|', $key);
                if(!$skip && $verbose){
                    # if $verbose (ie, fetch), require_once label and
                    # remember to strip "Id\t" from front of $key
                    $key = preg_match('/^[^\t]*\t(.*)/', $key, $matches) ? $matches[1] : $key;
                    $retvals[] = $key . ': ' . sprintf('clearing %d bytes', strlen($value));
                    Database::$engine->delete($key);
                }
            }
        }
        return $verbose ? $retvals : array();
    }

    /**
     * Return $elem: $val or error string.
     *
     * @param string $noid
     * @param string $verbose
     * @param        $id
     * @param string $elem
     *
     * @return string
     * @throws Exception
     */
    static protected function _id2elemval($noid, $verbose, $id, $elem)
    {
        $db = Database::getDb($noid);
        if(is_null($db)){
            return '';
        }

        $first = Globals::_RR . "/idmap/$elem\t";
        $values = Database::$engine->get_range($first);
        if(is_null($values)){
            return sprintf('error: id2elemval: access to database failed.');
        }
        if(empty($values)){
            return '';
        }
        $key = key($values);
        if(strpos($key, $first) !== 0){
            return '';
        }
        foreach($values as $key => $value){
            $pattern = preg_match('|' . preg_quote($first, '|') . '(.+)|', $key) ? $key : NULL;
            $newval = $id;
            if(!empty($pattern)){
                try{
                    # yyy kludgy use of unlikely delimiters (ascii 05: Enquiry)
                    $newval = preg_replace(chr(5) . preg_quote($pattern, chr(5)) . chr(5), $value, $newval);
                }
                catch(Exception $e){
                    return sprintf('error: id2elemval eval: %s', $e->getMessage());
                }
                # replaced, so return
                return ($verbose ? $elem . ': ' : '') . $newval;
            }
        }
        return '';
    }

}