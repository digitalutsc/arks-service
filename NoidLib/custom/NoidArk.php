<?php

namespace Noid\Lib\Custom;
require_once "NoidLib/custom/GlobalsArk.php";
use Noid\Lib\Noid;
use Noid\Lib\Custom\GlobalsArk;
use Noid\Lib\Custom\Database;


class NoidArk extends Noid {

    /**
     * Initialization.
     * * set the default time zone.
     * * create database interface entity.
     *
     * @throws Exception
     */
    static public function custom_init(String  $dbname)
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

}