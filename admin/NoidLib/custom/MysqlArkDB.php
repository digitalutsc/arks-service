<?php

namespace Noid\Lib\Custom;
require_once 'NoidLib/lib/Storage/DatabaseInterface.php';
require_once 'NoidLib/lib/Storage/MysqlDB.php';
require_once '../config/MysqlArkConf.php';

use Noid\Lib\Storage\DatabaseInterface;
use Noid\Lib\Storage\Database;
use Noid\Lib\Custom\Noid\Lib\Custom;
use \mysqli;
use \mysqli_result;
use Noid\Config\MysqlArkConf;


class MysqlArkDB implements DatabaseInterface
{
    protected $db_name;

    public function __construct($name)
    {
        $this->db_name = $name;

        // Check if mysql is installed.
        if (!extension_loaded('mysqli') || !class_exists('mysqli')) {
            throw new Exception('NOID requires the extension "Mysql improved" (mysqli).');
        }

        $this->handle = NULL;
    }

    /**
     * @throws Exception
     */
    private function connect()
    {
        // My lovely Maria (DB) lives my home (local). :)
        $this->handle = @new mysqli(
            isset(MysqlArkConf::$mysql_host) ? trim(MysqlArkConf::$mysql_host) : ini_get('mysqli.default_host'),
            isset(MysqlArkConf::$mysql_user) ? trim(MysqlArkConf::$mysql_user) : ini_get('mysqli.default_user'),
            isset(MysqlArkConf::$mysql_passwd) ? MysqlArkConf::$mysql_passwd : ini_get('mysqli.default_pw'),
            '', // default database is none. maybe selected l8r.
            isset(MysqlArkConf::$mysql_port) ? MysqlArkConf::$mysql_port : ini_get('mysqli.default_port'),
            isset(MysqlArkConf::$mysql_socket) ? trim(MysqlArkConf::$mysql_socket) : ini_get('mysqli.default_socket'));

        // Oops! I can't see her (Maria).
        if ($this->handle->connect_errno) {
            throw new Exception('Mysql connection error: ' . $this->handle->connect_errno);
        }
    }

    /**
     * @param string $name
     * @param string $mode
     *
     * @return mysqli|FALSE
     * @throws Exception
     */
    public function open($name, $mode)
    {
        if (is_null($this->handle))
            $this->connect();

        if (!is_null($this->handle)) {
            // determine the database name.
            $database = MysqlArkConf::$mysql_dbname; //empty(MysqlArkConf::$mysql_dbname) ? trim(MysqlArkConf::$mysql_dbname) : $this->db_name;

            // It's time for checking the db existence. If not exists, will create it.
            $this->handle->query("CREATE DATABASE IF NOT EXISTS `" . $database . "`");

            // select the database `noid`.
            $this->handle->select_db($database);

            // If the table is not exist, create it.
            $this->handle->query("CREATE TABLE IF NOT EXISTS `" . $this->db_name . "` (  `_key` VARCHAR(512) NOT NULL, `_value` VARCHAR(4096) DEFAULT NULL, PRIMARY KEY (`_key`))");

            // when create db
            if (strpos(strtolower($mode), DatabaseInterface::DB_CREATE) !== FALSE) {
                // if create mode, truncate the table records.
                $this->handle->query("TRUNCATE TABLE `" . $this->db_name . "`");
            }

            // Optimize the table for better performance.
            $this->handle->query("OPTIMIZE TABLE `" . $this->db_name . "`");

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
        if (!($this->handle instanceof mysqli)) {
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
        if (!($this->handle instanceof mysqli)) {
            return FALSE;
        }

        $key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

        if ($res = $this->handle->query("SELECT `_value` FROM `" . $this->db_name . "` WHERE `_key` = '{$key}'")) {
            $row = $res->fetch_array(MYSQLI_NUM);
            if (isset($row)) {
                $ret_val = $row[0];
                $res->free();
                return htmlspecialchars_decode($ret_val, ENT_QUOTES | ENT_HTML401);
            }
            else {
                return FALSE;
            }
        }
        return FALSE;
    }

    /**
     * Query ark data with any general where clause
     * @param $where
     * @return false|string
     */
    public function select($where)
    {

        if (!($this->handle instanceof mysqli)) {
            return FALSE;
        }

        if ($res = $this->handle->query("SELECT * FROM `" . $this->db_name . "` WHERE " . $where)) {
            return $res->fetch_all(MYSQLI_ASSOC);
        }
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
        if (!($this->handle instanceof mysqli)) {
            return FALSE;
        }

        $key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);
        $value = htmlspecialchars($value, ENT_QUOTES | ENT_HTML401);

        $qry = "INSERT INTO `" . $this->db_name . "` (`_key`, `_value`) VALUES ('{$key}', '{$value}') ON DUPLICATE KEY UPDATE `_value` = '{$value}'";
        return $this->handle->query($qry);
    }

    /**
     * @param string $key
     *
     * @return bool
     * @throws Exception
     */
    public function delete($key)
    {
        if (!($this->handle instanceof mysqli)) {
            return FALSE;
        }

        $key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

        return $this->handle->query("DELETE FROM `" . $this->db_name . "` WHERE `_key` = '{$key}'");
    }

    /**
     * @param string $key
     *
     * @return bool
     * @throws Exception
     */
    public function exists($key)
    {
        if (!($this->handle instanceof mysqli)) {
            return FALSE;
        }

        $key = htmlspecialchars($key, ENT_QUOTES | ENT_HTML401);

        /** @var mysqli_result $res */
        if ($res = $this->handle->query("SELECT `_key` FROM `" . $this->db_name . "` WHERE `_key` = '{$key}'")) {
            if ($res->num_rows > 0)
                return TRUE;
            else
                return FALSE;
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
        if (is_null($pattern) || !($this->handle instanceof mysqli)) {
            return NULL;
        }
        $results = array();

        /** @var mysqli_result $res */
        $pattern = htmlspecialchars($pattern, ENT_QUOTES | ENT_HTML401);

        if ($res = $this->handle->query("SELECT `_key`, `_value` FROM `" . $this->db_name . "` WHERE `_key` LIKE '%{$pattern}%'")) {
            while ($row = $res->fetch_array(MYSQLI_NUM)) {
                $key = htmlspecialchars_decode($row[0], ENT_QUOTES | ENT_HTML401);
                $value = htmlspecialchars_decode($row[1], ENT_QUOTES | ENT_HTML401);
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
        if (is_null($src_db) || is_null($this->handle) || !($this->handle instanceof mysqli)) {
            return FALSE;
        }

        // 1. erase all data. this step depends on database implementation.
        $this->handle->query("TRUNCATE TABLE `" . $this->db_name . "`");

        // 2. get data from source database.
        $imported_data = $src_db->get_range('');
        if (count($imported_data) == 0) {
            return FALSE;
        }

        // 3. write 'em all into this database.
        foreach ($imported_data as $k => $v) {
            $this->set($k, $v);
        }

        return TRUE;
    }
}
