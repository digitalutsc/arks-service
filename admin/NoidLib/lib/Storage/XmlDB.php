<?php
/**
 * Database Wrapper/Connector class, wrapping xml.
 * Noid class's db-related functions(open/close/read/write/...) will
 * be replaced with the functions of this class.
 *
 * XML database is faster than Berkeley DB. Because all the operations are executed in RAM.
 * Only when the database is closed, all the data, which loaded when the database is opened,
 * is stored into the XML file.
 *
 * However, Mysql DB is faster db engine, specially when database is BIGGER.
 *
 * Author: Hawk Johns
 * Created: 12/25/2018 20:51 PM
 * Editor: phpStorm
 */

namespace Noid\Lib\Storage;

use \Exception;
use \SimpleXMLElement;

require_once 'DatabaseInterface.php';

class XmlDB implements DatabaseInterface{
	/**
	 * XML-formatted storage:
	 *
	 * <noid>
	 *    <item k='key string encoded by base64'>
	 *        <v>value string encoded by base64</v>
	 *    </item>
	 * </noid>
	 *
	 * we use the base64-encoding for the key and value, cos it's safe and familiar to XML.
	 */

	/**
	 * Database file extension.
	 *
	 * @const string FILE_EXT
	 */
	const FILE_EXT = 'xml';

	/**
	 * @var string $file_path
	 */
	private $file_path;

	/**
	 * @var SimpleXMLElement $handle
	 */
	private $handle;

	/**
	 * BerkeleyDB constructor.
	 * @throws Exception
	 */
	public function __construct()
	{
		// Check if dba is installed.
		if(!extension_loaded('xml')){
			throw new Exception('NOID requires the extension "XML" (php-xml).');
		}

		$this->handle = NULL;
	}

	/**
	 * @param string $db_dir
	 * @param string $mode
	 *
	 * @return SimpleXMLElement|FALSE
	 * @throws Exception
	 */
	public function open($db_dir, $mode)
	{
		$path = $db_dir . DIRECTORY_SEPARATOR . DatabaseInterface::DATABASE_NAME;
		$this->file_path = $path . DIRECTORY_SEPARATOR . DatabaseInterface::TABLE_NAME . '.' . self::FILE_EXT;

		// create mode
		if(strpos(strtolower($mode), DatabaseInterface::DB_CREATE) !== FALSE){
			// don't create any file yet, but will be created when the db closed.
			$this->handle = new SimpleXMLElement('<?xml version="1.0"?><noid></noid>');
			return $this->handle;
		}

		// open mode
		if(file_exists($this->file_path)){
			// just return the object from the file.
			$this->handle = simplexml_load_file($this->file_path);
			return $this->handle;
		}

		return FALSE;
	}

	/**
	 * @return void
	 * @throws Exception
	 */
	public function close()
	{
		// well, it's time for saving the database into the disk.
		$this->handle->asXML($this->file_path);
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
		// internally, the encoded key is used.
		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

		// xml xpath searching...
		$item = $this->handle->xpath('//noid/item[@k="' . $key . '"]');

		// found it.
		if(count($item) > 0){
			return htmlspecialchars_decode($item[0][0]->v, ENT_QUOTES | ENT_HTML401);
		}

		return FALSE; // oh, no.
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
		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);
		$value = htmlspecialchars($value, ENT_QUOTES | ENT_HTML401);

		$item = $this->handle->xpath('//noid/item[@k="' . $key . '"]');

		// if it exists, remove it... for unique keying.
		if(count($item) > 0){
			unset($item[0][0]);
		}

		// insert new item
		/**
		 * @var SimpleXMLElement $item_node
		 */
		$item_node = $this->handle->addChild('item');
		$item_node->addAttribute('k', $key);
		$item_node->addChild('v', $value);

		return TRUE;
	}

	/**
	 * @param string $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function delete($key)
	{
		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

		// refer to: set()
		$item = $this->handle->xpath('//noid/item[@k="' . $key . '"]');

		// found it.
		if(count($item) > 0){
			// delete it.
			unset($item[0][0]);

			return TRUE;
		}

		return FALSE;
	}

	/**
	 * @param string $key
	 *
	 * @return bool
	 * @throws Exception
	 */
	public function exists($key)
	{
		$key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

		// find

		$item = $this->handle->xpath('//noid/item[@k="' . $key . '"]');

		// found it.
		if(count($item) > 0){
			return TRUE;
		}

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
		if(is_null($pattern) || !is_object($this->handle)){
			return NULL;
		}

		// a variable to be returned.
		$results = array();

		$pattern = htmlspecialchars($pattern, ENT_QUOTES | ENT_HTML401);

		// find all the records contained the specific pattern.
		$items = $this->handle->xpath("//noid/item[contains(@k, '" . $pattern . "')]");

		// keep 'em all.
		foreach($items as $item){
			if(isset($item->k)){
				$key = htmlspecialchars_decode($item->k, ENT_QUOTES | ENT_HTML401);
				if(isset($item->v)){
					$value = htmlspecialchars_decode($item->v, ENT_QUOTES | ENT_HTML401);
				}
				else{
					$value = '';
				}
				$results[$key] = $value;
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
		if(is_null($src_db) || is_null($this->handle) || !($this->handle instanceof SimpleXMLElement)){
			return FALSE;
		}

		// 1. erase all data. this step depends on database implementation.
		$this->handle = new SimpleXMLElement('<?xml version="1.0"?><noid></noid>');

		// 2. get data from source database.
		$imported_data = $src_db->get_range('');
		if(count($imported_data) == 0){
			print "(no data) ";
			return FALSE;
		}

		// 3. write 'em all into this database.
		foreach($imported_data as $k => $v){
			$this->set($k, $v);
		}

		return TRUE;
	}
}
