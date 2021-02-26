<?php
/**
 * This file acts as configuration for mysql connection.
 *
 * Created by PhpStorm.
 * User: Hawk Johns
 * Date: 12/25/2018
 * Time: 22:27
 */

namespace Noid\Lib\Storage;

class MysqlConf{
    static public $mysql_host = 'localhost';
    static public $mysql_user = 'root';
    static public $mysql_passwd = '';
    static public $mysql_dbname = 'noid';
    static public $mysql_port = 3306;
//	static public $mysql_socket = '';
}