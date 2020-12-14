<?php
namespace Noid\Lib\Custom;

include "NoidLib/lib/Globals.php";
use Noid\Lib\Globals;

class GlobalsArk extends Globals{
    // will add prefix in front of database name when dbcreate
    static public $db_prefix = "ARK_";
    static public $NAAN = 61220;

    const DB_TYPES = [
        'bdb' => 'Noid\Lib\Storage\BerkeleyDB',
        'mysql' => 'Noid\Lib\Storage\MysqlDB',
        'sqlite' => 'Noid\Lib\Storage\SqliteDB',
        'xml' => 'Noid\Lib\Storage\XmlDB',

        // customized for DSU
        'ark_mysql' => 'Noid\Lib\Custom\MysqlArkDB',
    ];
}