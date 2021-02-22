<?php
/**
 * Created by PhpStorm.
 * User: Home
 * Date: 12/28/2018
 * Time: 05:53
 */

namespace Noid\Lib\Custom;

use \Exception;

use Noid\Lib\Custom\Database;
use Noid\Lib\Globals;


class GeneratorArk{
	/**
	 * Convert a number to an extended digit according to $mask and $generator_type
	 * and return (without prefix or NAAN).  A $mask character of 'k' gets
	 * converted to '+' in the returned string; post-processing will eventually
	 * turn it into a computed check character.
	 *
	 * @param int    $num
	 * @param string $mask
	 *
	 * @return string
	 * @throws Exception
	 */
	static public function n2xdig($num, $mask)
	{
		$s = '';
		$div = NULL;
		$remainder = NULL;
		$c = NULL;

		# Check whether $mask is well-formed before proceeding.
		#
		if(!preg_match('/^[rsz][' . Globals::$repertoires . ']+k?$/', $mask)){
			return '';
		}

		$var_width = 0;   # we start in fixed width part of the mask
		$rmask = array_reverse(str_split($mask));  # process each char in reverse
		$alphabet = '';
		while($num != 0 || !$var_width){
			if(!$var_width){
				$c = array_shift($rmask);  # check next mask character,
				// Avoid to str_split() an empty value.
				if(strlen($c) == 0
					|| $c === 'r'
					|| $c === 's'
				){ # terminate on r or s even if
					break;   # $num is not all used up yet
				}
				if(isset(Globals::$alphabets[$c])){
					$alphabet = Globals::$alphabets[$c];
					$div = strlen($alphabet);
				}
				else if($c === 'z'){
					$var_width = 1;   # re-uses last $div value
					continue;
				}
				else if($c === 'k'){
					continue;
				}
			}
			$remainder = $num % $div;
			$num = intval($num / $div);
			$s = substr($alphabet, $remainder, 1) . $s;
		}
		if(substr($mask, -1) === 'k'){       # if it ends in a check character
			$s .= '+';      # represent it with plus in new id
		}
		return $s;
	}

	/**
	 * Generate the actual next id to give out.  May be randomly or sequentially
	 * selected.  This routine should not be called if there are ripe recyclable
	 * identifiers to use.
	 *
	 * This routine and n2xdig comprise the real heart of the minter software.
	 *
	 * @param string $noid
	 *
	 * @return string|NULL
	 * @throws Exception
	 */
	static public function _genid($noid)
	{
		$db = Database::getDb($noid);
		if(is_null($db)){
			return NULL;
		}

		Database::_dblock();

		# Variables:
		#   oacounter   overall counter's current value (last value minted)
		#   oatop   overall counter's greatest possible value of counter
		#   saclist (sub) active counters list
		#   siclist (sub) inactive counters list
		#   c$n/value   subcounter name's ($scn) value

		$oacounter = Database::$engine->get(Globals::_RR . "/oacounter");

		// Internally, _genid() is used only by mint() and seeded just before
		// with the last counter, so it can be set here to simplify generation.
		$seed = $oacounter;

		# yyy what are we going to do with counters for held? queued?

		if(Database::$engine->get(Globals::_RR."/oatop") != Globals::NOLIMIT && $oacounter >= Database::$engine->get(Globals::_RR."/oatop")){
			# Critical test of whether we're willing to re-use identifiers
			# by re-setting (wrapping) the counter to zero.  To be extra
			# careful we check both the longterm and wrap settings, even
			# though, in theory, wrap won't be set if longterm is set.
			#
			if(Database::$engine->get(Globals::_RR."/longterm") || !Database::$engine->get(Globals::_RR."/wrap")){
				Database::_dbunlock();
				$m = sprintf('error: identifiers exhausted (stopped at %s).', Database::$engine->get(Globals::_RR."/oatop"));
				Log::addmsg($noid, $m);
				Log::logmsg($noid, $m);
				return NULL;
			}
			# If we get here, term is not "long".
			Log::logmsg($noid, sprintf('%s: Resetting counter to zero; previously issued identifiers will be re-issued', Helper::getTemper()));
			if(Database::$engine->get(Globals::_RR."/generator_type") === 'sequential'){
				Database::$engine->set(Globals::_RR."/oacounter", 0);
			}
			else{
				Database::_init_counters($noid);   # yyy calls dblock -- problem?
			}
			$oacounter = 0;
		}
		# If we get here, the counter may actually have just been reset.

		# Deal with the easy sequential generator case and exit early.
		#
		if(Database::$engine->get(Globals::_RR."/generator_type") === 'sequential'){
			$id = self::n2xdig(Database::$engine->get(Globals::_RR."/oacounter"), Database::$engine->get(Globals::_RR."/mask"));
			Database::$engine->set(Globals::_RR."/oacounter", Database::$engine->get(Globals::_RR."/oacounter") + 1);   # incr to reflect new total
			Database::_dbunlock();
			return $id;
		}

		# If we get here, the generator must be of type "random".
		#
		$saclist = Database::$engine->get(Globals::_RR."/saclist");
		$saclist = explode(' ', trim($saclist));

		$len = count($saclist);
		if($len < 1){
			Database::_dbunlock();
			Log::addmsg($noid, sprintf('error: no active counters panic, but %s identifiers left?', $oacounter));
			return NULL;
		}

		switch(NoidArk::$random_generator){    # pick a specific counter name
		case 'Perl_Random':
		default:
			NoidArk::$_perlRandom->srand($seed);
			$randn = NoidArk::$_perlRandom->int_rand($len);
			break;

		case 'perl rand()':
			$cmd = 'perl -e "srand(' . $seed . '); print int(rand(' . $len . '));"';
			Helper::executeCommand($cmd, $status, $output, $errors);
			if($status != 0){
				Database::_dbunlock();
				Log::addmsg($noid, sprintf('error: perl rand() is not available: %s.', $errors));
				return NULL;
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
		$sctr = Database::$engine->get(Globals::_RR."/$sctrn/value"); # and get its value
		$sctr++;                # increment and
		Database::$engine->set(Globals::_RR."/$sctrn/value", $sctr);    # store new current value
		Database::$engine->set(Globals::_RR."/oacounter", Database::$engine->get(Globals::_RR."/oacounter") + 1);       # incr overall counter - some
		# redundancy for sanity's sake

		# deal with an exhausted subcounter
		if($sctr >= Database::$engine->get(Globals::_RR."/$sctrn/top")){
			/** @var string $c */
			$modsaclist = '';
			# remove from active counters list
			foreach($saclist as $c){     # drop $sctrn, but add it to
				if($c === $sctrn){     # inactive subcounters
					continue;
				}
				$modsaclist .= $c . ' ';
			}
			Database::$engine->set(Globals::_RR."/saclist", $modsaclist);     # update saclist
			Database::$engine->set(Globals::_RR."/siclist", Database::$engine->get(Globals::_RR."/siclist") . ' ' . $sctrn);      # and siclist
			#print "===> Exhausted counter $sctrn\n";
		}

		# $sctr holds counter value, $n holds ordinal of the counter itself
		$id = self::n2xdig(
			$sctr + ($n * Database::$engine->get(Globals::_RR."/percounter")),
			Database::$engine->get(Globals::_RR . "/mask"));
		Database::_dbunlock();
		return $id;
	}
}