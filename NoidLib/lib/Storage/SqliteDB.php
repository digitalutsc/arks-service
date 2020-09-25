<?php
/**
 * Database Wrapper/Connector class, wrapping Mysql.
 * Noid class's db-related functions(open/close/read/write/...) will
 * be replaced with the functions of this class.
 *
 * @Attention: we use the <string>base64-encoding</strong> here, because the keys and values may contain the special chars which is not allowed in SQL queries.
 *
 * Author: Hawk Johns
 * Created: 12/24/2018 3:27 AM
 * Editor: phpStorm
 */

namespace Noid\Lib\Storage;

use \Exception;
use \SQLite3;
use \SQLite3Result;

require_once 'DatabaseInterface.php';

class SqliteDB implements DatabaseInterface{
	/**
	 * Database file extension.
	 *
	 * @const string FILE_EXT
	 */
	const FILE_EXT = 'sqlite';

	/**
	 * @var SQLite3 $handle
	 */
	private $handle;

	/**
	 * SqliteDB: constructor.
	 * @throws Exception
	 */
	public function __construct()
	{
		// Check if sqlite3 is enabled.
		if(!extension_loaded('sqlite3') || !class_exists('SQLite3')){
			throw new Exception('NOID requires the extension "SQLite3".');
		}

		$this->handle = NULL;
	}

	/**
	 * @param string $db_dir
	 * @param string $mode
	 *
	 * @return SQLite3|FALSE
	 * @throws Exception
	 */
	public function open($db_dir, $mode)
	{
		$path = $db_dir . DIRECTORY_SEPARATOR . DatabaseInterface::DATABASE_NAME;
		$file_path = $path . DIRECTORY_SEPARATOR . DatabaseInterface::TABLE_NAME . '.' . self::FILE_EXT;

		if(!is_null($this->handle) && $this->handle instanceof SQLite3){
			$this->handle->close();
		}

		$this->handle = new SQLite3($file_path);
		// create mode
		if(strpos(strtolower($mode), DatabaseInterface::DB_CREATE) !== FALSE){
			// If the table is not exist, create it.
			$this->handle->exec("CREATE TABLE IF NOT EXISTS `" . DatabaseInterface::TABLE_NAME . "` (  `_key` VARCHAR(512) NOT NULL, `_value` VARCHAR(4096) DEFAULT NULL, PRIMARY KEY (`_key`))");

			// if create mode, truncate the table records.
			$this->handle->exec("DELETE FROM `" . DatabaseInterface::TABLE_NAME . "`");
		}

		return $this->handle;
	}

	/**
	 * @return void
	 * @throws Exception
	 */
	public function close()
	{
		if(is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return;
		}

		$this->handle->close();
		$this->handle = NULL;
	}

	/**
	 * @param string $key
	 *
	 * @return string|FALSE
	 * @throws Exception
	 */
	public function get($key)
	{
		if(is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return FALSE;
		}

		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

		$res = $this->handle->query("SELECT `_value` FROM `" . DatabaseInterface::TABLE_NAME . "` WHERE `_key` = '{$key}'");
		if($row = $res->fetchArray(SQLITE3_NUM)){
			$res->finalize();
			return htmlspecialchars_decode($row[0], ENT_QUOTES | ENT_HTML401);
		}
		$res->finalize();
		return FALSE;
	}

	/**
	 * @param string $key
	 * @param string $value
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function set($key, $value)
	{
		if(is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return FALSE;
		}

		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);
		$value = htmlspecialchars($value, ENT_QUOTES | ENT_HTML401);

		$qry = "REPLACE INTO `" . DatabaseInterface::TABLE_NAME . "` (`_key`, `_value`) VALUES ('{$key}', '{$value}')";
		return $this->handle->exec($qry);
	}

	/**
	 * @param string $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function delete($key)
	{
		if(is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return FALSE;
		}

		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

		return $this->handle->exec("DELETE FROM `" . DatabaseInterface::TABLE_NAME . "` WHERE `_key` = '{$key}'");
	}

	/**
	 * @param string $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function exists($key)
	{
		if(is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return FALSE;
		}

		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

		/** @var SQLite3Result $res */
		$res = $this->handle->query("SELECT `_key` FROM `" . DatabaseInterface::TABLE_NAME . "` WHERE `_key` = '{$key}'");
		if($row = $res->fetchArray(SQLITE3_NUM)){
			$res->finalize();
			return TRUE;
		}
		$res->finalize();
		return FALSE;
	}

	/**
	 * Workaround to get an array of all keys matching a simple pattern.
	 *
	 * @param string $pattern The pattern of the keys to retrieve (no regex).
	 *
	 * @return array Ordered associative array of matching keys and values.
	 * @throws Exception
	 */
	public function get_range($pattern)
	{
		if(is_null($pattern) || is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return NULL;
		}
		$results = array();

		/** @var SQLite3Result $res */
		$pattern = htmlspecialchars($pattern, ENT_QUOTES | ENT_HTML401);

		$res = $this->handle->query("SELECT `_key`, `_value` FROM `" . DatabaseInterface::TABLE_NAME . "` WHERE `_key` LIKE '%{$pattern}%'");

		while($row = $res->fetchArray(SQLITE3_NUM)){
			$key = htmlspecialchars_decode($row[0], ENT_QUOTES | ENT_HTML401);
			$value = htmlspecialchars_decode($row[1], ENT_QUOTES | ENT_HTML401);
			$results[$key] = $value;
		}
		$res->finalize();

		// @internal Ordered by default with Berkeley database.
		ksort($results);
		return $results;
	}

	/**
	 * Import all data from other data source.
	 * 1. erase all data here.
	 * 2. get data from source db by its get_range() invocation.
	 * 3. insert 'em all here.
	 *
	 * @attention when do this, the original data is erased.
	 *
	 * @param DatabaseInterface $src_db
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function import($src_db)
	{
		if(is_null($src_db) || is_null($this->handle) || !($this->handle instanceof SQLite3)){
			return FALSE;
		}

		// 1. erase all data. this step depends on database implementation.
		$this->handle->exec("DELETE FROM `" . DatabaseInterface::TABLE_NAME . "`");

		// 2. get data from source database.
		$imported_data = $src_db->get_range('');
		if(count($imported_data) == 0){
			return FALSE;
		}

		// 3. write 'em all into this database.
		foreach($imported_data as $k => $v){
			$this->set($k, $v);
		}

		return TRUE;
	}
}
