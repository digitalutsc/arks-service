<?php
/**
 * Created by PhpStorm.
 * User: Home
 * Date: 12/28/2018
 * Time: 06:54
 */

namespace Noid\Lib;

use \Exception;

require_once 'Db.php';
require_once 'Globals.php';

class Log{
	/**
	 * Adds an error message for a database pointer/object.  If the message
	 * pertains to a failed open, the pointer is null, in which case the
	 * message gets saved to what essentially acts like a global (possible
	 * threading conflict).
	 *
	 * @param string $noid
	 * @param string $message
	 *
	 * @return int 1
	 * @throws Exception
	 */
	static public function addmsg($noid, $message)
	{
		$noid = $noid ? : ''; # act like a global in case $noid undefined
		if(isset(Globals::$open_tab['msg'][$noid])){
			Globals::$open_tab['msg'][$noid] .= $message . PHP_EOL;
		}
		else{
			Globals::$open_tab['msg'][$noid] = $message . PHP_EOL;
		}
		return 1;
	}

	/**
	 * Returns accumulated messages for a database pointer/object.  If the
	 * second argument is non-zero, also reset the message to the empty string.
	 *
	 * @param string $noid
	 * @param int    $reset
	 *
	 * @return string
	 * @throws Exception
	 */
	static public function errmsg($noid = NULL, $reset = 0)
	{
		$noid = $noid ? : ''; # act like a global in case $noid undefined
		$s = isset(Globals::$open_tab['msg'][$noid]) ? Globals::$open_tab['msg'][$noid] : '';
		if($reset){
			Globals::$open_tab['msg'][$noid] = '';
		}
		return $s;
	}

	/**
	 * Logs a message.
	 *
	 * @param string $noid
	 * @param string $message
	 *
	 * @return int 1
	 * @throws Exception
	 */
	static public function logmsg($noid, $message)
	{
		$noid = $noid ? : ''; # act like a global in case $noid undefined
		if(!empty(Globals::$open_tab['log'][$noid])){
			fwrite(Globals::$open_tab['log'][$noid], $message . PHP_EOL);
		}
		# yyy file was opened for append -- hopefully that means always
		#     append even if others have appended to it since our last append;
		#     possible sync problems…
		return 1;
	}

	/**
	 * Record user (":/:/…") values in admin area.
	 *
	 * @param string $noid
	 * @param string $contact
	 * @param string $key
	 * @param string $value
	 *
	 * @return int 0 (error) or 1 (success)
	 * @throws Exception
	 */
	static public function note($noid, $contact, $key, $value)
	{
		Noid::init();

		$db = Db::getDb($noid);
		if(is_null($db)){
			return 0;
		}

		Db::_dblock();
		$status = Db::$engine->set(Globals::_RR . "/" . Globals::_RR . "/$key", $value);
		Db::_dbunlock();
		if(Db::$engine->get(Globals::_RR . "/longterm")){
			self::logmsg($noid, sprintf('note: note attempt under %s by %s', $key, $contact)
				. ($status ? '' : ' -- note failed'));
		}
		if(!$status){
			self::addmsg($noid, 'GloVal::$db_engine->set() error unknown.');
			return 0;
		}
		return 1;
	}

	/**
	 * Get a user note.
	 *
	 * @param string $noid
	 * @param string $key
	 *
	 * @return string The note.
	 * @throws Exception
	 */
	static public function get_note($noid, $key)
	{
		Noid::init();

		$db = Db::getDb($noid);
		if(is_null($db)){
			return NULL;
		}

		return Db::$engine->get(Globals::_RR . "/" . Globals::_RR . "/$key");
	}

	/**
	 * Get the value of any named internal variable (prefaced by GloVal::_RR)
	 * given an open database reference.
	 *
	 * @param string $noid
	 * @param string $varname
	 *
	 * @return string
	 * @throws Exception
	 */
	static public function getnoid($noid, $varname)
	{
		Noid::init();

		$db = Db::getDb($noid);
		if(is_null($db)){
			return NULL;
		}

		return Db::$engine->get(Globals::_RR . "/$varname");
	}
}