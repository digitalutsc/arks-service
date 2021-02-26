<?php
/**
 * Database Wrapper/Connector class, wrapping BerkeleyDB.
 * Noid class's db-related functions(open/close/read/write/...) will
 * be replaced with the functions of this class.
 *
 * Author: Hawk Johns
 * Created: 12/22/2018 5:51 AM
 * Editor: phpStorm
 */

namespace Noid\Lib\Storage;

use \Exception;

require_once 'DatabaseInterface.php';

class BerkeleyDB implements DatabaseInterface{
	/**
	 * Database file extension.
	 *
	 * @const string FILE_EXT
	 */
	const FILE_EXT = 'bdb';

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
	const DB_RANGE_PARTIAL = 'partial';
	const DB_RANGE_REGEX = 'regex';
	// To be able to fetch by range, unavailable via the extension "dba".
	const BDB_SET_RANGE = 27;

	/**
	 * @var resource $handle
	 */
	private $handle;

	/**
	 * BerkeleyDB constructor.
	 * @throws Exception
	 */
	public function __construct()
	{
		// Check if dba is installed.
		if(!extension_loaded('dba')){
			throw new Exception('NOID requires the extension "Database (dbm-style) Abstraction Layer" (dba).');
		}

		// Check if BerkeleyDB is installed.
		if(!in_array('db4', dba_handlers())){
			throw new Exception('BerkeleyDB is not installed.');
		}

		$this->handle = NULL;
	}

	/**
	 * @param string $db_dir
	 * @param string $mode
	 *
	 * @return resource|FALSE
	 * @throws Exception
	 */
	public function open($db_dir, $mode)
	{
		$path = $db_dir . DIRECTORY_SEPARATOR . DatabaseInterface::DATABASE_NAME;
		$file_path = $path . DIRECTORY_SEPARATOR . DatabaseInterface::TABLE_NAME . '.' . self::FILE_EXT;

		$envflags = self::BDB_INIT_LOCK | self::BDB_INIT_TXN | self::BDB_INIT_MPOOL;

		// In create mode, if file existed, fail.
		if(strpos(strtolower($mode), DatabaseInterface::DB_CREATE) !== FALSE){
			if(file_exists($file_path)){
				$descriptorSpec = array(
					0 => array('pipe', 'r'), //STDIN
					1 => array('pipe', 'w'), //STDOUT
					2 => array('pipe', 'w'), //STDERR
				);
				if($proc = proc_open('rm -f ' . $file_path . ' > /dev/null 2>&1', $descriptorSpec, $pipes, getcwd())){
					$output = stream_get_contents($pipes[1]);
					$errors = stream_get_contents($pipes[2]);
					foreach($pipes as $pipe){
						fclose($pipe);
					}
					$status = proc_close($proc);
				}
				else{
					throw new Exception("Failed to execute command: $cmd.");
				}
			}

			$envflags |= self::BDB_CREATE;
			$_GLOBAL['envargs']['-Flags'] = $envflags;

			# Create a logbdb file from scratch and make them writable
			$logbdb = $path . DIRECTORY_SEPARATOR . 'logbdb';
			if(!file_put_contents($logbdb, ' ') || !chmod($logbdb, 0666)){
//				Log::addmsg(NULL, "Couldn't chmod logbdb file: {$logbdb}");
				return FALSE;
			}
			if(is_writable($logbdb)){
				$_GLOBAL['envargs']['-ErrFile'] = $logbdb;
			}
		}

		$this->handle = dba_open($file_path, $mode, 'db4');

		return $this->handle;
	}

	/**
	 * @return void
	 * @throws Exception
	 */
	public function close()
	{
		if(!is_resource($this->handle)){
			return;
		}

		dba_sync($this->handle);
		dba_close($this->handle);
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
		if(!is_resource($this->handle)){
			return FALSE;
		}

		return dba_fetch($key, $this->handle);
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
		if(!is_resource($this->handle)){
			return FALSE;
		}

		return dba_replace($key, $value, $this->handle);
	}

	/**
	 * @param string $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function delete($key)
	{
		if(!is_resource($this->handle)){
			return FALSE;
		}

		return dba_delete($key, $this->handle);
	}

	/**
	 * @param string $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function exists($key)
	{
		if(!is_resource($this->handle)){
			return FALSE;
		}

		return dba_exists($key, $this->handle);
	}

	/**
	 * Workaround to get an array of all keys matching a simple pattern.
	 *
	 * @internal The default extension "dba" doesn't allow to get range of keys.
	 * This workaround may be slow on big bases and may need a lot of memory.
	 * @todo     Build a partial temporary base to avoid memory out for big bases.
	 *
	 * @param string $pattern The pattern of the keys to retrieve (no regex).
	 *
	 * @return array Ordered associative array of matching keys and values.
	 * @throws Exception
	 */
	public function get_range($pattern)
	{
		if(is_null($pattern) || !is_resource($this->handle)){
			return NULL;
		}
		$results = array();
		$key = dba_firstkey($this->handle);

		// Normalize and manage empty pattern.
		$pattern = (string)$pattern;
		if(strlen($pattern) == 0){
			while($key !== FALSE){
				$results[$key] = dba_fetch($key, $this->handle);
				$key = dba_nextkey($this->handle);
			}
		}
		// Manage partial pattern.
		else{
			while($key !== FALSE){
				if(strpos($key, $pattern) === 0){
					$results[$key] = dba_fetch($key, $this->handle);
				}
				$key = dba_nextkey($this->handle);
			}
		}
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
		if(is_null($src_db) || is_null($this->handle) || !is_resource($this->handle)){
			return FALSE;
		}

		// 1. erase all data. this step depends on database implementation.
		$data_to_del = $this->get_range('');
		foreach($data_to_del as $k => $v){
			$this->delete($k);
		}

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
