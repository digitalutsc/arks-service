<?php
/**
 * General key-value style database interface (class prototype).
 *
 * User: Hawk Johns
 * Date: 12/23/2018
 * Time: 21:02
 */

namespace Noid\Lib\Storage;

use \Exception;

interface DatabaseInterface{
	public const DB_CREATE = 'c';
	public const DB_RDONLY = 'r';
	public const DB_WRITE = 'w';

	/**
	 * Database name.
	 *
	 * For the file-based databases such as BerkeleyDB, XML and Json,
	 * this constant is used as the database directory name.
	 * And for the relative table-structured databases such as mysql,
	 * it is used as the named "default database name".
	 *
	 * @const string DATABASE_NAME
	 */
	public const DATABASE_NAME = 'NOID';

	/**
	 * Database table name.
	 *
	 * For the file-based databases such as BerkeleyDB, XML and Json,
	 * this constant is used as the database file name.
	 * And for the relative table-structured databases such as mysql,
	 * it is used as the named "table name".
	 *
	 * @const string TABLE_NAME
	 */
	public const TABLE_NAME = 'noid';

	/**
	 * Open database/file/other storage.
	 *
	 * @param string $name
	 * @param string $mode
	 *
	 * @return resource|object|FALSE
	 * @throws Exception
	 */
	public function open($name, $mode);

	/**
	 * Close the storage.
	 *
	 * @return void
	 * @throws Exception
	 */
	public function close();

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
	public function import($src_db);

	/**
	 * Get a value by a key.
	 *
	 * @param string   $key
	 *
	 * @return string|FALSE
	 * @throws Exception
	 */
	public function get($key);

	/**
	 * Set/insert a value into a key.
	 *
	 * @param string   $key
	 * @param string   $value
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function set($key, $value);

	/**
	 * Delete a record by a key.
	 *
	 * @param string   $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function delete($key);

	/**
	 * Check whether a record is exists.
	 *
	 * @param string   $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function exists($key);

	/**
	 * Get an array of values containing the pattern(no regexp).
	 *
	 * @param string          $pattern
	 *
	 * @return array
	 * @throws Exception
	 */
	public function get_range($pattern);
}
