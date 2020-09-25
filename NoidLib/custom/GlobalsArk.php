<?php
namespace Noid\Lib\Custom;

include "NoidLib/lib/Globals.php";
use Noid\Lib\Globals;

class GlobalsArk extends Globals{
    
    const DB_TYPES = [
        'bdb' => 'Noid\Lib\Storage\BerkeleyDB',
        'mysql' => 'Noid\Lib\Storage\MysqlDB',
        'sqlite' => 'Noid\Lib\Storage\SqliteDB',
        'xml' => 'Noid\Lib\Storage\XmlDB',

        // customized for DSU
        'ark_mysql' => 'Noid\Lib\Custom\MysqlArkDB',
    ];
}